from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.payments.service import PaymentVerificationError
from app.modules.subscriptions import pending_payment_reconciliation as recovery
from app.modules.subscriptions.models import PaymentTransaction
from app.modules.subscriptions.subscription_enums import (
    BillingInterval,
    PaymentProvider,
    PaymentStatus,
)
from app.tenant_management.models import SubscriptionPlan


def _transaction(status: PaymentStatus = PaymentStatus.PENDING) -> PaymentTransaction:
    transaction = PaymentTransaction(
        id=uuid4(),
        tenant_id=uuid4(),
        academic_term_id=uuid4(),
        provider=PaymentProvider.PAYSTACK,
        status=status,
        reference=f"term-{uuid4().hex}",
        plan_code=SubscriptionPlan.PROFESSIONAL,
        billing_interval=BillingInterval.TERM,
        amount=Decimal("35000.00"),
        amount_kobo=3_500_000,
        currency="NGN",
        raw_payload={"quote": {"amount_due_kobo": 3_500_000}},
    )
    transaction.created_at = datetime.now(timezone.utc)
    return transaction


def _successful_response(transaction: PaymentTransaction) -> dict:
    return {
        "data": {
            "status": "success",
            "reference": transaction.reference,
            "amount": transaction.amount_kobo,
            "currency": transaction.currency,
            "id": 1234,
            "metadata": {
                "payment_purpose": "term_subscription",
                "tenant_id": str(transaction.tenant_id),
                "academic_term_id": str(transaction.academic_term_id),
                "plan_code": transaction.plan_code.value,
            },
        }
    }


def _session_factory(transaction: PaymentTransaction):
    query_result = SimpleNamespace(scalar_one_or_none=lambda: transaction)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=query_result),
        commit=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return SessionContext, session


@pytest.mark.asyncio
async def test_claim_marks_cooldown_without_overwriting_quote(monkeypatch) -> None:
    transaction = _transaction()
    factory, db = _session_factory(transaction)
    monkeypatch.setattr(recovery, "AsyncSessionLocal", factory)
    now = datetime.now(timezone.utc)

    first = await recovery._claim(transaction.reference, now)
    second = await recovery._claim(transaction.reference, now)

    assert first is not None
    assert first.amount_kobo == transaction.amount_kobo
    assert second is None
    assert transaction.raw_payload["quote"]["amount_due_kobo"] == 3_500_000
    assert transaction.raw_payload[recovery.PROBE_KEY]["attempts"] == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_success_uses_existing_settlement_path(monkeypatch) -> None:
    transaction = _transaction()
    factory, db = _session_factory(transaction)
    monkeypatch.setattr(recovery, "AsyncSessionLocal", factory)
    response = _successful_response(transaction)

    with (
        patch.object(
            recovery,
            "settle_verified_term_payment",
            new=AsyncMock(return_value=object()),
        ) as settle,
        patch.object(
            recovery,
            "invalidate_tenant_subscription_cache",
            new=AsyncMock(),
        ) as invalidate,
    ):
        result = await recovery._settle(
            recovery.PaymentProbe(
                reference=transaction.reference,
                amount_kobo=transaction.amount_kobo,
                currency=transaction.currency,
                tenant_id=str(transaction.tenant_id),
                academic_term_id=str(transaction.academic_term_id),
                plan_code=transaction.plan_code.value,
            ),
            response,
        )

    assert result == "settled"
    settle.assert_awaited_once()
    assert settle.await_args.kwargs["commit"] is False
    db.commit.assert_awaited_once()
    invalidate.assert_awaited_once_with(transaction.tenant_id)


