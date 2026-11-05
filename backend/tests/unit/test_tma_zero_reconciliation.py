"""Auditable, tenant-safe manual exceptions to missed-TMA automatic zeros."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.teachers.models import TeacherMembership
from app.modules.tma import zero_reconciliation_service as mod
from app.modules.tma.models import TMAAssignmentStatus


def uid():
    return uuid.uuid4()


def fixture():
    actor = TenantAdmin(id=uid(), tenant_id=uid())
    assignment = SimpleNamespace(
        tenant_id=actor.tenant_id,
        id=uid(),
        current_revision_number=1,
        status=TMAAssignmentStatus.CLOSED,
        closed_at=datetime.now(timezone.utc),
        zero_grading_requested_at=datetime.now(timezone.utc),
        zero_grading_completed_at=None,
    )
    student = uid()
    failure = SimpleNamespace(
        id=uid(),
        tenant_id=actor.tenant_id,
        assignment_id=assignment.id,
        student_id=student,
        reason="Class has no teacher",
        attempts=2,
        resolved_at=None,
        resolution=None,
        resolution_note=None,
        resolved_by_actor_id=None,
    )
    return actor, assignment, student, failure


@pytest.mark.asyncio
async def test_admin_exemption_is_audited_and_does_not_write_any_score(monkeypatch):
    actor, assignment, student, failure = fixture()
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    row = MagicMock()
    row.scalar_one_or_none.return_value = failure
    empty = MagicMock()
    empty.first.return_value = None
    db = AsyncMock()
    db.execute.side_effect = [row, empty]
    invalidation = AsyncMock()
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", invalidation)
    from app.core.queue import arq

    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(arq, "enqueue_tma_zero_grading_job", enqueue)
    result = await mod.TMAZeroReconciliationService.exempt(
        db,
        actor=actor,
        assignment_id=assignment.id,
        student_id=student,
        reason="Student joined after closure",
    )
    assert result is failure
    assert result.resolution == "exempt"
    assert result.resolution_note == "Student joined after closure"
    assert result.resolved_by_actor_id == actor.id
    assert result.resolved_at is not None
    db.commit.assert_awaited_once()
    db.delete.assert_not_awaited()
    invalidation.assert_awaited_once_with(db)
    enqueue.assert_awaited_once_with(
        assignment_id=str(assignment.id),
        tenant_id=str(actor.tenant_id),
        closed_at=assignment.closed_at.isoformat(),
        reconciliation_id=str(failure.id),
    )


@pytest.mark.asyncio
async def test_teacher_cannot_exempt_student_even_when_lead():
    actor, assignment, student, failure = fixture()
    teacher = TeacherMembership(id=uid(), tenant_id=actor.tenant_id)
    with pytest.raises(ForbiddenException, match="administrator"):
        await mod.TMAZeroReconciliationService.exempt(
            AsyncMock(),
            actor=teacher,
            assignment_id=assignment.id,
            student_id=student,
            reason="Administrator only",
        )


@pytest.mark.asyncio
async def test_exemption_rejects_recorded_submission(monkeypatch):
    actor, assignment, student, failure = fixture()
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    result = MagicMock()
    result.scalar_one_or_none.return_value = failure
    submission = MagicMock()
    submission.first.return_value = (uid(),)
    db = AsyncMock()
    db.execute.side_effect = [result, submission]
    with pytest.raises(ConflictException, match="already has a score"):
        await mod.TMAZeroReconciliationService.exempt(
            db,
            actor=actor,
            assignment_id=assignment.id,
            student_id=student,
            reason="Exemption must not erase scores",
        )
    assert failure.resolved_at is None
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_tenant_cannot_view_blocked_students(monkeypatch):
    actor, assignment, student, failure = fixture()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=None))
    db = AsyncMock()
    with pytest.raises(NotFoundException):
        await mod.TMAZeroReconciliationService.list_conflicts(
            db, actor=actor, assignment_id=assignment.id
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_exemption_remains_successful_if_redis_dispatch_fails(monkeypatch):
    from app.core.queue import arq

    actor, assignment, student, failure = fixture()
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    row = MagicMock()
    row.scalar_one_or_none.return_value = failure
    empty = MagicMock()
    empty.first.return_value = None
    db = AsyncMock()
    db.execute.side_effect = [row, empty]
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", AsyncMock())
    enqueue = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    monkeypatch.setattr(arq, "enqueue_tma_zero_grading_job", enqueue)

    result = await mod.TMAZeroReconciliationService.exempt(
        db,
        actor=actor,
        assignment_id=assignment.id,
        student_id=student,
        reason="Recorded academic exception",
    )
    assert result is failure
    assert result.resolution == "exempt"
    db.commit.assert_awaited_once()
    enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_context_resolves_students_without_cross_tenant_lookup():
    from sqlalchemy.dialects import postgresql

    from app.modules.tma.router import _reconciliation_student_context

    tenant_id, assignment_id, student_id, class_id = uid(), uid(), uid(), uid()
    row = MagicMock()
    row.all.return_value = [(student_id, "Ada", "Lovelace", "ADM-102", class_id)]
    db = AsyncMock()
    db.execute.return_value = row

    context = await _reconciliation_student_context(
        db,
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        student_ids={student_id},
    )
    assert context[student_id] == {
        "student_name": "Ada Lovelace",
        "admission_number": "ADM-102",
        "class_id": class_id,
    }
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "students.tenant_id" in sql
    assert "tma_closure_eligibility" in sql
    assert "tma_closure_runs" in sql
    assert "students.id IN" in sql


@pytest.mark.asyncio
async def test_empty_reconciliation_context_does_not_hit_database():
    from app.modules.tma.router import _reconciliation_student_context

    db = AsyncMock()
    assert (
        await _reconciliation_student_context(
            db, tenant_id=uid(), assignment_id=uid(), student_ids=set()
        )
        == {}
    )
    db.execute.assert_not_awaited()
