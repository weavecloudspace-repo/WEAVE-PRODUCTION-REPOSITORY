"""Shared teacher purchase entry point for cloud staff and CBT staff.

Only the authenticated teacher's active membership may receive purchased credits.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.modules.cbt.ai.quota.payment_schemas import AIQuotaPurchaseCheckoutResponse, AIQuotaPurchaseQuote
from app.modules.cbt.ai.quota.payment_service import AIQuotaPaymentService
from app.modules.cbt.ai.quota.models import AIQuotaPurchaseStatus
from app.modules.cbt.ai.quota.schemas import AIQuotaPurchaseListResponse, AIQuotaPurchaseResponse
from app.modules.cbt.ai.quota.service import AIQuotaError, AIQuotaService
from app.modules.cbt.ai.service import CBTAIService
from app.modules.teachers.models import TeacherAccountStatus, TeacherMembershipStatus
from app.modules.teachers.repository import TeacherMembershipRepository


class AITeacherPurchaseService:
    @staticmethod
    def quote(credits: int) -> AIQuotaPurchaseQuote:
        try:
            return AIQuotaPaymentService.quote_purchase(credits)
        except AIQuotaError as exc:
            CBTAIService._raise_quota_error(exc)
            raise

    @staticmethod
    async def _active_membership(
        db: AsyncSession, *, tenant_id: UUID, membership_id: UUID,
    ):
        membership = await TeacherMembershipRepository.get_by_id(
            db, membership_id, tenant_id=tenant_id, load_account=True,
        )
        if (
            membership is None
            or membership.status != TeacherMembershipStatus.ACTIVE
            or membership.teacher_account is None
            or membership.teacher_account.account_status != TeacherAccountStatus.ACTIVE
            or not membership.teacher_account.is_active
        ):
            raise ForbiddenException("An active teacher membership is required.")
        return membership

    @classmethod
    async def checkout(
        cls, db: AsyncSession, *, tenant_id: UUID,
        membership_id: UUID, credits: int,
    ) -> AIQuotaPurchaseCheckoutResponse:
        membership = await cls._active_membership(
            db, tenant_id=tenant_id, membership_id=membership_id,
        )
        return await CBTAIService._run_quota(
            AIQuotaPaymentService.initialize_teacher_checkout(
                db, tenant_id=tenant_id, teacher_membership_id=membership_id,
                email=membership.teacher_account.email, credits=credits,
            )
        )

    @classmethod
    async def verify(
        cls, db: AsyncSession, *, tenant_id: UUID,
        membership_id: UUID, reference: str,
    ) -> AIQuotaPurchaseResponse:
        await cls._active_membership(
            db, tenant_id=tenant_id, membership_id=membership_id,
        )
        return await CBTAIService._run_quota(
            AIQuotaPaymentService.verify_teacher_checkout(
                db, tenant_id=tenant_id,
                teacher_membership_id=membership_id, reference=reference,
            )
        )

    @classmethod
    async def list_purchases(
        cls, db: AsyncSession, *, tenant_id: UUID,
        membership_id: UUID,
        status: AIQuotaPurchaseStatus | None = None,
        offset: int = 0, limit: int = 50,
    ) -> AIQuotaPurchaseListResponse:
        await cls._active_membership(
            db, tenant_id=tenant_id, membership_id=membership_id,
        )
        return await CBTAIService._run_quota(
            AIQuotaService.list_teacher_purchases(
                db, tenant_id=tenant_id, teacher_membership_id=membership_id,
                status=status, offset=offset, limit=limit,
            )
        )
