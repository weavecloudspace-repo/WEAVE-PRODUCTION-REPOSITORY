from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.cbt.ai.quota.payment_schemas import (
    AIQuotaPurchaseCheckoutResponse,
    AIQuotaPurchaseQuote,
)
from app.modules.cbt.ai.quota.pricing import ai_quota_pricing
from app.modules.cbt.ai.quota.repository import AIQuotaPurchaseRepository
from app.modules.cbt.ai.quota.schemas import AIQuotaPurchaseResponse
from app.modules.cbt.ai.quota.cache import invalidate_quota_cache
from app.modules.cbt.ai.quota.service import (
    AIQuotaConflictError,
    AIQuotaNotFoundError,
    AIQuotaService,
)
from app.modules.payments.enums import PaymentPurpose
from app.modules.payments.service import PaymentEngine
from app.modules.payments.webhook import PaymentWebhookSettlementResult


class AIQuotaPaymentService:
    """Tenant AI-credit purchase pricing and payment orchestration."""

    CURRENCY = "NGN"

    @staticmethod
    def quote_purchase(credits: int) -> AIQuotaPurchaseQuote:
        AIQuotaService._require_positive_credits(credits)
        minimum = int(ai_quota_pricing.CBT_AI_MINIMUM_PURCHASE_CREDITS)
        if credits < minimum:
            raise AIQuotaConflictError(f"AI credit purchases must be at least {minimum} credits.")
        unit_price_kobo = int(ai_quota_pricing.CBT_AI_CREDIT_UNIT_PRICE_KOBO)
        if unit_price_kobo <= 0:
            raise AIQuotaConflictError("AI credit purchasing is not configured.")
        return AIQuotaPurchaseQuote(
            credits=credits,
            unit_price_kobo=unit_price_kobo,
            amount_kobo=credits * unit_price_kobo,
            currency=AIQuotaPaymentService.CURRENCY,
        )

    @classmethod
    async def initialize_purchase_checkout(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        email: str,
        credits: int,
    ) -> AIQuotaPurchaseCheckoutResponse:
        quote = cls.quote_purchase(credits)
        callback_url = str(settings.PAYSTACK_AI_CREDIT_CALLBACK_URL or "").strip()
        if settings.is_production_like and not callback_url:
            raise AIQuotaConflictError(
                "PAYSTACK_AI_CREDIT_CALLBACK_URL is not configured for this environment."
            )

        reference = f"ai-credit-{tenant_id.hex[:12]}-{uuid.uuid4().hex[:16]}"
        purchase = await AIQuotaService.create_pending_purchase(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
            credits=quote.credits,
            amount_kobo=quote.amount_kobo,
            reference=reference,
        )
        metadata: dict[str, Any] = {
            "payment_purpose": PaymentPurpose.AI_CREDIT_PURCHASE.value,
            "tenant_id": str(tenant_id),
            "quota_purchase_id": str(purchase.id),
            "credits": quote.credits,
            "amount_kobo": quote.amount_kobo,
        }
        try:
            checkout = await PaymentEngine.initialize_checkout(
                email=email,
                amount_kobo=quote.amount_kobo,
                reference=reference,
                callback_url=callback_url,
                metadata=metadata,
            )
        except Exception:
            await AIQuotaService.mark_purchase_failed(
                db,
                tenant_id=tenant_id,
                reference=reference,
            )
            raise

        return AIQuotaPurchaseCheckoutResponse(
            purchase=purchase,
            quote=quote,
            authorization_url=checkout.authorization_url,
            access_code=checkout.access_code,
        )

    @classmethod
    async def verify_purchase_checkout(
        cls,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        reference: str,
    ) -> AIQuotaPurchaseResponse:
        await AIQuotaService._ensure_admin_account(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=tenant_admin_id,
        )
        purchase = await AIQuotaPurchaseRepository.get_by_reference(
            db,
            reference=reference.strip(),
        )
        if (
            purchase is None
            or purchase.tenant_id != tenant_id
            or purchase.initiated_by_admin_id != tenant_admin_id
        ):
            raise AIQuotaNotFoundError("Quota purchase was not found.")

        await PaymentEngine.verify_transaction(
            reference=purchase.reference,
            expected_amount_kobo=purchase.amount_kobo,
            expected_currency=cls.CURRENCY,
            expected_metadata={
                "payment_purpose": PaymentPurpose.AI_CREDIT_PURCHASE.value,
                "tenant_id": str(purchase.tenant_id),
                "quota_purchase_id": str(purchase.id),
                "credits": purchase.credits,
                "amount_kobo": purchase.amount_kobo,
            },
        )
        return await AIQuotaService.credit_verified_purchase(
            db,
            tenant_id=tenant_id,
            reference=purchase.reference,
        )

    @classmethod
    async def settle_verified_webhook_purchase(
        cls,
        db: AsyncSession,
        payload: dict[str, Any],
    ) -> PaymentWebhookSettlementResult:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        reference = str(data.get("reference") or "").strip()
        purchase = await AIQuotaPurchaseRepository.get_by_reference(
            db,
            reference=reference,
            lock=True,
        )
        if purchase is None:
            raise AIQuotaNotFoundError("Quota purchase was not found.")

        PaymentEngine.validate_successful_payload(
            payload,
            expected_reference=purchase.reference,
            expected_amount_kobo=purchase.amount_kobo,
            expected_currency=cls.CURRENCY,
            expected_metadata={
                "payment_purpose": PaymentPurpose.AI_CREDIT_PURCHASE.value,
                "tenant_id": str(purchase.tenant_id),
                "quota_purchase_id": str(purchase.id),
                "credits": purchase.credits,
                "amount_kobo": purchase.amount_kobo,
            },
        )
        await AIQuotaService.credit_verified_purchase(
            db,
            tenant_id=purchase.tenant_id,
            reference=purchase.reference,
            commit=False,
        )
        return PaymentWebhookSettlementResult(
            message="AI credit purchase webhook processed successfully."
            post_commit=lambda: invalidate_quota_cache(purchase.tenant_id),
        )
