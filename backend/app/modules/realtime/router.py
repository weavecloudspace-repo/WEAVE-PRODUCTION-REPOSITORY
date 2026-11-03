"""Authenticated browser WebSocket endpoint for Weave realtime events."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from app.config.database import AsyncSessionLocal
from app.config.logging import get_logger
from app.core.exceptions import AppException
from app.modules.realtime.authentication import (
    RealtimeIdentity,
    authenticate_realtime_access_token,
)
from app.modules.realtime.manager import RealtimeConnection, realtime_manager
from app.modules.realtime.schemas import (
    RealtimeAuthFrame,
    RealtimeAuthRefreshedFrame,
    RealtimeAuthRefreshFrame,
    RealtimeClientControlFrame,
    RealtimeConnectionReadyFrame,
    RealtimeErrorFrame,
    RealtimePingFrame,
    RealtimePongFrame,
    RealtimeContract,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/realtime", tags=["Realtime"])

AUTHENTICATION_TIMEOUT_SECONDS = 10
SESSION_REVALIDATION_SECONDS = 30
AUTHENTICATION_CLOSE_CODE = 4401
IDENTITY_CHANGE_CLOSE_CODE = 4403
_control_frame_adapter = TypeAdapter(RealtimeClientControlFrame)


async def _send_control(
    websocket: WebSocket,
    frame: RealtimeContract,
    *,
    connection: RealtimeConnection | None = None,
) -> None:
    payload = frame.model_dump(mode="json")
    if connection is None:
        await websocket.send_json(payload)
        return
    await realtime_manager.send_json(connection.connection_id, payload)


async def _send_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    connection: RealtimeConnection | None = None,
) -> None:
    await _send_control(
        websocket,
        RealtimeErrorFrame(code=code, message=message),
        connection=connection,
    )


async def _authenticate(access_token: str) -> RealtimeIdentity:
    # A database session exists only for this authentication operation. It is
    # deliberately not a WebSocket dependency because sockets can live for hours.
    async with AsyncSessionLocal() as db:
        return await authenticate_realtime_access_token(db, access_token=access_token)


def _seconds_until_expiry(identity: RealtimeIdentity) -> float:
    return max(
        0.0,
        (identity.token_expires_at - datetime.now(timezone.utc)).total_seconds(),
    )


async def _receive_control_frame(
    websocket: WebSocket,
    *,
    timeout: float | None = None,
) -> RealtimeAuthFrame | RealtimeAuthRefreshFrame | RealtimePingFrame:
    if timeout is None:
        payload = await websocket.receive_json()
    else:
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
    return _control_frame_adapter.validate_python(payload)


@router.websocket("/stream")
async def realtime_stream(websocket: WebSocket) -> None:
    """Serve one authenticated, multiplexed realtime browser connection."""

    connection: RealtimeConnection | None = None
    identity: RealtimeIdentity | None = None
    await websocket.accept()

    try:
        try:
            initial_frame = await _receive_control_frame(
                websocket,
                timeout=AUTHENTICATION_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ValidationError, ValueError, TypeError):
            await _send_error(
                websocket,
                code="authentication_required",
                message="The first WebSocket frame must authenticate the connection.",
            )
            await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
            return

        if not isinstance(initial_frame, RealtimeAuthFrame):
            await _send_error(
                websocket,
                code="authentication_required",
                message="The first WebSocket frame must be auth.",
            )
            await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
            return

        try:
            identity = await _authenticate(initial_frame.access_token)
        except AppException:
            await _send_error(
                websocket,
                code="authentication_failed",
                message="WebSocket authentication failed.",
            )
            await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
            return

        access_token = initial_frame.access_token
        last_verified_at = time.monotonic()
        connection = await realtime_manager.register(websocket, identity=identity)
        await _send_control(
            websocket,
            RealtimeConnectionReadyFrame(
                connection_id=connection.connection_id,
                token_expires_at=identity.token_expires_at,
            ),
            connection=connection,
        )

        while True:
            try:
                next_check = max(
                    0.0,
                    SESSION_REVALIDATION_SECONDS - (time.monotonic() - last_verified_at),
                )
                frame = await _receive_control_frame(
                    websocket,
                    timeout=min(_seconds_until_expiry(identity), next_check),
                )
            except TimeoutError:
                if _seconds_until_expiry(identity) <= 0:
                    await _send_error(
                        websocket,
                        code="authentication_expired",
                        message="The WebSocket access token expired.",
                        connection=connection,
                    )
                    await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
                    return
                try:
                    verified_identity = await _authenticate(access_token)
                except AppException:
                    await _send_error(
                        websocket,
                        code="authentication_failed",
                        message="The realtime session is no longer valid.",
                        connection=connection,
                    )
                    await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
                    return
                if not await realtime_manager.refresh_identity(
                    connection.connection_id, identity=verified_identity,
                ):
                    return
                identity = verified_identity
                last_verified_at = time.monotonic()
                continue
            except (ValidationError, ValueError, TypeError):
                await _send_error(
                    websocket,
                    code="invalid_control_frame",
                    message="The WebSocket control frame is invalid or unsupported.",
                    connection=connection,
                )
                continue

            if isinstance(frame, RealtimePingFrame):
                await _send_control(websocket, RealtimePongFrame(), connection=connection)
                continue

            if isinstance(frame, RealtimeAuthRefreshFrame):
                try:
                    refreshed_identity = await _authenticate(frame.access_token)
                except AppException:
                    await _send_error(
                        websocket,
                        code="authentication_failed",
                        message="WebSocket token refresh failed.",
                        connection=connection,
                    )
                    await websocket.close(code=AUTHENTICATION_CLOSE_CODE)
                    return

                refreshed = await realtime_manager.refresh_identity(
                    connection.connection_id,
                    identity=refreshed_identity,
                )
                if not refreshed:
                    await _send_error(
                        websocket,
                        code="identity_change_rejected",
                        message="A WebSocket token refresh cannot change identity.",
                        connection=connection,
                    )
                    await websocket.close(code=IDENTITY_CHANGE_CLOSE_CODE)
                    return

                identity = refreshed_identity
                access_token = frame.access_token
                last_verified_at = time.monotonic()
                await _send_control(
                    websocket,
                    RealtimeAuthRefreshedFrame(
                        token_expires_at=identity.token_expires_at,
                    ),
                    connection=connection,
                )
                continue

            await _send_error(
                websocket,
                code="unsupported_control_frame",
                message="This control frame is not valid after authentication.",
                connection=connection,
            )

    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        if not (
            "WebSocket is not connected" in str(exc)
            or "Cannot call \"receive\" once a disconnect message has been received" in str(exc)
        ):
            logger.exception("Unexpected realtime WebSocket failure.")
    except Exception:
        logger.exception("Unexpected realtime WebSocket failure.")
        try:
            await _send_error(
                websocket,
                code="internal_error",
                message="The realtime connection closed unexpectedly.",
                connection=connection,
            )
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if connection is not None:
            await realtime_manager.unregister(connection.connection_id)
