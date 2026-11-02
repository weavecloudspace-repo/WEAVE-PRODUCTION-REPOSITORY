"""Grouped CBT AI application routes."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request

from app.core.dependencies.db import DbSession
from app.modules.cbt.ai.authoring.trace_logging import trace_event, trace_request
from app.modules.cbt.ai.idempotency.service import CBTAIIdempotentAuthoringService
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
from app.modules.cbt.ai.schemas import (
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIRegenerateQuestionRequest,
    AIRegenerateQuestionResponse,
)
from app.modules.cbt.ai.service import CBTAIService
from app.modules.cbt.ai.transport import CBTGZipRoute
from app.modules.cbt.ai.teacher_purchase_service import AITeacherPurchaseService
from app.modules.cbt.dependencies import CurrentCBTActor


router = APIRouter(
    prefix="/ai",
    tags=["CBT AI"],
    route_class=CBTGZipRoute,
)


@router.post("/questions/generate", response_model=AIGenerateQuestionsResponse)
async def generate_questions(
    payload: AIGenerateQuestionsRequest,
    db: DbSession,
    current_actor: CurrentCBTActor,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> AIGenerateQuestionsResponse:
    with trace_request(
        idempotency_key=idempotency_key,
        operation="generate",
        request_id=getattr(request.state, "request_id", None),
    ):
        started = perf_counter()
        trace_event(
            "request.accepted",
            question_count=payload.question_count,
            visual_mode=payload.visual_mode,
            question_type_single=(payload.question_type_counts or {}).get("single_choice", 0),
            question_type_multiple=(payload.question_type_counts or {}).get("multiple_choice", 0),
        )
        try:
            result = await CBTAIIdempotentAuthoringService.generate_questions(
                db,
                actor=current_actor,
                request=payload,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            trace_event(
                "request.failed",
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
                http_status=getattr(exc, "status_code", None),
                reason=getattr(exc, "payload", {}).get("code")
                if isinstance(getattr(exc, "payload", None), dict)
                else None,
            )
            raise
        trace_event(
            "request.completed",
            duration_ms=(perf_counter() - started) * 1000,
            actual_count=len(result.questions),
            credits_charged=result.charge.credits_charged,
        )
        return result


@router.post("/questions/regenerate", response_model=AIRegenerateQuestionResponse)
async def regenerate_question(
    payload: AIRegenerateQuestionRequest,
    db: DbSession,
    current_actor: CurrentCBTActor,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> AIRegenerateQuestionResponse:
    with trace_request(
        idempotency_key=idempotency_key,
        operation="regenerate",
        request_id=getattr(request.state, "request_id", None),
    ):
        started = perf_counter()
        trace_event("request.accepted", question_count=1, visual_mode=payload.visual_mode)
        try:
            result = await CBTAIIdempotentAuthoringService.regenerate_question(
                db,
                actor=current_actor,
                request=payload,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            trace_event(
                "request.failed",
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
                http_status=getattr(exc, "status_code", None),
            )
            raise
        trace_event(
            "request.completed",
            duration_ms=(perf_counter() - started) * 1000,
            actual_count=1,
            credits_charged=result.charge.credits_charged,
        )
        return result


@router.get("/quota", response_model=AIQuotaStatusResponse)
async def get_my_quota(
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaStatusResponse:
    return await CBTAIService.get_quota_status(db, actor=current_actor)


@router.post("/quota/requests", response_model=AIQuotaRequestResponse)
async def request_credits(
    payload: AIQuotaRequestCreate,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaRequestResponse:
    return await CBTAIService.request_credits(db, actor=current_actor, credits=payload.credits)


@router.get("/quota/requests", response_model=AIQuotaRequestListResponse)
async def list_my_credit_requests(
    db: DbSession,
    current_actor: CurrentCBTActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    return await CBTAIService.list_my_credit_requests(
        db,
        actor=current_actor,
        offset=offset,
        limit=limit,
    )


@router.post("/quota/requests/{request_id}/cancel", response_model=AIQuotaRequestResponse)
async def cancel_my_credit_request(
    request_id: UUID,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaRequestResponse:
    return await CBTAIService.cancel_my_credit_request(
        db,
        actor=current_actor,
        request_id=request_id,
    )


@router.get("/admin/quota/summary", response_model=AITenantQuotaSummaryResponse)
async def get_tenant_quota_summary(
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AITenantQuotaSummaryResponse:
    return await CBTAIService.get_tenant_quota_summary(db, actor=current_actor)


@router.get("/admin/quota/actors", response_model=AIActorQuotaBalanceListResponse)
async def list_actor_quota_balances(
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIActorQuotaBalanceListResponse:
    return await CBTAIService.list_actor_quota_balances(db, actor=current_actor)


@router.get("/admin/quota/requests", response_model=AIQuotaRequestListResponse)
async def list_credit_requests(
    db: DbSession,
    current_actor: CurrentCBTActor,
    request_status: AIQuotaRequestStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    return await CBTAIService.list_credit_requests(
        db,
        actor=current_actor,
        status=request_status,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/admin/quota/requests/{request_id}/approve",
    response_model=AIQuotaRequestResponse,
)
async def approve_credit_request(
    request_id: UUID,
    payload: AIQuotaRequestApprove,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaRequestResponse:
    return await CBTAIService.approve_credit_request(
        db,
        actor=current_actor,
        request_id=request_id,
        approved_credits=payload.approved_credits,
        note=payload.note,
    )


@router.post(
    "/admin/quota/requests/{request_id}/reject",
    response_model=AIQuotaRequestResponse,
)
async def reject_credit_request(
    request_id: UUID,
    payload: AIQuotaRequestReject,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaRequestResponse:
    return await CBTAIService.reject_credit_request(
        db,
        actor=current_actor,
        request_id=request_id,
        note=payload.note,
    )


@router.post("/admin/quota/allocations", response_model=AICreditAllocationResponse)
async def allocate_credits(
    payload: AICreditAllocationCreate,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AICreditAllocationResponse:
    return await CBTAIService.allocate_credits(
        db,
        actor=current_actor,
        recipient_actor_type=payload.recipient_actor_type,
        recipient_actor_id=payload.recipient_actor_id,
        credits=payload.credits,
    )


@router.get("/admin/quota/allocations", response_model=AICreditAllocationListResponse)
async def list_credit_allocations(
    db: DbSession,
    current_actor: CurrentCBTActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AICreditAllocationListResponse:
    return await CBTAIService.list_credit_allocations(
        db,
        actor=current_actor,
        offset=offset,
        limit=limit,
    )


@router.post("/admin/quota/purchases/quote", response_model=AIQuotaPurchaseQuote)
async def quote_credit_purchase(
    payload: AIQuotaTopUpRequest,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseQuote:
    return CBTAIService.quote_credit_purchase(actor=current_actor, credits=payload.credits)


@router.post(
    "/admin/quota/purchases/checkout",
    response_model=AIQuotaPurchaseCheckoutResponse,
)
async def initialize_credit_purchase(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseCheckoutResponse:
    return await CBTAIService.initialize_credit_purchase(
        db,
        actor=current_actor,
        credits=payload.credits,
    )


@router.post(
    "/admin/quota/purchases/{reference}/verify",
    response_model=AIQuotaPurchaseResponse,
)
async def verify_credit_purchase(
    reference: str,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseResponse:
    return await CBTAIService.verify_credit_purchase(
        db,
        actor=current_actor,
        reference=reference,
    )


@router.get("/admin/quota/purchases", response_model=AIQuotaPurchaseListResponse)
async def list_credit_purchases(
    db: DbSession,
    current_actor: CurrentCBTActor,
    purchase_status: AIQuotaPurchaseStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaPurchaseListResponse:
    return await CBTAIService.list_credit_purchases(
        db,
        actor=current_actor,
        status=purchase_status,
        offset=offset,
        limit=limit,
    )


@router.get("/admin/quota/purchases/{purchase_id}", response_model=AIQuotaPurchaseResponse)
async def get_credit_purchase(
    purchase_id: UUID,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseResponse:
    return await CBTAIService.get_credit_purchase(
        db,
        actor=current_actor,
        purchase_id=purchase_id,
    )


# Additive teacher checkout routes; existing admin and generation routes are unchanged.
@router.post("/teacher/purchases/quote", response_model=AIQuotaPurchaseQuote)
async def quote_teacher_credit_purchase(
    payload: AIQuotaTopUpRequest,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseQuote:
    CBTAIService._require_teacher(current_actor)
    return AITeacherPurchaseService.quote(payload.credits)


@router.post(
    "/teacher/purchases/checkout",
    response_model=AIQuotaPurchaseCheckoutResponse,
)
async def checkout_teacher_credits(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseCheckoutResponse:
    membership_id = CBTAIService._require_teacher(current_actor)
    return await AITeacherPurchaseService.checkout(
        db,
        tenant_id=current_actor.tenant_id,
        membership_id=membership_id,
        credits=payload.credits,
    )


@router.post(
    "/teacher/purchases/{reference}/verify",
    response_model=AIQuotaPurchaseResponse,
)
async def verify_teacher_credits(
    reference: str,
    db: DbSession,
    current_actor: CurrentCBTActor,
) -> AIQuotaPurchaseResponse:
    membership_id = CBTAIService._require_teacher(current_actor)
    return await AITeacherPurchaseService.verify(
        db,
        tenant_id=current_actor.tenant_id,
        membership_id=membership_id,
        reference=reference,
    )


@router.get(
    "/teacher/purchases",
    response_model=AIQuotaPurchaseListResponse,
)
async def list_teacher_credit_purchases(
    db: DbSession,
    current_actor: CurrentCBTActor,
    purchase_status: AIQuotaPurchaseStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaPurchaseListResponse:
    membership_id = CBTAIService._require_teacher(current_actor)
    return await AITeacherPurchaseService.list_purchases(
        db,
        tenant_id=current_actor.tenant_id,
        membership_id=membership_id,
        status=purchase_status,
        offset=offset,
        limit=limit,
    )
