"""Automatic TMA deadline closure: safe worker replay and immediate write cutoff."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ConflictException
from app.modules.tma.models import TMAAssignmentStatus
from app.modules.tma import attempt_service as attempts
from app.modules.tma import expiration_service as expiration


def _assignment(*, closes_at: datetime | None = None, status=TMAAssignmentStatus.ACTIVE):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status=status,
        closes_at=closes_at,
        closed_at=None,
        current_revision_number=1,
    )


@pytest.mark.asyncio
async def test_worker_closes_due_assignments_without_touching_student_scores(monkeypatch):
    current = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
    first = _assignment(closes_at=current - timedelta(minutes=1))
    second = _assignment(closes_at=current)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [first, second])
    )
    invalidation = AsyncMock()
    monkeypatch.setattr(expiration, "flush_cache_invalidation_events", invalidation)

    result = await expiration.TMAExpirationService.close_due_assignments(
        db, now=current, batch_size=20
    )

    assert result == {"closed": 2}
    assert first.status == TMAAssignmentStatus.CLOSED
    assert second.status == TMAAssignmentStatus.CLOSED
    assert first.closed_at == current
    assert second.closed_at == current
    db.commit.assert_awaited_once()
    invalidation.assert_awaited_once_with(db)
    query = db.execute.call_args.args[0]
    assert "FOR UPDATE SKIP LOCKED" in str(
        query.compile(
            compile_kwargs={"literal_binds": True},
            dialect=postgresql.dialect(),
        )
    )


@pytest.mark.asyncio
async def test_worker_is_idempotent_when_no_due_assignments(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )
    invalidation = AsyncMock()
    monkeypatch.setattr(expiration, "flush_cache_invalidation_events", invalidation)
    assert await expiration.TMAExpirationService.close_due_assignments(db) == {"closed": 0}
    db.commit.assert_not_awaited()
    invalidation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("past", [True, False])
async def test_student_write_guard_enforces_exact_deadline_even_before_worker(monkeypatch, past):
    now = datetime.now(timezone.utc)
    assignment = _assignment(
        closes_at=now - timedelta(seconds=1) if past else now + timedelta(minutes=10)
    )
    student = SimpleNamespace(tenant_id=assignment.tenant_id)
    monkeypatch.setattr(
        attempts.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    term = AsyncMock()
    enrollment = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(attempts.TMAAuthorizationService, "require_open_term", term)
    monkeypatch.setattr(attempts.TMAAuthorizationService, "require_student_eligibility", enrollment)
    revision = SimpleNamespace(
        id=uuid.uuid4(), published_at=now - timedelta(days=1), invalidated_at=None
    )
    monkeypatch.setattr(
        attempts.TMARevisionRepository, "get_by_number", AsyncMock(return_value=revision)
    )

    if past:
        with pytest.raises(ConflictException, match="deadline"):
            await attempts.TMAAttemptService._active_assignment(
                AsyncMock(), student=student, assignment_id=assignment.id
            )
        term.assert_not_awaited()
    else:
        actual, active_revision, _ = await attempts.TMAAttemptService._active_assignment(
            AsyncMock(), student=student, assignment_id=assignment.id
        )
        assert actual is assignment
        assert active_revision is revision


@pytest.mark.asyncio
async def test_closed_status_blocks_student_write_even_without_deadline(monkeypatch):
    assignment = _assignment(status=TMAAssignmentStatus.CLOSED)
    monkeypatch.setattr(
        attempts.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    with pytest.raises(ConflictException, match="not active"):
        await attempts.TMAAttemptService._active_assignment(
            AsyncMock(),
            student=SimpleNamespace(tenant_id=assignment.tenant_id),
            assignment_id=assignment.id,
        )


@pytest.mark.asyncio
async def test_reopening_expired_assignment_requires_new_deadline(monkeypatch):
    from app.modules.tma import lifecycle_service as lifecycle
    from app.modules.tenant_admins.models import TenantAdmin

    owner = TenantAdmin(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    assignment = _assignment(
        closes_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status=TMAAssignmentStatus.CLOSED,
    )
    assignment.tenant_id = owner.tenant_id
    db = AsyncMock()
    monkeypatch.setattr(
        lifecycle.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(lifecycle.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    monkeypatch.setattr(
        lifecycle.TMAAuthorizationService, "require_assignment_management", lambda *_: None
    )
    with pytest.raises(ConflictException, match="Extend or clear"):
        await lifecycle.TMALifecycleService.reopen_assignment(
            db, actor=owner, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()


def test_worker_cron_preserves_cbts_and_tma_cancellation_jobs():
    from app.core.queue.heavy_worker import WorkerSettings

    names = {fn.__name__ for fn in WorkerSettings.functions}
    cron_names = {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}
    assert {"process_cbt_result_rollback_job", "process_tma_cancellation_job"} <= names
    assert {
        "poll_tma_deadlines",
        "poll_tma_cancellations",
        "recover_cbt_result_rollbacks",
    } <= cron_names
