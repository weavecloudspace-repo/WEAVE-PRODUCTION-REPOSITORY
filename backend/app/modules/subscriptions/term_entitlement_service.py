from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import ConflictException, NotFoundException
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermName,
    AcademicTermStatus,
)
from app.modules.subscriptions.cache import invalidate_tenant_subscription_cache
from app.modules.subscriptions.checkout_expiration import (
    EXPIRY_BATCH_SIZE,
    verify_before_abandoning,
)
from app.modules.subscriptions.models import PaymentTransaction, TermPlanEntitlement
from app.modules.subscriptions.plans import coerce_subscription_plan, get_plan_entitlements
from app.modules.payments.enums import PaymentPurpose
from app.modules.payments.service import PaymentEngine
from app.modules.subscriptions.repository import SubscriptionRepository
from app.modules.subscriptions.schemas import (
    SubscriptionCheckoutResponse,
    TermPlanBlocker,
    TermPlanOptionResponse,
    TermPlanOptionsResponse,
)
from app.modules.subscriptions.subscription_enums import (
    BillingInterval,
    PaymentProvider,
    PaymentStatus,
    TermEntitlementStatus,
)
from app.tenant_management.models import SubscriptionPlan

TERM_SAFETY_LIFETIME_DAYS = 214
PENDING_CHECKOUT_TTL = timedelta(minutes=1 if settings.ENV == "dev" else 30)
PAID_TERM_PLANS = {
    SubscriptionPlan.PLUS,
    SubscriptionPlan.PROFESSIONAL,
    SubscriptionPlan.ENTERPRISE,
}
PLAN_RANK = {
    SubscriptionPlan.FREE: 0,
    SubscriptionPlan.PLUS: 1,
    SubscriptionPlan.PROFESSIONAL: 2,
    SubscriptionPlan.ENTERPRISE: 3,
}
TERM_ORDER = {
    AcademicTermName.FIRST_TERM: 1,
    AcademicTermName.SECOND_TERM: 2,
    AcademicTermName.THIRD_TERM: 3,
}


