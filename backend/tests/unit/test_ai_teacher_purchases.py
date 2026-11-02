"""Credit purchase tests: teacher ownership, metadata, and once-only settlement."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import CheckConstraint

from app.modules.cbt.ai.quota.models import (
    AICreditLedgerBucket,
    AIQuotaPurchase,
    AIQuotaPurchaseStatus,
)
from app.modules.cbt.ai.quota.service import AIQuotaService
from app.modules.cbt.ai.quota.payment_service import AIQuotaPaymentService


def _id():
    return uuid.uuid4()


def _purchase(teacher=True):
    return SimpleNamespace(
        id=_id(),
        tenant_id=_id(),
        credits=75,
        amount_kobo=75000,
        reference="ai-credit-test-123",
        status=AIQuotaPurchaseStatus.PENDING,
        initiated_by_admin_id=None if teacher else _id(),
        initiated_by_teacher_membership_id=_id() if teacher else None,
        created_at=datetime.now(timezone.utc),
        credited_at=None,
    )


def test_purchase_model_restricts_to_one_purchaser() -> None:
    table = AIQuotaPurchase.__table__
    assert table.c.initiated_by_admin_id.nullable
    assert table.c.initiated_by_teacher_membership_id.nullable
    constraints = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    assert any(c.name == "ck_cbt_ai_quota_purchase_one_purchaser" for c in constraints)


@pytest.mark.asyncio
async def test_teacher_purchase_credits_only_personal_balance_once(monkeypatch) -> None:
    from app.modules.cbt.ai.quota import service as mod

    purchase = _purchase()
    account = SimpleNamespace(id=_id())
    balance = SimpleNamespace(available_credits=10, reserved_credits=0)
    monkeypatch.setattr(
        mod.AIQuotaPurchaseRepository,
        "get_by_reference",
        AsyncMock(return_value=purchase),
    )
    monkeypatch.setattr(
        mod.AIQuotaService,
        "_ensure_quota_account",
        AsyncMock(return_value=account),
    )
    monkeypatch.setattr(
        mod.AIQuotaService,
        "_ensure_extra_balance",
        AsyncMock(),
    )
    monkeypatch.setattr(
        mod.AIQuotaAccountRepository,
        "get_by_teacher_membership",
        AsyncMock(return_value=account),
    )
    monkeypatch.setattr(
        mod.AIExtraCreditBalanceRepository,
        "get_for_account",
        AsyncMock(return_value=balance),
    )
    saved = AsyncMock()
    ledger = AsyncMock()
    tenant_save = AsyncMock()
    monkeypatch.setattr(mod.AIExtraCreditBalanceRepository, "save", saved)
    monkeypatch.setattr(mod.AICreditLedgerRepository, "create", ledger)
    monkeypatch.setattr(mod.AITenantCreditBalanceRepository, "save", tenant_save)
    monkeypatch.setattr(mod.AIQuotaPurchaseRepository, "save", AsyncMock())
    monkeypatch.setattr(mod, "invalidate_quota_cache", AsyncMock())
    db = AsyncMock()
    first = await AIQuotaService.credit_verified_purchase(
        db,
        tenant_id=purchase.tenant_id,
        reference=purchase.reference,
    )
    assert first.status == AIQuotaPurchaseStatus.SUCCESS
    assert balance.available_credits == 85
    saved.assert_awaited_once()
    tenant_save.assert_not_awaited()
    entry = ledger.await_args.args[1]
    assert entry.bucket == AICreditLedgerBucket.TOP_UP
    assert entry.quota_account_id == account.id
    assert entry.credit_delta == 75

    await AIQuotaService.credit_verified_purchase(
        db,
        tenant_id=purchase.tenant_id,
        reference=purchase.reference,
    )
    assert balance.available_credits == 85
    ledger.assert_awaited_once()


@pytest.mark.asyncio
async def test_school_purchase_still_credits_school_reserve(monkeypatch) -> None:
    from app.modules.cbt.ai.quota import service as mod

    purchase = _purchase(teacher=False)
    balance = SimpleNamespace(available_credits=200)
    monkeypatch.setattr(
        mod.AIQuotaPurchaseRepository, "get_by_reference", AsyncMock(return_value=purchase)
    )
    monkeypatch.setattr(mod.AIQuotaService, "_ensure_tenant_balance", AsyncMock())
    monkeypatch.setattr(
        mod.AITenantCreditBalanceRepository, "get_for_tenant", AsyncMock(return_value=balance)
    )
    saved = AsyncMock()
    ledger = AsyncMock()
    monkeypatch.setattr(mod.AITenantCreditBalanceRepository, "save", saved)
    monkeypatch.setattr(mod.AIQuotaPurchaseRepository, "save", AsyncMock())
    monkeypatch.setattr(mod.AICreditLedgerRepository, "create", ledger)
    monkeypatch.setattr(mod, "invalidate_quota_cache", AsyncMock())
    await AIQuotaService.credit_verified_purchase(
        AsyncMock(),
        tenant_id=purchase.tenant_id,
        reference=purchase.reference,
    )
    assert balance.available_credits == 275
    saved.assert_awaited_once()
    assert ledger.await_args.args[1].bucket == AICreditLedgerBucket.TENANT_RESERVE


@pytest.mark.asyncio
async def test_verify_teacher_payment_requires_own_membership_and_metadata(monkeypatch) -> None:
    from app.modules.cbt.ai.quota import payment_service as mod

    purchase = _purchase()
    monkeypatch.setattr(
        mod.AIQuotaPurchaseRepository, "get_by_reference", AsyncMock(return_value=purchase)
    )
    verified = AsyncMock()
    credited = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(mod.PaymentEngine, "verify_transaction", verified)
    monkeypatch.setattr(mod.AIQuotaService, "credit_verified_purchase", credited)
    response = await AIQuotaPaymentService.verify_teacher_checkout(
        AsyncMock(),
        tenant_id=purchase.tenant_id,
        teacher_membership_id=purchase.initiated_by_teacher_membership_id,
        reference=purchase.reference,
    )
    assert response is credited.return_value
    assert verified.await_args.kwargs["expected_metadata"]["teacher_membership_id"] == str(
        purchase.initiated_by_teacher_membership_id
    )
    assert verified.await_args.kwargs["expected_amount_kobo"] == 75000
    with pytest.raises(mod.AIQuotaNotFoundError):
        await AIQuotaPaymentService.verify_teacher_checkout(
            AsyncMock(),
            tenant_id=purchase.tenant_id,
            teacher_membership_id=_id(),
            reference=purchase.reference,
        )
    assert verified.await_count == 1


@pytest.mark.asyncio
async def test_webhook_binds_teacher_metadata_to_database_purchase(monkeypatch) -> None:
    from app.modules.cbt.ai.quota import payment_service as mod

    purchase = _purchase()
    monkeypatch.setattr(
        mod.AIQuotaPurchaseRepository, "get_by_reference", AsyncMock(return_value=purchase)
    )
    validate = __import__("unittest.mock", fromlist=["Mock"]).Mock()
    settle = AsyncMock()
    monkeypatch.setattr(mod.PaymentEngine, "validate_successful_payload", validate)
    monkeypatch.setattr(mod.AIQuotaService, "credit_verified_purchase", settle)
    result = await AIQuotaPaymentService.settle_verified_webhook_purchase(
        AsyncMock(),
        {"data": {"reference": purchase.reference}},
    )
    expected = validate.call_args.kwargs["expected_metadata"]
    assert expected["teacher_membership_id"] == str(purchase.initiated_by_teacher_membership_id)
    assert expected["quota_purchase_id"] == str(purchase.id)
    assert settle.await_args.kwargs["commit"] is False
    assert result.message
