from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.payments.providers.paystack import PaystackClient
from app.modules.payments.service import (
    PaymentEngine,
    PaymentNotCompletedError,
    PaymentVerificationError,
)


def test_shared_paystack_client_has_no_legacy_recurring_plan_methods() -> None:
    assert not hasattr(PaystackClient, "fetch_plan")
    assert not hasattr(PaystackClient, "fetch_subscription")
    assert not hasattr(PaystackClient, "fetch_customer")
    assert not hasattr(PaystackClient, "list_subscriptions")
    assert not hasattr(PaystackClient, "disable_subscription")


@pytest.mark.asyncio
async def test_initialize_checkout_passes_backend_owned_amount_and_metadata(monkeypatch) -> None:
    provider = SimpleNamespace(
        initialize_transaction=AsyncMock(
            return_value={
                "status": True,
                "data": {
                    "authorization_url": "https://paystack.test/checkout",
                    "access_code": "access-code",
                },
            }
        )
    )
    monkeypatch.setattr("app.modules.payments.service.PaystackClient", lambda: provider)

    result = await PaymentEngine.initialize_checkout(
        email="admin@example.com",
        amount_kobo=250_000,
        reference="ai-credit-ref",
        callback_url="https://example.com/payments/callback",
        metadata={"payment_purpose": "ai_credit_purchase", "credits": 2500},
    )

    assert result.reference == "ai-credit-ref"
    assert result.authorization_url == "https://paystack.test/checkout"
    provider.initialize_transaction.assert_awaited_once_with(
        email="admin@example.com",
        amount_kobo=250_000,
        reference="ai-credit-ref",
        callback_url="https://example.com/payments/callback",
        metadata={"payment_purpose": "ai_credit_purchase", "credits": 2500},
    )


@pytest.mark.asyncio
async def test_initialize_checkout_rejects_non_positive_amount_before_provider_call(
    monkeypatch,
) -> None:
    provider = SimpleNamespace(initialize_transaction=AsyncMock())
    monkeypatch.setattr("app.modules.payments.service.PaystackClient", lambda: provider)

    with pytest.raises(ValueError, match="positive integer"):
        await PaymentEngine.initialize_checkout(
            email="admin@example.com",
            amount_kobo=0,
            reference="ref",
            callback_url="https://example.com/callback",
            metadata={},
        )

    provider.initialize_transaction.assert_not_awaited()


def test_verified_payload_rejects_amount_currency_reference_and_metadata_tampering() -> None:
    payload = {
        "data": {
            "id": 123,
            "status": "success",
            "reference": "expected-ref",
            "amount": 10_000,
            "currency": "NGN",
            "metadata": {
                "tenant_id": "tenant-1",
                "payment_purpose": "ai_credit_purchase",
            },
        }
    }

    verified = PaymentEngine.validate_successful_payload(
        payload,
        expected_reference="expected-ref",
        expected_amount_kobo=10_000,
        expected_currency="NGN",
        expected_metadata={
            "tenant_id": "tenant-1",
            "payment_purpose": "ai_credit_purchase",
        },
    )
    assert verified.provider_transaction_id == "123"
    assert verified.amount_kobo == 10_000

    for mutated, expected_message in (
        ({**payload["data"], "reference": "wrong-ref"}, "payment expectation"),
        ({**payload["data"], "amount": 1}, "payment expectation"),
        ({**payload["data"], "currency": "USD"}, "payment expectation"),
    ):
        with pytest.raises(PaymentVerificationError, match=expected_message):
            PaymentEngine.validate_successful_payload(
                {"data": mutated},
                expected_reference="expected-ref",
                expected_amount_kobo=10_000,
                expected_currency="NGN",
            )

    with pytest.raises(PaymentVerificationError, match="metadata"):
        PaymentEngine.validate_successful_payload(
            payload,
            expected_reference="expected-ref",
            expected_amount_kobo=10_000,
            expected_currency="NGN",
            expected_metadata={"tenant_id": "other-tenant"},
        )


@pytest.mark.asyncio
async def test_verify_transaction_uses_provider_then_validates_backend_expectation(
    monkeypatch,
) -> None:
    provider = SimpleNamespace(
        verify_transaction=AsyncMock(
            return_value={
                "data": {
                    "id": 99,
                    "status": "success",
                    "reference": "term-ref",
                    "amount": 35_000,
                    "currency": "NGN",
                    "metadata": {"tenant_id": "tenant-1"},
                }
            }
        )
    )
    monkeypatch.setattr("app.modules.payments.service.PaystackClient", lambda: provider)

    result = await PaymentEngine.verify_transaction(
        reference="term-ref",
        expected_amount_kobo=35_000,
        expected_currency="NGN",
        expected_metadata={"tenant_id": "tenant-1"},
    )

    assert result.reference == "term-ref"
    provider.verify_transaction.assert_awaited_once_with(reference="term-ref")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["abandoned", "failed", "pending", "ongoing", "processing", "queued"]
)
async def test_verify_transaction_distinguishes_unpaid_status(monkeypatch, status) -> None:
    provider = SimpleNamespace(
        verify_transaction=AsyncMock(return_value={"data": {"status": status, "reference": "ref"}})
    )
    monkeypatch.setattr("app.modules.payments.service.PaystackClient", lambda: provider)
    with pytest.raises(PaymentNotCompletedError) as raised:
        await PaymentEngine.verify_transaction(
            reference="ref", expected_amount_kobo=200_000, expected_currency="NGN"
        )
    assert raised.value.status == status


@pytest.mark.asyncio
async def test_unpaid_wrong_reference_is_integrity_error(monkeypatch) -> None:
    provider = SimpleNamespace(
        verify_transaction=AsyncMock(
            return_value={"data": {"status": "pending", "reference": "wrong"}}
        )
    )
    monkeypatch.setattr("app.modules.payments.service.PaystackClient", lambda: provider)
    with pytest.raises(PaymentVerificationError) as raised:
        await PaymentEngine.verify_transaction(
            reference="ref", expected_amount_kobo=200_000, expected_currency="NGN"
        )
    assert not isinstance(raised.value, PaymentNotCompletedError)
