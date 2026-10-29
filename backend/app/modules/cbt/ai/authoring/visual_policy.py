"""Batch visual distribution for CBT's existing Text / Allow Images modes.

For Allow Images (internal auto mode), target roughly 40% genuinely
visual-bearing questions while keeping text-only questions in the majority.
Small batches are rounded to a feasible integer count.
"""

from __future__ import annotations


def target_visual_question_count(question_count: int) -> int:
    """Return the deterministic image-bearing question target for an auto batch.

    Round 40% to the nearest whole question, with at least one visual and
    a strict text-only majority for batches of three or more.
    """
    if type(question_count) is not int or question_count < 1:
        raise ValueError("question_count must be a positive integer.")
    if question_count == 1:
        return 1
    rounded_target = max(1, (2 * question_count + 2) // 5)
    if question_count == 2:
        return 1
    return min(rounded_target, (question_count - 1) // 2)
