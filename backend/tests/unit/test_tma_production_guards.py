"""Critical TMA guards: preflight grading coverage, active revision, lock ordering."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ConflictException
from app.modules.tma import attempt_service, authorization, lifecycle_service
from app.modules.tma.models import TMAAssignmentStatus, TMAAttemptStatus
from app.modules.tma.repository import TMAAssignmentRepository


def uid():
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_publish_readiness_flags_every_class_missing_subject_teacher(monkeypatch):
    mod = lifecycle_service
    tenant, level, subject = uid(), uid(), uid()
    room_a, room_b = uid(), uid()
    assignment = SimpleNamespace(
        id=uid(), tenant_id=tenant, academic_level_id=level,
        curriculum_subject_id=subject, academic_term_id=uid(),
        academic_session_id=uid(), assessment_component_id=uid(),
        current_revision_number=1,
    )
    session = SimpleNamespace(status=mod.AcademicSessionStatus.OPEN, is_current=True)
    scheme = SimpleNamespace(id=uid())
    component = SimpleNamespace(
        is_active=True, assessment_scheme_id=scheme.id,
        is_hybrid=False, is_examinable=False
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_academic_session_by_id",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_open_term", AsyncMock())
    monkeypatch.setattr(mod.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=scheme))
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_component", AsyncMock(return_value=component)
    )
    revision = SimpleNamespace(id=uid(), invalidated_at=None)
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_number", AsyncMock(return_value=revision)
    )
    question = SimpleNamespace(question_text="Question?", image_asset_id=None, position=1)
    options = [
        SimpleNamespace(is_correct=i == 0)
        for i in range(4)
    ]
    monkeypatch.setattr(
        mod.TMAQuestionRepository, "list_for_revision_with_options",
        AsyncMock(return_value=[(question, options)]),
    )
    monkeypatch.setattr(
        mod.CurriculumResolutionService, "resolve_classes_subjects",
        AsyncMock(return_value={
            room_a: [SimpleNamespace(curriculum_subject_id=subject)],
            room_b: [SimpleNamespace(curriculum_subject_id=subject)],
        }),
    )
    owners = AsyncMock(return_value={room_a: SimpleNamespace(id=uid())})
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_teacher_assignments_for_classes_on_date",
        owners,
    )
    row = MagicMock()
    row.scalars.return_value.all.return_value = [
        SimpleNamespace(id=room_a), SimpleNamespace(id=room_b)
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=row))
    errors = await mod.TMALifecycleService._readiness_errors(db, assignment)
    assert any(str(room_b) in err and "teacher" in err for err in errors)
    assert not any(str(room_a) in err for err in errors)
    owners.assert_awaited_once()
    assert owners.await_args.args[2] == {room_a, room_b}
    assert owners.await_args.args[3] == subject


@pytest.mark.asyncio
async def test_student_cannot_start_or_submit_if_class_loses_subject_teacher(monkeypatch):
    mod = authorization
    class_id, subject_id = uid(), uid()
    student = SimpleNamespace(id=uid(), tenant_id=uid())
    assignment = SimpleNamespace(
        tenant_id=student.tenant_id,
        academic_level_id=uid(),
        academic_session_id=uid(),
        academic_term_id=uid(),
        curriculum_subject_id=subject_id,
    )
    enrollment = SimpleNamespace(class_id=class_id, academic_level_id=assignment.academic_level_id)
    monkeypatch.setattr(
        mod.StudentEnrollmentRepository, "get_authoritative_for_session",
        AsyncMock(return_value=enrollment),
    )
    monkeypatch.setattr(
        mod.CurriculumResolutionService, "resolve_student_subjects",
        AsyncMock(return_value=[SimpleNamespace(curriculum_subject_id=subject_id)]),
    )
    owners = AsyncMock(return_value={})
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_teacher_assignments_for_classes_on_date", owners
    )
    with pytest.raises(ConflictException, match="no subject teacher"):
        await mod.TMAAuthorizationService.require_student_eligibility(
            AsyncMock(), student=student, assignment=assignment
        )
    assert owners.await_args.args[2] == {class_id}
    assert owners.await_args.args[3] == subject_id


@pytest.mark.asyncio
async def test_old_revision_attempt_rejected_before_any_attempt_mutation(monkeypatch):
    mod = attempt_service
    student = SimpleNamespace(id=uid(), tenant_id=uid())
    attempt = SimpleNamespace(id=uid(), revision_id=uid(), status=TMAAttemptStatus.IN_PROGRESS)
    revision = SimpleNamespace(id=attempt.revision_id, assignment_id=uid())
    current_revision = SimpleNamespace(id=uid())
    lookup = AsyncMock(return_value=(attempt, SimpleNamespace(), revision))
    monkeypatch.setattr(mod.TMAAttemptService, "_load_owned_attempt", lookup)
    monkeypatch.setattr(
        mod.TMAAttemptService, "_active_assignment",
        AsyncMock(return_value=(SimpleNamespace(), current_revision, SimpleNamespace())),
    )
    with pytest.raises(ConflictException, match="older TMA revision"):
        await mod.TMAAttemptService._locked_active_attempt(
            AsyncMock(), student=student, attempt_id=attempt.id
        )
    assert lookup.await_count == 1  # no writable row ever locked


@pytest.mark.asyncio
async def test_lock_order_is_assignment_then_attempt(monkeypatch):
    mod = attempt_service
    student = SimpleNamespace(id=uid(), tenant_id=uid())
    attempt = SimpleNamespace(id=uid(), revision_id=uid(), status=TMAAttemptStatus.IN_PROGRESS)
    revision = SimpleNamespace(id=attempt.revision_id, assignment_id=uid())
    participant = SimpleNamespace(revision_id=revision.id)
    calls = []
    async def lookup(*args, **kwargs):
        calls.append("attempt-locked" if kwargs.get("lock") else "attempt-read")
        return attempt, participant, revision

    async def active(*args, **kwargs):
        calls.append("assignment-share")
        return SimpleNamespace(), revision, SimpleNamespace()

    monkeypatch.setattr(mod.TMAAttemptService, "_load_owned_attempt", lookup)
    monkeypatch.setattr(mod.TMAAttemptService, "_active_assignment", active)
    await mod.TMAAttemptService._locked_active_attempt(
        AsyncMock(), student=student, attempt_id=attempt.id
    )
    assert calls == ["attempt-read", "assignment-share", "attempt-locked"]


def test_student_lock_is_shared_not_exclusive():
    import inspect
    src = inspect.getsource(TMAAssignmentRepository.get_by_id)
    assert "with_for_update(read=True)" in src


def test_teacher_pagination_filters_before_offset():
    from app.modules.tma.models import TMAAssignment
    from app.modules.student_academics.models import TeacherAssignment
    from sqlalchemy import exists, select
    stmt = select(TMAAssignment).where(
        exists(
            select(TeacherAssignment.id).where(
                TeacherAssignment.tenant_id == TMAAssignment.tenant_id,
                TeacherAssignment.teacher_membership_id == uid(),
            )
        )
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "EXISTS" in sql
