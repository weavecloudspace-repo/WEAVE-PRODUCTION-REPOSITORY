"""Scheduled continuity activation must honor due dates and idempotency."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.student_academics.models import AcademicSessionStatus
from app.modules.students.models import StudentEnrollmentOutcome
from app.modules.students.scheduled_result_continuity import (
    ACTIVATED_ACTION,
    PENDING_ACTION,
    ScheduledResultContinuityService,
)


def _fixtures():
    tenant, student_id, session_id, level_id, audit_id = (uuid4() for _ in range(5))
    dest = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        student_id=student_id,
        academic_session_id=session_id,
        academic_level_id=level_id,
        class_id=uuid4(),
        started_on=date.today(),
        entry_outcome=StudentEnrollmentOutcome.RECLASSIFIED,
    )
    pending = SimpleNamespace(
        id=audit_id,
        tenant_id=tenant,
        entity_id=dest.id,
        acting_admin_id=uuid4(),
        reason="Move to next arm",
        metadata_json={
            "student_id": str(student_id),
            "academic_session_id": str(session_id),
            "source_level_id": str(level_id),
            "carry_finalized_results": False,
        },
    )
    return dest, pending


@pytest.mark.asyncio
async def test_due_scan_ignores_cancelled_enrollments_and_finished_markers():
    audit_id = uuid4()
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [audit_id]))
    )
    due = await ScheduledResultContinuityService.due_ids(db, limit=10)
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert due == [audit_id]
    assert "student_enrollments" in sql
    assert "NOT (EXISTS" in sql
    assert "started_on <= CURRENT_DATE" in sql
    assert "academic_sessions" in sql
    assert "academic_terms" in sql
    assert "row_number() OVER" in sql
    assert "tenant_position" in sql
    assert "academic_sessions.is_current IS true" in sql
    assert "academic_terms.is_current IS true" in sql
    assert PENDING_ACTION in statement.compile().params.values()
    assert ACTIVATED_ACTION in statement.compile().params.values()


@pytest.mark.asyncio
async def test_future_destination_does_not_transfer_results(monkeypatch):
    from app.modules.students import scheduled_result_continuity as mod

    dest, pending = _fixtures()
    dest.started_on = date.today() + timedelta(days=5)
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: pending),
                SimpleNamespace(scalar_one_or_none=lambda: None),
            ]
        ),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", AsyncMock(return_value=dest))
    apply = AsyncMock()
    monkeypatch.setattr(mod.AcademicResultContinuityService, "apply", apply)

    assert await ScheduledResultContinuityService.activate_one(db, pending.id) is None
    apply.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_worker_activation_is_idempotent(monkeypatch):
    from app.modules.students import scheduled_result_continuity as mod

    _dest, pending = _fixtures()
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: pending),
                SimpleNamespace(scalar_one_or_none=lambda: uuid4()),
            ]
        ),
        commit=AsyncMock(),
    )
    get = AsyncMock()
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", get)
    assert await ScheduledResultContinuityService.activate_one(db, pending.id) is None
    get.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_revalidates_and_commits_audited_changes(monkeypatch):
    from app.modules.students import scheduled_result_continuity as mod

    dest, pending = _fixtures()
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: pending),
                SimpleNamespace(scalar_one_or_none=lambda: None),
                SimpleNamespace(
                    scalar_one_or_none=lambda: SimpleNamespace(
                        status=AcademicSessionStatus.OPEN, is_current=True
                    )
                ),
            ]
        ),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", AsyncMock(return_value=dest))
    monkeypatch.setattr(
        mod.StudentEnrollmentRepository, "get_current", AsyncMock(return_value=dest)
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    apply = AsyncMock(
        return_value=[
            SimpleNamespace(applied=True),
            SimpleNamespace(applied=True),
            SimpleNamespace(applied=False),
        ]
    )
    audit = AsyncMock()
    invalidate = AsyncMock()
    commit = AsyncMock()
    monkeypatch.setattr(mod.AcademicResultContinuityService, "apply", apply)
    monkeypatch.setattr(mod.StudentAcademicRepository, "add_academic_lifecycle_audit", audit)
    monkeypatch.setattr(mod.StudentPlacementService, "_invalidate_derived_context", invalidate)
    monkeypatch.setattr(mod.StudentPlacementService, "_commit_with_readiness_invalidation", commit)
    changed = await ScheduledResultContinuityService.activate_one(db, pending.id)

    assert changed == 2
    assert apply.await_args.kwargs["destination_enrollment"] is dest
    assert apply.await_args.kwargs["effective_date"] == dest.started_on
    invalidate.assert_awaited_once()
    activated = audit.await_args.args[1]
    assert activated.action == ACTIVATED_ACTION
    assert activated.metadata_json["result_corrections"] == 2
    commit.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_edited_cross_level_move_never_forwards_old_results(monkeypatch):
    from app.modules.students import scheduled_result_continuity as mod

    dest, pending = _fixtures()
    dest.academic_level_id = uuid4()
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: pending),
                SimpleNamespace(scalar_one_or_none=lambda: None),
                SimpleNamespace(
                    scalar_one_or_none=lambda: SimpleNamespace(
                        status=AcademicSessionStatus.OPEN, is_current=True
                    )
                ),
            ]
        ),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", AsyncMock(return_value=dest))
    monkeypatch.setattr(
        mod.StudentEnrollmentRepository, "get_current", AsyncMock(return_value=dest)
    )
    apply = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(mod.AcademicResultContinuityService, "apply", apply)
    monkeypatch.setattr(mod.StudentAcademicRepository, "add_academic_lifecycle_audit", audit)

    assert await ScheduledResultContinuityService.activate_one(db, pending.id) == 0
    apply.assert_not_awaited()
    assert audit.await_args.args[1].metadata_json["outcome"] == "skipped"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduled_activation_takes_lifecycle_lock_before_enrollment_lock(monkeypatch):
    from app.modules.students import scheduled_result_continuity as mod

    dest, pending = _fixtures()
    dest.started_on = date.today() + timedelta(days=1)
    events = []

    async def guard(*_args, **_kwargs):
        events.append("lifecycle")

    async def load(*_args, **_kwargs):
        events.append("enrollment")
        return dest

    monkeypatch.setattr(mod, "ensure_academic_write_window", guard)
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", load)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: pending),
                SimpleNamespace(scalar_one_or_none=lambda: None),
            ]
        ),
        commit=AsyncMock(),
    )
    assert await ScheduledResultContinuityService.activate_one(db, pending.id) is None
    assert events == ["lifecycle", "enrollment"]


@pytest.mark.asyncio
async def test_due_scan_skips_failed_markers_during_bounded_backoff():
    from app.modules.students.scheduled_result_continuity import RETRY_ACTION

    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])))
    await ScheduledResultContinuityService.due_ids(db)
    statement = db.execute.await_args.args[0]
    params = statement.compile().params
    assert RETRY_ACTION in params.values()
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "created_at >=" in sql
    assert "NOT (EXISTS" in sql


@pytest.mark.asyncio
async def test_failed_activation_creates_retry_marker_for_same_tenant_only():
    from app.modules.student_academics.models import AcademicLifecycleAudit
    from app.modules.students.scheduled_result_continuity import RETRY_ACTION

    _, pending = _fixtures()
    nonlocal_marker: list[AcademicLifecycleAudit] = []
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: pending)),
        add=lambda value: nonlocal_marker.append(value),
        commit=AsyncMock(),
    )
    await ScheduledResultContinuityService.defer_failed(db, pending.id)
    assert len(nonlocal_marker) == 1
    marker = nonlocal_marker[0]
    assert marker.action == RETRY_ACTION
    assert marker.tenant_id == pending.tenant_id
    assert marker.entity_id == pending.entity_id
    assert marker.metadata_json["scheduled_audit_id"] == str(pending.id)
    db.commit.assert_awaited_once()
