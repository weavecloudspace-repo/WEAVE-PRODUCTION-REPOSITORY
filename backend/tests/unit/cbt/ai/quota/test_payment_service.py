from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

from app.config.settings import EnvironmentType
from app.core.exceptions import AppException, ConflictException
from app.modules.cbt.ai.quota.models import AIQuotaPurchaseStatus
from app.modules.cbt.ai.quota.payment_service import AIQuotaPaymentService
from app.modules.cbt.ai.quota.pricing import ai_quota_pricing
from app.modules.cbt.ai.quota.repository import AIQuotaPurchaseRepository
from app.modules.cbt.ai.quota.schemas import AIQuotaPurchaseResponse
from app.modules.cbt.ai.quota.service import AIQuotaConflictError, AIQuotaService
from app.modules.payments.providers.paystack import PaystackProviderError
from app.modules.payments.service import (
    PaymentEngine,
    PaymentNotCompletedError,
    PaymentVerificationError,
)


def _purchase_response(*, tenant_id, admin_id, credits, amount_kobo, reference):
    return AIQuotaPurchaseResponse(
        id=uuid4(),
        credits=credits,
        amount_kobo=amount_kobo,
        reference=reference,
        status=AIQuotaPurchaseStatus.PENDING,
        initiated_by_admin_id=admin_id,
        created_at=datetime.now(timezone.utc),
    )


def test_quote_uses_environment_price_and_minimum_without_maximum(monkeypatch) -> None:
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", 25)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 100)

    with pytest.raises(AIQuotaConflictError, match="at least 100"):
        AIQuotaPaymentService.quote_purchase(99)

    quote = AIQuotaPaymentService.quote_purchase(10_000_000)
    assert quote.credits == 10_000_000
    assert quote.unit_price_kobo == 25
    assert quote.amount_kobo == 250_000_000


def test_quote_rejects_checkout_when_unit_price_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", 0)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 1)

    with pytest.raises(AIQuotaConflictError, match="not configured"):
        AIQuotaPaymentService.quote_purchase(500)


@pytest.mark.asyncio
async def test_checkout_calculates_total_server_side_and_passes_trusted_amount(monkeypatch) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    monkeypatch.setattr(
        ai_quota_pricing, "PAYSTACK_CALLBACK_URL", "https://example.com/billing/subscription/verify"
    )
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", 40)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 100)
    monkeypatch.setattr(
        "app.modules.cbt.ai.quota.payment_service.settings.PAYSTACK_AI_CREDIT_CALLBACK_URL",
        "https://example.com/payments/ai-credits/complete",
    )

    async def create_pending(_db, **kwargs):
        return _purchase_response(
            tenant_id=tenant_id,
            admin_id=admin_id,
            credits=kwargs["credits"],
            amount_kobo=kwargs["amount_kobo"],
            reference=kwargs["reference"],
        )

    create_pending_mock = AsyncMock(side_effect=create_pending)
    monkeypatch.setattr(AIQuotaService, "create_pending_purchase", create_pending_mock)
    initialize = AsyncMock(
        return_value=SimpleNamespace(
            authorization_url="https://paystack.test/checkout",
            access_code="access-code",
        )
    )
    monkeypatch.setattr(PaymentEngine, "initialize_checkout", initialize)

    result = await AIQuotaPaymentService.initialize_purchase_checkout(
        SimpleNamespace(),
        tenant_id=tenant_id,
        tenant_admin_id=admin_id,
        email="admin@example.com",
        credits=2_500,
    )

    assert result.quote.amount_kobo == 100_000
    assert result.purchase.amount_kobo == 100_000
    create_kwargs = create_pending_mock.await_args.kwargs
    assert create_kwargs["amount_kobo"] == 100_000
    assert create_kwargs["credits"] == 2_500
    payment_kwargs = initialize.await_args.kwargs
    assert payment_kwargs["callback_url"] == "https://example.com/payments/ai-credits/complete"
    assert payment_kwargs["amount_kobo"] == 100_000
    assert payment_kwargs["metadata"]["credits"] == 2_500
    assert payment_kwargs["metadata"]["payment_purpose"] == "ai_credit_purchase"


