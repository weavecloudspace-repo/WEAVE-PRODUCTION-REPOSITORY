"""Regressions for the draft-only CBT withdrawal contract."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.modules.cbt.enums import CBTResultIngestionOutcome
from app.modules.cbt.results.rollback_schemas import CBTResultRollbackRequest
from app.modules.cbt.results.rollback_service import CBTResultRollbackService
from app.modules.student_academics.models import AcademicResultStatus


def _scenario():
    batch = SimpleNamespace(batch_id=uuid4(), source_exam_id=uuid4())
    parent = SimpleNamespace(status=AcademicResultStatus.DRAFT)
    score = SimpleNamespace(
        cbt_source_batch_id=batch.batch_id,
        source_exam_id=batch.source_exam_id,
        cbt_score=Decimal("12.00"),
        score=Decimal("12.00"),
        theory_score=None,
    )
    item = SimpleNamespace(
        outcome=CBTResultIngestionOutcome.APPLIED, incoming_score=Decimal("12.00")
    )
    component = SimpleNamespace(is_hybrid=False)
    return parent, score, batch, item, component


def test_rollback_rejects_duplicate_and_empty_targets():
    student = uuid4()
    with pytest.raises(ValidationError):
        CBTResultRollbackRequest(
            operation_id=uuid4(),
            source_batch_id=uuid4(),
            student_ids=[student, student],
            reason="Invalid score",
        )
    with pytest.raises(ValidationError):
        CBTResultRollbackRequest(
            operation_id=uuid4(), source_batch_id=uuid4(), student_ids=[], reason="Invalid score"
        )


def test_fingerprint_does_not_depend_on_target_order():
    a, b = uuid4(), uuid4()
    request = CBTResultRollbackRequest(
        operation_id=uuid4(), source_batch_id=uuid4(), student_ids=[a, b], reason="Wrong answer key"
    )
    assert CBTResultRollbackService.fingerprint(request) == CBTResultRollbackService.fingerprint(
        request.model_copy(update={"student_ids": [b, a]})
    )


@pytest.mark.parametrize(
    "status",
    [
        AcademicResultStatus.SUBMITTED,
        AcademicResultStatus.APPROVED,
        AcademicResultStatus.LOCKED,
    ],
)
def test_only_draft_academic_results_can_be_withdrawn(status):
    parent, score, batch, item, component = _scenario()
    parent.status = status
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        == "RESULT_NOT_DRAFT"
    )


def test_draft_and_hybrid_score_ownership():
    parent, score, batch, item, component = _scenario()
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        is None
    )
    component.is_hybrid = True
    score.theory_score = Decimal("3.00")
    score.score = Decimal("15.00")
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        is None
    )


def test_reject_unchanged_previous_batch_and_manual_edits():
    parent, score, batch, item, component = _scenario()
    item.outcome = CBTResultIngestionOutcome.UNCHANGED
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        == "NOT_ORIGINAL_PUBLICATION"
    )
    item.outcome = CBTResultIngestionOutcome.APPLIED
    score.cbt_source_batch_id = uuid4()
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        == "PUBLICATION_NOT_CURRENT"
    )
    score.cbt_source_batch_id = batch.batch_id
    score.score = Decimal("13.00")
    assert (
        CBTResultRollbackService.publication_conflict(
            parent=parent, score=score, batch=batch, item=item, component=component
        )
        == "SCORE_CHANGED"
    )
