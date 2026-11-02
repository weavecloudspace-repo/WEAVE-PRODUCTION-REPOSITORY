from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.cbt.ai.quota.models import (
    AICreditLedgerBucket,
    AICreditLedgerEventType,
    AICreditReservationStatus,
    AIQuotaActorType,
    AIQuotaPurchaseStatus,
    AIQuotaRequestStatus,
)
from app.modules.cbt.ai.quota.service import (
    AICreditAllocationRepository,
    AICreditLedgerRepository,
    AICreditReservationRepository,
    AIExtraCreditBalanceRepository,
    AIInsufficientCreditsError,
    AIQuotaAccountRepository,
    AIQuotaConflictError,
    AIQuotaPurchaseRepository,
    AIQuotaRequestRepository,
    AIQuotaReservationExpiredError,
    AIQuotaService,
    AITenantCreditBalanceRepository,
    AIWeeklyQuotaRepository,
)


def _db():
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


def _teacher_account(*, tenant_id=None, actor_id=None):
    tenant_id = tenant_id or uuid4()
    actor_id = actor_id or uuid4()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_type=AIQuotaActorType.TEACHER,
        teacher_membership_id=actor_id,
        tenant_admin_id=None,
    )


def _weekly(*, tenant_id, account_id, limit=100, used=0, reserved=0):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        quota_account_id=account_id,
        week_start=AIQuotaService._current_week_start(),
        credit_limit=limit,
        used_credits=used,
        reserved_credits=reserved,
    )


def _extra(*, tenant_id, account_id, available=0, reserved=0):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        quota_account_id=account_id,
        available_credits=available,
        reserved_credits=reserved,
    )


def _reservation(
    *,
    tenant_id,
    account_id,
    weekly_id,
    free,
    extra,
    status=AICreditReservationStatus.PENDING,
    expires_at=None,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        quota_account_id=account_id,
        weekly_quota_id=weekly_id,
        reserved_free_credits=free,
        reserved_extra_credits=extra,
        settled_free_credits=0,
        settled_extra_credits=0,
        status=status,
        created_at=now,
        expires_at=expires_at or now + timedelta(minutes=10),
        settled_at=None,
        released_at=None,
    )


def test_week_start_is_monday() -> None:
    assert AIQuotaService._week_start(date(2026, 9, 30)) == date(2026, 9, 28)
    assert AIQuotaService._week_start(date(2026, 9, 28)) == date(2026, 9, 28)


@pytest.mark.parametrize("credits", [0, -1, True, 1.5])
def test_positive_credit_guard_rejects_invalid_values(credits) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        AIQuotaService._require_positive_credits(credits)


def test_quota_status_response_calculates_spendable_balances() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    account = _teacher_account(tenant_id=tenant_id, actor_id=actor_id)
    weekly = _weekly(
        tenant_id=tenant_id,
        account_id=account.id,
        limit=100,
        used=30,
        reserved=10,
    )
    extra = _extra(
        tenant_id=tenant_id,
        account_id=account.id,
        available=80,
        reserved=20,
    )
    result = AIQuotaService._quota_status_response(
        account=account,
        weekly=weekly,
        extra=extra,
    )
    assert result.weekly.available_credits == 60
    assert result.extra.available_credits == 60
    assert result.total_available_credits == 120


