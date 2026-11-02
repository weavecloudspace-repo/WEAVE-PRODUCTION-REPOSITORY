"""Draft TMA deletion safeguards, ordering, and durable media cleanup."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Delete

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.teachers.models import TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma import draft_deletion_service as mod
from app.modules.tma.models import (
    TMAAssignmentStatus,
    TMADraftMediaCleanup,
    TMAMediaAsset,
    TMAQuestion,
    TMAQuestionOption,
    TMAAssignmentRevision,
    TMAAssignment,
)


def uid() -> uuid.UUID:
    return uuid.uuid4()


def context():
    admin = TenantAdmin(id=uid(), tenant_id=uid())
    assignment = SimpleNamespace(
        id=uid(),
        tenant_id=admin.tenant_id,
        status=TMAAssignmentStatus.DRAFT,
        current_revision_number=1,
        activated_at=None,
        closed_at=None,
        zero_grading_requested_at=None,
        created_by_actor_type="tenant_admin",
        created_by_actor_id=admin.id,
        lead_teacher_membership_id=None,
    )
    revision = SimpleNamespace(id=uid(), revision_number=1, published_at=None, invalidated_at=None)
    return admin, assignment, revision


def row_result(*, all_rows=None, first=None):
    return SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: all_rows or []),
        first=lambda: first,
    )


def db_for_delete(revision, *, assets=None, student=None, cancellation=None):
    db = AsyncMock()
    db.add_all = Mock()
    db.execute.side_effect = [
        row_result(all_rows=[revision]),
        row_result(first=student),
        row_result(first=cancellation),
        row_result(all_rows=assets or []),
        *[row_result() for _ in range(5)],
    ]
    return db


def setup(monkeypatch, assignment):
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    invalidate = Mock()
    flush = AsyncMock()
    monkeypatch.setattr(mod, "queue_cache_key_invalidation", invalidate)
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", flush)
    return invalidate, flush


@pytest.mark.asyncio
async def test_delete_draft_removes_children_in_dependency_order_and_queues_images(monkeypatch):
    admin, assignment, revision = context()
    keys = ["tenants/one/tma/image-a.png", "tenants/one/tma/image-b.png"]
    db = db_for_delete(revision, assets=keys)
    invalidate, flushed = setup(monkeypatch, assignment)
    await mod.TMADraftDeletionService.delete_draft(
        db, actor=admin, assignment_id=assignment.id
    )

    assert db.add_all.call_count == 1
    queued = db.add_all.call_args.args[0]
    assert [item.object_key for item in queued] == keys
    assert all(isinstance(item, TMADraftMediaCleanup) for item in queued)
    assert all(item.tenant_id == admin.tenant_id for item in queued)
    assert all(item.assignment_id == assignment.id for item in queued)
    deleted = [call.args[0].table.name for call in db.execute.call_args_list[4:]]
    assert deleted == [
        TMAQuestionOption.__tablename__,
        TMAQuestion.__tablename__,
        TMAMediaAsset.__tablename__,
        TMAAssignmentRevision.__tablename__,
        TMAAssignment.__tablename__,
    ]
    assert all(isinstance(call.args[0], Delete) for call in db.execute.call_args_list[4:])
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
    invalidate.assert_called_once()
    flushed.assert_awaited_once_with(db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"status": TMAAssignmentStatus.ACTIVE},
        {"status": TMAAssignmentStatus.CLOSED},
        {"status": TMAAssignmentStatus.CANCELLED},
        {"current_revision_number": 2},
        {"activated_at": "published"},
        {"closed_at": "closed"},
        {"zero_grading_requested_at": "graded"},
    ],
)
async def test_protected_assignments_never_delete(monkeypatch, changes):
    admin, assignment, revision = context()
    for key, value in changes.items():
        setattr(assignment, key, value)
    setup(monkeypatch, assignment)
    db = db_for_delete(revision)
    with pytest.raises(ConflictException, match="never-published"):
        await mod.TMADraftDeletionService.delete_draft(
            db, actor=admin, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()
    db.add_all.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("published,invalidated,revision_count", [(True, False, 1), (False, True, 1), (False, False, 2)])
async def test_historical_revision_is_immutable(monkeypatch, published, invalidated, revision_count):
    admin, assignment, revision = context()
    revision.published_at = "published" if published else None
    revision.invalidated_at = "invalidated" if invalidated else None
    setup(monkeypatch, assignment)
    db = db_for_delete(revision)
    db.execute.side_effect = [
        row_result(all_rows=[revision] * revision_count),
    ]
    with pytest.raises(ConflictException, match="revision history"):
        await mod.TMADraftDeletionService.delete_draft(
            db, actor=admin, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("student,cancellation", [(uuid.uuid4(), None), (None, uuid.uuid4())])
async def test_student_or_cancellation_history_blocks_deletion(monkeypatch, student, cancellation):
    admin, assignment, revision = context()
    setup(monkeypatch, assignment)
    db = db_for_delete(revision, student=student, cancellation=cancellation)
    with pytest.raises(ConflictException, match="student or cancellation history"):
        await mod.TMADraftDeletionService.delete_draft(
            db, actor=admin, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()
    db.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_collaborator_cannot_delete_an_admin_created_draft(monkeypatch):
    admin, assignment, revision = context()
    collaborator = TeacherMembership(id=uid(), tenant_id=admin.tenant_id)
    setup(monkeypatch, assignment)
    db = db_for_delete(revision)
    with pytest.raises(ForbiddenException):
        await mod.TMADraftDeletionService.delete_draft(
            db, actor=collaborator, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_assignment_cannot_be_deleted(monkeypatch):
    admin, assignment, revision = context()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=None))
    db = db_for_delete(revision)
    with pytest.raises(NotFoundException):
        await mod.TMADraftDeletionService.delete_draft(
            db, actor=admin, assignment_id=assignment.id
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_cleanup_retries_failures_and_deletes_successful_jobs(monkeypatch):
    okay = SimpleNamespace(
        id=uid(), tenant_id=uid(), assignment_id=uid(),
        object_key="one", attempts=0, last_error=None
    )
    broken = SimpleNamespace(
        id=uid(), tenant_id=uid(), assignment_id=uid(),
        object_key="two", attempts=0, last_error=None
    )
    storage = SimpleNamespace(delete_object=AsyncMock(side_effect=[None, RuntimeError("offline")]))
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    db = AsyncMock()
    db.execute.return_value = row_result(all_rows=[okay, broken])
    result = await mod.TMADraftDeletionService.cleanup_media(db)
    assert result == {"deleted": 1, "failed": 1}
    db.delete.assert_awaited_once_with(okay)
    assert broken.attempts == 1
    assert "offline" in broken.last_error
    db.commit.assert_awaited_once()
    assert storage.delete_object.await_count == 2


@pytest.mark.asyncio
async def test_no_pending_media_cleanup_is_noop(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = row_result()
    assert await mod.TMADraftDeletionService.cleanup_media(db) == {"deleted": 0, "failed": 0}
    db.commit.assert_not_awaited()
