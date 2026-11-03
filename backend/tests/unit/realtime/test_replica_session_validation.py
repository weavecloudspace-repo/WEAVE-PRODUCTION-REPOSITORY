"""Session validation and disconnected-socket regression coverage."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import UnauthorizedException
from app.modules.realtime.authentication import RealtimeIdentity, validate_realtime_session
from app.modules.realtime.manager import RealtimeConnectionManager


def identity():
    return RealtimeIdentity(
        actor_type="teacher",
        actor_id=uuid4(),
        tenant_id=uuid4(),
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        session_jti="test-session-jti",
    )


class Socket:
    def __init__(self, *, disconnected=False):
        self.accepted = False
        self.sent = []
        self.closed = []
        self.calls = 0
        self.disconnected = disconnected

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        self.calls += 1
        if self.calls == 1:
            return {"type": "auth", "access_token": "valid-access-token"}
        if self.disconnected:
            raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        await asyncio.Event().wait()

    async def send_json(self, value):
        self.sent.append(value)

    async def close(self, code=1000, reason=None):
        self.closed.append((code, reason))


@pytest.mark.asyncio
async def test_periodic_check_rejects_revoked_persistent_session(monkeypatch):
    from app.modules.realtime import authentication as auth

    active = identity()
    session = SimpleNamespace(
        actor_type=SimpleNamespace(value=active.actor_type),
        actor_id=active.actor_id,
        tenant_id=active.tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=datetime.now(timezone.utc),
        compromised_at=None,
    )
    monkeypatch.setattr(
        auth.AuthSessionRepository, "get_session_by_jti", AsyncMock(return_value=session)
    )
    with pytest.raises(UnauthorizedException, match="no longer valid"):
        await validate_realtime_session(AsyncMock(), identity=active)


@pytest.mark.asyncio
async def test_periodic_check_accepts_active_session(monkeypatch):
    from app.modules.realtime import authentication as auth

    active = identity()
    session = SimpleNamespace(
        actor_type=SimpleNamespace(value=active.actor_type),
        actor_id=active.actor_id,
        tenant_id=active.tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
        compromised_at=None,
    )
    db_lookup = AsyncMock(return_value=session)
    monkeypatch.setattr(auth.AuthSessionRepository, "get_session_by_jti", db_lookup)
    await validate_realtime_session(AsyncMock(), identity=active)
    db_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_websocket_revalidates_even_with_no_client_frames(monkeypatch):
    from app.modules.realtime import router as realtime_router

    active = identity()
    socket = Socket()
    revalidate = AsyncMock(side_effect=UnauthorizedException("Session revoked"))
    monkeypatch.setattr(realtime_router, "_authenticate", AsyncMock(return_value=active))
    monkeypatch.setattr(realtime_router, "_validate_active_session", revalidate)
    monkeypatch.setattr(realtime_router, "SESSION_REVALIDATION_SECONDS", 0)
    manager = RealtimeConnectionManager()
    monkeypatch.setattr(realtime_router, "realtime_manager", manager)
    await asyncio.wait_for(realtime_router.realtime_stream(socket), timeout=2)
    assert revalidate.await_count == 1
    assert socket.closed[-1][0] == 4401
    assert await manager.get_all_connections() == []


@pytest.mark.asyncio
async def test_disconnected_runtime_error_is_cleanly_handled(monkeypatch):
    from app.modules.realtime import router as realtime_router

    active = identity()
    socket = Socket(disconnected=True)
    monkeypatch.setattr(realtime_router, "_authenticate", AsyncMock(return_value=active))
    manager = RealtimeConnectionManager()
    monkeypatch.setattr(realtime_router, "realtime_manager", manager)
    await asyncio.wait_for(realtime_router.realtime_stream(socket), timeout=2)
    assert socket.accepted
    assert await manager.get_all_connections() == []
