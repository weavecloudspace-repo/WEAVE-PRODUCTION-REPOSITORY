from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Iterable

from redis.asyncio import Redis

from app.config.logging import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

_CONSUME_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call("TTL", KEYS[1])
return {current, ttl}
"""

_rate_limit_redis_client: Redis | None = None
_fallback_records: defaultdict[str, list[float]] = defaultdict(list)
_fallback_lock = Lock()
_last_redis_error_log_at = 0.0
_REDIS_ERROR_LOG_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class RateLimitResult:
    """Current state of one rate-limit bucket."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_after: int
    current: int
    backend_unavailable: bool = False


def _log_redis_fallback(error: Exception) -> None:
    """Log Redis limiter fallback without flooding logs."""

    global _last_redis_error_log_at

    now = time.time()
    if now - _last_redis_error_log_at < _REDIS_ERROR_LOG_INTERVAL_SECONDS:
        return

    _last_redis_error_log_at = now
    log_message = (
        "Redis rate limiter unavailable; denying security-sensitive requests."
        if settings.is_production_like
        else "Redis rate limiter unavailable; using in-memory fallback."
    )
    logger.error(log_message, extra={"error": str(error)})


def _redis_failure_result(*, limit: int, window_seconds: int) -> RateLimitResult:
    """Fail closed when the shared production limiter is unavailable."""

    return RateLimitResult(
        allowed=False,
        limit=limit,
        remaining=0,
        retry_after=max(min(window_seconds, 60), 1),
        reset_after=max(min(window_seconds, 60), 1),
        current=limit + 1,
        backend_unavailable=True,
    )


def _prune_fallback_records(
    key: str,
    *,
    now: float,
    window_seconds: int,
) -> list[float]:
    records = [
        timestamp for timestamp in _fallback_records[key] if now - timestamp < window_seconds
    ]
    _fallback_records[key] = records
    return records


def _fallback_status(
    key: str,
    *,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    now = time.time()

    with _fallback_lock:
        records = _prune_fallback_records(
            key,
            now=now,
            window_seconds=window_seconds,
        )
        current = len(records)
        allowed = current < limit

        retry_after = 0
        reset_after = 0
        if records:
            reset_after = max(int(window_seconds - (now - records[0])), 1)
            retry_after = reset_after if not allowed else 0

    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=max(limit - current, 0),
        retry_after=retry_after,
        reset_after=reset_after,
        current=current,
    )


def _fallback_consume(
    key: str,
    *,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    now = time.time()

    with _fallback_lock:
        records = _prune_fallback_records(
            key,
            now=now,
            window_seconds=window_seconds,
        )
        records.append(now)
        _fallback_records[key] = records

        current = len(records)
        allowed = current <= limit
        reset_after = max(int(window_seconds - (now - records[0])), 1)
        retry_after = reset_after if not allowed else 0

    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=max(limit - current, 0),
        retry_after=retry_after,
        reset_after=reset_after,
        current=current,
    )


def _fallback_clear(keys: Iterable[str]) -> None:
    key_list = [key for key in keys if key]
    if not key_list:
        return

    with _fallback_lock:
        for key in key_list:
            _fallback_records.pop(key, None)


async def get_rate_limit_redis_client() -> Redis:
    """Return a Redis client dedicated to rate limiting."""

    global _rate_limit_redis_client

    if _rate_limit_redis_client is not None:
        return _rate_limit_redis_client

    redis_url = settings.RATE_LIMIT_REDIS_URL or settings.REDIS_URL
    if not redis_url:
        raise RuntimeError("Redis URL is required for rate limiting.")

    _rate_limit_redis_client = Redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=2,
        socket_connect_timeout=2,
        health_check_interval=30,
    )

    try:
        await _rate_limit_redis_client.ping()
    except Exception:
        await _rate_limit_redis_client.aclose()
        _rate_limit_redis_client = None
        raise
    return _rate_limit_redis_client


class RedisFixedWindowRateLimiter:
    """Fixed-window Redis limiter with development-only local fallback."""

    async def status(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        try:
            client = await get_rate_limit_redis_client()
            raw_current = await client.get(key)
            current = int(raw_current or 0)

            ttl = await client.ttl(key) if current > 0 else 0
            if ttl < 0:
                ttl = window_seconds if current > 0 else 0

            allowed = current < limit
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=max(limit - current, 0),
                retry_after=ttl if not allowed else 0,
                reset_after=ttl,
                current=current,
            )
        except Exception as exc:
            _log_redis_fallback(exc)
            if settings.is_production_like:
                return _redis_failure_result(limit=limit, window_seconds=window_seconds)
            return _fallback_status(
                key,
                limit=limit,
                window_seconds=window_seconds,
            )

    async def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        try:
            client = await get_rate_limit_redis_client()
            current, ttl = await client.eval(
                _CONSUME_SCRIPT,
                1,
                key,
                window_seconds,
            )

            current = int(current)
            ttl = int(ttl)
            if ttl < 0:
                ttl = window_seconds

            allowed = current <= limit
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=max(limit - current, 0),
                retry_after=ttl if not allowed else 0,
                reset_after=ttl,
                current=current,
            )
        except Exception as exc:
            _log_redis_fallback(exc)
            if settings.is_production_like:
                return _redis_failure_result(limit=limit, window_seconds=window_seconds)
            return _fallback_consume(
                key,
                limit=limit,
                window_seconds=window_seconds,
            )

    async def clear(self, keys: Iterable[str]) -> None:
        key_list = [key for key in keys if key]
        if not key_list:
            return

        if not settings.is_production_like:
            _fallback_clear(key_list)

        try:
            client = await get_rate_limit_redis_client()
            await client.delete(*key_list)
        except Exception as exc:
            _log_redis_fallback(exc)
