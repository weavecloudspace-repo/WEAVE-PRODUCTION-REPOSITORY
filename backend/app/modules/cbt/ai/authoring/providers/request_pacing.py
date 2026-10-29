"""Shared Qwen vision request pacing for CBT AI.

Redis atomically reserves a slot for the SAME OpenRouter key/model across
workers and tenants. Without Redis, an in-process pace provides a safe local
development fallback; production should keep runtime Redis connected.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

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


class OpenRouterPacingError(RuntimeError):
    """The provider is busy or the distributed pace is unavailable."""


class VisionRequestPacer:
    def __init__(self) -> None:
        self._gate = asyncio.Lock()
        self.local_vision_gate = asyncio.Semaphore(1)
        self._next_local: dict[str, float] = {}

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
