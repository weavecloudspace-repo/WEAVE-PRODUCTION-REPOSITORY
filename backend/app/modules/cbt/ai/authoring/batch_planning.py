"""Deterministic internal batching for large synchronous CBT AI requests.

Chunks are chosen so each keeps the existing visual policy unchanged while the
combined response retains the caller's exact 60/40 target. No external jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from typing import Mapping

from app.modules.cbt.ai.authoring.visual_policy import target_visual_question_count


MAX_QUESTIONS_PER_MODEL_CALL = 10
SUPPORTED_TYPES = frozenset({"single_choice", "multiple_choice"})


@dataclass(frozen=True, slots=True)
class QuestionBatchPlan:
    count: int
    visual_target: int | None
    type_counts: dict[str, int] | None


def _visual_chunk_sizes(count: int, max_size: int) -> tuple[int, ...]:
    """Choose the fewest chunks whose individual visual targets sum exactly.

    The existing policy enforces a strict text-only majority for chunk sizes
    above two. Prefer fewer calls and more balanced sizes. Avoid single-item
    chunks because their mandatory visual would distort the global split.
    """
    overall_target = target_visual_question_count(count)

    @lru_cache(maxsize=None)
    def solve(left: int, visual_left: int) -> tuple[int, ...] | None:
        if left == 0:
            return () if visual_left == 0 else None
        best: tuple[int, ...] | None = None
        for size in range(min(max_size, left), 1, -1):
            required = target_visual_question_count(size)
            if required > visual_left:
                continue
            tail = solve(left - size, visual_left - required)
            if tail is None:
                continue
            candidate = (size, *tail)
            if best is None or (len(candidate), max(candidate) - min(candidate)) < (
                len(best),
                max(best) - min(best),
            ):
                best = candidate
        return best

    result = solve(count, overall_target)
    if result is None:
        raise ValueError(
            "Cannot partition the request while preserving its visual distribution."
        )
    return result


def plan_question_batches(
    count: int,
    *,
    visual_mode: str,
    expected_type_counts: Mapping[str, int] | None = None,
    max_size: int = MAX_QUESTIONS_PER_MODEL_CALL,
) -> list[QuestionBatchPlan]:
    """Allocate exact question and type counts across bounded model calls."""
    if type(count) is not int or count < 1:
        raise ValueError("question_count must be a positive integer.")
    if type(max_size) is not int or max_size < 2:
        raise ValueError("max_size must be at least two.")
    if visual_mode not in {"auto", "text_only"}:
        raise ValueError(f"Unsupported visual mode: {visual_mode!r}.")

    remaining_types: dict[str, int] | None = None
    if expected_type_counts is not None:
        if any(
            key not in SUPPORTED_TYPES or type(value) is not int or value < 0
            for key, value in expected_type_counts.items()
        ):
            raise ValueError("Invalid requested question-type distribution.")
        remaining_types = dict(expected_type_counts)
        if sum(remaining_types.values()) != count:
            raise ValueError("Question-type counts must sum to question_count.")

    if count <= max_size:
        sizes = (count,)
    elif visual_mode == "auto":
        sizes = _visual_chunk_sizes(count, max_size)
    else:
        number_of_chunks = ceil(count / max_size)
        base, extra = divmod(count, number_of_chunks)
        sizes = tuple(base + (1 if index < extra else 0) for index in range(number_of_chunks))

    plans: list[QuestionBatchPlan] = []
    remaining_total = count
    for size in sizes:
        type_counts: dict[str, int] | None = None
        if remaining_types is not None:
            type_counts = {
                key: remaining * size // remaining_total
                for key, remaining in remaining_types.items()
            }
            slots = size - sum(type_counts.values())
            for key in sorted(
                remaining_types,
                key=lambda item: (
                    -(remaining_types[item] * size % remaining_total),
                    item,
                ),
            ):
                if slots == 0:
                    break
                if type_counts[key] < remaining_types[key]:
                    type_counts[key] += 1
                    slots -= 1
            if slots:
                raise AssertionError("Question-type distribution allocation failed.")
            for key, allocated in type_counts.items():
                remaining_types[key] -= allocated

        plans.append(
            QuestionBatchPlan(
                count=size,
                visual_target=target_visual_question_count(size) if visual_mode == "auto" else None,
                type_counts=type_counts,
            )
        )
        remaining_total -= size

    if remaining_total != 0 or (remaining_types and any(remaining_types.values())):
        raise AssertionError("Generated question-batch plan is incomplete.")
    return plans
