"""Regression coverage for placement review findings."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestException
from app.modules.student_academics.models import AcademicTermStatus
from app.modules.students.enrollment_schemas import (
    PlacementImpactPreviewRequest,
    StudentClassReassignmentRequest,
)
from app.modules.students.models import AcademicStatus
from app.modules.students.placement_service import StudentPlacementService
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.students.service import StudentService


def _context():
    tenant, session_id, level_id, student_id = (uuid4() for _ in range(4))
    return SimpleNamespace(
        actor=SimpleNamespace(id=uuid4(), tenant_id=tenant),
        student=SimpleNamespace(id=student_id, status=AcademicStatus.ACTIVE),
        current=SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            academic_session_id=session_id,
            academic_level_id=level_id,
            class_id=uuid4(),
            started_on=date.today() - timedelta(days=20),
        ),
        target=SimpleNamespace(id=uuid4(), academic_level_id=level_id),
        session_id=session_id,
        level_id=level_id,
    )


@pytest.mark.asyncio
async def test_scheduled_move_keeps_results_with_current_class_until_activation(monkeypatch):
    from app.modules.students import placement_service as mod

    ctx = _context()
    db = SimpleNamespace(commit=AsyncMock())
    audit = AsyncMock()
    apply = AsyncMock()
    invalidate = AsyncMock()
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=ctx.student))
    monkeypatch.setattr(
        StudentPlacementService, "_require_open_session",
        AsyncMock(return_value=SimpleNamespace(id=ctx.session_id)),
    )
    monkeypatch.setattr(
        StudentPlacementService, "_require_target_class", AsyncMock(return_value=ctx.target)
    )
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=ctx.current))
    monkeypatch.setattr(StudentEnrollmentRepository, "get_upcoming", AsyncMock(return_value=None))
    monkeypatch.setattr(StudentPlacementService, "_close_segment", AsyncMock())
    monkeypatch.setattr(
        StudentPlacementService, "_create_segment", AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(mod.StudentAcademicRepository, "add_academic_lifecycle_audit", audit)
    monkeypatch.setattr(mod.AcademicResultContinuityService, "apply", apply)
    monkeypatch.setattr(StudentPlacementService, "_invalidate_derived_context", invalidate)
    monkeypatch.setattr(
        StudentService, "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=ctx.student.id)),
    )

    await StudentPlacementService.reassign_class(
        db,
        actor=ctx.actor,
        student_id=ctx.student.id,
        payload=StudentClassReassignmentRequest(
            target_class_id=ctx.target.id,
            academic_session_id=ctx.session_id,
            effective_date=date.today() + timedelta(days=5),
            reason="Schedule next classroom",
            carry_finalized_results=False,
        ),
    )

    apply.assert_not_awaited()
    invalidate.assert_not_awaited()
    assert audit.await_args.args[1].action == "result_continuity_scheduled"
    assert audit.await_args.args[1].metadata_json["source_level_id"] == str(ctx.level_id)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_no_op_preserves_existing_report_cards(monkeypatch):
    from app.modules.students import placement_service as mod

    ctx = _context()
    db = SimpleNamespace(commit=AsyncMock())
    invalidate = AsyncMock()
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=ctx.student))
    monkeypatch.setattr(
        StudentPlacementService, "_require_open_session",
        AsyncMock(return_value=SimpleNamespace(id=ctx.session_id)),
    )
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=ctx.current))
    monkeypatch.setattr(mod.AcademicResultContinuityService, "apply", AsyncMock(return_value=[]))
    monkeypatch.setattr(StudentPlacementService, "_invalidate_derived_context", invalidate)
    monkeypatch.setattr(
        StudentService, "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=ctx.student.id)),
    )
    await StudentPlacementService.reconcile_existing_results(
        db,
        actor=ctx.actor,
        student_id=ctx.student.id,
        academic_session_id=ctx.session_id,
        reason="Idempotency check",
    )
    db.commit.assert_awaited_once()
    invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_cache_invalidates_only_after_commit(monkeypatch):
    from app.modules.students import placement_service as mod

    order = []

    async def commit():
        order.append("committed")

    async def invalidate(**_kwargs):
        order.append("invalidated")

    monkeypatch.setattr(
        mod.ReportReadinessCache, "invalidate_student_session", invalidate
    )
    await StudentPlacementService._commit_with_readiness_invalidation(
        SimpleNamespace(commit=commit),
        tenant_id=uuid4(),
        student_id=uuid4(),
        academic_session_id=uuid4(),
    )
    assert order == ["committed", "invalidated"]


@pytest.mark.asyncio
async def test_preview_rejects_non_current_term_instead_of_mix_terms(monkeypatch):
    ctx = _context()
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(
                    id=uuid4(), is_current=False, status=AcademicTermStatus.CLOSED
                )
            )
        )
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=ctx.student))
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=ctx.current))
    with pytest.raises(BadRequestException, match="current open academic term"):
        await StudentPlacementService.impact_preview(
            db,
            actor=ctx.actor,
            student_id=ctx.student.id,
            payload=PlacementImpactPreviewRequest(
                target_academic_level_id=ctx.level_id,
                target_class_id=ctx.target.id,
                academic_session_id=ctx.session_id,
                academic_term_id=uuid4(),
                effective_date=date.today(),
            ),
        )
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_does_not_call_unselected_elective_applicable(monkeypatch):
    from app.modules.students import placement_service as mod
    from app.modules.student_academics.curriculum_service import CurriculumResolutionService
    from app.modules.subjects.repository import SubjectRepository

    ctx = _context()
    elective = SimpleNamespace(
        curriculum_subject_id=uuid4(),
        subject_id=uuid4(),
        is_elective=True,
        elective_group_id=uuid4(),
    )
    compulsory = SimpleNamespace(
        curriculum_subject_id=uuid4(),
        subject_id=uuid4(),
        is_elective=False,
        elective_group_id=None,
    )
    term = SimpleNamespace(id=uuid4(), is_current=True, status=AcademicTermStatus.OPEN)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: term),
                SimpleNamespace(scalars=lambda: []),
                SimpleNamespace(scalars=lambda: []),
                SimpleNamespace(scalar_one_or_none=lambda: None),
                SimpleNamespace(scalar_one_or_none=lambda: None),
            ]
        )
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=ctx.student))
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=ctx.current))
    monkeypatch.setattr(
        StudentPlacementService, "_require_target_class", AsyncMock(return_value=ctx.target)
    )
    monkeypatch.setattr(
        CurriculumResolutionService, "resolve_class_subjects",
        AsyncMock(return_value=[elective, compulsory]),
    )
    monkeypatch.setattr(StudentPlacementService, "_department_name", AsyncMock(return_value=None))
    monkeypatch.setattr(
        SubjectRepository, "get_subject_by_id",
        AsyncMock(return_value=SimpleNamespace(name="Subject")),
    )
    monkeypatch.setattr(mod.AcademicResultContinuityService, "inspect", AsyncMock(return_value=[]))
    response = await StudentPlacementService.impact_preview(
        db,
        actor=ctx.actor,
        student_id=ctx.student.id,
        payload=PlacementImpactPreviewRequest(
            target_academic_level_id=ctx.level_id,
            target_class_id=ctx.target.id,
            academic_session_id=ctx.session_id,
            academic_term_id=term.id,
            effective_date=date.today(),
        ),
    )
    assert [s.curriculum_subject_id for s in response.subjects_remaining_applicable] == [
        compulsory.curriculum_subject_id
    ]
    assert [s.curriculum_subject_id for s in response.subjects_becoming_historical_only] == [
        elective.curriculum_subject_id
    ]
    assert any("historical-only" in warning for warning in response.warnings)
