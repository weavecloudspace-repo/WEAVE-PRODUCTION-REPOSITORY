"""Version-aware tenant AI quota read cache.

Balance writes never use this cache. PostgreSQL remains authoritative, and a
monotonic Redis generation prevents older in-flight reads from repopulating the
active cache namespace after a committed credit mutation.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.config.settings import settings
from app.core.cache.manager import CacheManager
from app.core.cache.redis import get_redis

T = TypeVar("T", bound=BaseModel)


def generation_key(tenant_id: UUID) -> str:
    return f"tenant:{tenant_id}:cbt:ai:quota:generation"


async def _generation(tenant_id: UUID) -> str | None:
    if not settings.CACHE_ENABLED or not settings.AI_QUOTA_READ_CACHE_ENABLED:
        return None
    redis = get_redis()
    if redis is None:
        return None
    try:
        value = await redis.get(generation_key(tenant_id))
    except Exception:
        return None
    return value.decode("ascii") if isinstance(value, bytes) else str(value or "0")


async def get_cached_quota(
    *, tenant_id: UUID, identity: str, response_type: type[T],
    fetcher: Callable[[], Awaitable[T]],
) -> T:
    version = await _generation(tenant_id)
    if version is None:
        return await fetcher()
    week = datetime.now(timezone.utc).date().isocalendar()
    # Weekly quotas reset at ISO-week boundary; the cache must not cross weeks.
    key = f"tenant:{tenant_id}:cbt:ai:quota:v{version}:{week.year}-{week.week}:{identity}"
    cached = await CacheManager.get_json(key)
    if cached is not None:
        # Reject a hit when a concurrent credit mutation advanced the version.
        if await _generation(tenant_id) == version:
            return response_type.model_validate(cached)
    result = await fetcher()
    if await _generation(tenant_id) == version:
        await CacheManager.set_json(
            key, result.model_dump(mode="json"),
            settings.AI_QUOTA_READ_CACHE_TTL_SECONDS,
        )
    return result


async def invalidate_quota_cache(tenant_id: UUID) -> None:
    """Invoke only after an authoritative DB commit."""
    redis = get_redis()
    if redis is None:
        return
    try:
        await redis.incr(generation_key(tenant_id))
    except Exception:
        # Redis errors never roll back successful accounting transactions.
        return
