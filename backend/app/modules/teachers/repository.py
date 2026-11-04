"""Repositories for global teacher accounts and tenant teacher memberships."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.teachers.models import (
    TeacherAccount,
    TeacherInvitation,
    TeacherInvitationStatus,
    TeacherMembership,
    TeacherMembershipStatus,
    TeacherMembershipSubject,
)


class TeacherAccountRepository:
    @staticmethod
    async def add(
        db: AsyncSession,
        account: TeacherAccount,
    ) -> TeacherAccount:
        db.add(account)
        await db.flush()
        return account

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        account_id: UUID,
        *,
        lock: bool = False,
    ) -> TeacherAccount | None:
        query = select(TeacherAccount).where(
            TeacherAccount.id == account_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_email(
        db: AsyncSession,
        normalized_email: str,
        *,
        lock: bool = False,
    ) -> TeacherAccount | None:
        query = select(TeacherAccount).where(
            TeacherAccount.email == normalized_email.strip().casefold(),
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def email_exists(
        db: AsyncSession,
        normalized_email: str,
    ) -> bool:
        result = await db.execute(
            select(TeacherAccount.id).where(
                TeacherAccount.email == normalized_email.strip().casefold(),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_memberships(
        db: AsyncSession,
        account_id: UUID,
    ) -> list[TeacherMembership]:
        result = await db.execute(
            select(TeacherMembership)
            .options(joinedload(TeacherMembership.teacher_account))
            .where(
                TeacherMembership.teacher_account_id == account_id,
            )
            .order_by(TeacherMembership.created_at.asc())
        )
        return list(result.scalars().unique().all())

    @staticmethod
    async def save(
        db: AsyncSession,
        account: TeacherAccount,
    ) -> TeacherAccount:
        db.add(account)
        await db.flush()
        return account


class TeacherMembershipRepository:
    @staticmethod
    async def add(
        db: AsyncSession,
        membership: TeacherMembership,
    ) -> TeacherMembership:
        db.add(membership)
        await db.flush()
        return membership

    @staticmethod
    async def create_teacher(
        db: AsyncSession,
        teacher: TeacherMembership,
    ) -> TeacherMembership:
        return await TeacherMembershipRepository.add(db, teacher)

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        membership_id: UUID,
        *,
        tenant_id: UUID | None = None,
        lock: bool = False,
        load_account: bool = True,
        load_subjects: bool = False,
    ) -> TeacherMembership | None:
        filters = [TeacherMembership.id == membership_id]
        if tenant_id is not None:
            filters.append(TeacherMembership.tenant_id == tenant_id)

        query = select(TeacherMembership).where(*filters)
        if load_account:
            query = query.options(
                selectinload(TeacherMembership.teacher_account),
            )
        if load_subjects:
            query = query.options(
                selectinload(
                    TeacherMembership.subject_links,
                ).selectinload(TeacherMembershipSubject.subject)
            )
        if lock:
            query = query.with_for_update()

        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_teacher_by_id(
        db: AsyncSession,
        tenant_id: UUID,
        teacher_id: UUID,
        *,
        lock: bool = False,
    ) -> TeacherMembership | None:
        return await TeacherMembershipRepository.get_by_id(
            db,
            teacher_id,
            tenant_id=tenant_id,
            lock=lock,
            load_account=True,
            load_subjects=True,
        )

    @staticmethod
    async def get_by_account_and_tenant(
        db: AsyncSession,
        account_id: UUID,
        tenant_id: UUID,
        *,
        lock: bool = False,
    ) -> TeacherMembership | None:
        query = (
            select(TeacherMembership)
            .options(selectinload(TeacherMembership.teacher_account))
            .where(
                TeacherMembership.teacher_account_id == account_id,
                TeacherMembership.tenant_id == tenant_id,
            )
        )
        if lock:
            query = query.with_for_update()
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(
        db: AsyncSession,
        email: str,
        *,
        tenant_id: UUID | None = None,
    ) -> TeacherMembership | None:
        filters = [
            TeacherAccount.email == email.strip().casefold(),
        ]
        if tenant_id is not None:
            filters.append(TeacherMembership.tenant_id == tenant_id)

        result = await db.execute(
            select(TeacherMembership)
            .join(TeacherMembership.teacher_account)
            .options(joinedload(TeacherMembership.teacher_account))
            .where(*filters)
            .order_by(TeacherMembership.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_staff_id(
        db: AsyncSession,
        tenant_id: UUID,
        staff_id: str,
    ) -> TeacherMembership | None:
        result = await db.execute(
            select(TeacherMembership)
            .options(joinedload(TeacherMembership.teacher_account))
            .where(
                TeacherMembership.tenant_id == tenant_id,
                func.lower(TeacherMembership.staff_id) == staff_id.strip().lower(),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def staff_id_exists(
        db: AsyncSession,
        tenant_id: UUID,
        staff_id: str,
        *,
        exclude_membership_id: UUID | None = None,
        exclude_teacher_id: UUID | None = None,
    ) -> bool:
        excluded_id = exclude_membership_id or exclude_teacher_id
        query = select(TeacherMembership.id).where(
            TeacherMembership.tenant_id == tenant_id,
            func.lower(TeacherMembership.staff_id) == staff_id.strip().lower(),
        )
        if excluded_id is not None:
            query = query.where(TeacherMembership.id != excluded_id)
        result = await db.execute(query)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: TeacherMembershipStatus | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TeacherMembership], int]:
        filters = [TeacherMembership.tenant_id == tenant_id]
        if status is not None:
            filters.append(TeacherMembership.status == status)

        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    TeacherMembership.staff_id.ilike(pattern),
                    TeacherMembership.job_title.ilike(pattern),
                    TeacherMembership.department.ilike(pattern),
                    TeacherMembership.teacher_account.has(
                        or_(
                            TeacherAccount.email.ilike(pattern),
                            TeacherAccount.first_name.ilike(pattern),
                            TeacherAccount.last_name.ilike(pattern),
                            TeacherAccount.qualification.ilike(pattern),
                            TeacherAccount.specialization.ilike(pattern),
                        )
                    ),
                )
            )

        total = (
            await db.execute(select(func.count()).select_from(TeacherMembership).where(*filters))
        ).scalar_one()

        result = await db.execute(
            select(TeacherMembership)
            .options(
                joinedload(TeacherMembership.teacher_account),
                selectinload(
                    TeacherMembership.subject_links,
                ).selectinload(TeacherMembershipSubject.subject),
            )
            .where(*filters)
            .order_by(TeacherMembership.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().unique().all()), total

    @staticmethod
    async def list_all_teachers(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> tuple[list[TeacherMembership], int]:
        return await TeacherMembershipRepository.list_for_tenant(
            db,
            tenant_id,
            search=search,
            offset=skip,
            limit=limit,
        )

    @staticmethod
    async def list_usable_for_account(
        db: AsyncSession,
        account_id: UUID,
    ) -> list[TeacherMembership]:
        result = await db.execute(
            select(TeacherMembership)
            .options(joinedload(TeacherMembership.teacher_account))
            .where(
                TeacherMembership.teacher_account_id == account_id,
                TeacherMembership.status.in_(
                    [
                        TeacherMembershipStatus.ACTIVE,
                        TeacherMembershipStatus.SUSPENDED,
                    ]
                ),
            )
            .order_by(TeacherMembership.created_at.asc())
        )
        return list(result.scalars().unique().all())

    @staticmethod
    async def count_active_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(TeacherMembership)
            .where(
                TeacherMembership.tenant_id == tenant_id,
                TeacherMembership.status == TeacherMembershipStatus.ACTIVE,
            )
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    async def save(
        db: AsyncSession,
        membership: TeacherMembership | None = None,
        *,
        teacher: TeacherMembership | None = None,
    ) -> TeacherMembership:
        record = membership or teacher
        if record is None:
            raise ValueError("membership is required")
        db.add(record)
        await db.flush()
        return record

    @staticmethod
    async def delete_teacher(
        db: AsyncSession,
        teacher: TeacherMembership,
    ) -> None:
        teacher.status = TeacherMembershipStatus.INACTIVE
        db.add(teacher)
        await db.flush()


class TeacherInvitationRepository:
    @staticmethod
    async def add(
        db: AsyncSession,
        invitation: TeacherInvitation,
    ) -> TeacherInvitation:
        db.add(invitation)
        await db.flush()
        return invitation

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        tenant_id: UUID,
        invitation_id: UUID,
        *,
        lock: bool = False,
    ) -> TeacherInvitation | None:
        query = select(TeacherInvitation).where(
            TeacherInvitation.tenant_id == tenant_id,
            TeacherInvitation.id == invitation_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_token_digest(
        db: AsyncSession,
        token_digest: str,
        *,
        lock: bool = False,
    ) -> TeacherInvitation | None:
        query = select(TeacherInvitation).where(
            TeacherInvitation.token_digest == token_digest,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_pending_for_email(
        db: AsyncSession,
        tenant_id: UUID,
        normalized_email: str,
        *,
        lock: bool = False,
    ) -> TeacherInvitation | None:
        query = select(TeacherInvitation).where(
            TeacherInvitation.tenant_id == tenant_id,
            TeacherInvitation.invited_email == normalized_email.strip().casefold(),
            TeacherInvitation.status == TeacherInvitationStatus.PENDING,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: TeacherInvitationStatus | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TeacherInvitation], int]:
        filters = [TeacherInvitation.tenant_id == tenant_id]
        if status is not None:
            filters.append(TeacherInvitation.status == status)
        if search and search.strip():
            filters.append(TeacherInvitation.invited_email.ilike(f"%{search.strip()}%"))

        total = (
            await db.execute(select(func.count()).select_from(TeacherInvitation).where(*filters))
        ).scalar_one()

        result = await db.execute(
            select(TeacherInvitation)
            .where(*filters)
            .order_by(TeacherInvitation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    @staticmethod
    async def save(
        db: AsyncSession,
        invitation: TeacherInvitation,
    ) -> TeacherInvitation:
        db.add(invitation)
        await db.flush()
        return invitation


class TeacherMembershipSubjectRepository:
    @staticmethod
    async def add_many(
        db: AsyncSession,
        tenant_id: UUID,
        membership_id: UUID,
        subject_ids: list[UUID],
    ) -> list[TeacherMembershipSubject]:
        links = [
            TeacherMembershipSubject(
                tenant_id=tenant_id,
                teacher_membership_id=membership_id,
                subject_id=subject_id,
            )
            for subject_id in subject_ids
        ]
        db.add_all(links)
        await db.flush()
        return links

    @staticmethod
    async def list_for_membership(
        db: AsyncSession,
        tenant_id: UUID,
        membership_id: UUID,
    ) -> list[TeacherMembershipSubject]:
        result = await db.execute(
            select(TeacherMembershipSubject)
            .options(
                selectinload(
                    TeacherMembershipSubject.subject,
                )
            )
            .where(
                TeacherMembershipSubject.tenant_id == tenant_id,
                TeacherMembershipSubject.teacher_membership_id == membership_id,
            )
            .order_by(TeacherMembershipSubject.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_membership_and_subject(
        db: AsyncSession,
        tenant_id: UUID,
        membership_id: UUID,
        subject_id: UUID,
        *,
        lock: bool = False,
    ) -> TeacherMembershipSubject | None:
        query = select(TeacherMembershipSubject).where(
            TeacherMembershipSubject.tenant_id == tenant_id,
            TeacherMembershipSubject.teacher_membership_id == membership_id,
            TeacherMembershipSubject.subject_id == subject_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def save(
        db: AsyncSession,
        link: TeacherMembershipSubject,
    ) -> TeacherMembershipSubject:
        db.add(link)
        await db.flush()
        return link


# Tenant-facing repository name. Global account code imports
# TeacherAccountRepository explicitly.
TeacherRepository = TeacherMembershipRepository
