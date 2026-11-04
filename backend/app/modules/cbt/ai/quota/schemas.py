"""Internal contracts for CBT AI quota and credit-accounting workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.cbt.ai.quota.models import (
    AICreditReservationStatus,
    AIQuotaActorType,
    AIQuotaPurchaseStatus,
    AIQuotaRequestStatus,
)


MAX_QUOTA_ADMIN_NOTE_LENGTH = 2_000


class AIQuotaSchemaBase(BaseModel):
    """Base configuration for quota request/response contracts."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class AIQuotaRequestCreate(AIQuotaSchemaBase):
    """Teacher request for additional AI credits from the school reserve."""

    credits: int = Field(gt=0)


class AIQuotaRequestApprove(AIQuotaSchemaBase):
    """Admin approval payload for a pending teacher credit request."""

    approved_credits: int | None = Field(default=None, gt=0)
    note: str | None = Field(
        default=None,
        max_length=MAX_QUOTA_ADMIN_NOTE_LENGTH,
    )


class AIQuotaRequestReject(AIQuotaSchemaBase):
    """Admin rejection payload for a pending teacher credit request."""

    note: str | None = Field(
        default=None,
        max_length=MAX_QUOTA_ADMIN_NOTE_LENGTH,
    )


class AICreditAllocationCreate(AIQuotaSchemaBase):
    """Direct tenant-reserve allocation to a teacher or tenant admin."""

    recipient_actor_type: AIQuotaActorType
    recipient_actor_id: uuid.UUID
    credits: int = Field(gt=0)


class AIQuotaTopUpRequest(AIQuotaSchemaBase):
    """Tenant-admin intent to purchase additional tenant AI credits."""

    credits: int = Field(gt=0)


class AIWeeklyQuotaStatus(AIQuotaSchemaBase):
    week_start: date
    credit_limit: int = Field(ge=0)
    used_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    available_credits: int = Field(ge=0)


class AIExtraCreditStatus(AIQuotaSchemaBase):
    balance_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    available_credits: int = Field(ge=0)


class AIQuotaStatusResponse(AIQuotaSchemaBase):
    quota_account_id: uuid.UUID
    actor_type: AIQuotaActorType
    actor_id: uuid.UUID
    weekly: AIWeeklyQuotaStatus
    extra: AIExtraCreditStatus
    total_available_credits: int = Field(ge=0)


class AIQuotaRequestResponse(AIQuotaSchemaBase):
    id: uuid.UUID
    requester_quota_account_id: uuid.UUID
    requested_credits: int = Field(gt=0)
    approved_credits: int | None = Field(default=None, gt=0)
    status: AIQuotaRequestStatus
    reviewed_by_admin_id: uuid.UUID | None = None
    allocation_id: uuid.UUID | None = None
    admin_note: str | None = None
    requester_name: str | None = None
    requester_email: str | None = None
    reviewer_email: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AIQuotaRequestListResponse(AIQuotaSchemaBase):
    items: list[AIQuotaRequestResponse]
    total: int = Field(ge=0)


class AIActorQuotaBalance(AIQuotaSchemaBase):
    quota_account_id: uuid.UUID
    actor_type: AIQuotaActorType
    actor_id: uuid.UUID
    display_name: str
    email: str | None = None
    weekly_available_credits: int = Field(ge=0)
    weekly_used_credits: int = Field(ge=0)
    extra_available_credits: int = Field(ge=0)
    total_available_credits: int = Field(ge=0)


class AIActorQuotaBalanceListResponse(AIQuotaSchemaBase):
    items: list[AIActorQuotaBalance]
    total: int = Field(ge=0)
    weekly_used_credits_total: int = Field(default=0, ge=0)


class AITenantQuotaSummaryResponse(AIQuotaSchemaBase):
    tenant_reserve_credits: int = Field(ge=0)
    quota_actor_count: int = Field(ge=0)
    pending_request_count: int = Field(ge=0)
    personal_extra_balance_total: int = Field(ge=0)
    personal_extra_reserved_total: int = Field(ge=0)


class AICreditAllocationResponse(AIQuotaSchemaBase):
    id: uuid.UUID
    recipient_quota_account_id: uuid.UUID
    recipient_actor_type: AIQuotaActorType
    recipient_actor_id: uuid.UUID
    recipient_name: str | None = None
    recipient_email: str | None = None
    allocated_by_admin_id: uuid.UUID
    allocator_email: str | None = None
    credits: int = Field(gt=0)
    created_at: datetime


class AICreditAllocationListResponse(AIQuotaSchemaBase):
    items: list[AICreditAllocationResponse]
    total: int = Field(ge=0)


class AIQuotaPurchaseResponse(AIQuotaSchemaBase):
    id: uuid.UUID
    credits: int = Field(gt=0)
    amount_kobo: int = Field(gt=0)
    reference: str
    status: AIQuotaPurchaseStatus
    initiated_by_admin_id: uuid.UUID | None
    initiated_by_teacher_membership_id: uuid.UUID | None = None
    initiated_by_email: str | None = None
    created_at: datetime
    credited_at: datetime | None = None


class AIQuotaPurchaseListResponse(AIQuotaSchemaBase):
    items: list[AIQuotaPurchaseResponse]
    total: int = Field(ge=0)


class AICreditReservationResponse(AIQuotaSchemaBase):
    id: uuid.UUID
    quota_account_id: uuid.UUID
    status: AICreditReservationStatus
    reserved_free_credits: int = Field(ge=0)
    reserved_extra_credits: int = Field(ge=0)
    total_reserved_credits: int = Field(gt=0)
    expires_at: datetime


class AICreditSettlementResponse(AIQuotaSchemaBase):
    reservation_id: uuid.UUID
    settled_free_credits: int = Field(ge=0)
    settled_extra_credits: int = Field(ge=0)
    total_settled_credits: int = Field(ge=0)
    released_credits: int = Field(ge=0)
    settled_at: datetime
