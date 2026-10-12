"""Provider-aware expiry of stale Paystack term checkouts.

The checkout TTL only triggers a provider status check. It must never be taken
as evidence that payment did not complete. Webhooks and the reconciliation
worker may settle the same reference concurrently; callers hold the payment
row lock until their transaction commits.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.core.exceptions import ConflictException
from app.modules.payments.enums import PaymentPurpose
from app.modules.payments.providers.paystack import PaystackClient
from app.modules.payments.service import PaymentEngine, PaymentVerificationError
from app.modules.subscriptions.models import PaymentTransaction
from app.modules.subscriptions.subscription_enums import PaymentStatus

logger = get_logger(__name__)

# A gateway-level "pending" is not a definitive failed payment. Allow an
# additional window for delayed bank transfers and asynchronous settlement.
PENDING_GATEWAY_GRACE = timedelta(hours=2)
EXPIRY_BATCH_SIZE = 8
EXPIRY_PROBE_KEY = "paystack_expiration_probe"

ExpiryDecision = Literal["abandoned", "settled", "deferred", "skipped"]


def _record_probe(transaction: PaymentTransaction, *, now: datetime, status: str) -> None:
    """Persist last probe time so the hourly scan rotates across a backlog."""
    transaction.raw_payload = {
        **(transaction.raw_payload or {}),
        EXPIRY_PROBE_KEY: {"last_checked_at": now.isoformat(), "status": status},
    }


async def verify_before_abandoning(
    db: AsyncSession,
    transaction: PaymentTransaction,
    *,
    as_of: datetime | None = None,
) -> ExpiryDecision:
    """Check the gateway before converting one locked pending row to abandoned.

    A provider outage, ambiguous response, or invalid successful payload fails
    closed: leave the checkout pending and let the worker retry it. Never apply
    an unvalidated payment to a tenant entitlement.
    """
    if transaction.status != PaymentStatus.PENDING:
        return "skipped"

    now = as_of or datetime.now(timezone.utc)
    reference = transaction.reference

    try:
        response = await PaystackClient().verify_transaction(reference=reference)
    except Exception as exc:
        _record_probe(transaction, now=now, status="unavailable")
        logger.warning(
            "subscription.expiration.paystack_unavailable",
            extra={"reference": reference, "error_type": type(exc).__name__},
        )
        return "deferred"

    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict) or str(data.get("reference") or "") != reference:
        _record_probe(transaction, now=now, status="invalid_response")
        logger.warning(
            "subscription.expiration.invalid_gateway_response",
            extra={"reference": reference},
        )
        return "deferred"

    gateway_status = str(data.get("status") or "").lower()
    _record_probe(transaction, now=now, status=gateway_status or "unknown")
    if gateway_status == "success":
        try:
            PaymentEngine.validate_successful_payload(
                response,
                expected_reference=reference,
                expected_amount_kobo=transaction.amount_kobo,
                expected_currency=transaction.currency,
                expected_metadata={
                    "payment_purpose": PaymentPurpose.TERM_SUBSCRIPTION.value,
                    "tenant_id": str(transaction.tenant_id),
                    "academic_term_id": str(transaction.academic_term_id),
                    "plan_code": transaction.plan_code.value,
                },
            )
        except (PaymentVerificationError, ValueError, TypeError):
            logger.error(
                "subscription.expiration.payment_mismatch",
                extra={"reference": reference},
            )
            return "deferred"

        # Local import avoids the payment_settlement -> entitlement_service
        # dependency cycle. Never commit here: the owning caller commits once.
        from app.modules.subscriptions.payment_settlement import settle_verified_term_payment

        try:
            await settle_verified_term_payment(db, transaction, response, commit=False)
        except ConflictException as exc:
            # A successful payment must not be labelled unpaid if term state
            # now prevents activation. Keep the row for manual intervention.
            logger.error(
                "subscription.expiration.settlement_deferred",
                extra={"reference": reference, "error_type": type(exc).__name__},
            )
            return "deferred"
        return "settled"

    if gateway_status in {"failed", "abandoned"} or (
        gateway_status == "pending"
        and transaction.created_at is not None
        and transaction.created_at < now - PENDING_GATEWAY_GRACE
    ):
        transaction.status = PaymentStatus.ABANDONED
        transaction.failure_reason = (
            "Checkout expired after Paystack confirmed no successful payment."
        )
        return "abandoned"

    # Still pending within the grace window, or an unknown gateway status.
    return "deferred"