@pytest.mark.asyncio
async def test_abandoned_success_requires_manual_review(monkeypatch) -> None:
    transaction = _transaction(status=PaymentStatus.ABANDONED)
    factory, db = _session_factory(transaction)
    monkeypatch.setattr(recovery, "AsyncSessionLocal", factory)

    with (
        patch.object(
            recovery,
            "settle_verified_term_payment",
            new=AsyncMock(return_value=None),
        ) as settle,
        patch.object(
            recovery,
            "invalidate_tenant_subscription_cache",
            new=AsyncMock(),
        ),
    ):
        result = await recovery._settle(
            recovery.PaymentProbe(
                reference=transaction.reference,
                amount_kobo=transaction.amount_kobo,
                currency=transaction.currency,
                tenant_id=str(transaction.tenant_id),
                academic_term_id=str(transaction.academic_term_id),
                plan_code=transaction.plan_code.value,
            ),
            _successful_response(transaction),
        )

    assert result == "review_required"
    settle.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mismatched_success_never_calls_settlement(monkeypatch) -> None:
    transaction = _transaction()
    factory, db = _session_factory(transaction)
    monkeypatch.setattr(recovery, "AsyncSessionLocal", factory)
    response = _successful_response(transaction)
    response["data"]["metadata"]["tenant_id"] = str(uuid4())

    with patch.object(recovery, "settle_verified_term_payment", new=AsyncMock()) as settle:
        with pytest.raises(PaymentVerificationError):
            await recovery._settle(
                recovery.PaymentProbe(
                    reference=transaction.reference,
                    amount_kobo=transaction.amount_kobo,
                    currency=transaction.currency,
                    tenant_id=str(transaction.tenant_id),
                    academic_term_id=str(transaction.academic_term_id),
                    plan_code=transaction.plan_code.value,
                ),
                response,
            )

    settle.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_provider_state_is_retried_without_settlement(monkeypatch) -> None:
    transaction = _transaction()
    probe = recovery.PaymentProbe(
        reference=transaction.reference,
        amount_kobo=transaction.amount_kobo,
        currency=transaction.currency,
        tenant_id=str(transaction.tenant_id),
        academic_term_id=str(transaction.academic_term_id),
        plan_code=transaction.plan_code.value,
    )
    monkeypatch.setattr(
        recovery, "_due_references", AsyncMock(return_value=[transaction.reference])
    )
    monkeypatch.setattr(recovery, "_claim", AsyncMock(return_value=probe))
    settle = AsyncMock()
    monkeypatch.setattr(recovery, "_settle", settle)
    fake_provider = SimpleNamespace(
        verify_transaction=AsyncMock(return_value={"data": {"status": "pending"}})
    )
    monkeypatch.setattr(recovery, "PaystackClient", lambda: fake_provider)

    result = await recovery.reconcile_pending_term_payments()

    assert result["claimed"] == 1
    assert result["not_successful"] == 1
    assert result["settled"] == 0
    settle.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_isolated_from_next_payment(monkeypatch) -> None:
    first = _transaction()
    second = _transaction()
    monkeypatch.setattr(
        recovery,
        "_due_references",
        AsyncMock(return_value=[first.reference, second.reference]),
    )
    monkeypatch.setattr(
        recovery,
        "_claim",
        AsyncMock(
            side_effect=[
                recovery.PaymentProbe(
                    first.reference,
                    first.amount_kobo,
                    first.currency,
                    str(first.tenant_id),
                    str(first.academic_term_id),
                    first.plan_code.value,
                ),
                recovery.PaymentProbe(
                    second.reference,
                    second.amount_kobo,
                    second.currency,
                    str(second.tenant_id),
                    str(second.academic_term_id),
                    second.plan_code.value,
                ),
            ]
        ),
    )
    provider = SimpleNamespace(
        verify_transaction=AsyncMock(
            side_effect=[RuntimeError("provider unavailable"), _successful_response(second)]
        )
    )
    monkeypatch.setattr(recovery, "PaystackClient", lambda: provider)
    monkeypatch.setattr(recovery, "_settle", AsyncMock(return_value="settled"))

    result = await recovery.reconcile_pending_term_payments()

    assert result["errors"] == 1
    assert result["settled"] == 1
