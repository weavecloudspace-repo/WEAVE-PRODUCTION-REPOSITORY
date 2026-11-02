"""Internal batch planning must retain original CBT question constraints."""

from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.batch_planning import plan_question_batches
from app.modules.cbt.ai.authoring.visual_policy import target_visual_question_count


@pytest.mark.parametrize("size", range(11, 61))
def test_hybrid_batches_keep_exact_global_visual_target(size: int) -> None:
    batches = plan_question_batches(size, visual_mode="auto")
    assert sum(batch.count for batch in batches) == size
    assert all(2 <= batch.count <= 10 for batch in batches)
    assert len(batches) >= 2
    assert all(
        batch.visual_target == target_visual_question_count(batch.count) for batch in batches
    )
    assert sum(batch.visual_target or 0 for batch in batches) == target_visual_question_count(size)


@pytest.mark.parametrize("size", [5, 10, 11, 15, 20, 21, 37, 50])
def test_text_only_batches_preserve_count_and_size(size: int) -> None:
    batches = plan_question_batches(size, visual_mode="text_only")
    assert sum(batch.count for batch in batches) == size
    assert all(batch.count <= 10 for batch in batches)
    assert all(batch.visual_target is None for batch in batches)
    assert len(batches) == (size + 9) // 10


@pytest.mark.parametrize("size", [11, 12, 14, 15, 20, 24, 30, 51])
def test_question_types_distributed_without_loss(size: int) -> None:
    expected = {"single_choice": size - size // 3, "multiple_choice": size // 3}
    batches = plan_question_batches(size, visual_mode="auto", expected_type_counts=expected)
    assert sum(batch.type_counts["single_choice"] for batch in batches) == expected["single_choice"]
    assert (
        sum(batch.type_counts["multiple_choice"] for batch in batches)
        == expected["multiple_choice"]
    )
    assert all(sum(batch.type_counts.values()) == batch.count for batch in batches)
    assert all(all(value >= 0 for value in batch.type_counts.values()) for batch in batches)


@pytest.mark.parametrize(
    "type_counts",
    [{"single_choice": 8}, {"single_choice": -1, "multiple_choice": 21}, {"essay": 20}],
)
def test_invalid_type_counts_are_rejected_before_provider(type_counts) -> None:
    with pytest.raises(ValueError):
        plan_question_batches(20, visual_mode="auto", expected_type_counts=type_counts)


def test_twenty_hybrid_questions_become_two_tens() -> None:
    batches = plan_question_batches(
        20,
        visual_mode="auto",
        expected_type_counts={"single_choice": 12, "multiple_choice": 8},
    )
    assert [(b.count, b.visual_target) for b in batches] == [(10, 4), (10, 4)]
    assert [b.type_counts for b in batches] == [
        {"single_choice": 6, "multiple_choice": 4},
        {"single_choice": 6, "multiple_choice": 4},
    ]