@pytest.mark.asyncio
async def test_reservation_uses_weekly_free_credits_first(monkeypatch) -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    account = _teacher_account(tenant_id=tenant_id, actor_id=actor_id)
    weekly = _weekly(tenant_id=tenant_id, account_id=account.id, used=70)
    extra = _extra(tenant_id=tenant_id, account_id=account.id, available=100)
    db = _db()

    monkeypatch.setattr(AIQuotaService, "_ensure_quota_account", AsyncMock(return_value=account))
    monkeypatch.setattr(AIQuotaService, "_ensure_weekly_quota", AsyncMock(return_value=weekly))
    monkeypatch.setattr(
        AIWeeklyQuotaRepository,
        "get_for_account_week",
        AsyncMock(return_value=weekly),
    )
    monkeypatch.setattr(
        AIExtraCreditBalanceRepository,
        "get_for_account",
        AsyncMock(return_value=extra),
    )
    monkeypatch.setattr(AIWeeklyQuotaRepository, "save", AsyncMock(return_value=weekly))
    monkeypatch.setattr(AIExtraCreditBalanceRepository, "save", AsyncMock(return_value=extra))

    async def create_reservation(_db, reservation):
        reservation.id = uuid4()
        return reservation

    monkeypatch.setattr(AICreditReservationRepository, "create", create_reservation)

    result = await AIQuotaService.reserve_credits(
        db,
        tenant_id=tenant_id,
        actor_type=AIQuotaActorType.TEACHER,
        actor_id=actor_id,
        credits=50,
    )
    assert result.reserved_free_credits == 30
    assert result.reserved_extra_credits == 20
    assert weekly.reserved_credits == 30
    assert extra.reserved_credits == 20
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reservation_rejects_insufficient_total_credits(monkeypatch) -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    account = _teacher_account(tenant_id=tenant_id, actor_id=actor_id)
    weekly = _weekly(tenant_id=tenant_id, account_id=account.id, used=95)
    extra = _extra(tenant_id=tenant_id, account_id=account.id, available=10)
    db = _db()

    monkeypatch.setattr(AIQuotaService, "_ensure_quota_account", AsyncMock(return_value=account))
    monkeypatch.setattr(AIQuotaService, "_ensure_weekly_quota", AsyncMock(return_value=weekly))
    monkeypatch.setattr(
        AIWeeklyQuotaRepository, "get_for_account_week", AsyncMock(return_value=weekly)
    )
    monkeypatch.setattr(
        AIExtraCreditBalanceRepository, "get_for_account", AsyncMock(return_value=extra)
    )

    with pytest.raises(AIInsufficientCreditsError) as error:
        await AIQuotaService.reserve_credits(
            db,
            tenant_id=tenant_id,
            actor_type=AIQuotaActorType.TEACHER,
            actor_id=actor_id,
            credits=20,
        )
    assert error.value.requested_credits == 20
    assert error.value.available_credits == 15
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_consumes_actual_usage_and_releases_unused_hold(monkeypatch) -> None:
    tenant_id = uuid4()
    account_id = uuid4()
    weekly = _weekly(tenant_id=tenant_id, account_id=account_id, reserved=20)
    extra = _extra(tenant_id=tenant_id, account_id=account_id, available=50, reserved=10)
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=account_id,
        weekly_id=weekly.id,
        free=20,
        extra=10,
    )
    db = _db()
    ledger_entries = []

    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )
    monkeypatch.setattr(
        AIQuotaService, "_locked_weekly_for_reservation", AsyncMock(return_value=weekly)
    )
    monkeypatch.setattr(
        AIExtraCreditBalanceRepository, "get_for_account", AsyncMock(return_value=extra)
    )
    monkeypatch.setattr(AIWeeklyQuotaRepository, "save", AsyncMock(return_value=weekly))
    monkeypatch.setattr(AIExtraCreditBalanceRepository, "save", AsyncMock(return_value=extra))
    monkeypatch.setattr(AICreditReservationRepository, "save", AsyncMock(return_value=reservation))

    async def create_many(_db, entries):
        ledger_entries.extend(entries)
        return list(entries)

    monkeypatch.setattr(AICreditLedgerRepository, "create_many", create_many)

    result = await AIQuotaService.settle_reservation(
        db,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
        actual_credits=23,
    )
    assert result.settled_free_credits == 20
    assert result.settled_extra_credits == 3
    assert result.released_credits == 7
    assert weekly.used_credits == 20
    assert weekly.reserved_credits == 0
    assert extra.available_credits == 47
    assert extra.reserved_credits == 0
    assert reservation.status == AICreditReservationStatus.SETTLED
    assert {entry.bucket for entry in ledger_entries} == {
        AICreditLedgerBucket.WEEKLY_FREE,
        AICreditLedgerBucket.TOP_UP,
    }
    assert all(entry.event_type == AICreditLedgerEventType.CONSUMPTION for entry in ledger_entries)


@pytest.mark.asyncio
async def test_settlement_is_idempotent_after_already_settled(monkeypatch) -> None:
    tenant_id = uuid4()
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=uuid4(),
        weekly_id=uuid4(),
        free=20,
        extra=0,
        status=AICreditReservationStatus.SETTLED,
    )
    reservation.settled_free_credits = 12
    reservation.settled_at = datetime.now(timezone.utc)
    db = _db()
    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )

    result = await AIQuotaService.settle_reservation(
        db,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
        actual_credits=12,
    )
    assert result.total_settled_credits == 12
    assert result.released_credits == 8
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_rejects_actual_usage_above_reserved(monkeypatch) -> None:
    tenant_id = uuid4()
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=uuid4(),
        weekly_id=uuid4(),
        free=10,
        extra=5,
    )
    db = _db()
    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )
    with pytest.raises(AIQuotaConflictError, match="exceeds the reserved"):
        await AIQuotaService.settle_reservation(
            db,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            actual_credits=16,
        )
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_reservation_is_released_before_expiry_error(monkeypatch) -> None:
    tenant_id = uuid4()
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=uuid4(),
        weekly_id=uuid4(),
        free=10,
        extra=0,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = _db()
    release = AsyncMock()
    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )
    monkeypatch.setattr(AIQuotaService, "_release_locked_reservation", release)

    with pytest.raises(AIQuotaReservationExpiredError):
        await AIQuotaService.settle_reservation(
            db,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            actual_credits=5,
        )
    release.assert_awaited_once()
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_reservation_is_idempotent(monkeypatch) -> None:
    tenant_id = uuid4()
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=uuid4(),
        weekly_id=uuid4(),
        free=10,
        extra=0,
        status=AICreditReservationStatus.RELEASED,
    )
    db = _db()
    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )
    result = await AIQuotaService.release_reservation(
        db,
        tenant_id=tenant_id,
        reservation_id=reservation.id,
    )
    assert result.status == AICreditReservationStatus.RELEASED
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cannot_release_settled_reservation(monkeypatch) -> None:
    tenant_id = uuid4()
    reservation = _reservation(
        tenant_id=tenant_id,
        account_id=uuid4(),
        weekly_id=uuid4(),
        free=10,
        extra=0,
        status=AICreditReservationStatus.SETTLED,
    )
    reservation.settled_at = datetime.now(timezone.utc)
    db = _db()
    monkeypatch.setattr(
        AICreditReservationRepository, "get_by_tenant_and_id", AsyncMock(return_value=reservation)
    )
    with pytest.raises(AIQuotaConflictError, match="cannot be released"):
        await AIQuotaService.release_reservation(
            db,
            tenant_id=tenant_id,
            reservation_id=reservation.id,
        )


