"""Aggregate CBT pairing and tenant-admin management routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_tenant_admin
from app.core.exceptions import ForbiddenException
from app.modules.cbt.pairing.rate_limit import CBTPairingRateLimiter
from app.modules.cbt.pairing.schemas import (
    CBTServerCredentialRotationResponse,
    CBTServerListResponse,
    CBTServerResponse,
    CBTServerRevokeRequest,
    PairingCode,
    PairingRequest,
    PairingResult,
    PairingStatusRequest,
    PairingStatusResponse,
)
from app.modules.cbt.pairing.repository import CBTServerRepository
from app.modules.cbt.pairing.service import CBTPairingService, CBTPairingStatusService
from app.modules.cbt.releases.schemas import CBTReleaseResponse
from app.modules.cbt.releases.service import (
    CBTReleaseService,
    CBTReleaseUnavailableError,
)
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import FeatureCode
from app.modules.tenant_admins.models import TenantAdmin

router = APIRouter(tags=["CBT Pairing"])
CurrentTenantAdmin = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]


def tenant_id_for(admin: TenantAdmin) -> UUID:
    if admin.tenant_id is None:
        raise ForbiddenException(detail="Tenant admin is not attached to a tenant")
    return admin.tenant_id


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "/releases/latest",
    response_model=CBTReleaseResponse,
    tags=["CBT Releases"],
)
async def get_latest_cbt_release() -> CBTReleaseResponse:
    """Return the published installer that matches this Weave environment."""

    try:
        return await CBTReleaseService.get_latest()
    except CBTReleaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/pairing/verify",
    response_model=PairingResult,
    status_code=status.HTTP_201_CREATED,
)
async def pair_server(
    payload: PairingRequest,
    request: Request,
    db: DbSession,
) -> PairingResult:
    """Exchange a one-time pairing challenge for a new tenant-owned server identity."""

    await CBTPairingRateLimiter.check(ip_address=_client_ip(request))
    result = await CBTPairingService.pair_server(db=db, payload=payload)
    await SubscriptionFeatureService.invalidate_tenant_subscription_state(
        result.tenant.id,
        db=db,
    )
    return result


@router.post("/pairing/codes", response_model=PairingCode, status_code=status.HTTP_201_CREATED)
async def create_pairing_code(db: DbSession, current_admin: CurrentTenantAdmin) -> PairingCode:
    return await CBTPairingService.create_pairing_code(db=db, admin=current_admin)


@router.post("/pairing/status", response_model=PairingStatusResponse)
async def get_pairing_status(
    payload: PairingStatusRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> PairingStatusResponse:
    return await CBTPairingStatusService.get_status(
        db,
        admin=current_admin,
        pairing_code=payload.pairing_code,
    )


@router.get("/servers", response_model=CBTServerListResponse)
async def list_cbt_servers(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerListResponse:
    servers = await CBTServerRepository.list_for_tenant(db, tenant_id_for(current_admin))
    items = [CBTServerResponse.model_validate(server) for server in servers]
    return CBTServerListResponse(items=items, total=len(items))


@router.get("/servers/{server_id}", response_model=CBTServerResponse)
async def get_cbt_server(
    server_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerResponse:
    return await CBTPairingService.get_server(
        db=db,
        admin=current_admin,
        server_id=server_id,
    )


@router.post("/servers/{server_id}/suspend", response_model=CBTServerResponse)
async def suspend_cbt_server(
    server_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerResponse:
    return await CBTPairingService.suspend_server(
        db=db,
        admin=current_admin,
        server_id=server_id,
    )


@router.post("/servers/{server_id}/reactivate", response_model=CBTServerResponse)
async def reactivate_cbt_server(
    server_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerResponse:
    tenant_id = tenant_id_for(current_admin)
    await SubscriptionFeatureService.ensure_feature_enabled(
        db,
        tenant_id,
        FeatureCode.CBT_PAIRING,
    )
    return await CBTPairingService.reactivate_server(
        db=db,
        admin=current_admin,
        server_id=server_id,
    )


@router.post(
    "/servers/{server_id}/rotate-credential",
    response_model=CBTServerCredentialRotationResponse,
)
async def rotate_cbt_server_key(
    server_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerCredentialRotationResponse:
    tenant_id = tenant_id_for(current_admin)
    await SubscriptionFeatureService.ensure_feature_enabled(
        db,
        tenant_id,
        FeatureCode.CBT_PAIRING,
    )
    return await CBTPairingService.rotate_server_credential(
        db=db,
        admin=current_admin,
        server_id=server_id,
    )


@router.post("/servers/{server_id}/revoke", response_model=CBTServerResponse)
async def revoke_cbt_server(
    server_id: UUID,
    payload: CBTServerRevokeRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerResponse:
    result = await CBTPairingService.revoke_server(
        db=db,
        admin=current_admin,
        server_id=server_id,
        reason=payload.reason,
        confirmation_literal=payload.confirmation_literal,
    )
    await SubscriptionFeatureService.invalidate_tenant_subscription_state(
        tenant_id_for(current_admin),
        db=db,
    )
    return result


@router.post("/servers/{server_id}/unrevoke", response_model=CBTServerResponse)
async def unrevoke_cbt_server(
    server_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> CBTServerResponse:
    """Restore a tenant-owned server to suspended, subject to plan capacity."""
    result = await CBTPairingService.unrevoke_server(
        db=db, admin=current_admin, server_id=server_id
    )
    await SubscriptionFeatureService.invalidate_tenant_subscription_state(
        tenant_id_for(current_admin), db=db
    )
    return result
