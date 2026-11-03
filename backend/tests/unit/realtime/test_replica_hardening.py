"""Cross-replica WebSocket safety regression tests.

These tests simulate independent connection registries sharing one Redis backend.
They intentionally do not require a live Railway deployment.
"""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect

from app.modules.cbt.sync import ownership as ownership_mod
from app.modules.cbt.sync.manager import CBTConnectionManager
from app.modules.realtime.authentication import RealtimeIdentity
from app.modules.realtime.broker import RealtimeRedisBroker
from app.modules.realtime.manager import RealtimeConnectionManager
from app.modules.realtime.schemas import RealtimeAudience, RealtimeBrokerMessage, RealtimeEvent


class Socket:
    def __init__(self, *, stall=False):
        self.sent = []
        self.closes = []
        self.stall = stall

    async def send_json(self, payload):
        if self.stall:
            await asyncio.Event().wait()
        self.sent.append(payload)

    async def close(self, code=1000, reason=None):
        self.closes.append((code, reason))


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    async def set(self, key, value, *, ex):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def publish(self, channel, value):
        self.published.append((channel, json.loads(value)))
        return 1

    async def eval(self, script, _numkeys, key, token, *args):
        if self.values.get(key) != token:
            return 0
        if "DEL" in script:
            del self.values[key]
            return 1
        return 1


def actor_identity(*, session_jti, actor_id=None, tenant_id=None):
    return RealtimeIdentity(
        actor_type="teacher",
        actor_id=actor_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        session_jti=session_jti,
    )


@pytest.mark.asyncio
async def test_browser_replicas_dispatch_shared_event_to_local_connections_only():
    actor_id, tenant_id = uuid4(), uuid4()
    first, second = RealtimeConnectionManager(), RealtimeConnectionManager()
    socket_a, socket_b, foreign_socket = Socket(), Socket(), Socket()
    current = actor_identity(session_jti="sid-a", actor_id=actor_id, tenant_id=tenant_id)
    await first.register(socket_a, identity=current)
    await second.register(socket_b, identity=replace(current, session_jti="sid-b"))
    await second.register(foreign_socket, identity=actor_identity(session_jti="foreign"))
    event = RealtimeEvent(type="notification.created", data={"id": "event"})
    audience = RealtimeAudience(
        kind="actor", actor_type="teacher", actor_id=actor_id, tenant_id=tenant_id
    )
    # Each API replica receives the broker message independently.
    await asyncio.gather(
        first.dispatch(event=event, audience=audience),
        second.dispatch(event=event, audience=audience),
    )
    assert len(socket_a.sent) == len(socket_b.sent) == 1
    assert foreign_socket.sent == []


@pytest.mark.asyncio
async def test_revocation_disconnects_only_matching_persistent_session():
    manager = RealtimeConnectionManager()
    first, second = Socket(), Socket()
    actor_id, tenant_id = uuid4(), uuid4()
    await manager.register(
        first,
        identity=actor_identity(session_jti="revoked", actor_id=actor_id, tenant_id=tenant_id),
    )
    await manager.register(
        second, identity=actor_identity(session_jti="valid", actor_id=actor_id, tenant_id=tenant_id)
    )
    assert await manager.disconnect_session("revoked") == 1
    assert first.closes[0][0] == 4401
    assert not second.closes
    assert len(await manager.get_all_connections()) == 1


@pytest.mark.asyncio
async def test_stalled_browser_send_is_bounded_and_removed(monkeypatch):
    from app.modules.realtime import manager as module

    monkeypatch.setattr(module, "BROWSER_SEND_TIMEOUT_SECONDS", 0.01)
    manager = RealtimeConnectionManager()
    dead, healthy = Socket(stall=True), Socket()
    identity = actor_identity(session_jti="same")
    await manager.register(dead, identity=identity)
    await manager.register(healthy, identity=identity)
    await asyncio.wait_for(
        manager.dispatch(
            event=RealtimeEvent(type="notification.created"),
            audience=RealtimeAudience(kind="tenant", tenant_id=identity.tenant_id),
        ),
        timeout=1,
    )
    assert len(healthy.sent) == 1
    assert dead.closes[0][0] == 1011
    assert len(await manager.get_all_connections()) == 1