@pytest.mark.asyncio
async def test_stale_reservation_recovery_releases_every_locked_item(monkeypatch) -> None:
    tenant_id = uuid4()
    reservations = [
        _reservation(tenant_id=tenant_id, account_id=uuid4(), weekly_id=uuid4(), free=5, extra=0),
        _reservation(tenant_id=tenant_id, account_id=uuid4(), weekly_id=uuid4(), free=7, extra=0),
    ]
    db = _db()
    monkeypatch.setattr(
        AICreditReservationRepository,
        "list_expired_pending_for_recovery",
        AsyncMock(return_value=reservations),
    )
    monkeypatch.setattr(AIWeeklyQuotaRepository, "lock_many_buckets", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        AIExtraCreditBalanceRepository, "lock_many_buckets", AsyncMock(return_value=[])
    )
    release = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "_release_locked_reservation", release)
    count = await AIQuotaService.expire_stale_reservations(db, limit=10)
    assert count == 2
    assert release.await_count == 2
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_allocate_from_tenant_reserve_moves_credits_and_writes_double_entry_ledger(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    account_id = uuid4()
    tenant_balance = SimpleNamespace(available_credits=500)
    extra = SimpleNamespace(available_credits=25, reserved_credits=0)
    db = _db()
    captured = []

    monkeypatch.setattr(AITenantCreditBalanceRepository, "save", AsyncMock())
    monkeypatch.setattr(AIExtraCreditBalanceRepository, "save", AsyncMock())

    async def create_allocation(_db, allocation):
        allocation.id = uuid4()
        return allocation

    async def create_many(_db, entries):
        captured.extend(entries)
        return list(entries)

    monkeypatch.setattr(AICreditAllocationRepository, "create", create_allocation)
    monkeypatch.setattr(AICreditLedgerRepository, "create_many", create_many)

    allocation = await AIQuotaService._allocate_from_tenant_reserve(
        db,
        tenant_id=tenant_id,
        tenant_admin_id=admin_id,
        recipient_quota_account_id=account_id,
        credits=120,
        tenant_balance=tenant_balance,
        extra_balance=extra,
    )
    assert allocation.credits == 120
    assert tenant_balance.available_credits == 380
    assert extra.available_credits == 145
    assert [entry.credit_delta for entry in captured] == [-120, 120]
    assert [entry.event_type for entry in captured] == [
        AICreditLedgerEventType.ALLOCATION_OUT,
        AICreditLedgerEventType.ALLOCATION_IN,
    ]


@pytest.mark.asyncio
async def test_allocation_rejects_insufficient_tenant_reserve() -> None:
    with pytest.raises(AIInsufficientCreditsError) as error:
        await AIQuotaService._allocate_from_tenant_reserve(
            _db(),
            tenant_id=uuid4(),
            tenant_admin_id=uuid4(),
            recipient_quota_account_id=uuid4(),
            credits=100,
            tenant_balance=SimpleNamespace(available_credits=20),
            extra_balance=SimpleNamespace(available_credits=0, reserved_credits=0),
        )
    assert error.value.available_credits == 20


@pytest.mark.asyncio
async def test_create_and_cancel_teacher_quota_request(monkeypatch) -> None:
    tenant_id = uuid4()
    membership_id = uuid4()
    account = _teacher_account(tenant_id=tenant_id, actor_id=membership_id)
    db = _db()
    stored = {}

    monkeypatch.setattr(AIQuotaService, "_ensure_quota_account", AsyncMock(return_value=account))

    async def create_request(_db, request):
        request.id = uuid4()
        request.created_at = datetime.now(timezone.utc)
        stored[request.id] = request
        return request

    async def get_request(_db, *, tenant_id, request_id, lock=False):
        return stored.get(request_id)

    monkeypatch.setattr(AIQuotaRequestRepository, "create", create_request)
    monkeypatch.setattr(AIQuotaRequestRepository, "get_by_tenant_and_id", get_request)
    monkeypatch.setattr(AIQuotaRequestRepository, "save", AsyncMock())

    created = await AIQuotaService.create_quota_request(
        db,
        tenant_id=tenant_id,
        teacher_membership_id=membership_id,
        credits=75,
    )
    assert created.status == AIQuotaRequestStatus.PENDING

    cancelled = await AIQuotaService.cancel_my_quota_request(
        db,
        tenant_id=tenant_id,
        teacher_membership_id=membership_id,
        request_id=created.id,
    )
    assert cancelled.status == AIQuotaRequestStatus.CANCELLED
    assert cancelled.cancelled_at is not None


@pytest.mark.asyncio
async def test_approval_cannot_exceed_requested_credits(monkeypatch) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        requester_quota_account_id=uuid4(),
        requested_credits=50,
        status=AIQuotaRequestStatus.PENDING,
    )
    db = _db()
    monkeypatch.setattr(AIQuotaService, "_ensure_admin_account", AsyncMock())
    monkeypatch.setattr(AIQuotaService, "_ensure_extra_balance", AsyncMock())
    monkeypatch.setattr(AIQuotaService, "_ensure_tenant_balance", AsyncMock())
    monkeypatch.setattr(
        AIQuotaRequestRepository, "get_by_tenant_and_id", AsyncMock(return_value=request)
    )

    with pytest.raises(AIQuotaConflictError, match="cannot exceed requested"):
        await AIQuotaService.approve_quota_request(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=admin_id,
            request_id=request.id,
            approved_credits=51,
        )


