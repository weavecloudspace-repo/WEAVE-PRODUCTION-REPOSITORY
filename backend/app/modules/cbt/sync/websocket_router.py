"""Authenticated machine WebSocket used as the low-latency CBT sync wake path."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config.database import AsyncSessionLocal
from app.config.logging import get_logger
from app.core.exceptions import AppException, ForbiddenException
from app.modules.cbt.auth.schemas import AuthenticatedCBTServer
from app.modules.cbt.auth.service import CBTMachineAuthService
from app.modules.cbt.sync.manager import CBTMachineConnection, cbt_connection_manager
from app.modules.cbt.sync.ownership import CBTSocketOwnership, CBT_LEASE_REFRESH_SECONDS
from app.modules.cbt.sync.service import CBTSyncService

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["CBT Sync"])
AUTHENTICATION_CLOSE_CODE = 4401
FORBIDDEN_CLOSE_CODE = 4403


def _extract_bearer_credential(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization")
    if not authorization:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credential.strip():
        return None
    return credential.strip()


async def _authenticate_server(credential: str) -> AuthenticatedCBTServer:
    async with AsyncSessionLocal() as db:
        return await CBTMachineAuthService.authenticate_server(
            db,
            server_credential=credential,
        )


async def _latest_cursor(current_server: AuthenticatedCBTServer) -> int:
    async with AsyncSessionLocal() as db:
        return await CBTSyncService.get_latest_cursor(
            db,
            tenant_id=current_server.tenant_id,
        )


async def _send(connection: CBTMachineConnection, message: dict) -> None:
    async with connection.send_lock:
        await asyncio.wait_for(connection.websocket.send_json(message), timeout=8.0)


@router.websocket("/stream")
async def cbt_sync_stream(websocket: WebSocket) -> None:
    connection: CBTMachineConnection | None = None
    ownership_token: str | None = None
    server_id: uuid.UUID | None = None
    credential = _extract_bearer_credential(websocket)
    if credential is None:
        await websocket.close(
            code=AUTHENTICATION_CLOSE_CODE,
            reason="CBT server authentication is required.",
        )
        return

    try:
        try:
            current_server = await _authenticate_server(credential)
        except ForbiddenException:
            await websocket.close(
                code=FORBIDDEN_CLOSE_CODE,
                reason="CBT server is not permitted to synchronize.",
            )
            return
        except AppException:
            await websocket.close(
                code=AUTHENTICATION_CLOSE_CODE,
                reason="CBT server authentication failed.",
            )
            return

        server_id = current_server.server_id
        ownership_token = uuid.uuid4().hex
        await CBTSocketOwnership.claim(server_id, ownership_token)
        await websocket.accept()
        connection = await cbt_connection_manager.register(
            server_id=current_server.server_id,
            credential_id=current_server.credential_id,
            tenant_id=current_server.tenant_id,
            websocket=websocket,
            ownership_token=ownership_token,
        )
        await _send(
            connection,
            {
                "type": "connection.ready",
                "server_id": str(current_server.server_id),
                "cursor": await _latest_cursor(current_server),
            },
        )

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=CBT_LEASE_REFRESH_SECONDS,
                )
            except TimeoutError:
                message = None
            if not await CBTSocketOwnership.renew(server_id, ownership_token):
                await cbt_connection_manager.disconnect_server(
                    server_id,
                    expected_websocket=websocket,
                    code=4001,
                    reason="CBT socket ownership moved to another replica.",
                )
                return
            if not await cbt_connection_manager.ensure_authorized(connection):
                return
            if message is None:
                continue
            if not isinstance(message, dict):
                await _send(
                    connection,
                    {
                        "type": "error",
                        "code": "invalid_control_frame",
                        "message": "Control frames must be JSON objects.",
                    },
                )
                continue
            if message.get("type") == "ping":
                await _send(connection, {"type": "pong"})
                continue
            await _send(
                connection,
                {
                    "type": "error",
                    "code": "unsupported_control_frame",
                    "message": "Unsupported CBT synchronization control frame.",
                },
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected CBT synchronization WebSocket failure.")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if connection is not None:
            await cbt_connection_manager.unregister(
                server_id=connection.server_id,
                websocket=websocket,
            )
        if server_id is not None and ownership_token is not None:
            try:
                await CBTSocketOwnership.release(server_id, ownership_token)
            except Exception:
                logger.exception("Failed to release CBT socket ownership lease.")
