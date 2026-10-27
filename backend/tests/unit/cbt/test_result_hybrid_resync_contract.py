"""Only an intact, unowned theory-only hybrid component can receive a CBT resync."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.modules.cbt.results.service import CBTResultIngestionService


def record():
    return SimpleNamespace(
        cbt_score=None,
        theory_score=Decimal("8"),
        score=Decimal("8"),
        cbt_maximum_score=Decimal("20"),
        source_exam_id=None,
        cbt_source_batch_id=None,
    )


def test_withdrawn_hybrid_theory_can_be_reused_without_adding_duplicate_component():
    assert CBTResultIngestionService._can_fill_unpublished_hybrid(
        record(),
        component=SimpleNamespace(is_hybrid=True),
        cbt_maximum_score=Decimal("20"),
    )


def test_locked_or_modified_score_or_existing_publication_cannot_be_implicitly_overwritten():
    examples = [
        {"cbt_score": Decimal("2")},
        {"score": Decimal("9")},
        {"source_exam_id": uuid4()},
        {"cbt_source_batch_id": uuid4()},
        {"cbt_maximum_score": Decimal("10")},
    ]
    for changes in examples:
        value = record()
        for key, item in changes.items():
            setattr(value, key, item)
        assert not CBTResultIngestionService._can_fill_unpublished_hybrid(
            value,
            component=SimpleNamespace(is_hybrid=True),
            cbt_maximum_score=Decimal("20"),
        )


def test_non_hybrid_scores_are_never_adopted():
    assert not CBTResultIngestionService._can_fill_unpublished_hybrid(
        record(),
        component=SimpleNamespace(is_hybrid=False),
        cbt_maximum_score=Decimal("20"),
    )
