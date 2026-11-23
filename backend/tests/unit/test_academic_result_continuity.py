"""Focused score-continuity regression tests; no database required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.student_academics.models import AcademicResultStatus
from app.modules.students.result_continuity import (
    AcademicResultContinuityService,
    ResultContinuityDecision,
)


def _fixture(status=AcademicResultStatus.DRAFT):
    result = SimpleNamespace(
        id=uuid4(),
        status=status,
        class_id=uuid4(),
        student_enrollment_id=uuid4(),
        teacher_assignment_id=uuid4(),
        teacher_membership_id=uuid4(),
        total_score=9,
    )
    destination = SimpleNamespace(id=uuid4(), class_id=uuid4())
    teacher = SimpleNamespace(id=uuid4(), teacher_membership_id=uuid4())
    return result, destination, teacher


async def _apply(monkeypatch, result, destination, teacher, *, consent=False):
    action = "automatic" if result.status == AcademicResultStatus.DRAFT else "requires_confirmation"
    inspect_mock = AsyncMock(return_value=[ResultContinuityDecision(result, action, "", teacher)])
    audit_mock = AsyncMock()
    monkeypatch.setattr(AcademicResultContinuityService, "inspect", inspect_mock)
    from app.modules.student_academics.repository import StudentAcademicRepository

    monkeypatch.setattr(StudentAcademicRepository, "add_academic_lifecycle_audit", audit_mock)
    db = MagicMock()
    result_before = result.total_score
    await AcademicResultContinuityService.apply(
        db,
        actor_id=uuid4(),
        tenant_id=uuid4(),
        student_id=uuid4(),
        academic_session_id=uuid4(),
        source_level_id=uuid4(),
        destination_enrollment=destination,
        effective_date=__import__("datetime").date.today(),
        reason="Wrong Class",
        carry_finalized_results=consent,
    )
    assert result.total_score == result_before
    return db, audit_mock


@pytest.mark.asyncio
async def test_draft_reconciliation_keeps_canonical_result_and_score(monkeypatch):
    result, destination, teacher = _fixture()
    db, audit = await _apply(monkeypatch, result, destination, teacher)
    assert result.class_id == destination.class_id
    assert result.student_enrollment_id == destination.id
    assert result.teacher_assignment_id == teacher.id
    assert result.teacher_membership_id == teacher.teacher_membership_id
    db.add.assert_called_once_with(result)
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_locked_result_remains_unchanged_without_explicit_admin_consent(monkeypatch):
    result, destination, teacher = _fixture(AcademicResultStatus.LOCKED)
    initial = (result.class_id, result.student_enrollment_id, result.teacher_assignment_id)
    db, audit = await _apply(monkeypatch, result, destination, teacher, consent=False)
    assert initial == (result.class_id, result.student_enrollment_id, result.teacher_assignment_id)
    db.add.assert_not_called()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_result_ownership_correction_requires_consent_and_preserves_status(
    monkeypatch,
):
    result, destination, teacher = _fixture(AcademicResultStatus.LOCKED)
    db, audit = await _apply(monkeypatch, result, destination, teacher, consent=True)
    assert result.class_id == destination.class_id
    assert result.status == AcademicResultStatus.LOCKED
    db.add.assert_called_once_with(result)
    audit.assert_awaited_once()
    metadata = audit.await_args.args[1].metadata_json
    assert metadata["finalized_authorized"] is True
    assert metadata["marks_changed"] is False


@pytest.mark.asyncio
async def test_cross_level_inspection_never_proposes_score_transfer():
    target = SimpleNamespace(id=uuid4(), academic_level_id=uuid4())
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: target))
    decisions = await AcademicResultContinuityService.inspect(
        db,
        tenant_id=uuid4(),
        student_id=uuid4(),
        academic_session_id=uuid4(),
        source_level_id=uuid4(),
        target_class_id=target.id,
        effective_date=__import__("datetime").date.today(),
    )
    assert decisions == []
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_needs_attention_filter_is_applied_before_database_pagination():
    from sqlalchemy.dialects import postgresql
    from app.modules.tma.repository import TMAAssignmentRepository

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one=lambda: 0),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
        ]
    )
    rows, count = await TMAAssignmentRepository.list_for_scope(
        db, uuid4(), needs_attention=True, offset=30, limit=24
    )
    assert rows == [] and count == 0
    sql = str(db.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "zero_grading_requested_at IS NOT NULL" in sql
    assert "zero_grading_completed_at IS NULL" in sql
    assert "zero_grading_error IS NOT NULL" in sql


@pytest.mark.asyncio
async def test_repeated_transfer_reconciles_stale_enrollment_even_when_class_matches(monkeypatch):
    """Returning to SS3 C must update result enrollment, not duplicate the score."""
    from datetime import date

    from app.modules.student_academics.assessment_repository import AssessmentRepository
    from app.modules.student_academics.curriculum_service import CurriculumResolutionService
    from app.modules.student_academics.repository import StudentAcademicRepository

    tenant_id, student_id, session_id, level_id, class_id = [uuid4() for _ in range(5)]
    prior_enrollment_id = uuid4()
    destination_enrollment_id = uuid4()
    subject_id, scheme_id = uuid4(), uuid4()
    result = SimpleNamespace(
        id=uuid4(),
        class_id=class_id,
        student_enrollment_id=prior_enrollment_id,
        curriculum_subject_id=subject_id,
        assessment_scheme_id=scheme_id,
        status=AcademicResultStatus.DRAFT,
        total_score=9,
    )
    classroom = SimpleNamespace(id=class_id, academic_level_id=level_id)
    prior_enrollment = SimpleNamespace(class_id=class_id, academic_level_id=level_id)
    term = SimpleNamespace(id=uuid4())
    teacher = SimpleNamespace(id=uuid4(), teacher_membership_id=uuid4())
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: classroom),
            SimpleNamespace(scalar_one_or_none=lambda: term),
            SimpleNamespace(scalars=lambda: [result]),
            SimpleNamespace(scalar_one_or_none=lambda: classroom),
            SimpleNamespace(scalar_one_or_none=lambda: prior_enrollment),
        ]
    )
    monkeypatch.setattr(
        CurriculumResolutionService,
        "resolve_class_subjects",
        AsyncMock(return_value=[SimpleNamespace(curriculum_subject_id=subject_id)]),
    )
    monkeypatch.setattr(
        AssessmentRepository,
        "get_active_scheme",
        AsyncMock(return_value=SimpleNamespace(id=scheme_id)),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "get_teacher_assignments_for_classes_on_date",
        AsyncMock(return_value={class_id: teacher}),
    )

    decisions = await AcademicResultContinuityService.inspect(
        db,
        tenant_id=tenant_id,
        student_id=student_id,
        academic_session_id=session_id,
        source_level_id=level_id,
        target_class_id=class_id,
        effective_date=date.today(),
        destination_enrollment_id=destination_enrollment_id,
    )
    assert len(decisions) == 1
    assert decisions[0].action == "automatic"
    assert decisions[0].result is result
