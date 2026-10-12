# ====================================== #
#          cbt/auth/router.py            #
# ====================================== #

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    Request,
)

from app.core.dependencies.db import DbSession
from app.core.exceptions import UnauthorizedException
from app.core.rate_limits.auth_rate_limits import AuthRateLimitService
from app.modules.cbt.auth.schemas import (
    AuthenticatedCBTServer,
    CBTServerHostnameResponse,
    CBTActorRefreshRequest,
    CBTActorTokenPair,
    CBTStaffAuthResponse,
    CBTStaffLoginRequest,
)
from app.modules.cbt.auth.service import (
    CBTActorAuthorizationService,
    CBTStaffAuthService,
)
from app.modules.cbt.dependencies import CurrentCBTServer
from app.modules.cbt.repository import CBTServerRepository
from app.core.exceptions import NotFoundException


router = APIRouter(
    tags=["CBT Authentication"],
)


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None

    return request.client.host if request.client else None


@router.get(
    "/server/me",
    response_model=AuthenticatedCBTServer,
)
async def get_current_server(
    current_server: CurrentCBTServer,
) -> AuthenticatedCBTServer:
    return current_server


@router.get("/server/hostname", response_model=CBTServerHostnameResponse)
async def get_current_server_hostname(
    db: DbSession, current_server: CurrentCBTServer
) -> CBTServerHostnameResponse:
    """No user-controlled tenant or server identifier is accepted."""
    server = await CBTServerRepository.get_by_tenant_and_id(
        db, tenant_id=current_server.tenant_id, server_id=current_server.server_id
    )
    if server is None:
        raise NotFoundException(detail="CBT server not found")
    return CBTServerHostnameResponse(server_id=server.id, hostname=server.hostname)


@router.post(
    "/auth/staff/login",
    response_model=CBTStaffAuthResponse,
)
async def authenticate_staff(
    payload: CBTStaffLoginRequest,
    db: DbSession,
    current_server: CurrentCBTServer,
    request: Request,
    background_tasks: BackgroundTasks,
) -> CBTStaffAuthResponse:

    client_ip = _client_ip(request)

    await AuthRateLimitService.check_login_allowed(
        identifier=str(payload.email),
        ip_address=client_ip,
    )

    try:
        result = await CBTStaffAuthService.authenticate_staff(
            db,
            payload=payload,
            current_server=current_server,
            client_ip=client_ip,
            background_tasks=background_tasks,
        )

    except UnauthorizedException:
        await AuthRateLimitService.record_failed_login(
            identifier=str(payload.email),
            ip_address=client_ip,
        )
        raise

    await AuthRateLimitService.clear_login_failures(
        identifier=str(payload.email),
        ip_address=client_ip,
    )

    return result


@router.post(
    "/auth/staff/refresh",
    response_model=CBTActorTokenPair,
)
async def refresh_staff_authorization(
    payload: CBTActorRefreshRequest,
    db: DbSession,
    current_server: CurrentCBTServer,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
) -> CBTActorTokenPair:
    """Rotate one CBT staff cloud authorization without extending its hard expiry."""

    return await CBTActorAuthorizationService.refresh_actor_authorization(
        db,
        current_server=current_server,
        refresh_token=payload.refresh_token,
        idempotency_key=idempotency_key,
    )
