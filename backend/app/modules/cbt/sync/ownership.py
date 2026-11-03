"""Redis-backed cross-replica ownership for CBT synchronization WebSockets.

A WebSocket always belongs to a single API process. This short lease prevents an
older connection on another replica from continuing to act as the current owner.
The CBT cursor log in PostgreSQL remains authoritative for synchronization.
"""

from __future__ import annotations

import json
import uuid

from app.core.cache.redis import get_runtime_redis

CBT_OWNERSHIP_CHANNEL = "weave:cbt:sync:socket-ownership:v1"
CBT_LEASE_SECONDS = 90
CBT_LEASE_REFRESH_SECONDS = 20

_RENEW_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class CBTSocketOwnership:
    """One live connection token per CBT machine across all Weave replicas."""

    @staticmethod
    def _client():
        client = get_runtime_redis()
        if client is None:
            raise RuntimeError("Redis is required for CBT socket coordination.")
        return client

    @staticmethod
    def _key(server_id: uuid.UUID) -> str:
        return f"weave:cbt:sync:socket-owner:{server_id}"

    @classmethod
    async def claim(cls, server_id: uuid.UUID, ownership_token: str) -> None:
        client = cls._client()
        await client.set(cls._key(server_id), ownership_token, ex=CBT_LEASE_SECONDS)
        await client.publish(
            CBT_OWNERSHIP_CHANNEL,
            json.dumps({
                "server_id": str(server_id),
                "ownership_token": ownership_token,
            }),
        )

    @classmethod
    async def is_current(cls, server_id: uuid.UUID, ownership_token: str) -> bool:
        return await cls._client().get(cls._key(server_id)) == ownership_token

    @classmethod
    async def renew(cls, server_id: uuid.UUID, ownership_token: str) -> bool:
        return bool(
            await cls._client().eval(
                _RENEW_IF_OWNER, 1, cls._key(server_id),
                ownership_token, CBT_LEASE_SECONDS,
            )
        )

    @classmethod
    async def release(cls, server_id: uuid.UUID, ownership_token: str) -> None:
        await cls._client().eval(
            _RELEASE_IF_OWNER, 1, cls._key(server_id), ownership_token,
        )
