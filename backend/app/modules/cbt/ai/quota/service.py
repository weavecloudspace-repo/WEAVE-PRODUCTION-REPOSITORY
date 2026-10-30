"""Quota, reservation, allocation, and purchase accounting for CBT AI."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cbt.ai.quota.cache import invalidate_quota_cache
from app.modules.cbt.ai.quota.models import (
    AICreditAllocation,
    AICreditLedger,
    AICreditLedgerBucket,
    AICreditLedgerEventType,
    AICreditReservation,
    AICreditReservationStatus,
    AIExtraCreditBalance,
    AIQuotaAccount,
    AIQuotaActorType,
    AIQuotaPurchase,
    AIQuotaPurchaseStatus,
    AIQuotaRequest,
    AIQuotaRequestStatus,
    AITenantCreditBalance,
    AIWeeklyQuota,
)
from app.modules.cbt.ai.quota.repository import (
    AICreditAllocationRepository,
    AICreditLedgerRepository,
    AICreditReservationRepository,
    AIExtraCreditBalanceRepository,
    AIQuotaAccountRepository,
    AIQuotaPurchaseRepository,
    AIQuotaRequestRepository,
    AITenantCreditBalanceRepository,
    AIWeeklyQuotaRepository,
)
from app.modules.cbt.ai.quota.schemas import (
    AIActorQuotaBalance,
    AIActorQuotaBalanceListResponse,
    AICreditAllocationListResponse,
    AICreditAllocationResponse,
    AICreditReservationResponse,
    AICreditSettlementResponse,
    AIExtraCreditStatus,
    AIQuotaPurchaseListResponse,
    AIQuotaPurchaseResponse,
    AIQuotaRequestListResponse,
    AIQuotaRequestResponse,
    AIQuotaStatusResponse,
    AITenantQuotaSummaryResponse,
    AIWeeklyQuotaStatus,
)
from app.modules.teachers.models import TeacherAccount
from app.modules.teachers.repository import TeacherMembershipRepository
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tenant_admins.repository import TenantAdminRepository


DEFAULT_WEEKLY_FREE_CREDITS = 100
DEFAULT_RESERVATION_TTL = timedelta(minutes=15)


class AIQuotaError(RuntimeError):
    """Base error raised by the CBT AI quota domain."""


class AIQuotaNotFoundError(AIQuotaError):
    """Raised when a tenant-scoped quota resource cannot be found."""


class AIQuotaConflictError(AIQuotaError):
    """Raised when a quota operation conflicts with the current state."""


class AIQuotaPermissionError(AIQuotaError):
    """Raised when an actor cannot perform the requested quota operation."""


class AIInsufficientCreditsError(AIQuotaError):
    """Raised when a credit bucket cannot cover the requested amount."""

    def __init__(
        self,
        *,
        requested_credits: int,
        available_credits: int,
        message: str = "Insufficient AI credits.",
    ) -> None:
        super().__init__(message)
        self.requested_credits = requested_credits
        self.available_credits = available_credits


class AIQuotaReservationExpiredError(AIQuotaConflictError):
    """Raised when settlement is attempted after a reservation expired."""


class AIQuotaService:
    """
    Manage CBT AI credits without exposing accounting internals to CBT clients.

    Public/dashboard responsibilities:
    - expose actor quota status
    - create/list/cancel teacher credit requests
    - expose tenant quota summaries and actor balances
    - approve/reject requests and allocate tenant credits
    - expose allocation and purchase history

    Application-internal responsibilities:
    - reserve credits before an AI operation
    - settle actual consumption after success
    - release reservations after failure
    - recover stale reservations
    - create and settle trusted tenant purchase records

    The service owns credit accounting. Payment-provider calls, question
    generation, authentication, authorization, and HTTP routing live elsewhere.
    """

    @classmethod
    async def get_quota_status(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        actor_type: AIQuotaActorType,
        actor_id: uuid.UUID,
    ) -> AIQuotaStatusResponse:
        """Return the current weekly + personal top-up quota for one actor."""

        account = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        week_start = cls._current_week_start()
        weekly = await cls._ensure_weekly_quota(
            db,
            tenant_id=tenant_id,
            quota_account_id=account.id,
            week_start=week_start,
        )
        extra = await AIExtraCreditBalanceRepository.get_for_account(
            db,
            tenant_id=tenant_id,
            quota_account_id=account.id,
        )
        return cls._quota_status_response(
            account=account,
            weekly=weekly,
            extra=extra,
        )

    @classmethod
    async def create_quota_request(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_membership_id: uuid.UUID,
        credits: int,
    ) -> AIQuotaRequestResponse:
        """Create a teacher request for credits from the tenant reserve."""

        cls._require_positive_credits(credits)
        account = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=AIQuotaActorType.TEACHER,
            actor_id=teacher_membership_id,
        )
        request = AIQuotaRequest(
            tenant_id=tenant_id,
            requester_quota_account_id=account.id,
            requested_credits=credits,
            status=AIQuotaRequestStatus.PENDING,
        )
        try:
            await AIQuotaRequestRepository.create(db, request)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._quota_request_response(request)

    @classmethod
    async def list_my_quota_requests(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_membership_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaRequestListResponse:
        """List a teacher's own quota requests."""

        account = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=AIQuotaActorType.TEACHER,
            actor_id=teacher_membership_id,
        )
        requests, total = await AIQuotaRequestRepository.list_for_requester(
            db,
            tenant_id=tenant_id,
            requester_quota_account_id=account.id,
            offset=offset,
            limit=limit,
        )
        return AIQuotaRequestListResponse(
            items=[cls._quota_request_response(item) for item in requests],
            total=total,
        )

    @classmethod
    async def cancel_my_quota_request(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_membership_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> AIQuotaRequestResponse:
        """Cancel a teacher-owned request while it is still pending."""

        account = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=AIQuotaActorType.TEACHER,
            actor_id=teacher_membership_id,
        )
        try:
            request = await AIQuotaRequestRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                request_id=request_id,
                lock=True,
            )
            if request is None or request.requester_quota_account_id != account.id:
                raise AIQuotaNotFoundError("Quota request was not found.")
            if request.status != AIQuotaRequestStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota requests can be cancelled.")
            request.status = AIQuotaRequestStatus.CANCELLED
            request.cancelled_at = cls._now()
            await AIQuotaRequestRepository.save(db, request)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._quota_request_response(request)

    @classmethod
    async def get_tenant_quota_summary(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
    ) -> AITenantQuotaSummaryResponse:
        """Return tenant-reserve and actor-level quota aggregates."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        tenant_balance = await AITenantCreditBalanceRepository.get_for_tenant(
            db,
            tenant_id=tenant_id,
        )
        rows = await AIQuotaAccountRepository.list_balance_context_for_tenant(
            db,
            tenant_id=tenant_id,
            week_start=cls._current_week_start(),
        )
        _, pending_count = await AIQuotaRequestRepository.list_for_tenant_with_requester(
            db,
            tenant_id=tenant_id,
            status=AIQuotaRequestStatus.PENDING,
            offset=0,
            limit=1,
        )
        extra_balance_total = 0
        extra_reserved_total = 0
        for _, _, extra, _, _, _ in rows:
            if extra is None:
                continue
            extra_balance_total += extra.available_credits
            extra_reserved_total += extra.reserved_credits
        return AITenantQuotaSummaryResponse(
            tenant_reserve_credits=(
                tenant_balance.available_credits if tenant_balance is not None else 0
            ),
            quota_actor_count=len(rows),
            pending_request_count=pending_count,
            personal_extra_balance_total=extra_balance_total,
            personal_extra_reserved_total=extra_reserved_total,
        )

    @classmethod
    async def list_actor_quota_balances(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
    ) -> AIActorQuotaBalanceListResponse:
        """Return current quota balances for provisioned tenant AI actors."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        rows = await AIQuotaAccountRepository.list_balance_context_for_tenant(
            db,
            tenant_id=tenant_id,
            week_start=cls._current_week_start(),
        )
        items: list[AIActorQuotaBalance] = []
        for account, weekly, extra, _, teacher, admin in rows:
            weekly_limit = (
                weekly.credit_limit if weekly is not None else DEFAULT_WEEKLY_FREE_CREDITS
            )
            weekly_used = weekly.used_credits if weekly is not None else 0
            weekly_reserved = weekly.reserved_credits if weekly is not None else 0
            weekly_available = max(
                weekly_limit - weekly_used - weekly_reserved,
                0,
            )
            extra_available = (
                max(extra.available_credits - extra.reserved_credits, 0) if extra is not None else 0
            )
            display_name, email = cls._actor_display_identity(
                teacher=teacher,
                admin=admin,
            )
            items.append(
                AIActorQuotaBalance(
                    quota_account_id=account.id,
                    actor_type=account.actor_type,
                    actor_id=cls._actor_id(account),
                    display_name=display_name,
                    email=email,
                    weekly_available_credits=weekly_available,
                    weekly_used_credits=weekly_used,
                    extra_available_credits=extra_available,
                    total_available_credits=weekly_available + extra_available,
                )
            )
        return AIActorQuotaBalanceListResponse(items=items, total=len(items))

    @classmethod
    async def list_quota_requests(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        status: AIQuotaRequestStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaRequestListResponse:
        """List tenant quota requests with requester/reviewer identity."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        rows, total = await AIQuotaRequestRepository.list_for_tenant_with_requester(
            db,
            tenant_id=tenant_id,
            status=status,
            offset=offset,
            limit=limit,
        )
        items: list[AIQuotaRequestResponse] = []
        for request, _, _, teacher, reviewer in rows:
            requester_name, requester_email = cls._actor_display_identity(
                teacher=teacher,
                admin=None,
            )
            items.append(
                cls._quota_request_response(
                    request,
                    requester_name=requester_name,
                    requester_email=requester_email,
                    reviewer_email=(reviewer.email if reviewer else None),
                )
            )
        return AIQuotaRequestListResponse(items=items, total=total)

    @classmethod
    async def approve_quota_request(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        request_id: uuid.UUID,
        approved_credits: int | None = None,
        note: str | None = None,
    ) -> AIQuotaRequestResponse:
        """Approve a pending teacher request and allocate tenant credits atomically."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        initial_request = await AIQuotaRequestRepository.get_by_tenant_and_id(
            db,
            tenant_id=tenant_id,
            request_id=request_id,
        )
        if initial_request is None:
            raise AIQuotaNotFoundError("Quota request was not found.")
        await cls._ensure_extra_balance(
            db,
            tenant_id=tenant_id,
            quota_account_id=initial_request.requester_quota_account_id,
        )
        await cls._ensure_tenant_balance(db, tenant_id=tenant_id)
        try:
            request = await AIQuotaRequestRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                request_id=request_id,
                lock=True,
            )
            if request is None:
                raise AIQuotaNotFoundError("Quota request was not found.")
            if request.status != AIQuotaRequestStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota requests can be approved.")
            credits = (
                approved_credits if approved_credits is not None else request.requested_credits
            )
            cls._require_positive_credits(credits)
            if credits > request.requested_credits:
                raise AIQuotaConflictError("Approved credits cannot exceed requested credits.")
            tenant_balance = await AITenantCreditBalanceRepository.get_for_tenant(
                db,
                tenant_id=tenant_id,
                lock=True,
            )
            extra = await AIExtraCreditBalanceRepository.get_for_account(
                db,
                tenant_id=tenant_id,
                quota_account_id=request.requester_quota_account_id,
                lock=True,
            )
            if tenant_balance is None or extra is None:
                raise AIQuotaConflictError("Quota balance state is incomplete.")
            allocation = await cls._allocate_from_tenant_reserve(
                db,
                tenant_id=tenant_id,
                tenant_admin_id=tenant_admin_id,
                recipient_quota_account_id=request.requester_quota_account_id,
                credits=credits,
                tenant_balance=tenant_balance,
                extra_balance=extra,
            )
            request.status = AIQuotaRequestStatus.APPROVED
            request.reviewed_by_admin_id = tenant_admin_id
            request.approved_credits = credits
            request.allocation_id = allocation.id
            request.reviewed_at = cls._now()
            request.admin_note = cls._clean_note(note)
            await AIQuotaRequestRepository.save(db, request)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._quota_request_response(request)

    @classmethod
    async def reject_quota_request(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        request_id: uuid.UUID,
        note: str | None = None,
    ) -> AIQuotaRequestResponse:
        """Reject a pending teacher credit request."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        try:
            request = await AIQuotaRequestRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                request_id=request_id,
                lock=True,
            )
            if request is None:
                raise AIQuotaNotFoundError("Quota request was not found.")
            if request.status != AIQuotaRequestStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota requests can be rejected.")
            request.status = AIQuotaRequestStatus.REJECTED
            request.reviewed_by_admin_id = tenant_admin_id
            request.reviewed_at = cls._now()
            request.admin_note = cls._clean_note(note)
            await AIQuotaRequestRepository.save(db, request)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._quota_request_response(request)

    @classmethod
    async def allocate_credits(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        recipient_actor_type: AIQuotaActorType,
        recipient_actor_id: uuid.UUID,
        credits: int,
    ) -> AICreditAllocationResponse:
        """Allocate tenant-reserve credits directly to an actor's top-up balance."""

        cls._require_positive_credits(credits)
        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        recipient = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=recipient_actor_type,
            actor_id=recipient_actor_id,
        )
        await cls._ensure_extra_balance(
            db,
            tenant_id=tenant_id,
            quota_account_id=recipient.id,
        )
        await cls._ensure_tenant_balance(db, tenant_id=tenant_id)
        try:
            tenant_balance = await AITenantCreditBalanceRepository.get_for_tenant(
                db,
                tenant_id=tenant_id,
                lock=True,
            )
            extra = await AIExtraCreditBalanceRepository.get_for_account(
                db,
                tenant_id=tenant_id,
                quota_account_id=recipient.id,
                lock=True,
            )
            if tenant_balance is None or extra is None:
                raise AIQuotaConflictError("Quota balance state is incomplete.")
            allocation = await cls._allocate_from_tenant_reserve(
                db,
                tenant_id=tenant_id,
                tenant_admin_id=tenant_admin_id,
                recipient_quota_account_id=recipient.id,
                credits=credits,
                tenant_balance=tenant_balance,
                extra_balance=extra,
            )
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._allocation_response(
            allocation=allocation,
            account=recipient,
        )

    @classmethod
    async def list_credit_allocations(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> AICreditAllocationListResponse:
        """List tenant credit allocations for the admin dashboard."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        rows, total = await AICreditAllocationRepository.list_for_tenant_with_actor_details(
            db,
            tenant_id=tenant_id,
            offset=offset,
            limit=limit,
        )
        items: list[AICreditAllocationResponse] = []
        for allocation, account, _, teacher, recipient_admin, allocator in rows:
            name, email = cls._actor_display_identity(
                teacher=teacher,
                admin=recipient_admin,
            )
            items.append(
                cls._allocation_response(
                    allocation=allocation,
                    account=account,
                    recipient_name=name,
                    recipient_email=email,
                    allocator_email=allocator.email,
                )
            )
        return AICreditAllocationListResponse(items=items, total=total)

    @classmethod
    async def create_pending_purchase(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        credits: int,
        amount_kobo: int,
        reference: str,
    ) -> AIQuotaPurchaseResponse:
        """
        Create a pending purchase from trusted payment-service input.

        `amount_kobo` and `reference` must come from server-side payment
        orchestration, never directly from an untrusted CBT request body.
        """

        cls._require_positive_credits(credits)
        if type(amount_kobo) is not int or amount_kobo <= 0:
            raise ValueError("amount_kobo must be a positive integer.")
        normalized_reference = reference.strip()
        if not normalized_reference:
            raise ValueError("reference cannot be blank.")
        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        existing = await AIQuotaPurchaseRepository.get_by_reference(
            db,
            reference=normalized_reference,
        )
        if existing is not None:
            if (
                existing.tenant_id == tenant_id
                and existing.initiated_by_admin_id == tenant_admin_id
                and existing.credits == credits
                and existing.amount_kobo == amount_kobo
            ):
                response = cls._purchase_response(existing)
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                return response
            raise AIQuotaConflictError("A different quota purchase already uses this reference.")
        purchase = AIQuotaPurchase(
            tenant_id=tenant_id,
            initiated_by_admin_id=tenant_admin_id,
            credits=credits,
            amount_kobo=amount_kobo,
            reference=normalized_reference,
            status=AIQuotaPurchaseStatus.PENDING,
        )
        try:
            await AIQuotaPurchaseRepository.create(db, purchase)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._purchase_response(purchase)

    @classmethod
    async def credit_verified_purchase(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        reference: str,
        commit: bool = True,
    ) -> AIQuotaPurchaseResponse:
        """Credit tenant reserve exactly once after trusted payment verification."""

        normalized_reference = reference.strip()
        purchase_preview = await AIQuotaPurchaseRepository.get_by_reference(
            db,
            reference=normalized_reference,
        )
        if purchase_preview is None or purchase_preview.tenant_id != tenant_id:
            raise AIQuotaNotFoundError("Quota purchase was not found.")
        await cls._ensure_tenant_balance(db, tenant_id=tenant_id)
        try:
            purchase = await AIQuotaPurchaseRepository.get_by_reference(
                db,
                reference=normalized_reference,
                lock=True,
            )
            if purchase is None or purchase.tenant_id != tenant_id:
                raise AIQuotaNotFoundError("Quota purchase was not found.")
            if purchase.status == AIQuotaPurchaseStatus.SUCCESS:
                response = cls._purchase_response(purchase)
                if commit:
                    await db.commit()
                    await invalidate_quota_cache(tenant_id)
                return response
            if purchase.status != AIQuotaPurchaseStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota purchases can be credited.")
            tenant_balance = await AITenantCreditBalanceRepository.get_for_tenant(
                db,
                tenant_id=tenant_id,
                lock=True,
            )
            if tenant_balance is None:
                raise AIQuotaConflictError("Tenant credit balance is missing.")
            tenant_balance.available_credits += purchase.credits
            purchase.status = AIQuotaPurchaseStatus.SUCCESS
            purchase.credited_at = cls._now()
            await AITenantCreditBalanceRepository.save(db, tenant_balance)
            await AIQuotaPurchaseRepository.save(db, purchase)
            await AICreditLedgerRepository.create(
                db,
                AICreditLedger(
                    tenant_id=tenant_id,
                    quota_account_id=None,
                    bucket=AICreditLedgerBucket.TENANT_RESERVE,
                    event_type=AICreditLedgerEventType.PURCHASE,
                    credit_delta=purchase.credits,
                    purchase_id=purchase.id,
                    description="Tenant AI credit purchase credited.",
                ),
            )
            if commit:
                await db.commit()
                await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._purchase_response(purchase)

    @classmethod
    async def mark_purchase_failed(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        reference: str,
    ) -> AIQuotaPurchaseResponse:
        """Mark a still-pending purchase as failed without moving credits."""

        try:
            purchase = await AIQuotaPurchaseRepository.get_by_reference(
                db,
                reference=reference.strip(),
                lock=True,
            )
            if purchase is None or purchase.tenant_id != tenant_id:
                raise AIQuotaNotFoundError("Quota purchase was not found.")
            if purchase.status == AIQuotaPurchaseStatus.FAILED:
                response = cls._purchase_response(purchase)
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                return response
            if purchase.status != AIQuotaPurchaseStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota purchases can be marked failed.")
            purchase.status = AIQuotaPurchaseStatus.FAILED
            await AIQuotaPurchaseRepository.save(db, purchase)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._purchase_response(purchase)

    @classmethod
    async def cancel_pending_purchase(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        purchase_id: uuid.UUID,
    ) -> AIQuotaPurchaseResponse:
        """Cancel a pending purchase record before successful payment."""

        try:
            purchase = await AIQuotaPurchaseRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                purchase_id=purchase_id,
                lock=True,
            )
            if purchase is None:
                raise AIQuotaNotFoundError("Quota purchase was not found.")
            if purchase.status == AIQuotaPurchaseStatus.CANCELLED:
                response = cls._purchase_response(purchase)
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                return response
            if purchase.status != AIQuotaPurchaseStatus.PENDING:
                raise AIQuotaConflictError("Only pending quota purchases can be cancelled.")
            purchase.status = AIQuotaPurchaseStatus.CANCELLED
            await AIQuotaPurchaseRepository.save(db, purchase)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._purchase_response(purchase)

    @classmethod
    async def list_tenant_quota_purchases(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        status: AIQuotaPurchaseStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaPurchaseListResponse:
        """List tenant AI-credit purchases for the admin dashboard."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        rows, total = await AIQuotaPurchaseRepository.list_for_tenant_with_admin(
            db,
            tenant_id=tenant_id,
            status=status,
            offset=offset,
            limit=limit,
        )
        return AIQuotaPurchaseListResponse(
            items=[
                cls._purchase_response(
                    purchase,
                    initiated_by_email=admin.email,
                )
                for purchase, admin in rows
            ],
            total=total,
        )

    @classmethod
    async def get_quota_purchase(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        purchase_id: uuid.UUID,
    ) -> AIQuotaPurchaseResponse:
        """Return one tenant purchase for admin-side status polling/display."""

        await cls._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        purchase = await AIQuotaPurchaseRepository.get_by_tenant_and_id(
            db,
            tenant_id=tenant_id,
            purchase_id=purchase_id,
        )
        if purchase is None:
            raise AIQuotaNotFoundError("Quota purchase was not found.")
        return cls._purchase_response(purchase)

    @classmethod
    async def reserve_credits(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        actor_type: AIQuotaActorType,
        actor_id: uuid.UUID,
        credits: int,
        ttl: timedelta = DEFAULT_RESERVATION_TTL,
    ) -> AICreditReservationResponse:
        """
        Reserve credits before an external AI operation.

        Weekly free credits are always reserved first, then personal top-up
        credits. This method commits before returning so callers can perform
        slow provider HTTP work without holding database locks.
        """

        cls._require_positive_credits(credits)
        if ttl.total_seconds() <= 0:
            raise ValueError("Reservation TTL must be positive.")
        account = await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        week_start = cls._current_week_start()
        await cls._ensure_weekly_quota(
            db,
            tenant_id=tenant_id,
            quota_account_id=account.id,
            week_start=week_start,
        )
        try:
            weekly = await AIWeeklyQuotaRepository.get_for_account_week(
                db,
                tenant_id=tenant_id,
                quota_account_id=account.id,
                week_start=week_start,
                lock=True,
            )
            extra = await AIExtraCreditBalanceRepository.get_for_account(
                db,
                tenant_id=tenant_id,
                quota_account_id=account.id,
                lock=True,
            )
            if weekly is None:
                raise AIQuotaConflictError("Weekly quota state is missing.")
            free_available = max(
                weekly.credit_limit - weekly.used_credits - weekly.reserved_credits,
                0,
            )
            extra_available = (
                max(extra.available_credits - extra.reserved_credits, 0) if extra is not None else 0
            )
            total_available = free_available + extra_available
            if total_available < credits:
                raise AIInsufficientCreditsError(
                    requested_credits=credits,
                    available_credits=total_available,
                )
            reserved_free = min(credits, free_available)
            reserved_extra = credits - reserved_free
            weekly.reserved_credits += reserved_free
            await AIWeeklyQuotaRepository.save(db, weekly)
            if reserved_extra:
                if extra is None:
                    raise AIQuotaConflictError(
                        "Extra-credit balance disappeared during reservation."
                    )
                extra.reserved_credits += reserved_extra
                await AIExtraCreditBalanceRepository.save(db, extra)
            reservation = AICreditReservation(
                tenant_id=tenant_id,
                quota_account_id=account.id,
                weekly_quota_id=weekly.id,
                reserved_free_credits=reserved_free,
                reserved_extra_credits=reserved_extra,
                settled_free_credits=0,
                settled_extra_credits=0,
                status=AICreditReservationStatus.PENDING,
                expires_at=cls._now() + ttl,
            )
            await AICreditReservationRepository.create(db, reservation)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._reservation_response(reservation)

    @classmethod
    async def settle_reservation(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        actual_credits: int,
    ) -> AICreditSettlementResponse:
        """Settle actual AI consumption and release any unused reserved amount."""

        if type(actual_credits) is not int or actual_credits < 0:
            raise ValueError("actual_credits must be a non-negative integer.")
        try:
            reservation = await AICreditReservationRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                lock=True,
            )
            if reservation is None:
                raise AIQuotaNotFoundError("Credit reservation was not found.")
            if reservation.status == AICreditReservationStatus.SETTLED:
                response = cls._settlement_response(reservation)
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                return response
            if reservation.status in {
                AICreditReservationStatus.RELEASED,
                AICreditReservationStatus.EXPIRED,
            }:
                raise AIQuotaConflictError("This credit reservation is no longer pending.")
            now = cls._now()
            if reservation.expires_at <= now:
                await cls._release_locked_reservation(
                    db,
                    reservation=reservation,
                    expired=True,
                    released_at=now,
                )
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                raise AIQuotaReservationExpiredError(
                    "Credit reservation expired before settlement."
                )
            reserved_total = reservation.reserved_free_credits + reservation.reserved_extra_credits
            if actual_credits > reserved_total:
                raise AIQuotaConflictError("Actual credit usage exceeds the reserved amount.")
            weekly = await cls._locked_weekly_for_reservation(
                db,
                reservation=reservation,
            )
            extra = None
            if reservation.reserved_extra_credits:
                extra = await AIExtraCreditBalanceRepository.get_for_account(
                    db,
                    tenant_id=tenant_id,
                    quota_account_id=reservation.quota_account_id,
                    lock=True,
                )
                if extra is None:
                    raise AIQuotaConflictError("Reserved extra-credit balance is missing.")
            settled_free = min(
                actual_credits,
                reservation.reserved_free_credits,
            )
            settled_extra = actual_credits - settled_free
            if weekly.reserved_credits < reservation.reserved_free_credits:
                raise AIQuotaConflictError("Weekly reserved-credit state is inconsistent.")
            weekly.reserved_credits -= reservation.reserved_free_credits
            weekly.used_credits += settled_free
            await AIWeeklyQuotaRepository.save(db, weekly)
            if reservation.reserved_extra_credits:
                assert extra is not None
                if extra.reserved_credits < reservation.reserved_extra_credits:
                    raise AIQuotaConflictError("Extra reserved-credit state is inconsistent.")
                if extra.available_credits < settled_extra:
                    raise AIQuotaConflictError("Extra-credit balance cannot cover settlement.")
                extra.reserved_credits -= reservation.reserved_extra_credits
                extra.available_credits -= settled_extra
                await AIExtraCreditBalanceRepository.save(db, extra)
            reservation.settled_free_credits = settled_free
            reservation.settled_extra_credits = settled_extra
            reservation.status = AICreditReservationStatus.SETTLED
            reservation.settled_at = now
            await AICreditReservationRepository.save(db, reservation)
            ledger_entries: list[AICreditLedger] = []
            if settled_free:
                ledger_entries.append(
                    AICreditLedger(
                        tenant_id=tenant_id,
                        quota_account_id=reservation.quota_account_id,
                        bucket=AICreditLedgerBucket.WEEKLY_FREE,
                        event_type=AICreditLedgerEventType.CONSUMPTION,
                        credit_delta=-settled_free,
                        reservation_id=reservation.id,
                        description="CBT AI weekly free-credit consumption.",
                    )
                )
            if settled_extra:
                ledger_entries.append(
                    AICreditLedger(
                        tenant_id=tenant_id,
                        quota_account_id=reservation.quota_account_id,
                        bucket=AICreditLedgerBucket.TOP_UP,
                        event_type=AICreditLedgerEventType.CONSUMPTION,
                        credit_delta=-settled_extra,
                        reservation_id=reservation.id,
                        description="CBT AI top-up credit consumption.",
                    )
                )
            await AICreditLedgerRepository.create_many(db, ledger_entries)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except AIQuotaReservationExpiredError:
            raise
        except Exception:
            await db.rollback()
            raise
        return cls._settlement_response(reservation)

    @classmethod
    async def release_reservation(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> AICreditReservationResponse:
        """Release a pending reservation after an AI operation fails."""

        try:
            reservation = await AICreditReservationRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                lock=True,
            )
            if reservation is None:
                raise AIQuotaNotFoundError("Credit reservation was not found.")
            if reservation.status in {
                AICreditReservationStatus.RELEASED,
                AICreditReservationStatus.EXPIRED,
            }:
                response = cls._reservation_response(reservation)
                await db.commit()
                await invalidate_quota_cache(tenant_id)
                return response
            if reservation.status == AICreditReservationStatus.SETTLED:
                raise AIQuotaConflictError("A settled credit reservation cannot be released.")
            await cls._release_locked_reservation(
                db,
                reservation=reservation,
                expired=False,
                released_at=cls._now(),
            )
            await db.commit()
            await invalidate_quota_cache(tenant_id)
        except Exception:
            await db.rollback()
            raise
        return cls._reservation_response(reservation)

    @classmethod
    async def expire_stale_reservations(
        cls,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Recover expired pending reservations for a worker/maintenance job."""

        if limit <= 0:
            raise ValueError("limit must be positive.")
        now = as_of or cls._now()
        try:
            reservations = await AICreditReservationRepository.list_expired_pending_for_recovery(
                db,
                as_of=now,
                limit=limit,
            )
            for reservation in reservations:
                await cls._release_locked_reservation(
                    db,
                    reservation=reservation,
                    expired=True,
                    released_at=now,
                )
            await db.commit()
            for affected_tenant in {reservation.tenant_id for reservation in reservations}:
                await invalidate_quota_cache(affected_tenant)
        except Exception:
            await db.rollback()
            raise
        return len(reservations)

    @classmethod
    async def _allocate_from_tenant_reserve(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        recipient_quota_account_id: uuid.UUID,
        credits: int,
        tenant_balance: AITenantCreditBalance,
        extra_balance: AIExtraCreditBalance,
    ) -> AICreditAllocation:
        """Move locked tenant-reserve credits into a locked actor top-up balance."""

        if tenant_balance.available_credits < credits:
            raise AIInsufficientCreditsError(
                requested_credits=credits,
                available_credits=tenant_balance.available_credits,
                message="Tenant AI credit reserve is insufficient.",
            )
        tenant_balance.available_credits -= credits
        extra_balance.available_credits += credits
        allocation = AICreditAllocation(
            tenant_id=tenant_id,
            recipient_quota_account_id=recipient_quota_account_id,
            allocated_by_admin_id=tenant_admin_id,
            credits=credits,
        )
        await AITenantCreditBalanceRepository.save(db, tenant_balance)
        await AIExtraCreditBalanceRepository.save(db, extra_balance)
        await AICreditAllocationRepository.create(db, allocation)
        await AICreditLedgerRepository.create_many(
            db,
            [
                AICreditLedger(
                    tenant_id=tenant_id,
                    quota_account_id=None,
                    bucket=AICreditLedgerBucket.TENANT_RESERVE,
                    event_type=AICreditLedgerEventType.ALLOCATION_OUT,
                    credit_delta=-credits,
                    allocation_id=allocation.id,
                    description="AI credits allocated from tenant reserve.",
                ),
                AICreditLedger(
                    tenant_id=tenant_id,
                    quota_account_id=recipient_quota_account_id,
                    bucket=AICreditLedgerBucket.TOP_UP,
                    event_type=AICreditLedgerEventType.ALLOCATION_IN,
                    credit_delta=credits,
                    allocation_id=allocation.id,
                    description="AI credits allocated to actor top-up balance.",
                ),
            ],
        )
        return allocation

    @classmethod
    async def _release_locked_reservation(
        cls,
        db: AsyncSession,
        *,
        reservation: AICreditReservation,
        expired: bool,
        released_at: datetime,
    ) -> None:
        """Release bucket holds for an already-locked pending reservation."""

        weekly = await cls._locked_weekly_for_reservation(
            db,
            reservation=reservation,
        )
        if weekly.reserved_credits < reservation.reserved_free_credits:
            raise AIQuotaConflictError("Weekly reserved-credit state is inconsistent.")
        weekly.reserved_credits -= reservation.reserved_free_credits
        await AIWeeklyQuotaRepository.save(db, weekly)
        if reservation.reserved_extra_credits:
            extra = await AIExtraCreditBalanceRepository.get_for_account(
                db,
                tenant_id=reservation.tenant_id,
                quota_account_id=reservation.quota_account_id,
                lock=True,
            )
            if extra is None:
                raise AIQuotaConflictError("Reserved extra-credit balance is missing.")
            if extra.reserved_credits < reservation.reserved_extra_credits:
                raise AIQuotaConflictError("Extra reserved-credit state is inconsistent.")
            extra.reserved_credits -= reservation.reserved_extra_credits
            await AIExtraCreditBalanceRepository.save(db, extra)
        reservation.status = (
            AICreditReservationStatus.EXPIRED if expired else AICreditReservationStatus.RELEASED
        )
        reservation.released_at = released_at
        await AICreditReservationRepository.save(db, reservation)

    @classmethod
    async def _locked_weekly_for_reservation(
        cls,
        db: AsyncSession,
        *,
        reservation: AICreditReservation,
    ) -> AIWeeklyQuota:
        """Load the exact weekly bucket that funded a reservation."""

        created_at = reservation.created_at
        if created_at.tzinfo is not None:
            created_date = created_at.astimezone(timezone.utc).date()
        else:
            created_date = created_at.date()
        weekly = await AIWeeklyQuotaRepository.get_for_account_week(
            db,
            tenant_id=reservation.tenant_id,
            quota_account_id=reservation.quota_account_id,
            week_start=cls._week_start(created_date),
            lock=True,
        )
        if weekly is None:
            raise AIQuotaConflictError("Weekly quota backing this reservation is missing.")
        if reservation.weekly_quota_id is not None and weekly.id != reservation.weekly_quota_id:
            raise AIQuotaConflictError("Reservation weekly-quota reference is inconsistent.")
        return weekly

    @classmethod
    async def _ensure_quota_account(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        actor_type: AIQuotaActorType,
        actor_id: uuid.UUID,
    ) -> AIQuotaAccount:
        """Resolve or lazily provision the canonical tenant-scoped quota actor."""

        if actor_type == AIQuotaActorType.TEACHER:
            existing = await AIQuotaAccountRepository.get_by_teacher_membership(
                db,
                tenant_id=tenant_id,
                teacher_membership_id=actor_id,
            )
            if existing is not None:
                return existing
            membership = await TeacherMembershipRepository.get_by_id(
                db,
                actor_id,
                tenant_id=tenant_id,
                load_account=False,
            )
            if membership is None:
                raise AIQuotaNotFoundError("Teacher membership was not found.")
            account = AIQuotaAccount(
                tenant_id=tenant_id,
                actor_type=actor_type,
                teacher_membership_id=actor_id,
                tenant_admin_id=None,
            )
        elif actor_type == AIQuotaActorType.TENANT_ADMIN:
            existing = await AIQuotaAccountRepository.get_by_tenant_admin(
                db,
                tenant_id=tenant_id,
                tenant_admin_id=actor_id,
            )
            if existing is not None:
                return existing
            admin = await TenantAdminRepository.get_by_tenant_and_id(
                db,
                tenant_id=tenant_id,
                admin_id=actor_id,
            )
            if admin is None:
                raise AIQuotaNotFoundError("Tenant admin was not found.")
            account = AIQuotaAccount(
                tenant_id=tenant_id,
                actor_type=actor_type,
                teacher_membership_id=None,
                tenant_admin_id=actor_id,
            )
        else:
            raise ValueError(f"Unsupported AI quota actor type: {actor_type!r}.")
        try:
            await AIQuotaAccountRepository.create(db, account)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
            return account
        except IntegrityError:
            await db.rollback()
            if actor_type == AIQuotaActorType.TEACHER:
                existing = await AIQuotaAccountRepository.get_by_teacher_membership(
                    db,
                    tenant_id=tenant_id,
                    teacher_membership_id=actor_id,
                )
            else:
                existing = await AIQuotaAccountRepository.get_by_tenant_admin(
                    db,
                    tenant_id=tenant_id,
                    tenant_admin_id=actor_id,
                )
            if existing is None:
                raise
            return existing

    @classmethod
    async def _ensure_admin_account(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
    ) -> AIQuotaAccount:
        return await cls._ensure_quota_account(
            db,
            tenant_id=tenant_id,
            actor_type=AIQuotaActorType.TENANT_ADMIN,
            actor_id=tenant_admin_id,
        )

    @classmethod
    async def _ensure_weekly_quota(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_id: uuid.UUID,
        week_start: date,
    ) -> AIWeeklyQuota:
        existing = await AIWeeklyQuotaRepository.get_for_account_week(
            db,
            tenant_id=tenant_id,
            quota_account_id=quota_account_id,
            week_start=week_start,
        )
        if existing is not None:
            return existing
        quota = AIWeeklyQuota(
            tenant_id=tenant_id,
            quota_account_id=quota_account_id,
            week_start=week_start,
            credit_limit=DEFAULT_WEEKLY_FREE_CREDITS,
            used_credits=0,
            reserved_credits=0,
        )
        try:
            await AIWeeklyQuotaRepository.create(db, quota)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
            return quota
        except IntegrityError:
            await db.rollback()
            existing = await AIWeeklyQuotaRepository.get_for_account_week(
                db,
                tenant_id=tenant_id,
                quota_account_id=quota_account_id,
                week_start=week_start,
            )
            if existing is None:
                raise
            return existing

    @classmethod
    async def _ensure_extra_balance(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_id: uuid.UUID,
    ) -> AIExtraCreditBalance:
        existing = await AIExtraCreditBalanceRepository.get_for_account(
            db,
            tenant_id=tenant_id,
            quota_account_id=quota_account_id,
        )
        if existing is not None:
            return existing
        balance = AIExtraCreditBalance(
            tenant_id=tenant_id,
            quota_account_id=quota_account_id,
            available_credits=0,
            reserved_credits=0,
        )
        try:
            await AIExtraCreditBalanceRepository.create(db, balance)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
            return balance
        except IntegrityError:
            await db.rollback()
            existing = await AIExtraCreditBalanceRepository.get_for_account(
                db,
                tenant_id=tenant_id,
                quota_account_id=quota_account_id,
            )
            if existing is None:
                raise
            return existing

    @classmethod
    async def _ensure_tenant_balance(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> AITenantCreditBalance:
        existing = await AITenantCreditBalanceRepository.get_for_tenant(
            db,
            tenant_id=tenant_id,
        )
        if existing is not None:
            return existing
        balance = AITenantCreditBalance(
            tenant_id=tenant_id,
            available_credits=0,
        )
        try:
            await AITenantCreditBalanceRepository.create(db, balance)
            await db.commit()
            await invalidate_quota_cache(tenant_id)
            return balance
        except IntegrityError:
            await db.rollback()
            existing = await AITenantCreditBalanceRepository.get_for_tenant(
                db,
                tenant_id=tenant_id,
            )
            if existing is None:
                raise
            return existing

    @classmethod
    def _quota_status_response(
        cls,
        *,
        account: AIQuotaAccount,
        weekly: AIWeeklyQuota,
        extra: AIExtraCreditBalance | None,
    ) -> AIQuotaStatusResponse:
        weekly_available = max(
            weekly.credit_limit - weekly.used_credits - weekly.reserved_credits,
            0,
        )
        extra_balance = extra.available_credits if extra is not None else 0
        extra_reserved = extra.reserved_credits if extra is not None else 0
        extra_available = max(extra_balance - extra_reserved, 0)
        return AIQuotaStatusResponse(
            quota_account_id=account.id,
            actor_type=account.actor_type,
            actor_id=cls._actor_id(account),
            weekly=AIWeeklyQuotaStatus(
                week_start=weekly.week_start,
                credit_limit=weekly.credit_limit,
                used_credits=weekly.used_credits,
                reserved_credits=weekly.reserved_credits,
                available_credits=weekly_available,
            ),
            extra=AIExtraCreditStatus(
                balance_credits=extra_balance,
                reserved_credits=extra_reserved,
                available_credits=extra_available,
            ),
            total_available_credits=weekly_available + extra_available,
        )

    @staticmethod
    def _quota_request_response(
        request: AIQuotaRequest,
        *,
        requester_name: str | None = None,
        requester_email: str | None = None,
        reviewer_email: str | None = None,
    ) -> AIQuotaRequestResponse:
        return AIQuotaRequestResponse(
            id=request.id,
            requester_quota_account_id=request.requester_quota_account_id,
            requested_credits=request.requested_credits,
            approved_credits=request.approved_credits,
            status=request.status,
            reviewed_by_admin_id=request.reviewed_by_admin_id,
            allocation_id=request.allocation_id,
            admin_note=request.admin_note,
            requester_name=requester_name,
            requester_email=requester_email,
            reviewer_email=reviewer_email,
            created_at=request.created_at,
            reviewed_at=request.reviewed_at,
            cancelled_at=request.cancelled_at,
        )

    @classmethod
    def _allocation_response(
        cls,
        *,
        allocation: AICreditAllocation,
        account: AIQuotaAccount,
        recipient_name: str | None = None,
        recipient_email: str | None = None,
        allocator_email: str | None = None,
    ) -> AICreditAllocationResponse:
        return AICreditAllocationResponse(
            id=allocation.id,
            recipient_quota_account_id=allocation.recipient_quota_account_id,
            recipient_actor_type=account.actor_type,
            recipient_actor_id=cls._actor_id(account),
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            allocated_by_admin_id=allocation.allocated_by_admin_id,
            allocator_email=allocator_email,
            credits=allocation.credits,
            created_at=allocation.created_at,
        )

    @staticmethod
    def _purchase_response(
        purchase: AIQuotaPurchase,
        *,
        initiated_by_email: str | None = None,
    ) -> AIQuotaPurchaseResponse:
        return AIQuotaPurchaseResponse(
            id=purchase.id,
            credits=purchase.credits,
            amount_kobo=purchase.amount_kobo,
            reference=purchase.reference,
            status=purchase.status,
            initiated_by_admin_id=purchase.initiated_by_admin_id,
            initiated_by_email=initiated_by_email,
            created_at=purchase.created_at,
            credited_at=purchase.credited_at,
        )

    @staticmethod
    def _reservation_response(
        reservation: AICreditReservation,
    ) -> AICreditReservationResponse:
        return AICreditReservationResponse(
            id=reservation.id,
            quota_account_id=reservation.quota_account_id,
            status=reservation.status,
            reserved_free_credits=reservation.reserved_free_credits,
            reserved_extra_credits=reservation.reserved_extra_credits,
            total_reserved_credits=(
                reservation.reserved_free_credits + reservation.reserved_extra_credits
            ),
            expires_at=reservation.expires_at,
        )

    @staticmethod
    def _settlement_response(
        reservation: AICreditReservation,
    ) -> AICreditSettlementResponse:
        if reservation.settled_at is None:
            raise AIQuotaConflictError("Settled reservation is missing settled_at.")
        reserved_total = reservation.reserved_free_credits + reservation.reserved_extra_credits
        settled_total = reservation.settled_free_credits + reservation.settled_extra_credits
        return AICreditSettlementResponse(
            reservation_id=reservation.id,
            settled_free_credits=reservation.settled_free_credits,
            settled_extra_credits=reservation.settled_extra_credits,
            total_settled_credits=settled_total,
            released_credits=max(reserved_total - settled_total, 0),
            settled_at=reservation.settled_at,
        )

    @staticmethod
    def _actor_id(account: AIQuotaAccount) -> uuid.UUID:
        if account.actor_type == AIQuotaActorType.TEACHER:
            if account.teacher_membership_id is None:
                raise AIQuotaConflictError("Teacher quota account is malformed.")
            return account.teacher_membership_id
        if account.tenant_admin_id is None:
            raise AIQuotaConflictError("Tenant-admin quota account is malformed.")
        return account.tenant_admin_id

    @staticmethod
    def _actor_display_identity(
        *,
        teacher: TeacherAccount | None,
        admin: TenantAdmin | None,
    ) -> tuple[str, str | None]:
        if teacher is not None:
            name = " ".join(
                part.strip()
                for part in (teacher.first_name, teacher.last_name)
                if part and part.strip()
            )
            return (name or teacher.email, teacher.email)
        if admin is not None:
            return (admin.email, admin.email)
        return ("Unknown actor", None)

    @staticmethod
    def _clean_note(note: str | None) -> str | None:
        if note is None:
            return None
        cleaned = note.strip()
        return cleaned or None

    @staticmethod
    def _require_positive_credits(credits: int) -> None:
        if type(credits) is not int or credits <= 0:
            raise ValueError("credits must be a positive integer.")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _week_start(day: date) -> date:
        return day - timedelta(days=day.weekday())

    @classmethod
    def _current_week_start(cls) -> date:
        return cls._week_start(cls._now().date())