@pytest.mark.asyncio
async def test_verified_purchase_credits_tenant_once_and_is_idempotent(monkeypatch) -> None:
    tenant_id = uuid4()
    purchase = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        initiated_by_admin_id=uuid4(),
        credits=500,
        amount_kobo=100000,
        reference="ref-1",
        status=AIQuotaPurchaseStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        credited_at=None,
    )
    tenant_balance = SimpleNamespace(available_credits=100)
    db = _db()
    ledger = []

    async def get_purchase(_db, *, reference, lock=False):
        return purchase

    async def create_ledger(_db, entry):
        ledger.append(entry)
        return entry

    monkeypatch.setattr(AIQuotaPurchaseRepository, "get_by_reference", get_purchase)
    monkeypatch.setattr(
        AIQuotaService, "_ensure_tenant_balance", AsyncMock(return_value=tenant_balance)
    )
    monkeypatch.setattr(
        AITenantCreditBalanceRepository, "get_for_tenant", AsyncMock(return_value=tenant_balance)
    )
    monkeypatch.setattr(AITenantCreditBalanceRepository, "save", AsyncMock())
    monkeypatch.setattr(AIQuotaPurchaseRepository, "save", AsyncMock())
    monkeypatch.setattr(AICreditLedgerRepository, "create", create_ledger)

    first = await AIQuotaService.credit_verified_purchase(
        db,
        tenant_id=tenant_id,
        reference="ref-1",
    )
    assert first.status == AIQuotaPurchaseStatus.SUCCESS
    assert tenant_balance.available_credits == 600
    assert len(ledger) == 1
    assert ledger[0].event_type == AICreditLedgerEventType.PURCHASE

    second = await AIQuotaService.credit_verified_purchase(
        db,
        tenant_id=tenant_id,
        reference="ref-1",
    )
    assert second.status == AIQuotaPurchaseStatus.SUCCESS
    assert tenant_balance.available_credits == 600
    assert len(ledger) == 1


@pytest.mark.asyncio
async def test_purchase_reference_conflict_is_rejected(monkeypatch) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    existing = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        initiated_by_admin_id=admin_id,
        credits=100,
        amount_kobo=1000,
        reference="same-ref",
        status=AIQuotaPurchaseStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        credited_at=None,
    )
    db = _db()
    monkeypatch.setattr(AIQuotaService, "_ensure_admin_account", AsyncMock())
    monkeypatch.setattr(
        AIQuotaPurchaseRepository, "get_by_reference", AsyncMock(return_value=existing)
    )

    with pytest.raises(AIQuotaConflictError, match="different quota purchase"):
        await AIQuotaService.create_pending_purchase(
            db,
            tenant_id=tenant_id,
            tenant_admin_id=admin_id,
            credits=200,
            amount_kobo=2000,
            reference="same-ref",
        )
