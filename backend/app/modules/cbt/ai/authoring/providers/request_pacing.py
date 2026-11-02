"""Shared Qwen vision request pacing for CBT AI.

Redis atomically reserves a slot for the SAME OpenRouter key/model across
workers and tenants. Without Redis, an in-process pace provides a safe local
development fallback; production should keep runtime Redis connected.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import time
import uuid
from collections.abc import AsyncIterator

from app.config.settings import settings
from app.core.cache.redis import get_runtime_redis

# Redis TIME is authoritative; no clocks from distinct application workers
# participate in the reservation calculation.
_RESERVE_SLOT = """
local parts = redis.call('TIME')
local now = tonumber(parts[1]) * 1000 + math.floor(tonumber(parts[2]) / 1000)
local next_at = tonumber(redis.call('GET', KEYS[1]) or '0')
local wait = math.max(0, next_at - now)
if wait > tonumber(ARGV[2]) then
    return -1
end
local slot = math.max(now, next_at)
redis.call('SET', KEYS[1], tostring(slot + tonumber(ARGV[1])), 'PX',
    math.ceil(wait + tonumber(ARGV[1]) + 60000))
return wait
"""

_EXTEND_COOLDOWN = """
local parts = redis.call('TIME')
local now = tonumber(parts[1]) * 1000 + math.floor(tonumber(parts[2]) / 1000)
local next_at = tonumber(redis.call('GET', KEYS[1]) or '0')
local target = math.max(next_at, now + tonumber(ARGV[1]))
redis.call('SET', KEYS[1], tostring(target), 'PX',
    math.ceil(target - now + 60000))
return target - now
"""


_IMAGE_PERMIT_ACQUIRE = """
local parts = redis.call('TIME')
local now = tonumber(parts[1]) * 1000 + math.floor(tonumber(parts[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    return 0
end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) + 60000)
return 1
"""


class OpenRouterPacingError(RuntimeError):
    """The provider is busy or the distributed pace is unavailable."""


class VisionRequestPacer:
    def __init__(self) -> None:
        self._gate = asyncio.Lock()
        self.local_vision_gate = asyncio.Semaphore(1)
        self.local_image_gate = asyncio.Semaphore(2)
        self._next_local: dict[str, float] = {}

    @asynccontextmanager
    async def image_global_permit(
        self,
        *,
        api_key: str,
        model: str,
        max_concurrent: int,
        max_wait: float,
        lease_seconds: float,
    ) -> AsyncIterator[None]:
        """Limit in-flight image calls globally, not only their start rate.

        Redis ZSET reservations are atomic. A bounded lease protects against
        leaked permits on worker crashes; a long provider timeout must fit
        within that lease. The local semaphore is acquired by the caller.
        """
        redis = get_runtime_redis()
        if redis is None:
            if settings.is_production_like:
                raise OpenRouterPacingError("Redis is required for distributed image concurrency.")
            yield
            return

        key = self._key(api_key, model) + ":active"
        token = uuid.uuid4().hex
        deadline = time.monotonic() + max_wait
        acquired = False
        try:
            while True:
                try:
                    acquired = bool(
                        await redis.eval(
                            _IMAGE_PERMIT_ACQUIRE,
                            1,
                            key,
                            max_concurrent,
                            max(1000, round(lease_seconds * 1000)),
                            token,
                        )
                    )
                except Exception as exc:
                    raise OpenRouterPacingError(
                        "Distributed image concurrency limiter unavailable."
                    ) from exc
                if acquired:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OpenRouterPacingError("Qwen image queue is full; retry later.")
                await asyncio.sleep(min(1.0, remaining))
            yield
        finally:
            if acquired:
                try:
                    await redis.zrem(key, token)
                except Exception:
                    # The Redis lease self-expires after worker/Redis failure.
                    pass

    @staticmethod
    def _key(api_key: str, model: str) -> str:
        fingerprint = hashlib.sha256(f"{api_key}:{model}".encode()).hexdigest()[:24]
        return f"cbt:openrouter:vision:next:{fingerprint}"

    async def wait_for_slot(
        self, *, api_key: str, model: str, interval: float, max_wait: float
    ) -> None:
        if interval <= 0:
            return
        redis = get_runtime_redis()
        key = self._key(api_key, model)
        if redis is not None:
            try:
                wait_ms = int(
                    await redis.eval(
                        _RESERVE_SLOT,
                        1,
                        key,
                        max(1, round(interval * 1000)),
                        max(0, round(max_wait * 1000)),
                    )
                )
            except Exception as exc:
                # Don't silently bypass a shared production throttle: multiple
                # workers would then bombard the same upstream model.
                raise OpenRouterPacingError(
                    "Shared OpenRouter request pacing is unavailable."
                ) from exc
            if wait_ms < 0:
                raise OpenRouterPacingError("OpenRouter vision queue is at capacity; retry later.")
            if wait_ms:
                await asyncio.sleep(wait_ms / 1000)
            return

        if settings.is_production_like:
            raise OpenRouterPacingError("Runtime Redis is required for shared vision pacing.")

        # Single-process local fallback, used when runtime Redis is not
        # connected (typical local development).
        async with self._gate:
            now = time.monotonic()
            next_at = self._next_local.get(key, now)
            delay = max(0.0, next_at - now)
            if delay > max_wait:
                raise OpenRouterPacingError("OpenRouter vision queue is at capacity.")
            self._next_local[key] = max(now, next_at) + interval
        if delay:
            await asyncio.sleep(delay)

    async def cooldown(self, *, api_key: str, model: str, delay: float) -> None:
        """Publish a short upstream 429 cooldown to all workers."""
        if delay <= 0:
            return
        key = self._key(api_key, model)
        redis = get_runtime_redis()
        if redis is not None:
            try:
                await redis.eval(_EXTEND_COOLDOWN, 1, key, max(1, round(delay * 1000)))
            except Exception as exc:
                raise OpenRouterPacingError(
                    "Shared OpenRouter retry cooldown is unavailable."
                ) from exc
            return
        async with self._gate:
            self._next_local[key] = max(self._next_local.get(key, 0.0), time.monotonic() + delay)


vision_request_pacer = VisionRequestPacer()
