"""Reopening preserves published work and enforces lifecycle authorization."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.teachers.models import TeacherMembership
from app.modules.tma import lifecycle_service as mod
from app.modules.tma.models import TMAActorType, TMAAssignmentStatus


@pytest.fixture
def context(monkeypatch):
    actor = TenantAdmin(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    assignment = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=actor.tenant_id,
        status=TMAAssignmentStatus.CLOSED,
        current_revision_number=1,
        activated_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        created_by_actor_type=TMAActorType.TEACHER,
        created_by_actor_id=uuid.uuid4(),
    )
    revision = SimpleNamespace(published_at=assignment.activated_at, invalidated_at=None)
    lookup = AsyncMock(return_value=assignment)
    access = AsyncMock()
    readiness = AsyncMock(return_value=[])
    save = AsyncMock()
    invalidation = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", lookup)
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", access)
    monkeypatch.setattr(mod.TMALifecycleService, "_readiness_errors", readiness)
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_number", AsyncMock(return_value=revision)
    )
    monkeypatch.setattr(mod.TMARevisionRepository, "save", AsyncMock())
    monkeypatch.setattr(mod.TMAAssignmentRepository, "save", save)
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", invalidation)
    return SimpleNamespace(
        actor=actor,
        assignment=assignment,
        revision=revision,
        lookup=lookup,
        access=access,
        readiness=readiness,
        save=save,
        invalidation=invalidation,
        db=AsyncMock(),
    )


async def reopen(c):
    return await mod.TMALifecycleService.reopen_assignment(
        c.db, actor=c.actor, assignment_id=c.assignment.id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("teacher", [False, True])
async def test_reopen_preserves_revision_and_original_activation(context, teacher):
    c = context
    if teacher:
        c.actor = TeacherMembership(
            id=c.assignment.created_by_actor_id, tenant_id=c.actor.tenant_id
        )
    published_at = c.revision.published_at
    assert await reopen(c) is c.assignment
    assert c.assignment.status == TMAAssignmentStatus.ACTIVE
    assert c.assignment.closed_at is None
    assert c.assignment.activated_at == published_at
    assert c.assignment.current_revision_number == 1
    assert c.revision.published_at == published_at
    mod.TMARevisionRepository.save.assert_not_awaited()
    c.lookup.assert_awaited_once_with(c.db, c.actor.tenant_id, c.assignment.id, lock=True)
    c.access.assert_awaited_once_with(c.db, actor=c.actor, assignment=c.assignment)
    c.db.commit.assert_awaited_once()
    c.invalidation.assert_awaited_once_with(c.db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [s for s in TMAAssignmentStatus if s != TMAAssignmentStatus.CLOSED]
)
async def test_rejects_other_lifecycle_states(context, status):
    c = context
    c.assignment.status = status
    with pytest.raises(ConflictException, match="Only a closed"):
        await reopen(c)
    c.db.commit.assert_not_awaited()
    c.readiness.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_collaborator(context):
    c = context
    c.actor = TeacherMembership(id=uuid.uuid4(), tenant_id=c.actor.tenant_id)
    with pytest.raises(ForbiddenException):
        await reopen(c)
    c.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_wrong_tenant(context):
    c = context
    c.actor = TenantAdmin(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    with pytest.raises(NotFoundException):
        await reopen(c)
    c.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_assignment(context):
    c = context
    c.lookup.return_value = None
    with pytest.raises(NotFoundException):
        await reopen(c)
    c.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issue",
    ["Current academic session is not open.", "A valid current revision is required."],
)
async def test_failed_readiness_preserves_closed_state(context, issue):
    c = context
    c.readiness.return_value = [issue]
    with pytest.raises(ConflictException, match=issue):
        await reopen(c)
    assert c.assignment.status == TMAAssignmentStatus.CLOSED
    c.save.assert_not_awaited()
    c.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpublished_revision_cannot_reopen(context):
    c = context
    c.revision.published_at = None
    with pytest.raises(ConflictException, match="published revision"):
        await reopen(c)
    c.db.commit.assert_not_awaited()
