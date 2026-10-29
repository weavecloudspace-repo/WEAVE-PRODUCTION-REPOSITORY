"""Redis cache generations avoid cross-tenant leakage and stale post-mutation reads."""
from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import BaseModel

from app.modules.cbt.ai.quota import cache


class Balance(BaseModel):
    remaining: int


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def incr(self, key):
        current = int(self.values.get(key, "0"))
        self.values[key] = str(current + 1)
        return current + 1


@pytest.mark.asyncio
async def test_quota_cache_reuses_reads_then_invalidates_after_commit(monkeypatch):
    redis = FakeRedis()
    entries = {}
    monkeypatch.setattr(cache, "get_redis", lambda: redis)
    monkeypatch.setattr(cache.settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(cache.settings, "AI_QUOTA_READ_CACHE_ENABLED", True)

    async def get_json(key):
        return entries.get(key)

    async def set_json(key, value, ttl):
        assert ttl > 0
        entries[key] = value
        return True

    monkeypatch.setattr(cache.CacheManager, "get_json", get_json)
    monkeypatch.setattr(cache.CacheManager, "set_json", set_json)
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    other = UUID("00000000-0000-0000-0000-000000000002")
    state = {"remaining": 100, "calls": 0}

    async def fetch():
        state["calls"] += 1
        return Balance(remaining=state["remaining"])

    async def read(tid):
        return await cache.get_cached_quota(
            tenant_id=tid,
            identity="actor:teacher:123",
            response_type=Balance,
            fetcher=fetch,
        )

    assert (await read(tenant)).remaining == 100
    assert (await read(tenant)).remaining == 100
    assert state["calls"] == 1
    state["remaining"] = 80
    await cache.invalidate_quota_cache(tenant)
    assert (await read(tenant)).remaining == 80
    assert state["calls"] == 2
    assert (await read(other)).remaining == 80
    assert state["calls"] == 3  # Per-tenant namespace isolation


@pytest.mark.asyncio
async def test_redis_unavailable_falls_back_to_database(monkeypatch):
    monkeypatch.setattr(cache, "get_redis", lambda: None)
    calls = []
    async def fetch():
        calls.append(True)
        return Balance(remaining=10)
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    await cache.get_cached_quota(
        tenant_id=tenant, identity="quota", response_type=Balance, fetcher=fetch
    )
    await cache.get_cached_quota(
        tenant_id=tenant, identity="quota", response_type=Balance, fetcher=fetch
    )
    assert len(calls) == 2
