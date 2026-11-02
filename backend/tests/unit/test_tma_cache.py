import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.cache import manager
from app.core.cache.events import CACHE_INVALIDATION_EVENTS, flush_cache_invalidation_events
from app.modules.tma import cache
from app.modules.tma.cache_events import queue_tma_invalidations, discard_tma_invalidations
from app.modules.tma.models import TMAAssignment
from app.modules.student_academics.models import AssessmentComponent


class RedisStub:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def unlink(self, *keys):
        count = 0
        for key in keys:
            count += key in self.values
            self.values.pop(key, None)
        return count


@pytest.fixture
def redis(monkeypatch):
    stub = RedisStub()
    monkeypatch.setattr(cache, "get_redis", lambda: stub)
    monkeypatch.setattr(manager, "get_redis", lambda: stub)
    return stub


@pytest.mark.asyncio
async def test_staff_cache_hit_and_isolation(redis):
    actor = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    fetch = AsyncMock(return_value={"items": ["question"]})
    assert await cache.cached_staff_read(actor, "questions", fetch, ttl=15) == {
        "items": ["question"]
    }
    assert await cache.cached_staff_read(actor, "questions", fetch, ttl=15) == {
        "items": ["question"]
    }
    assert fetch.await_count == 1
    await cache.cached_staff_read(
        SimpleNamespace(tenant_id=uuid4(), id=actor.id), "questions", fetch
    )
    await cache.cached_staff_read(
        SimpleNamespace(tenant_id=actor.tenant_id, id=uuid4()), "questions", fetch
    )
    await cache.cached_staff_read(actor, "questions", fetch, params={"assignment": uuid4()})
    assert fetch.await_count == 4
    assert 15 in redis.ttls.values()
    assert all(key.startswith("tenant:") for key in redis.values)


@pytest.mark.asyncio
async def test_cache_key_separates_pages_and_reuses_canonical_parameters(redis):
    actor = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    fetch = AsyncMock(return_value={"items": []})
    await cache.cached_staff_read(actor, "assignments", fetch, params={"offset": 0, "limit": 24})
    await cache.cached_staff_read(actor, "assignments", fetch, params={"limit": 24, "offset": 0})
    await cache.cached_staff_read(actor, "assignments", fetch, params={"offset": 24, "limit": 24})
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_commit_flush_invalidates_tma_namespace(redis):
    actor = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    fetch = AsyncMock(return_value={"score": "old"})
    await cache.cached_staff_read(actor, "assignments", fetch)
    session = Session()
    session.add(TMAAssignment(tenant_id=actor.tenant_id))
    queue_tma_invalidations(session)
    assert cache.generation_key(actor.tenant_id) in redis.values
    await flush_cache_invalidation_events(SimpleNamespace(sync_session=session))
    fetch.return_value = {"score": "new"}
    assert await cache.cached_staff_read(actor, "assignments", fetch) == {"score": "new"}
    assert fetch.await_count == 2
    session.close()


def test_rollback_discards_tma_invalidation_and_academic_edits_queue_it():
    session = Session()
    tenant = uuid4()
    session.add(AssessmentComponent(tenant_id=tenant))
    queue_tma_invalidations(session)
    assert any(
        event.value == cache.generation_key(tenant)
        for event in session.info[CACHE_INVALIDATION_EVENTS]
    )
    discard_tma_invalidations(session, SimpleNamespace(parent=object()))
    assert session.info[CACHE_INVALIDATION_EVENTS]
    discard_tma_invalidations(session)
    assert not session.info[CACHE_INVALIDATION_EVENTS]
    session.close()


@pytest.mark.asyncio
async def test_inflight_read_cannot_restore_invalidated_namespace(redis):
    actor = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow():
        started.set()
        await release.wait()
        return {"value": "old"}

    old = asyncio.create_task(cache.cached_staff_read(actor, "questions", slow))
    await started.wait()
    await redis.unlink(cache.generation_key(actor.tenant_id))
    fresh = AsyncMock(return_value={"value": "new"})
    await cache.cached_staff_read(actor, "questions", fresh)
    release.set()
    await old
    assert await cache.cached_staff_read(actor, "questions", fresh) == {"value": "new"}
    assert fresh.await_count == 1


@pytest.mark.asyncio
async def test_redis_unavailable_or_failed_fetch_does_not_block_or_cache_errors(redis, monkeypatch):
    actor = SimpleNamespace(tenant_id=uuid4(), id=uuid4())
    fail = AsyncMock(side_effect=RuntimeError("database failure"))
    with pytest.raises(RuntimeError):
        await cache.cached_staff_read(actor, "questions", fail)
    assert list(redis.values) == [cache.generation_key(actor.tenant_id)]
    monkeypatch.setattr(cache, "get_redis", lambda: None)
    fetch = AsyncMock(return_value={"items": []})
    assert await cache.cached_staff_read(actor, "questions", fetch) == {"items": []}


@pytest.mark.asyncio
async def test_cached_questions_cannot_bypass_current_assignment_access(monkeypatch):
    from app.modules.tma import router
    from app.modules.tenant_admins.models import TenantAdmin
    from app.core.exceptions import ForbiddenException

    cached = AsyncMock(return_value=[])
    monkeypatch.setattr(router, "cached_staff_read", cached)
    monkeypatch.setattr(
        router.TMAAssignmentService,
        "get_assignment",
        AsyncMock(side_effect=ForbiddenException("Access revoked")),
    )
    with pytest.raises(ForbiddenException):
        await router.list_questions(uuid4(), None, TenantAdmin(id=uuid4(), tenant_id=uuid4()))
    cached.assert_not_awaited()