@pytest.mark.asyncio
async def test_cbt_lease_replacement_and_stale_release_across_replicas(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ownership_mod, "get_runtime_redis", lambda: redis)
    machine_id, tenant_id = uuid4(), uuid4()
    replica_one, replica_two = CBTConnectionManager(), CBTConnectionManager()
    old_socket, new_socket = Socket(), Socket()

    await ownership_mod.CBTSocketOwnership.claim(machine_id, "older")
    await replica_one.register(
        server_id=machine_id,
        credential_id=uuid4(),
        tenant_id=tenant_id,
        websocket=old_socket,
        ownership_token="older",
    )
    await ownership_mod.CBTSocketOwnership.claim(machine_id, "newer")
    await replica_two.register(
        server_id=machine_id,
        credential_id=uuid4(),
        tenant_id=tenant_id,
        websocket=new_socket,
        ownership_token="newer",
    )
    channel, event = redis.published[-1]
    assert channel == ownership_mod.CBT_OWNERSHIP_CHANNEL
    assert await replica_one.disconnect_replaced(**event) is True
    assert old_socket.closes[0][0] == 4001
    assert await replica_two.disconnect_replaced(**event) is False
    assert await ownership_mod.CBTSocketOwnership.renew(machine_id, "older") is False
    assert await ownership_mod.CBTSocketOwnership.renew(machine_id, "newer") is True
    await ownership_mod.CBTSocketOwnership.release(machine_id, "older")
    assert await ownership_mod.CBTSocketOwnership.is_current(machine_id, "newer")
    await ownership_mod.CBTSocketOwnership.release(machine_id, "newer")
    assert await redis.get(ownership_mod.CBTSocketOwnership._key(machine_id)) is None


@pytest.mark.asyncio
async def test_stale_cbt_socket_cannot_disconnect_new_local_owner(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ownership_mod, "get_runtime_redis", lambda: redis)
    machine_id, tenant_id = uuid4(), uuid4()
    manager = CBTConnectionManager()
    old, new = Socket(), Socket()
    await ownership_mod.CBTSocketOwnership.claim(machine_id, "one")
    stale = await manager.register(
        server_id=machine_id,
        credential_id=uuid4(),
        tenant_id=tenant_id,
        websocket=old,
        ownership_token="one",
    )
    await ownership_mod.CBTSocketOwnership.claim(machine_id, "two")
    await manager.register(
        server_id=machine_id,
        credential_id=uuid4(),
        tenant_id=tenant_id,
        websocket=new,
        ownership_token="two",
    )
    assert await manager.ensure_authorized(stale) is False
    assert not new.closes
    assert await manager.has_tenant_connections(tenant_id)


@pytest.mark.asyncio
async def test_redis_broker_handles_cross_replica_revocation_event():
    session_id = "session-to-close"
    payload = RealtimeBrokerMessage(
        event=RealtimeEvent(type="auth.session.revoked", data={"session_jti": session_id}),
        audience=RealtimeAudience(kind="actor", actor_type="teacher", actor_id=uuid4()),
    )

    class PubSub:
        async def listen(self):
            yield {
                "type": "message",
                "channel": "weave:realtime:v1",
                "data": payload.model_dump_json(),
            }
            raise asyncio.CancelledError

    broker = RealtimeRedisBroker()
    broker._pubsub = PubSub()
    broker._connect_subscriber = AsyncMock()
    with (
        patch(
            "app.modules.realtime.broker.realtime_manager.disconnect_session",
            new_callable=AsyncMock,
        ) as close,
        patch(
            "app.modules.realtime.broker.realtime_manager.dispatch", new_callable=AsyncMock
        ) as deliver,
    ):
        with pytest.raises(asyncio.CancelledError):
            await broker._listen()
    close.assert_awaited_once_with(session_id)
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_cbt_replacement_event_dispatches_without_realtime_delivery():
    machine_id = uuid4()
    content = json.dumps({"server_id": str(machine_id), "ownership_token": "new"})

    class PubSub:
        async def listen(self):
            yield {
                "type": "message",
                "channel": ownership_mod.CBT_OWNERSHIP_CHANNEL,
                "data": content,
            }
            raise asyncio.CancelledError

    broker = RealtimeRedisBroker()
    broker._pubsub = PubSub()
    broker._connect_subscriber = AsyncMock()
    with (
        patch(
            "app.modules.realtime.broker.cbt_connection_manager.disconnect_replaced",
            new_callable=AsyncMock,
        ) as close,
        patch(
            "app.modules.realtime.broker.realtime_manager.dispatch", new_callable=AsyncMock
        ) as dispatch,
    ):
        with pytest.raises(asyncio.CancelledError):
            await broker._listen()
    close.assert_awaited_once_with(server_id=str(machine_id), ownership_token="new")
    dispatch.assert_not_awaited()
