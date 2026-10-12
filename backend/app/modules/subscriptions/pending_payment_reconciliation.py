"""Bounded Paystack recovery for pending and recently abandoned term payments.

Webhooks remain the primary settlement mechanism. Probes never activate an
abandoned checkout: the existing settlement path quarantines late money for
manual reconciliation instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import BigInteger, and_, case, cast, or_, select

from app.config.database import AsyncSessionLocal
from app.config.logging import get_logger
from app.modules.payments.enums import PaymentPurpose
from app.modules.payments.providers.paystack import PaystackClient
from app.modules.payments.service import PaymentEngine
from app.modules.subscriptions.cache import invalidate_tenant_subscription_cache
from app.modules.subscriptions.models import PaymentTransaction
from app.modules.subscriptions.payment_settlement import settle_verified_term_payment
from app.modules.subscriptions.subscription_enums import PaymentProvider, PaymentStatus

logger = get_logger(__name__)

BATCH_SIZE = 8
PROBE_KEY = "paystack_reconciliation_probe"
PENDING_INTERVAL = timedelta(minutes=5)
ABANDONED_INTERVAL = timedelta(minutes=30)
ABANDONED_LOOKBACK = timedelta(days=7)
MIN_CHECKOUT_AGE = timedelta(minutes=1)


@dataclass(frozen=True)
class PaymentProbe:
    reference: str
    amount_kobo: int
    currency: str
    tenant_id: str
    academic_term_id: str
    plan_code: str

    @property
    def expected_metadata(self) -> dict[str, str]:
        return {
            "payment_purpose": PaymentPurpose.TERM_SUBSCRIPTION.value,
            "tenant_id": self.tenant_id,
            "academic_term_id": self.academic_term_id,
            "plan_code": self.plan_code,
        }


async def _due_references(now: datetime, batch_size: int) -> list[str]:
    """Select only due rows; prefer pending checkouts over recovery probes."""
    next_epoch = cast(
        PaymentTransaction.raw_payload[PROBE_KEY]["next_epoch"].astext,
        BigInteger,
    )
    statement = (
        select(PaymentTransaction.reference)
        .where(
            PaymentTransaction.provider == PaymentProvider.PAYSTACK,
            PaymentTransaction.created_at <= now - MIN_CHECKOUT_AGE,
            or_(
                PaymentTransaction.status == PaymentStatus.PENDING,
                and_(
                    PaymentTransaction.status == PaymentStatus.ABANDONED,
                    PaymentTransaction.created_at >= now - ABANDONED_LOOKBACK,
                ),
            ),
            or_(next_epoch.is_(None), next_epoch <= int(now.timestamp())),
        )
        .order_by(
            case((PaymentTransaction.status == PaymentStatus.PENDING, 0), else_=1),
            PaymentTransaction.created_at.asc(),
        )
        .limit(batch_size)
    )
    async with AsyncSessionLocal() as db:
        result = await db.execute(statement)
        return list(result.scalars().all())


async def _claim(reference: str, now: datetime) -> PaymentProbe | None:
    """Commit a cooldown claim before any network request, without holding a DB lock."""
    async with AsyncSessionLocal() as db:
        transaction = (
            await db.execute(
                select(PaymentTransaction)
                .where(PaymentTransaction.reference == reference)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if transaction is None or transaction.provider != PaymentProvider.PAYSTACK:
            return None
        if transaction.status not in (PaymentStatus.PENDING, PaymentStatus.ABANDONED):
            return None
        if (
            transaction.status == PaymentStatus.ABANDONED
            and transaction.created_at < now - ABANDONED_LOOKBACK
        ):
            return None
        if transaction.reconciliation_required:
            return None

        raw = dict(transaction.raw_payload or {})
        previous = raw.get(PROBE_KEY)
        previous = previous if isinstance(previous, dict) else {}
        next_epoch = previous.get("next_epoch")
        if isinstance(next_epoch, int) and next_epoch > int(now.timestamp()):
            return None

        interval = (
            PENDING_INTERVAL
            if transaction.status == PaymentStatus.PENDING
            else ABANDONED_INTERVAL
        )
        raw[PROBE_KEY] = {
            "attempts": int(previous.get("attempts") or 0) + 1,
            "last_checked_at": now.isoformat(),
            "next_epoch": int((now + interval).timestamp()),
        }
        transaction.raw_payload = raw
        probe = PaymentProbe(
            reference=transaction.reference,
            amount_kobo=transaction.amount_kobo,
            currency=transaction.currency,
            tenant_id=str(transaction.tenant_id),
            academic_term_id=str(transaction.academic_term_id),
            plan_code=transaction.plan_code.value,
        )
        await db.commit()
        return probe


async def _settle(probe: PaymentProbe, payload: dict[str, Any]) -> str:
    """Lock and re-read current state; the webhook or admin might already have settled."""
    async with AsyncSessionLocal() as db:
        transaction = (
            await db.execute(
                select(PaymentTransaction)
                .where(PaymentTransaction.reference == probe.reference)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if transaction is None or transaction.status not in (
            PaymentStatus.PENDING,
            PaymentStatus.ABANDONED,
        ):
            return "skipped"

        # Validate provider truth against the locked, backend-owned transaction.
        PaymentEngine.validate_successful_payload(
            payload,
            expected_reference=transaction.reference,
            expected_amount_kobo=transaction.amount_kobo,
            expected_currency=transaction.currency,
            expected_metadata={
                "payment_purpose": PaymentPurpose.TERM_SUBSCRIPTION.value,
                "tenant_id": str(transaction.tenant_id),
                "academic_term_id": str(transaction.academic_term_id),
                "plan_code": transaction.plan_code.value,
            },
        )
        entitlement = await settle_verified_term_payment(
            db, transaction, payload, commit=False
        )
        await db.commit()
        tenant_id = transaction.tenant_id

    await invalidate_tenant_subscription_cache(tenant_id)
    return "review_required" if entitlement is None else "settled"


async def reconcile_pending_term_payments(batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Retry due references; failures are isolated and retried at the next interval."""
    now = datetime.now(timezone.utc)
    counts = {
        "claimed": 0,
        "not_successful": 0,
        "settled": 0,
        "review_required": 0,
        "skipped": 0,
        "errors": 0,
    }
    references = await _due_references(now, max(1, min(batch_size, BATCH_SIZE)))
    provider = PaystackClient()

    for reference in references:
        try:
            probe = await _claim(reference, now)
            if probe is None:
                counts["skipped"] += 1
                continue
            counts["claimed"] += 1
            response = await provider.verify_transaction(reference=probe.reference)
            data = response.get("data")
            if not isinstance(data, dict) or data.get("status") != "success":
                counts["not_successful"] += 1
                continue
            outcome = await _settle(probe, response)
            counts[outcome] += 1
        except Exception as exc:
            counts["errors"] += 1
            logger.error(
                "subscription.payment_probe.failed",
                extra={"reference": reference, "error_type": type(exc).__name__},
            )

    logger.info("subscription.payment_probe.completed", extra=counts)
    return counts