class TermPlanEntitlementService:
    @staticmethod
    async def _term(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> AcademicTerm:
        query = select(AcademicTerm).where(
            AcademicTerm.id == term_id,
            AcademicTerm.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        term = (await db.execute(query)).scalar_one_or_none()
        if term is None:
            raise NotFoundException("Academic term not found.")
        return term

    @staticmethod
    async def _session(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> AcademicSession:
        query = select(AcademicSession).where(
            AcademicSession.id == session_id,
            AcademicSession.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        session = (await db.execute(query)).scalar_one_or_none()
        if session is None:
            raise NotFoundException("Academic session not found.")
        return session

    @staticmethod
    async def get_active(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TermPlanEntitlement | None:
        query = (
            select(TermPlanEntitlement)
            .where(
                TermPlanEntitlement.tenant_id == tenant_id,
                TermPlanEntitlement.academic_term_id == term_id,
                TermPlanEntitlement.status == TermEntitlementStatus.ACTIVE,
            )
            .order_by(TermPlanEntitlement.activated_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def _get_entitlement_for_transaction(
        db: AsyncSession,
        transaction_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TermPlanEntitlement | None:
        query = (
            select(TermPlanEntitlement)
            .where(TermPlanEntitlement.payment_transaction_id == transaction_id)
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def _get_pending_checkout(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> PaymentTransaction | None:
        query = (
            select(PaymentTransaction)
            .where(
                PaymentTransaction.tenant_id == tenant_id,
                PaymentTransaction.academic_term_id == term_id,
                PaymentTransaction.provider == PaymentProvider.PAYSTACK,
                PaymentTransaction.status == PaymentStatus.PENDING,
            )
            .order_by(PaymentTransaction.created_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    def _pending_checkout_is_stale(
        transaction: PaymentTransaction,
        *,
        as_of: datetime | None = None,
    ) -> bool:
        now = as_of or datetime.now(timezone.utc)
        return (
            transaction.status == PaymentStatus.PENDING
            and transaction.created_at is not None
            and transaction.created_at < now - PENDING_CHECKOUT_TTL
        )

    @staticmethod
    async def expire_stale_pending_checkouts(
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
        tenant_id: uuid.UUID | None = None,
        term_id: uuid.UUID | None = None,
    ) -> int:
        now = as_of or datetime.now(timezone.utc)
        query = select(PaymentTransaction).where(
            PaymentTransaction.provider == PaymentProvider.PAYSTACK,
            PaymentTransaction.status == PaymentStatus.PENDING,
            PaymentTransaction.created_at < now - PENDING_CHECKOUT_TTL,
        )
        if tenant_id is not None:
            query = query.where(PaymentTransaction.tenant_id == tenant_id)
        if term_id is not None:
            query = query.where(PaymentTransaction.academic_term_id == term_id)
        # Bounded provider checks: no bulk write can mark an unverified
        # checkout abandoned. SKIP LOCKED avoids fighting webhook settlement.
        rows = list(
            (
                await db.execute(
                    query.order_by(
                        PaymentTransaction.raw_payload["paystack_expiration_probe"][
                            "last_checked_at"
                        ]
                        .astext.asc()
                        .nullsfirst(),
                        PaymentTransaction.created_at.asc(),
                    )
                    .limit(EXPIRY_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        abandoned = 0
        for transaction in rows:
            decision = await verify_before_abandoning(db, transaction, as_of=now)
            if decision == "abandoned":
                abandoned += 1
        if rows:
            await db.flush()
        return abandoned

    @staticmethod
    def amount_kobo(plan: SubscriptionPlan) -> int:
        canonical = coerce_subscription_plan(plan)
        fields = {
            SubscriptionPlan.PLUS: "PAYSTACK_PLUS_TERM_AMOUNT_KOBO",
            SubscriptionPlan.PROFESSIONAL: "PAYSTACK_PROFESSIONAL_TERM_AMOUNT_KOBO",
            SubscriptionPlan.ENTERPRISE: "PAYSTACK_ENTERPRISE_TERM_AMOUNT_KOBO",
        }
        if canonical not in fields:
            return 0
        return int(getattr(settings, fields[canonical]))

    @staticmethod
    def _transition(
        existing: TermPlanEntitlement | None,
        target_plan: SubscriptionPlan,
    ) -> str:
        target = coerce_subscription_plan(target_plan)
        if existing is None:
            return "select"
        current = coerce_subscription_plan(existing.plan_code)
        if current == target:
            return "current"
        if PLAN_RANK[target] > PLAN_RANK[current]:
            return "upgrade"
        return "downgrade"

    @staticmethod
    def _ensure_paid_settlement_term_state(term: AcademicTerm) -> None:
        if term.status not in {
            AcademicTermStatus.DRAFT,
            AcademicTermStatus.OPEN,
            AcademicTermStatus.CLOSING,
        }:
            raise ConflictException(
                "A paid term transaction cannot be activated after the academic term is closed."
            )

    @staticmethod
    async def _ensure_draft_selection_allowed(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term: AcademicTerm,
    ) -> None:
        if term.status != AcademicTermStatus.DRAFT:
            return

        session = await TermPlanEntitlementService._session(
            db,
            tenant_id,
            term.academic_session_id,
            lock=True,
        )
        if session.status != AcademicSessionStatus.OPEN or not session.is_current:
            raise ConflictException(
                "Plans can only be selected for the next term of the current open session.",
                payload={
                    "code": "TERM_PLAN_SELECTION_NOT_READY",
                    "term_id": str(term.id),
                },
            )

        siblings = list(
            (
                await db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.tenant_id == tenant_id,
                        AcademicTerm.academic_session_id == term.academic_session_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        current_position = TERM_ORDER[term.name]
        earlier_not_closed = [
            row
            for row in siblings
            if TERM_ORDER[row.name] < current_position and row.status != AcademicTermStatus.CLOSED
        ]
        active_other = [
            row
            for row in siblings
            if row.id != term.id
            and row.status in {AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING}
        ]
        if earlier_not_closed or active_other:
            raise ConflictException(
                "This term is not ready for plan selection yet. Finish the current or earlier term first.",
                payload={
                    "code": "TERM_PLAN_SELECTION_NOT_READY",
                    "term_id": str(term.id),
                },
            )

    @staticmethod
    async def _usage_and_blockers(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term: AcademicTerm,
        plan: SubscriptionPlan,
    ) -> tuple[dict, list[TermPlanBlocker]]:
        canonical = coerce_subscription_plan(plan)
        usage = await SubscriptionRepository.get_all_resource_usage(
            db,
            tenant_id,
            academic_session_id=term.academic_session_id,
        )
        limits = get_plan_entitlements(canonical).limits
        blockers = [
            TermPlanBlocker(
                resource=resource,
                used=used,
                limit=int(limits[resource]),
                over_by=used - int(limits[resource]),
            )
            for resource, used in usage.items()
            if limits.get(resource) is not None and used > int(limits[resource])
        ]
        return usage, blockers

    @staticmethod
    async def _paid_to_date(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> int:
        return await SubscriptionRepository.sum_successful_term_payments(
            db,
            tenant_id=tenant_id,
            academic_term_id=term_id,
        )

    @staticmethod
    def _amount_due(
        *,
        transition: str,
        target_plan: SubscriptionPlan,
        paid_to_date_kobo: int,
    ) -> int:
        if transition in {"current", "downgrade"}:
            return 0
        target_price = TermPlanEntitlementService.amount_kobo(target_plan)
        return max(target_price - paid_to_date_kobo, 0)

    @staticmethod
    async def get_plan_options(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> TermPlanOptionsResponse:
        term = await TermPlanEntitlementService._term(db, tenant_id, term_id, lock=False)
        if term.status in {AcademicTermStatus.CLOSING, AcademicTermStatus.CLOSED}:
            raise ConflictException(
                "Plan changes are not available while a term is closing or closed.",
                payload={
                    "code": "TERM_PLAN_CHANGES_CLOSED",
                    "term_id": str(term.id),
                },
            )
        await TermPlanEntitlementService._ensure_draft_selection_allowed(db, tenant_id, term)
        existing = await TermPlanEntitlementService.get_active(db, tenant_id, term_id)
        paid_to_date = await TermPlanEntitlementService._paid_to_date(db, tenant_id, term_id)

        options: list[TermPlanOptionResponse] = []
        for target in (
            SubscriptionPlan.FREE,
            SubscriptionPlan.PLUS,
            SubscriptionPlan.PROFESSIONAL,
            SubscriptionPlan.ENTERPRISE,
        ):
            transition = TermPlanEntitlementService._transition(existing, target)
            _, blockers = await TermPlanEntitlementService._usage_and_blockers(
                db, tenant_id, term, target
            )
            amount_due = TermPlanEntitlementService._amount_due(
                transition=transition,
                target_plan=target,
                paid_to_date_kobo=paid_to_date,
            )
            options.append(
                TermPlanOptionResponse(
                    plan_code=target,
                    transition=transition,
                    eligible=not blockers,
                    requires_payment=amount_due > 0,
                    list_price_kobo=TermPlanEntitlementService.amount_kobo(target),
                    paid_to_date_kobo=paid_to_date,
                    amount_due_kobo=amount_due,
                    blockers=blockers,
                )
            )

        return TermPlanOptionsResponse(
            term_id=term.id,
            academic_session_id=term.academic_session_id,
            term_status=term.status.value,
            current_plan=(
                coerce_subscription_plan(existing.plan_code) if existing is not None else None
            ),
            paid_to_date_kobo=paid_to_date,
            options=options,
        )

    @staticmethod
    def _checkout_response(transaction: PaymentTransaction) -> SubscriptionCheckoutResponse:
        return SubscriptionCheckoutResponse(
            reference=transaction.reference,
            authorization_url=transaction.authorization_url or "",
            access_code=transaction.access_code or "",
            amount=transaction.amount,
            amount_kobo=transaction.amount_kobo,
            currency=transaction.currency,
            plan_code=transaction.plan_code.value,
            billing_interval=BillingInterval.TERM,
        )

    @staticmethod
    async def ensure_open_eligible(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> TermPlanEntitlement:
        term = await TermPlanEntitlementService._term(db, tenant_id, term_id, lock=True)
        entitlement = await TermPlanEntitlementService.get_active(db, tenant_id, term_id, lock=True)
        now = datetime.now(timezone.utc)
        if entitlement is None or (
            entitlement.safety_expires_at and entitlement.safety_expires_at <= now
        ):
            tenant = await SubscriptionRepository.get_tenant(db, tenant_id)
            suggested = coerce_subscription_plan(getattr(tenant, "initial_plan_intent", None))
            raise ConflictException(
                "Choose a plan for this academic term before opening it.",
                payload={
                    "code": "TERM_PLAN_SELECTION_REQUIRED",
                    "term_id": str(term_id),
                    "suggested_plan": suggested.value,
                    "payment_required": suggested in PAID_TERM_PLANS,
                    "amount_kobo": TermPlanEntitlementService.amount_kobo(suggested),
                },
            )

        _, blockers = await TermPlanEntitlementService._usage_and_blockers(
            db,
            tenant_id,
            term,
            coerce_subscription_plan(entitlement.plan_code),
        )
        if blockers:
            raise ConflictException(
                "Current school usage exceeds the selected term plan.",
                payload={
                    "code": "TERM_PLAN_INELIGIBLE",
                    "term_id": str(term_id),
                    "current_plan": coerce_subscription_plan(entitlement.plan_code).value,
                    "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
                },
            )
        return entitlement

    @staticmethod
    async def activate_free(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        admin_id: uuid.UUID | None,
    ) -> TermPlanEntitlement:
        term = await TermPlanEntitlementService._term(db, tenant_id, term_id, lock=True)
        if term.status != AcademicTermStatus.DRAFT:
            raise ConflictException(
                "Free can only be selected while the academic term is still a draft."
            )
        await TermPlanEntitlementService._ensure_draft_selection_allowed(db, tenant_id, term)
        existing = await TermPlanEntitlementService.get_active(db, tenant_id, term_id, lock=True)
        if existing:
            if coerce_subscription_plan(existing.plan_code) == SubscriptionPlan.FREE:
                return existing
            raise ConflictException("This term already has an active paid entitlement.")

        _, blockers = await TermPlanEntitlementService._usage_and_blockers(
            db, tenant_id, term, SubscriptionPlan.FREE
        )
        if blockers:
            raise ConflictException(
                "Current school usage exceeds Free plan limits.",
                payload={
                    "code": "FREE_PLAN_LIMITS_EXCEEDED",
                    "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
                },
            )

        now = datetime.now(timezone.utc)
        entitlement = TermPlanEntitlement(
            tenant_id=tenant_id,
            academic_term_id=term_id,
            plan_code=SubscriptionPlan.FREE,
            status=TermEntitlementStatus.ACTIVE,
            amount=Decimal("0"),
            currency="NGN",
            provider=PaymentProvider.MANUAL,
            activated_at=now,
            safety_expires_at=now + timedelta(days=TERM_SAFETY_LIFETIME_DAYS),
            activated_by_admin_id=admin_id,
        )
        db.add(entitlement)
        tenant = await SubscriptionRepository.get_tenant(db, tenant_id)
        if tenant:
            tenant.initial_plan_intent = None
            tenant.plan = SubscriptionPlan.FREE
            tenant.trial_ends_at = None
        await db.flush()
        await db.commit()
        await invalidate_tenant_subscription_cache(tenant_id)
        return entitlement

    @staticmethod
    async def initialize_paid_checkout(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        plan: SubscriptionPlan,
        email: str,
    ) -> SubscriptionCheckoutResponse:
        target = coerce_subscription_plan(plan)
        if target not in PAID_TERM_PLANS:
            raise ConflictException("Select Plus, Professional, or Enterprise for paid activation.")

        term = await TermPlanEntitlementService._term(db, tenant_id, term_id, lock=True)
        if term.status not in {AcademicTermStatus.DRAFT, AcademicTermStatus.OPEN}:
            raise ConflictException(
                "Only the term being opened or the current open term can start a paid-plan checkout."
            )
        await TermPlanEntitlementService._ensure_draft_selection_allowed(db, tenant_id, term)

        existing = await TermPlanEntitlementService.get_active(db, tenant_id, term_id, lock=True)
        transition = TermPlanEntitlementService._transition(existing, target)
        if transition in {"current", "downgrade"}:
            raise ConflictException(
                "This plan change does not require Paystack checkout.",
                payload={
                    "code": "NO_PAYMENT_REQUIRED",
                    "term_id": str(term_id),
                    "target_plan": target.value,
                },
            )

        _, blockers = await TermPlanEntitlementService._usage_and_blockers(
            db, tenant_id, term, target
        )
        if blockers:
            raise ConflictException(
                "Current school usage exceeds the selected plan limits.",
                payload={
                    "code": "TARGET_PLAN_INELIGIBLE",
                    "term_id": str(term_id),
                    "target_plan": target.value,
                    "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
                },
            )

        paid_to_date = await TermPlanEntitlementService._paid_to_date(db, tenant_id, term_id)
        amount_kobo = TermPlanEntitlementService._amount_due(
            transition=transition,
            target_plan=target,
            paid_to_date_kobo=paid_to_date,
        )
        if amount_kobo <= 0:
            raise ConflictException(
                "This plan change is already covered by payments made for this term.",
                payload={
                    "code": "NO_PAYMENT_REQUIRED",
                    "term_id": str(term_id),
                    "target_plan": target.value,
                },
            )

        pending = await TermPlanEntitlementService._get_pending_checkout(
            db, tenant_id, term_id, lock=True
        )
        if pending is not None:
            now = datetime.now(timezone.utc)
            reusable = bool(pending.authorization_url) and (
                pending.created_at is None or pending.created_at >= now - PENDING_CHECKOUT_TTL
            )
            if reusable:
                if pending.plan_code != target:
                    raise ConflictException(
                        "A different term-plan checkout is already in progress. "
                        "Finish or wait for that checkout to expire before choosing another plan."
                    )
                return TermPlanEntitlementService._checkout_response(pending)
            decision = await verify_before_abandoning(db, pending, as_of=now)
            if decision == "settled":
                # Commit the recovered payment before rejecting a second checkout.
                await db.commit()
                await invalidate_tenant_subscription_cache(tenant_id)
                raise ConflictException(
                    "Your previous Paystack payment was confirmed. "
                    "Check your current subscription before starting another checkout."
                )
            if decision != "abandoned":
                raise ConflictException(
                    "The previous checkout is still awaiting Paystack confirmation. "
                    "Please check payment history before starting another payment."
                )

        callback_url = str(settings.PAYSTACK_CALLBACK_URL or "").strip()
        if settings.is_production_like and not callback_url:
            raise ConflictException("Paystack callback URL is not configured for this environment.")

        reference = f"term-{term_id.hex[:12]}-{uuid.uuid4().hex[:16]}"
        transaction = PaymentTransaction(
            tenant_id=tenant_id,
            academic_term_id=term_id,
            provider=PaymentProvider.PAYSTACK,
            status=PaymentStatus.PENDING,
            reference=reference,
            plan_code=target,
            billing_interval=BillingInterval.TERM,
            amount=Decimal(amount_kobo) / 100,
            amount_kobo=amount_kobo,
            currency="NGN",
            raw_payload={
                "quote": {
                    "target_plan_price_kobo": TermPlanEntitlementService.amount_kobo(target),
                    "paid_to_date_kobo": paid_to_date,
                    "amount_due_kobo": amount_kobo,
                    "transition": transition,
                }
            },
        )
        db.add(transaction)
        await db.flush()

        checkout = await PaymentEngine.initialize_checkout(
            email=email,
            amount_kobo=amount_kobo,
            reference=reference,
            callback_url=callback_url,
            metadata={
                "payment_purpose": PaymentPurpose.TERM_SUBSCRIPTION.value,
                "tenant_id": str(tenant_id),
                "academic_term_id": str(term_id),
                "plan_code": target.value,
                "amount_kobo": amount_kobo,
                "target_plan_price_kobo": TermPlanEntitlementService.amount_kobo(target),
                "paid_to_date_kobo": paid_to_date,
                "transition": transition,
            },
        )
        transaction.authorization_url = checkout.authorization_url
        transaction.access_code = checkout.access_code

        await db.commit()
        return TermPlanEntitlementService._checkout_response(transaction)

    @staticmethod
    async def change_plan(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        target_plan: SubscriptionPlan,
        admin_id: uuid.UUID | None,
    ) -> TermPlanEntitlement:
        target = coerce_subscription_plan(target_plan)
        term = await TermPlanEntitlementService._term(db, tenant_id, term_id, lock=True)
        if term.status != AcademicTermStatus.OPEN:
            raise ConflictException(
                "Zero-cost plan changes are only available during the current open term."
            )

        await TermPlanEntitlementService.expire_stale_pending_checkouts(
            db,
            tenant_id=tenant_id,
            term_id=term_id,
        )
        pending = await TermPlanEntitlementService._get_pending_checkout(
            db, tenant_id, term_id, lock=True
        )
        if pending is not None:
            raise ConflictException(
                "Complete or wait for the current Paystack checkout to expire before changing plans."
            )

        existing = await TermPlanEntitlementService.get_active(db, tenant_id, term_id, lock=True)
        if existing is None:
            raise ConflictException("The current term does not have a plan entitlement to change.")

        transition = TermPlanEntitlementService._transition(existing, target)
        if transition == "current":
            return existing

        _, blockers = await TermPlanEntitlementService._usage_and_blockers(
            db, tenant_id, term, target
        )
        if blockers:
            raise ConflictException(
                "Current school usage exceeds the selected plan limits.",
                payload={
                    "code": "TARGET_PLAN_INELIGIBLE",
                    "term_id": str(term_id),
                    "target_plan": target.value,
                    "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
                },
            )

        paid_to_date = await TermPlanEntitlementService._paid_to_date(db, tenant_id, term_id)
        amount_due = TermPlanEntitlementService._amount_due(
            transition=transition,
            target_plan=target,
            paid_to_date_kobo=paid_to_date,
        )
        if amount_due > 0:
            raise ConflictException(
                "This plan change requires payment.",
                payload={
                    "code": "PAYMENT_REQUIRED",
                    "term_id": str(term_id),
                    "target_plan": target.value,
                    "amount_kobo": amount_due,
                },
            )

        now = datetime.now(timezone.utc)
        existing.status = TermEntitlementStatus.CLOSED
        existing.closed_at = now
        existing.closed_reason = (
            "mid_term_downgrade" if transition == "downgrade" else "zero_cost_reupgrade"
        )
        entitlement = TermPlanEntitlement(
            tenant_id=tenant_id,
            academic_term_id=term_id,
            plan_code=target,
            status=TermEntitlementStatus.ACTIVE,
            payment_transaction_id=None,
            amount=Decimal("0"),
            currency="NGN",
            provider=PaymentProvider.MANUAL,
            activated_at=now,
            safety_expires_at=now + timedelta(days=TERM_SAFETY_LIFETIME_DAYS),
            activated_by_admin_id=admin_id,
        )
        db.add(entitlement)
        tenant = await SubscriptionRepository.get_tenant(db, tenant_id)
        if tenant:
            tenant.plan = target
            tenant.initial_plan_intent = None
        await db.flush()
        await db.commit()
        await invalidate_tenant_subscription_cache(tenant_id)
        return entitlement

    @staticmethod
    async def activate_verified_transaction(
        db: AsyncSession,
        transaction: PaymentTransaction,
        provider_data: dict,
        *,
        commit: bool = True,
    ) -> TermPlanEntitlement:
        if transaction.academic_term_id is None:
            raise ConflictException("Payment is not attached to an academic term.")

        data = provider_data.get("data") or provider_data
        if (
            data.get("status") != "success"
            or int(data.get("amount") or -1) != transaction.amount_kobo
            or data.get("currency") != transaction.currency
        ):
            raise ConflictException(
                "Paystack verification did not match the expected term payment."
            )

        metadata = data.get("metadata") or {}
        if (
            str(metadata.get("tenant_id")) != str(transaction.tenant_id)
            or str(metadata.get("academic_term_id")) != str(transaction.academic_term_id)
            or str(metadata.get("plan_code")) != transaction.plan_code.value
        ):
            raise ConflictException(
                "Paystack term payment metadata did not match the expected purchase."
            )

        already_activated = await TermPlanEntitlementService._get_entitlement_for_transaction(
            db, transaction.id, lock=True
        )
        if already_activated is not None:
            return already_activated

        term = await TermPlanEntitlementService._term(
            db,
            transaction.tenant_id,
            transaction.academic_term_id,
            lock=True,
        )
        TermPlanEntitlementService._ensure_paid_settlement_term_state(term)

        existing = await TermPlanEntitlementService.get_active(
            db,
            transaction.tenant_id,
            transaction.academic_term_id,
            lock=True,
        )
        if existing is not None:
            transition = TermPlanEntitlementService._transition(existing, transaction.plan_code)
            if transition != "upgrade":
                raise ConflictException(
                    "The term plan changed while this payment was in progress. Contact support before retrying."
                )

        now = datetime.now(timezone.utc)
        if existing:
            existing.status = TermEntitlementStatus.CLOSED
            existing.closed_at = now
            existing.closed_reason = "mid_term_upgrade"

        quote_snapshot = dict((transaction.raw_payload or {}).get("quote") or {})
        transaction.status = PaymentStatus.SUCCESS
        transaction.paid_at = now
        transaction.provider_transaction_id = (
            str(data.get("id"))
            if data.get("id") is not None
            else transaction.provider_transaction_id
        )
        transaction.raw_payload = {**data, "weave_quote": quote_snapshot}

        entitlement = TermPlanEntitlement(
            tenant_id=transaction.tenant_id,
            academic_term_id=transaction.academic_term_id,
            plan_code=transaction.plan_code,
            status=TermEntitlementStatus.ACTIVE,
            payment_transaction_id=transaction.id,
            amount=transaction.amount,
            currency=transaction.currency,
            provider=PaymentProvider.PAYSTACK,
            activated_at=now,
            safety_expires_at=now + timedelta(days=TERM_SAFETY_LIFETIME_DAYS),
        )
        db.add(entitlement)

        tenant = await SubscriptionRepository.get_tenant(db, transaction.tenant_id)
        if tenant:
            tenant.initial_plan_intent = None
            tenant.trial_ends_at = None
            if term.status == AcademicTermStatus.OPEN and term.is_current:
                tenant.plan = coerce_subscription_plan(transaction.plan_code)

        await db.flush()
        if commit:
            await db.commit()
            await invalidate_tenant_subscription_cache(transaction.tenant_id)
        return entitlement

    @staticmethod
    async def mark_effective_for_open_term(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term: AcademicTerm,
        entitlement: TermPlanEntitlement,
    ) -> None:
        """Synchronize the legacy tenant plan snapshot only when a term becomes effective.

        TermPlanEntitlement plus the current OPEN term remain authoritative for access.
        tenant.plan is only a compatibility snapshot for remaining presentation/read paths.
        """
        if (
            term.tenant_id != tenant_id
            or term.status != AcademicTermStatus.OPEN
            or not term.is_current
        ):
            raise ConflictException(
                "A term entitlement can only become effective for the current open term."
            )
        if (
            entitlement.tenant_id != tenant_id
            or entitlement.academic_term_id != term.id
            or entitlement.status != TermEntitlementStatus.ACTIVE
        ):
            raise ConflictException(
                "The selected entitlement does not belong to the current open term."
            )
        tenant = await SubscriptionRepository.get_tenant(db, tenant_id)
        if tenant is None:
            raise NotFoundException("Tenant not found.")
        tenant.plan = coerce_subscription_plan(entitlement.plan_code)
        tenant.initial_plan_intent = None
        tenant.trial_ends_at = None
        await db.flush()

    @staticmethod
    async def close_for_term(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        reason: str = "term_closed",
    ) -> None:
        await TermPlanEntitlementService.expire_stale_pending_checkouts(
            db,
            tenant_id=tenant_id,
            term_id=term_id,
        )
        pending = await TermPlanEntitlementService._get_pending_checkout(
            db, tenant_id, term_id, lock=True
        )
        if pending is not None:
            raise ConflictException(
                "This academic term still has a pending Paystack checkout. "
                "Complete the payment or wait for the checkout to expire before finalizing closure."
            )

        entitlement = await TermPlanEntitlementService.get_active(db, tenant_id, term_id, lock=True)
        if entitlement:
            entitlement.status = TermEntitlementStatus.CLOSED
            entitlement.closed_at = datetime.now(timezone.utc)
            entitlement.closed_reason = reason

        tenant = await SubscriptionRepository.get_tenant(db, tenant_id)
        if tenant is not None:
            tenant.plan = SubscriptionPlan.FREE

    @staticmethod
    async def reconcile(
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, int]:
        """Safety repair only; normal entitlement closure is synchronous with term closure."""
        now = as_of or datetime.now(timezone.utc)
        await TermPlanEntitlementService.expire_stale_pending_checkouts(db, as_of=now)
        result = await db.execute(
            select(TermPlanEntitlement, AcademicTerm.status)
            .join(AcademicTerm, AcademicTerm.id == TermPlanEntitlement.academic_term_id)
            .where(
                TermPlanEntitlement.status == TermEntitlementStatus.ACTIVE,
                or_(
                    AcademicTerm.status == AcademicTermStatus.CLOSED,
                    TermPlanEntitlement.safety_expires_at <= now,
                ),
            )
            .with_for_update()
        )
        repaired_closed = 0
        safety_expired = 0
        tenant_ids: set[uuid.UUID] = set()
        for entitlement, term_status in result.all():
            tenant_ids.add(entitlement.tenant_id)
            if term_status == AcademicTermStatus.CLOSED:
                entitlement.status = TermEntitlementStatus.CLOSED
                entitlement.closed_at = now
                entitlement.closed_reason = "reconciled_closed_term"
                repaired_closed += 1
            else:
                entitlement.status = TermEntitlementStatus.EXPIRED
                entitlement.expired_at = now
                entitlement.closed_reason = "safety_cap_reached"
                safety_expired += 1
        await db.commit()
        for tenant_id in tenant_ids:
            await invalidate_tenant_subscription_cache(tenant_id)
        return {"closed_term_repaired": repaired_closed, "safety_expired": safety_expired}
