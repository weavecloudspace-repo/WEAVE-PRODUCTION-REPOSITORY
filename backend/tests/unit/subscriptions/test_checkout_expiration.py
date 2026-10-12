"""Provider-aware expiry must never equate a local TTL with payment failure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException
from app.modules.subscriptions.checkout_expiration import (
    PENDING_GATEWAY_GRACE,
    verify_before_abandoning,
)
from app.modules.subscriptions.models import PaymentTransaction
from app.modules.subscriptions.subscription_enums import (
    BillingInterval,
    PaymentProvider,
    PaymentStatus,
)
from app.modules.subscriptions.term_entitlement_service import (
    PENDING_CHECKOUT_TTL,
    TermPlanEntitlementService,
)
from app.tenant_management.models import SubscriptionPlan


def transaction(*, age: timedelta = timedelta(minutes=31)) -> PaymentTransaction:
    row = PaymentTransaction(
        id=uuid4(),
        tenant_id=uuid4(),
        academic_term_id=uuid4(),
        provider=PaymentProvider.PAYSTACK,
        status=PaymentStatus.PENDING,
        reference=f"term-{uuid4().hex}",
        plan_code=SubscriptionPlan.PLUS,
        billing_interval=BillingInterval.TERM,
        amount=Decimal("40000.00"),
        amount_kobo=4_000_000,
        currency="NGN",
    )
    row.created_at = datetime.now(timezone.utc) - age
    return row


def gateway(row: PaymentTransaction, status: str) -> dict:
    return {
        "data": {
            "id": 90001,
            "reference": row.reference,
            "status": status,
            "amount": row.amount_kobo,
            "currency": row.currency,
            "metadata": {
                "payment_purpose": "term_subscription",
                "tenant_id": str(row.tenant_id),
                "academic_term_id": str(row.academic_term_id),
                "plan_code": row.plan_code.value,
            },
        }
    }


def fake_provider(monkeypatch, *, response=None, error=None):
    client = SimpleNamespace(
        verify_transaction=AsyncMock(
            side_effect=error,
            return_value=response,
        )
    )
    monkeypatch.setattr(
        "app.modules.subscriptions.checkout_expiration.PaystackClient",
        lambda: client,
    )
    return client


@pytest.mark.asyncio
async def test_gateway_success_settles_instead_of_abandoning(monkeypatch) -> None:
    row = transaction()
    client = fake_provider(monkeypatch, response=gateway(row, "success"))
    with patch(
        "app.modules.subscriptions.payment_settlement.settle_verified_term_payment",
        new=AsyncMock(return_value=object()),
    ) as settle:
        decision = await verify_before_abandoning(MagicMock(), row)

    assert decision == "settled"
    assert row.status == PaymentStatus.PENDING  # the mocked settler does not mutate
    client.verify_transaction.assert_awaited_once_with(reference=row.reference)
    assert settle.await_args.kwargs["commit"] is False


@pytest.mark.asyncio
async def test_pending_gateway_payment_in_grace_is_not_abandoned(monkeypatch) -> None:
    row = transaction(age=PENDING_CHECKOUT_TTL + timedelta(minutes=1))
    fake_provider(monkeypatch, response=gateway(row, "pending"))
    assert await verify_before_abandoning(MagicMock(), row) == "deferred"
    assert row.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_stale_gateway_pending_is_abandoned_after_grace(monkeypatch) -> None:
    row = transaction(age=PENDING_GATEWAY_GRACE + timedelta(minutes=1))
    fake_provider(monkeypatch, response=gateway(row, "pending"))
    assert await verify_before_abandoning(MagicMock(), row) == "abandoned"
    assert row.status == PaymentStatus.ABANDONED


@pytest.mark.asyncio
async def test_confirmed_failed_payment_can_be_abandoned(monkeypatch) -> None:
    row = transaction()
    fake_provider(monkeypatch, response=gateway(row, "failed"))
    assert await verify_before_abandoning(MagicMock(), row) == "abandoned"
    assert row.status == PaymentStatus.ABANDONED


@pytest.mark.asyncio
async def test_provider_timeout_defers_abandonment(monkeypatch) -> None:
    row = transaction(age=timedelta(days=3))
    fake_provider(monkeypatch, error=TimeoutError("Paystack unavailable"))
    assert await verify_before_abandoning(MagicMock(), row) == "deferred"
    assert row.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_wrong_reference_never_abandons(monkeypatch) -> None:
    row = transaction()
    payload = gateway(row, "failed")
    payload["data"]["reference"] = "a-different-transaction"
    fake_provider(monkeypatch, response=payload)
    assert await verify_before_abandoning(MagicMock(), row) == "deferred"
    assert row.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_bad_payment_metadata_cannot_activate(monkeypatch) -> None:
    row = transaction()
    payload = gateway(row, "success")
    payload["data"]["metadata"]["tenant_id"] = str(uuid4())
    fake_provider(monkeypatch, response=payload)
    with patch(
        "app.modules.subscriptions.payment_settlement.settle_verified_term_payment",
        new=AsyncMock(),
    ) as settle:
        assert await verify_before_abandoning(MagicMock(), row) == "deferred"
    assert row.status == PaymentStatus.PENDING
    settle.assert_not_awaited()


@pytest.mark.asyncio
async def test_settlement_conflict_defers_without_abandonment(monkeypatch) -> None:
    row = transaction()
    fake_provider(monkeypatch, response=gateway(row, "success"))
    with patch(
        "app.modules.subscriptions.payment_settlement.settle_verified_term_payment",
        new=AsyncMock(side_effect=ConflictException("term state changed")),
    ):
        assert await verify_before_abandoning(MagicMock(), row) == "deferred"
    assert row.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_hourly_expiry_checks_gateway_before_updating_rows(monkeypatch) -> None:
    paid, unpaid = transaction(), transaction()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [paid, unpaid]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    decisions = AsyncMock(side_effect=["settled", "abandoned"])
    monkeypatch.setattr(
        "app.modules.subscriptions.term_entitlement_service.verify_before_abandoning",
        decisions,
    )

    expired = await TermPlanEntitlementService.expire_stale_pending_checkouts(db)

    assert expired == 1
    assert decisions.await_count == 2
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_replacement_checkout_requires_provider_confirmation(monkeypatch) -> None:
    row = transaction()
    term = SimpleNamespace(status="open", is_current=True)
    db = MagicMock()
    db.commit = AsyncMock()
    monkeypatch.setattr(
        "app.modules.subscriptions.term_entitlement_service.verify_before_abandoning",
        AsyncMock(return_value="deferred"),
    )
    with (
        patch.object(TermPlanEntitlementService, "_term", new=AsyncMock(return_value=term)),
        patch.object(
            TermPlanEntitlementService,
            "_ensure_draft_selection_allowed",
            new=AsyncMock(),
        ),
        patch.object(TermPlanEntitlementService, "get_active", new=AsyncMock(return_value=None)),
        patch.object(
            TermPlanEntitlementService,
            "_usage_and_blockers",
            new=AsyncMock(return_value=({}, [])),
        ),
        patch.object(TermPlanEntitlementService, "_paid_to_date", new=AsyncMock(return_value=0)),
        patch.object(
            TermPlanEntitlementService,
            "_get_pending_checkout",
            new=AsyncMock(return_value=row),
        ),
        patch.object(TermPlanEntitlementService, "amount_kobo", return_value=4_000_000),
    ):
        with pytest.raises(ConflictException, match="awaiting Paystack confirmation"):
            await TermPlanEntitlementService.initialize_paid_checkout(
                db,
                row.tenant_id,
                row.academic_term_id,
                SubscriptionPlan.PLUS,
                "admin@school.test",
            )
    assert row.status == PaymentStatus.PENDING
    db.commit.assert_not_awaited()
