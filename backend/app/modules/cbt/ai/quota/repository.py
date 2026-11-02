"""Data access layer for CBT AI quota and credit accounting."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.cbt.ai.quota.models import (
    AICreditAllocation,
    AICreditLedger,
    AICreditLedgerBucket,
    AICreditLedgerEventType,
    AICreditReservation,
    AICreditReservationStatus,
    AIExtraCreditBalance,
    AIQuotaAccount,
    AIQuotaPurchase,
    AIQuotaPurchaseStatus,
    AIQuotaRequest,
    AIQuotaRequestStatus,
    AITenantCreditBalance,
    AIWeeklyQuota,
)
from app.modules.teachers.models import TeacherAccount, TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin


class AIQuotaAccountRepository:
    """Database operations for tenant-scoped AI quota accounts."""

    @staticmethod
    async def create(
        db: AsyncSession,
        account: AIQuotaAccount,
    ) -> AIQuotaAccount:
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def save(
        db: AsyncSession,
        account: AIQuotaAccount,
    ) -> AIQuotaAccount:
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def get_by_tenant_and_id(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        account_id: uuid.UUID,
        lock: bool = False,
    ) -> AIQuotaAccount | None:
        query = select(AIQuotaAccount).where(
            AIQuotaAccount.id == account_id,
            AIQuotaAccount.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_teacher_membership(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_membership_id: uuid.UUID,
        lock: bool = False,
    ) -> AIQuotaAccount | None:
        query = select(AIQuotaAccount).where(
            AIQuotaAccount.tenant_id == tenant_id,
            AIQuotaAccount.teacher_membership_id == teacher_membership_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_tenant_admin(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        tenant_admin_id: uuid.UUID,
        lock: bool = False,
    ) -> AIQuotaAccount | None:
        query = select(AIQuotaAccount).where(
            AIQuotaAccount.tenant_id == tenant_id,
            AIQuotaAccount.tenant_admin_id == tenant_admin_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_many_by_ids(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        account_ids: Sequence[uuid.UUID],
    ) -> list[AIQuotaAccount]:
        if not account_ids:
            return []
        result = await db.execute(
            select(AIQuotaAccount).where(
                AIQuotaAccount.tenant_id == tenant_id,
                AIQuotaAccount.id.in_(account_ids),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> list[AIQuotaAccount]:
        result = await db.execute(
            select(AIQuotaAccount)
            .where(AIQuotaAccount.tenant_id == tenant_id)
            .order_by(AIQuotaAccount.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_balance_context_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        week_start: date,
    ) -> list[
        tuple[
            AIQuotaAccount,
            AIWeeklyQuota | None,
            AIExtraCreditBalance | None,
            TeacherMembership | None,
            TeacherAccount | None,
            TenantAdmin | None,
        ]
    ]:
        """Load actor identity and both personal credit buckets in one query.

        This is the preferred read path for tenant credit dashboards. It avoids
        one query per account for weekly quota, top-up balance, or actor profile.
        """

        teacher_membership = aliased(TeacherMembership)
        teacher_account = aliased(TeacherAccount)
        tenant_admin = aliased(TenantAdmin)

        result = await db.execute(
            select(
                AIQuotaAccount,
                AIWeeklyQuota,
                AIExtraCreditBalance,
                teacher_membership,
                teacher_account,
                tenant_admin,
            )
            .outerjoin(
                AIWeeklyQuota,
                and_(
                    AIWeeklyQuota.quota_account_id == AIQuotaAccount.id,
                    AIWeeklyQuota.tenant_id == tenant_id,
                    AIWeeklyQuota.week_start == week_start,
                ),
            )
            .outerjoin(
                AIExtraCreditBalance,
                and_(
                    AIExtraCreditBalance.quota_account_id == AIQuotaAccount.id,
                    AIExtraCreditBalance.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                teacher_membership,
                and_(
                    teacher_membership.id == AIQuotaAccount.teacher_membership_id,
                    teacher_membership.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                teacher_account,
                teacher_account.id == teacher_membership.teacher_account_id,
            )
            .outerjoin(
                tenant_admin,
                and_(
                    tenant_admin.id == AIQuotaAccount.tenant_admin_id,
                    tenant_admin.tenant_id == tenant_id,
                ),
            )
            .where(AIQuotaAccount.tenant_id == tenant_id)
            .order_by(AIQuotaAccount.created_at.asc())
        )
        return [tuple(row) for row in result.all()]


class AIWeeklyQuotaRepository:
    """Database operations for weekly free-credit buckets."""

    @staticmethod
    async def create(
        db: AsyncSession,
        quota: AIWeeklyQuota,
    ) -> AIWeeklyQuota:
        db.add(quota)
        await db.flush()
        return quota

    @staticmethod
    async def save(
        db: AsyncSession,
        quota: AIWeeklyQuota,
    ) -> AIWeeklyQuota:
        db.add(quota)
        await db.flush()
        return quota

    @staticmethod
    async def get_for_account_week(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_id: uuid.UUID,
        week_start: date,
        lock: bool = False,
    ) -> AIWeeklyQuota | None:
        query = select(AIWeeklyQuota).where(
            AIWeeklyQuota.tenant_id == tenant_id,
            AIWeeklyQuota.quota_account_id == quota_account_id,
            AIWeeklyQuota.week_start == week_start,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_accounts_week(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_ids: Sequence[uuid.UUID],
        week_start: date,
    ) -> list[AIWeeklyQuota]:
        if not quota_account_ids:
            return []
        result = await db.execute(
            select(AIWeeklyQuota).where(
                AIWeeklyQuota.tenant_id == tenant_id,
                AIWeeklyQuota.quota_account_id.in_(quota_account_ids),
                AIWeeklyQuota.week_start == week_start,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def lock_many_buckets(
        db: AsyncSession, *, keys: set[tuple[uuid.UUID, uuid.UUID, date]]
    ) -> list[AIWeeklyQuota]:
        if not keys:
            return []
        rows = await db.execute(
            select(AIWeeklyQuota)
            .where(
                tuple_(
                    AIWeeklyQuota.tenant_id,
                    AIWeeklyQuota.quota_account_id,
                    AIWeeklyQuota.week_start,
                ).in_(keys)
            )
            .order_by(
                AIWeeklyQuota.tenant_id,
                AIWeeklyQuota.quota_account_id,
                AIWeeklyQuota.week_start,
            )
            .with_for_update()
        )
        return list(rows.scalars().all())


class AIExtraCreditBalanceRepository:
    """Database operations for persistent actor top-up balances."""

    @staticmethod
    async def create(
        db: AsyncSession,
        balance: AIExtraCreditBalance,
    ) -> AIExtraCreditBalance:
        db.add(balance)
        await db.flush()
        return balance

    @staticmethod
    async def save(
        db: AsyncSession,
        balance: AIExtraCreditBalance,
    ) -> AIExtraCreditBalance:
        db.add(balance)
        await db.flush()
        return balance

    @staticmethod
    async def get_for_account(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_id: uuid.UUID,
        lock: bool = False,
    ) -> AIExtraCreditBalance | None:
        query = select(AIExtraCreditBalance).where(
            AIExtraCreditBalance.tenant_id == tenant_id,
            AIExtraCreditBalance.quota_account_id == quota_account_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_accounts(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_ids: Sequence[uuid.UUID],
    ) -> list[AIExtraCreditBalance]:
        if not quota_account_ids:
            return []
        result = await db.execute(
            select(AIExtraCreditBalance).where(
                AIExtraCreditBalance.tenant_id == tenant_id,
                AIExtraCreditBalance.quota_account_id.in_(quota_account_ids),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def lock_many_buckets(
        db: AsyncSession, *, keys: set[tuple[uuid.UUID, uuid.UUID]]
    ) -> list[AIExtraCreditBalance]:
        if not keys:
            return []
        rows = await db.execute(
            select(AIExtraCreditBalance)
            .where(
                tuple_(
                    AIExtraCreditBalance.tenant_id,
                    AIExtraCreditBalance.quota_account_id,
                ).in_(keys)
            )
            .order_by(
                AIExtraCreditBalance.tenant_id,
                AIExtraCreditBalance.quota_account_id,
            )
            .with_for_update()
        )
        return list(rows.scalars().all())


class AITenantCreditBalanceRepository:
    """Database operations for the tenant-wide purchased credit reserve."""

    @staticmethod
    async def create(
        db: AsyncSession,
        balance: AITenantCreditBalance,
    ) -> AITenantCreditBalance:
        db.add(balance)
        await db.flush()
        return balance

    @staticmethod
    async def save(
        db: AsyncSession,
        balance: AITenantCreditBalance,
    ) -> AITenantCreditBalance:
        db.add(balance)
        await db.flush()
        return balance

    @staticmethod
    async def get_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        lock: bool = False,
    ) -> AITenantCreditBalance | None:
        query = select(AITenantCreditBalance).where(
            AITenantCreditBalance.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()


class AICreditReservationRepository:
    """Database operations for in-flight AI credit reservations."""

    @staticmethod
    async def create(
        db: AsyncSession,
        reservation: AICreditReservation,
    ) -> AICreditReservation:
        db.add(reservation)
        await db.flush()
        return reservation

    @staticmethod
    async def save(
        db: AsyncSession,
        reservation: AICreditReservation,
    ) -> AICreditReservation:
        db.add(reservation)
        await db.flush()
        return reservation

    @staticmethod
    async def get_by_tenant_and_id(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        lock: bool = False,
    ) -> AICreditReservation | None:
        query = select(AICreditReservation).where(
            AICreditReservation.id == reservation_id,
            AICreditReservation.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_expired_pending_for_recovery(
        db: AsyncSession,
        *,
        as_of: datetime,
        limit: int = 100,
        tenant_ids: set[uuid.UUID] | None = None,
    ) -> list[AICreditReservation]:
        """Lock a batch of stale reservations without blocking other workers."""

        result = await db.execute(
            select(AICreditReservation)
            .where(
                *(
                    [AICreditReservation.tenant_id.in_(tenant_ids)]
                    if tenant_ids is not None
                    else []
                ),
                AICreditReservation.status == AICreditReservationStatus.PENDING,
                AICreditReservation.expires_at <= as_of,
            )
            .order_by(AICreditReservation.expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())


class AICreditAllocationRepository:
    """Database operations for tenant-reserve allocations to actors."""

    @staticmethod
    async def create(
        db: AsyncSession,
        allocation: AICreditAllocation,
    ) -> AICreditAllocation:
        db.add(allocation)
        await db.flush()
        return allocation

    @staticmethod
    async def get_by_tenant_and_id(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        allocation_id: uuid.UUID,
    ) -> AICreditAllocation | None:
        result = await db.execute(
            select(AICreditAllocation).where(
                AICreditAllocation.id == allocation_id,
                AICreditAllocation.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_tenant_with_actor_details(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[
        list[
            tuple[
                AICreditAllocation,
                AIQuotaAccount,
                TeacherMembership | None,
                TeacherAccount | None,
                TenantAdmin | None,
                TenantAdmin,
            ]
        ],
        int,
    ]:
        """List allocations with recipient and allocator identity in one query."""

        recipient_membership = aliased(TeacherMembership)
        recipient_teacher = aliased(TeacherAccount)
        recipient_admin = aliased(TenantAdmin)
        allocating_admin = aliased(TenantAdmin)

        filters = [AICreditAllocation.tenant_id == tenant_id]
        total = int(
            (
                await db.execute(
                    select(func.count()).select_from(AICreditAllocation).where(*filters)
                )
            ).scalar_one()
        )

        result = await db.execute(
            select(
                AICreditAllocation,
                AIQuotaAccount,
                recipient_membership,
                recipient_teacher,
                recipient_admin,
                allocating_admin,
            )
            .join(
                AIQuotaAccount,
                and_(
                    AIQuotaAccount.id == AICreditAllocation.recipient_quota_account_id,
                    AIQuotaAccount.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                recipient_membership,
                and_(
                    recipient_membership.id == AIQuotaAccount.teacher_membership_id,
                    recipient_membership.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                recipient_teacher,
                recipient_teacher.id == recipient_membership.teacher_account_id,
            )
            .outerjoin(
                recipient_admin,
                and_(
                    recipient_admin.id == AIQuotaAccount.tenant_admin_id,
                    recipient_admin.tenant_id == tenant_id,
                ),
            )
            .join(
                allocating_admin,
                and_(
                    allocating_admin.id == AICreditAllocation.allocated_by_admin_id,
                    allocating_admin.tenant_id == tenant_id,
                ),
            )
            .where(*filters)
            .order_by(AICreditAllocation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total


class AIQuotaRequestRepository:
    """Database operations for teacher top-up requests."""

    @staticmethod
    async def create(
        db: AsyncSession,
        request: AIQuotaRequest,
    ) -> AIQuotaRequest:
        db.add(request)
        await db.flush()
        return request

    @staticmethod
    async def save(
        db: AsyncSession,
        request: AIQuotaRequest,
    ) -> AIQuotaRequest:
        db.add(request)
        await db.flush()
        return request

    @staticmethod
    async def get_by_tenant_and_id(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        request_id: uuid.UUID,
        lock: bool = False,
    ) -> AIQuotaRequest | None:
        query = select(AIQuotaRequest).where(
            AIQuotaRequest.id == request_id,
            AIQuotaRequest.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_tenant_with_requester(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        status: AIQuotaRequestStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[
        list[
            tuple[
                AIQuotaRequest,
                AIQuotaAccount,
                TeacherMembership | None,
                TeacherAccount | None,
                TenantAdmin | None,
            ]
        ],
        int,
    ]:
        """List requests with requester and reviewer identity without N+1 reads."""

        requester_membership = aliased(TeacherMembership)
        requester_teacher = aliased(TeacherAccount)
        reviewer_admin = aliased(TenantAdmin)

        filters = [AIQuotaRequest.tenant_id == tenant_id]
        if status is not None:
            filters.append(AIQuotaRequest.status == status)

        total = int(
            (
                await db.execute(select(func.count()).select_from(AIQuotaRequest).where(*filters))
            ).scalar_one()
        )

        result = await db.execute(
            select(
                AIQuotaRequest,
                AIQuotaAccount,
                requester_membership,
                requester_teacher,
                reviewer_admin,
            )
            .join(
                AIQuotaAccount,
                and_(
                    AIQuotaAccount.id == AIQuotaRequest.requester_quota_account_id,
                    AIQuotaAccount.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                requester_membership,
                and_(
                    requester_membership.id == AIQuotaAccount.teacher_membership_id,
                    requester_membership.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                requester_teacher,
                requester_teacher.id == requester_membership.teacher_account_id,
            )
            .outerjoin(
                reviewer_admin,
                and_(
                    reviewer_admin.id == AIQuotaRequest.reviewed_by_admin_id,
                    reviewer_admin.tenant_id == tenant_id,
                ),
            )
            .where(*filters)
            .order_by(AIQuotaRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    @staticmethod
    async def list_for_requester(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        requester_quota_account_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AIQuotaRequest], int]:
        filters = [
            AIQuotaRequest.tenant_id == tenant_id,
            AIQuotaRequest.requester_quota_account_id == requester_quota_account_id,
        ]
        total = int(
            (
                await db.execute(select(func.count()).select_from(AIQuotaRequest).where(*filters))
            ).scalar_one()
        )
        result = await db.execute(
            select(AIQuotaRequest)
            .where(*filters)
            .order_by(AIQuotaRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total


class AIQuotaPurchaseRepository:
    """Database operations for tenant AI-credit purchases."""

    @staticmethod
    async def create(
        db: AsyncSession,
        purchase: AIQuotaPurchase,
    ) -> AIQuotaPurchase:
        db.add(purchase)
        await db.flush()
        return purchase

    @staticmethod
    async def save(
        db: AsyncSession,
        purchase: AIQuotaPurchase,
    ) -> AIQuotaPurchase:
        db.add(purchase)
        await db.flush()
        return purchase

    @staticmethod
    async def get_by_tenant_and_id(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        purchase_id: uuid.UUID,
        lock: bool = False,
    ) -> AIQuotaPurchase | None:
        query = select(AIQuotaPurchase).where(
            AIQuotaPurchase.id == purchase_id,
            AIQuotaPurchase.tenant_id == tenant_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_reference(
        db: AsyncSession,
        *,
        reference: str,
        lock: bool = False,
    ) -> AIQuotaPurchase | None:
        query = select(AIQuotaPurchase).where(
            AIQuotaPurchase.reference == reference,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_tenant_with_admin(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        status: AIQuotaPurchaseStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[tuple[AIQuotaPurchase, TenantAdmin]], int]:
        filters = [
            AIQuotaPurchase.tenant_id == tenant_id,
            AIQuotaPurchase.initiated_by_admin_id.is_not(None),
        ]
        if status is not None:
            filters.append(AIQuotaPurchase.status == status)

        total = int(
            (
                await db.execute(select(func.count()).select_from(AIQuotaPurchase).where(*filters))
            ).scalar_one()
        )
        result = await db.execute(
            select(AIQuotaPurchase, TenantAdmin)
            .join(
                TenantAdmin,
                and_(
                    TenantAdmin.id == AIQuotaPurchase.initiated_by_admin_id,
                    TenantAdmin.tenant_id == tenant_id,
                ),
            )
            .where(*filters)
            .order_by(AIQuotaPurchase.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total

    @staticmethod
    async def list_for_teacher(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        membership_id: uuid.UUID,
        status: AIQuotaPurchaseStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AIQuotaPurchase], int]:
        filters = [
            AIQuotaPurchase.tenant_id == tenant_id,
            AIQuotaPurchase.initiated_by_teacher_membership_id == membership_id,
        ]
        if status is not None:
            filters.append(AIQuotaPurchase.status == status)
        total = int(
            (
                await db.execute(select(func.count()).select_from(AIQuotaPurchase).where(*filters))
            ).scalar_one()
        )
        rows = (
            (
                await db.execute(
                    select(AIQuotaPurchase)
                    .where(*filters)
                    .order_by(AIQuotaPurchase.created_at.desc(), AIQuotaPurchase.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total


class AICreditLedgerRepository:
    """Append-only database operations for AI credit movements."""

    @staticmethod
    async def create(
        db: AsyncSession,
        entry: AICreditLedger,
    ) -> AICreditLedger:
        db.add(entry)
        await db.flush()
        return entry

    @staticmethod
    async def create_many(
        db: AsyncSession,
        entries: Sequence[AICreditLedger],
    ) -> list[AICreditLedger]:
        if not entries:
            return []
        items = list(entries)
        db.add_all(items)
        await db.flush()
        return items

    @staticmethod
    async def list_for_tenant_with_references(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        quota_account_id: uuid.UUID | None = None,
        bucket: AICreditLedgerBucket | None = None,
        event_type: AICreditLedgerEventType | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[
        list[
            tuple[
                AICreditLedger,
                AICreditReservation | None,
                AICreditAllocation | None,
                AIQuotaPurchase | None,
            ]
        ],
        int,
    ]:
        """List ledger rows and optional source records in a single read."""

        filters = [AICreditLedger.tenant_id == tenant_id]
        if quota_account_id is not None:
            filters.append(AICreditLedger.quota_account_id == quota_account_id)
        if bucket is not None:
            filters.append(AICreditLedger.bucket == bucket)
        if event_type is not None:
            filters.append(AICreditLedger.event_type == event_type)
        if date_from is not None:
            filters.append(AICreditLedger.created_at >= date_from)
        if date_to is not None:
            filters.append(AICreditLedger.created_at <= date_to)

        total = int(
            (
                await db.execute(select(func.count()).select_from(AICreditLedger).where(*filters))
            ).scalar_one()
        )
        result = await db.execute(
            select(
                AICreditLedger,
                AICreditReservation,
                AICreditAllocation,
                AIQuotaPurchase,
            )
            .outerjoin(
                AICreditReservation,
                and_(
                    AICreditReservation.id == AICreditLedger.reservation_id,
                    AICreditReservation.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                AICreditAllocation,
                and_(
                    AICreditAllocation.id == AICreditLedger.allocation_id,
                    AICreditAllocation.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                AIQuotaPurchase,
                and_(
                    AIQuotaPurchase.id == AICreditLedger.purchase_id,
                    AIQuotaPurchase.tenant_id == tenant_id,
                ),
            )
            .where(*filters)
            .order_by(AICreditLedger.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in result.all()], total