@pytest.mark.asyncio
async def test_provider_initialization_failure_marks_pending_purchase_failed(monkeypatch) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", 10)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 1)
    monkeypatch.setattr(
        "app.modules.cbt.ai.quota.payment_service.settings.PAYSTACK_AI_CREDIT_CALLBACK_URL",
        "https://example.com/payments/ai-credits/complete",
    )

    purchase = _purchase_response(
        tenant_id=tenant_id,
        admin_id=admin_id,
        credits=500,
        amount_kobo=5_000,
        reference="ai-credit-ref",
    )
    monkeypatch.setattr(
        AIQuotaService,
        "create_pending_purchase",
        AsyncMock(return_value=purchase),
    )
    monkeypatch.setattr(
        PaymentEngine,
        "initialize_checkout",
        AsyncMock(side_effect=RuntimeError("provider unavailable")),
    )
    mark_failed = AsyncMock(return_value=purchase)
    monkeypatch.setattr(AIQuotaService, "mark_purchase_failed", mark_failed)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await AIQuotaPaymentService.initialize_purchase_checkout(
            SimpleNamespace(),
            tenant_id=tenant_id,
            tenant_admin_id=admin_id,
            email="admin@example.com",
            credits=500,
        )

    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.kwargs["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_browser_verification_uses_backend_purchase_expectation_before_crediting(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    purchase = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        initiated_by_admin_id=admin_id,
        credits=500,
        amount_kobo=25_000,
        reference="ai-credit-ref",
    )
    monkeypatch.setattr(AIQuotaService, "_ensure_admin_account", AsyncMock())
    monkeypatch.setattr(
        AIQuotaPurchaseRepository,
        "get_by_reference",
        AsyncMock(return_value=purchase),
    )
    verify = AsyncMock()
    monkeypatch.setattr(PaymentEngine, "verify_transaction", verify)
    credited = _purchase_response(
        tenant_id=tenant_id,
        admin_id=admin_id,
        credits=500,
        amount_kobo=25_000,
        reference="ai-credit-ref",
    ).model_copy(update={"status": AIQuotaPurchaseStatus.SUCCESS})
    credit = AsyncMock(return_value=credited)
    monkeypatch.setattr(AIQuotaService, "credit_verified_purchase", credit)

    result = await AIQuotaPaymentService.verify_purchase_checkout(
        SimpleNamespace(),
        tenant_id=tenant_id,
        tenant_admin_id=admin_id,
        reference="ai-credit-ref",
    )

    assert result.status == AIQuotaPurchaseStatus.SUCCESS
    verify.assert_awaited_once()
    assert verify.await_args.kwargs["expected_amount_kobo"] == 25_000
    assert verify.await_args.kwargs["expected_metadata"]["credits"] == 500
    credit.assert_awaited_once_with(
        ANY,
        tenant_id=tenant_id,
        reference="ai-credit-ref",
    )


@pytest.mark.asyncio
async def test_webhook_settlement_rejects_tampered_amount_before_crediting(monkeypatch) -> None:
    tenant_id = uuid4()
    purchase = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        initiated_by_admin_id=uuid4(),
        credits=500,
        amount_kobo=25_000,
        reference="ai-credit-ref",
    )
    monkeypatch.setattr(
        AIQuotaPurchaseRepository,
        "get_by_reference",
        AsyncMock(return_value=purchase),
    )
    credit = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "credit_verified_purchase", credit)

    payload = {
        "data": {
            "id": 1,
            "status": "success",
            "reference": "ai-credit-ref",
            "amount": 1,
            "currency": "NGN",
            "metadata": {
                "payment_purpose": "ai_credit_purchase",
                "tenant_id": str(tenant_id),
                "quota_purchase_id": str(purchase.id),
                "credits": 500,
                "amount_kobo": 25_000,
            },
        }
    }

    with pytest.raises(PaymentVerificationError):
        await AIQuotaPaymentService.settle_verified_webhook_purchase(
            SimpleNamespace(),
            payload,
        )

    credit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", [EnvironmentType.STAGING, EnvironmentType.PRODUCTION])
