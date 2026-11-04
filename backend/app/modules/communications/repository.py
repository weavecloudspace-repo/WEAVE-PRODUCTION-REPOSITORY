"""Low-level communication queries."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.modules.communications.enums import CommunicationActorType, NotificationStatus
from app.modules.students.models import Student
from app.modules.teachers.models import Teacher, TeacherAccount
from app.modules.parents.models import Parent, ParentAccount
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.superadmin.models import SuperAdmin
from app.modules.communications.models import (
    Conversation,
    ConversationParticipant,
    Message,
    Notice,
    NotificationDelivery,
)


class CommunicationRepository:
    @staticmethod
    async def save(db: AsyncSession, row):
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    @staticmethod
    async def get_conversation_for_actor(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        actor_type: CommunicationActorType,
        actor_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
    ) -> Conversation | None:
        stmt = (
            select(Conversation)
            .join(ConversationParticipant)
            .options(
                selectinload(Conversation.participants),
                selectinload(Conversation.messages),
            )
            .where(
                Conversation.id == conversation_id,
                ConversationParticipant.actor_type == actor_type,
                ConversationParticipant.actor_id == actor_id,
                ConversationParticipant.left_at.is_(None),
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(
                or_(
                    Conversation.tenant_id == tenant_id,
                    ConversationParticipant.tenant_id == tenant_id,
                )
            )
        return (await db.execute(stmt)).unique().scalar_one_or_none()

    @staticmethod
    async def list_conversations_for_actor(
        db: AsyncSession,
        *,
        actor_type: CommunicationActorType,
        actor_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        offset: int,
        limit: int,
        search: str | None = None,
        counterpart_type: CommunicationActorType | None = None,
    ) -> tuple[list[Conversation], int]:
        base = (
            select(Conversation)
            .join(ConversationParticipant)
            .where(
                ConversationParticipant.actor_type == actor_type,
                ConversationParticipant.actor_id == actor_id,
                ConversationParticipant.left_at.is_(None),
            )
        )
        if tenant_id is not None:
            base = base.where(
                or_(
                    Conversation.tenant_id == tenant_id,
                    ConversationParticipant.tenant_id == tenant_id,
                )
            )
        # Search and counterpart-role constraints must run before offset/limit.
        counterpart = aliased(ConversationParticipant)
        counterpart_filters = [
            counterpart.conversation_id == Conversation.id,
            counterpart.left_at.is_(None),
            or_(
                counterpart.actor_type != actor_type,
                counterpart.actor_id != actor_id,
            ),
        ]
        if counterpart_type is not None:
            counterpart_filters.append(counterpart.actor_type == counterpart_type)
        search_term = (search or "").strip()
        if search_term:
            escaped = search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            student_match = (
                exists(
                    select(Student.id).where(
                        Student.id == counterpart.actor_id,
                        or_(
                            Student.first_name.ilike(pattern, escape="\\"),
                            Student.last_name.ilike(pattern, escape="\\"),
                            Student.admission_number.ilike(pattern, escape="\\"),
                            func.concat(Student.first_name, " ", Student.last_name).ilike(
                                pattern, escape="\\"
                            ),
                        ),
                    )
                )
                .correlate(counterpart)
            )
            teacher_match = (
                exists(
                    select(Teacher.id)
                    .join(TeacherAccount, Teacher.teacher_account_id == TeacherAccount.id)
                    .where(
                        Teacher.id == counterpart.actor_id,
                        or_(
                            TeacherAccount.first_name.ilike(pattern, escape="\\"),
                            TeacherAccount.last_name.ilike(pattern, escape="\\"),
                            TeacherAccount.email.ilike(pattern, escape="\\"),
                            Teacher.staff_id.ilike(pattern, escape="\\"),
                            func.concat(
                                TeacherAccount.first_name, " ", TeacherAccount.last_name
                            ).ilike(pattern, escape="\\"),
                        ),
                    )
                )
                .correlate(counterpart)
            )
            parent_match = (
                exists(
                    select(Parent.id)
                    .join(ParentAccount, Parent.parent_account_id == ParentAccount.id)
                    .where(
                        Parent.id == counterpart.actor_id,
                        or_(
                            ParentAccount.first_name.ilike(pattern, escape="\\"),
                            ParentAccount.last_name.ilike(pattern, escape="\\"),
                            ParentAccount.email.ilike(pattern, escape="\\"),
                            func.concat(
                                ParentAccount.first_name, " ", ParentAccount.last_name
                            ).ilike(pattern, escape="\\"),
                        ),
                    )
                )
                .correlate(counterpart)
            )
            admin_match = (
                exists(
                    select(TenantAdmin.id).where(
                        TenantAdmin.id == counterpart.actor_id,
                        TenantAdmin.email.ilike(pattern, escape="\\"),
                    )
                )
                .correlate(counterpart)
            )
            superadmin_match = (
                exists(
                    select(SuperAdmin.id).where(
                        SuperAdmin.id == counterpart.actor_id,
                        SuperAdmin.email.ilike(pattern, escape="\\"),
                    )
                )
                .correlate(counterpart)
            )
            matching_counterpart = exists(
                select(counterpart.id).where(
                    *counterpart_filters,
                    or_(
                        and_(
                            counterpart.actor_type == CommunicationActorType.STUDENT,
                            student_match,
                        ),
                        and_(
                            counterpart.actor_type == CommunicationActorType.TEACHER,
                            teacher_match,
                        ),
                        and_(
                            counterpart.actor_type == CommunicationActorType.PARENT,
                            parent_match,
                        ),
                        and_(
                            counterpart.actor_type == CommunicationActorType.TENANT_ADMIN,
                            admin_match,
                        ),
                        and_(
                            counterpart.actor_type == CommunicationActorType.SUPERADMIN,
                            superadmin_match,
                        ),
                    ),
                )
            ).correlate(Conversation)
            matching_message = exists(
                select(Message.id).where(
                    Message.conversation_id == Conversation.id,
                    Message.deleted_at.is_(None),
                    Message.body.ilike(pattern, escape="\\"),
                )
            ).correlate(Conversation)
            base = base.where(
                or_(
                    Conversation.subject.ilike(pattern, escape="\\"),
                    matching_counterpart,
                    matching_message,
                )
            )
        if counterpart_type is not None:
            base = base.where(
                exists(select(counterpart.id).where(*counterpart_filters)).correlate(
                    Conversation
                )
            )

        total = int(
            (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        rows = (
            (
                await db.execute(
                    base.options(
                        selectinload(Conversation.participants),
                        selectinload(Conversation.messages),
                    )
                    .order_by(Conversation.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return list(rows), total

    @staticmethod
    async def find_direct_conversation(
        db: AsyncSession,
        *,
        sender_type: CommunicationActorType,
        sender_id: uuid.UUID,
        recipient_type: CommunicationActorType,
        recipient_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
    ) -> Conversation | None:
        participant = ConversationParticipant
        subquery = (
            select(participant.conversation_id)
            .where(
                or_(
                    and_(
                        participant.actor_type == sender_type,
                        participant.actor_id == sender_id,
                    ),
                    and_(
                        participant.actor_type == recipient_type,
                        participant.actor_id == recipient_id,
                    ),
                ),
                participant.left_at.is_(None),
            )
            .group_by(participant.conversation_id)
            .having(func.count(participant.id) == 2)
        )
        stmt = select(Conversation).where(
            Conversation.id.in_(subquery),
            Conversation.closed_at.is_(None),
        )
        if tenant_id is not None:
            stmt = stmt.where(Conversation.tenant_id == tenant_id)
        return (
            (
                await db.execute(
                    stmt.options(
                        selectinload(Conversation.participants),
                        selectinload(Conversation.messages),
                    )
                )
            )
            .unique()
            .scalar_one_or_none()
        )

    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        *,
        actor_type: CommunicationActorType,
        actor_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        status: NotificationStatus | None,
        source_type: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[NotificationDelivery], int, int]:
        filters = [
            NotificationDelivery.recipient_actor_type == actor_type,
            NotificationDelivery.recipient_actor_id == actor_id,
            NotificationDelivery.status != NotificationStatus.DISMISSED,
        ]
        if tenant_id is not None:
            filters.append(
                or_(
                    NotificationDelivery.tenant_id == tenant_id,
                    NotificationDelivery.tenant_id.is_(None),
                )
            )
        if status is not None:
            filters.append(NotificationDelivery.status == status)
        if source_type:
            filters.append(NotificationDelivery.source_type == source_type)
        stmt = select(NotificationDelivery).where(and_(*filters))
        total = int(
            (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        unread_filters = [
            NotificationDelivery.recipient_actor_type == actor_type,
            NotificationDelivery.recipient_actor_id == actor_id,
            NotificationDelivery.status == NotificationStatus.UNREAD,
        ]
        if tenant_id is not None:
            unread_filters.append(
                or_(
                    NotificationDelivery.tenant_id == tenant_id,
                    NotificationDelivery.tenant_id.is_(None),
                )
            )
        if source_type:
            unread_filters.append(NotificationDelivery.source_type == source_type)
        unread = int(
            (
                await db.execute(
                    select(func.count()).select_from(NotificationDelivery).where(*unread_filters)
                )
            ).scalar_one()
        )
        rows = (
            (
                await db.execute(
                    stmt.order_by(NotificationDelivery.delivered_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total, unread

    @staticmethod
    async def get_notification_for_actor(
        db: AsyncSession,
        *,
        notification_id: uuid.UUID,
        actor_type: CommunicationActorType,
        actor_id: uuid.UUID,
    ) -> NotificationDelivery | None:
        return (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == notification_id,
                    NotificationDelivery.recipient_actor_type == actor_type,
                    NotificationDelivery.recipient_actor_id == actor_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_notice(db: AsyncSession, notice_id: uuid.UUID) -> Notice | None:
        return (
            (
                await db.execute(
                    select(Notice)
                    .options(selectinload(Notice.audiences))
                    .where(Notice.id == notice_id)
                )
            )
            .unique()
            .scalar_one_or_none()
        )
