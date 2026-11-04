"""WEAVE-authenticated access to existing CBT AI wallets and purchases.

CBT machine authentication is retained on /cbt/ai; these routes require a
normal, tenant-scoped WEAVE staff session.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.core.dependencies.db import DbSession
from app.modules.cbt.ai.quota.models import AIQuotaPurchaseStatus, AIQuotaRequestStatus
from app.modules.cbt.ai.quota.payment_schemas import (
    AIQuotaPurchaseCheckoutResponse,
    AIQuotaPurchaseQuote,
)
from app.modules.cbt.ai.quota.schemas import (
    AIActorQuotaBalanceListResponse,
    AICreditAllocationCreate,
    AICreditAllocationListResponse,
    AICreditAllocationResponse,
    AIQuotaPurchaseListResponse,
    AIQuotaPurchaseResponse,
    AIQuotaRequestApprove,
    AIQuotaRequestCreate,
    AIQuotaRequestListResponse,
    AIQuotaRequestReject,
    AIQuotaRequestResponse,
    AIQuotaStatusResponse,
    AIQuotaTopUpRequest,
    AITenantQuotaSummaryResponse,
)
from app.modules.cbt.ai.service import CBTAIService
from app.modules.cbt.ai.teacher_purchase_service import AITeacherPurchaseService
from app.modules.tma.ai_actor import to_existing_ai_actor
from app.modules.tma.router import Author

router = APIRouter(prefix="/ai", tags=["WEAVE AI Credits"])


@router.get("/quota", response_model=AIQuotaStatusResponse)
async def get_cloud_ai_quota(db: DbSession, actor: Author) -> AIQuotaStatusResponse:
    return await CBTAIService.get_quota_status(db, actor=to_existing_ai_actor(actor))


@router.post("/quota/requests", response_model=AIQuotaRequestResponse)
async def request_cloud_ai_credits(
    payload: AIQuotaRequestCreate,
    db: DbSession,
    actor: Author,
) -> AIQuotaRequestResponse:
    return await CBTAIService.request_credits(
        db,
        actor=to_existing_ai_actor(actor),
        credits=payload.credits,
    )


@router.get("/quota/requests", response_model=AIQuotaRequestListResponse)
async def list_my_cloud_credit_requests(
    db: DbSession,
    actor: Author,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    return await CBTAIService.list_my_credit_requests(
        db,
        actor=to_existing_ai_actor(actor),
        offset=offset,
        limit=limit,
    )


@router.post(
    "/quota/requests/{request_id}/cancel",
    response_model=AIQuotaRequestResponse,
)
async def cancel_cloud_credit_request(
    request_id: UUID,
    db: DbSession,
    actor: Author,
) -> AIQuotaRequestResponse:
    return await CBTAIService.cancel_my_credit_request(
        db,
        actor=to_existing_ai_actor(actor),
        request_id=request_id,
    )


@router.get("/admin/quota/summary", response_model=AITenantQuotaSummaryResponse)
async def admin_cloud_quota_summary(
    db: DbSession,
    actor: Author,
) -> AITenantQuotaSummaryResponse:
    return await CBTAIService.get_tenant_quota_summary(
        db,
        actor=to_existing_ai_actor(actor),
    )


@router.get("/admin/quota/actors", response_model=AIActorQuotaBalanceListResponse)
async def admin_cloud_actor_balances(
    db: DbSession,
    actor: Author,
    search: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIActorQuotaBalanceListResponse:
    balances = await CBTAIService.list_actor_quota_balances(
        db,
        actor=to_existing_ai_actor(actor),
    )
    # Balance snapshots are already cached tenant-wide; search the complete
    # authorized snapshot before slicing rather than only the first 100.
    term = (search or "").strip().casefold()
    matches = [
        item for item in balances.items
        if not term or term in item.display_name.casefold() or term in (item.email or "").casefold()
    ]
    return balances.model_copy(update={"items": matches[offset : offset + limit], "total": len(matches)})


@router.get("/admin/quota/requests", response_model=AIQuotaRequestListResponse)
async def admin_cloud_credit_requests(
    db: DbSession,
    actor: Author,
    request_status: AIQuotaRequestStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    return await CBTAIService.list_credit_requests(
        db,
        actor=to_existing_ai_actor(actor),
        status=request_status,
        search=search,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/admin/quota/requests/{request_id}/approve",
    response_model=AIQuotaRequestResponse,
)
async def admin_cloud_approve_request(
    request_id: UUID,
    payload: AIQuotaRequestApprove,
    db: DbSession,
    actor: Author,
) -> AIQuotaRequestResponse:
    return await CBTAIService.approve_credit_request(
        db,
        actor=to_existing_ai_actor(actor),
        request_id=request_id,
        approved_credits=payload.approved_credits,
        note=payload.note,
    )


@router.post(
    "/admin/quota/requests/{request_id}/reject",
    response_model=AIQuotaRequestResponse,
)
async def admin_cloud_reject_request(
    request_id: UUID,
    payload: AIQuotaRequestReject,
    db: DbSession,
    actor: Author,
) -> AIQuotaRequestResponse:
    return await CBTAIService.reject_credit_request(
        db,
        actor=to_existing_ai_actor(actor),
        request_id=request_id,
        note=payload.note,
    )


@router.post("/admin/quota/allocations", response_model=AICreditAllocationResponse)
async def admin_cloud_allocate_credits(
    payload: AICreditAllocationCreate,
    db: DbSession,
    actor: Author,
) -> AICreditAllocationResponse:
    return await CBTAIService.allocate_credits(
        db,
        actor=to_existing_ai_actor(actor),
        recipient_actor_type=payload.recipient_actor_type,
        recipient_actor_id=payload.recipient_actor_id,
        credits=payload.credits,
    )


@router.get("/admin/quota/allocations", response_model=AICreditAllocationListResponse)
async def admin_cloud_list_allocations(
    db: DbSession,
    actor: Author,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AICreditAllocationListResponse:
    return await CBTAIService.list_credit_allocations(
        db,
        actor=to_existing_ai_actor(actor),
        offset=offset,
        limit=limit,
    )


@router.post("/admin/quota/purchases/quote", response_model=AIQuotaPurchaseQuote)
async def admin_cloud_purchase_quote(
    payload: AIQuotaTopUpRequest,
    actor: Author,
) -> AIQuotaPurchaseQuote:
    return CBTAIService.quote_credit_purchase(
        actor=to_existing_ai_actor(actor),
        credits=payload.credits,
    )


@router.post(
    "/admin/quota/purchases/checkout",
    response_model=AIQuotaPurchaseCheckoutResponse,
)
async def admin_cloud_purchase_checkout(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    actor: Author,
) -> AIQuotaPurchaseCheckoutResponse:
    return await CBTAIService.initialize_credit_purchase(
        db,
        actor=to_existing_ai_actor(actor),
        credits=payload.credits,
    )


@router.post(
    "/admin/quota/purchases/{reference}/verify",
    response_model=AIQuotaPurchaseResponse,
)
async def admin_cloud_verify_purchase(
    reference: str,
    db: DbSession,
    actor: Author,
) -> AIQuotaPurchaseResponse:
    return await CBTAIService.verify_credit_purchase(
        db,
        actor=to_existing_ai_actor(actor),
        reference=reference,
    )


@router.get("/admin/quota/purchases", response_model=AIQuotaPurchaseListResponse)
async def admin_cloud_list_purchases(
    db: DbSession,
    actor: Author,
    purchase_status: AIQuotaPurchaseStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaPurchaseListResponse:
    return await CBTAIService.list_credit_purchases(
        db,
        actor=to_existing_ai_actor(actor),
        status=purchase_status,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/admin/quota/purchases/{purchase_id}",
    response_model=AIQuotaPurchaseResponse,
)
async def admin_cloud_get_purchase(
    purchase_id: UUID,
    db: DbSession,
    actor: Author,
) -> AIQuotaPurchaseResponse:
    return await CBTAIService.get_credit_purchase(
        db,
        actor=to_existing_ai_actor(actor),
        purchase_id=purchase_id,
    )


@router.post("/teacher/purchases/quote", response_model=AIQuotaPurchaseQuote)
async def teacher_cloud_purchase_quote(
    payload: AIQuotaTopUpRequest,
    actor: Author,
) -> AIQuotaPurchaseQuote:
    CBTAIService._require_teacher(to_existing_ai_actor(actor))
    return AITeacherPurchaseService.quote(payload.credits)


@router.post(
    "/teacher/purchases/checkout",
    response_model=AIQuotaPurchaseCheckoutResponse,
)
async def teacher_cloud_purchase_checkout(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    actor: Author,
) -> AIQuotaPurchaseCheckoutResponse:
    ai_actor = to_existing_ai_actor(actor)
    membership_id = CBTAIService._require_teacher(ai_actor)
    return await AITeacherPurchaseService.checkout(
        db,
        tenant_id=ai_actor.tenant_id,
        membership_id=membership_id,
        credits=payload.credits,
    )


@router.post(
    "/teacher/purchases/{reference}/verify",
    response_model=AIQuotaPurchaseResponse,
)
async def teacher_cloud_verify_purchase(
    reference: str,
    db: DbSession,
    actor: Author,
) -> AIQuotaPurchaseResponse:
    ai_actor = to_existing_ai_actor(actor)
    membership_id = CBTAIService._require_teacher(ai_actor)
    return await AITeacherPurchaseService.verify(
        db,
        tenant_id=ai_actor.tenant_id,
        membership_id=membership_id,
        reference=reference,
    )


@router.get("/teacher/purchases", response_model=AIQuotaPurchaseListResponse)
async def teacher_cloud_list_purchases(
    db: DbSession,
    actor: Author,
    purchase_status: AIQuotaPurchaseStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaPurchaseListResponse:
    ai_actor = to_existing_ai_actor(actor)
    membership_id = CBTAIService._require_teacher(ai_actor)
    return await AITeacherPurchaseService.list_purchases(
        db,
        tenant_id=ai_actor.tenant_id,
        membership_id=membership_id,
        status=purchase_status,
        offset=offset,
        limit=limit,
    )