@pytest.mark.parametrize("callback", [None, "", "   "])
async def test_missing_ai_callback_never_falls_back_to_subscription(
    monkeypatch,
    environment,
    callback,
) -> None:
    monkeypatch.setattr(ai_quota_pricing, "ENV", environment)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", 2000)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 1)
    monkeypatch.setattr(ai_quota_pricing, "PAYSTACK_AI_CREDIT_CALLBACK_URL", callback)
    monkeypatch.setattr(
        ai_quota_pricing,
        "PAYSTACK_CALLBACK_URL",
        "https://example.com/billing/subscription/verify",
    )
    create_pending = AsyncMock()
    initialize = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "create_pending_purchase", create_pending)
    monkeypatch.setattr(PaymentEngine, "initialize_checkout", initialize)

    with pytest.raises(AIQuotaConflictError, match="PAYSTACK_AI_CREDIT_CALLBACK_URL"):
        await AIQuotaPaymentService.initialize_purchase_checkout(
            SimpleNamespace(),
            tenant_id=uuid4(),
            tenant_admin_id=uuid4(),
            email="admin@example.com",
            credits=10,
        )

    create_pending.assert_not_awaited()
    initialize.assert_not_awaited()


def test_twenty_naira_credit_price(monkeypatch) -> None:
    from app.config.settings import Settings

    default_price = Settings.model_fields["CBT_AI_CREDIT_UNIT_PRICE_KOBO"].default
    assert default_price == 2000
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_CREDIT_UNIT_PRICE_KOBO", default_price)
    monkeypatch.setattr(ai_quota_pricing, "CBT_AI_MINIMUM_PURCHASE_CREDITS", 1)
    assert AIQuotaPaymentService.quote_purchase(3).amount_kobo == 6000


@pytest.mark.asyncio
@pytest.mark.parametrize("teacher", [False, True])
@pytest.mark.parametrize(
    ("error", "expected_status", "message"),
    [
        (PaymentNotCompletedError("abandoned"), 409, "not been completed"),
        (PaymentNotCompletedError("pending"), 409, "awaiting confirmation"),
        (PaymentNotCompletedError("failed"), 409, "unsuccessful"),
        (PaymentVerificationError("mismatch"), 409, "Contact support"),
        (PaystackProviderError("provider unavailable"), 503, "temporarily unavailable"),
    ],
)
async def test_unverified_purchase_returns_safe_error_without_crediting(
    monkeypatch, teacher, error, expected_status, message
) -> None:
    tenant_id, actor_id = uuid4(), uuid4()
    purchase = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        initiated_by_admin_id=actor_id if not teacher else None,
        initiated_by_teacher_membership_id=actor_id if teacher else None,
        credits=100,
        amount_kobo=200_000,
        reference="ai-credit-ref",
    )
    monkeypatch.setattr(AIQuotaService, "_ensure_admin_account", AsyncMock())
    monkeypatch.setattr(
        AIQuotaPurchaseRepository, "get_by_reference", AsyncMock(return_value=purchase)
    )
    monkeypatch.setattr(PaymentEngine, "verify_transaction", AsyncMock(side_effect=error))
    credit = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "credit_verified_purchase", credit)
    with pytest.raises(AppException, match=message) as raised:
        if teacher:
            await AIQuotaPaymentService.verify_teacher_checkout(
                SimpleNamespace(),
                tenant_id=tenant_id,
                teacher_membership_id=actor_id,
                reference=purchase.reference,
            )
        else:
            await AIQuotaPaymentService.verify_purchase_checkout(
                SimpleNamespace(),
                tenant_id=tenant_id,
                tenant_admin_id=actor_id,
                reference=purchase.reference,
            )
    assert raised.value.status_code == expected_status
    if expected_status == 409:
        assert isinstance(raised.value, ConflictException)
    credit.assert_not_awaited()
