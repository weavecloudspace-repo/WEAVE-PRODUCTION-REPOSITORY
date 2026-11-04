"""Hierarchy-aware message, inbox, notice, and notification routes."""

from __future__ import annotations

import uuid
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    CurrentActor,
    get_current_actor,
    get_current_parent,
    get_current_student,
    get_current_superadmin,
    get_current_teacher,
    get_current_tenant_admin,
)
from app.core.exceptions import ForbiddenException
from app.modules.communications.enums import (
    CommunicationActorType,
    NoticeStatus,
    NotificationSourceType,
    NotificationStatus,
)
from app.modules.communications.messaging_service import MessagingService
from app.modules.communications.notice_service import NoticeService
from app.modules.communications.notification_service import NotificationService
from app.modules.communications.recipient_resolver import actor_type_for
from app.modules.communications.schemas import (
    AvailableRecipientGroup,
    AvailableRecipientsResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationParticipantResponse,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
    NoticeCreate,
    NoticeListResponse,
    NoticePublishRequest,
    NoticeResponse,
    NoticeUpdate,
    NotificationListResponse,
    NotificationResponse,
    ReceivedNoticeListResponse,
    ReceivedNoticeResponse,
    RecipientPreviewResponse,
    UnreadCountResponse,
)
from app.modules.parents.models import Parent, ParentAccount
from app.modules.students.models import Student
from app.modules.superadmin.models import SuperAdmin
from app.modules.teachers.models import Teacher, TeacherAccount
from app.modules.tenant_admins.models import TenantAdmin

router = APIRouter(prefix="/communications", tags=["Communications"])
messages_router = APIRouter(prefix="/messages", tags=["Messages"])
inbox_router = APIRouter(prefix="/inbox", tags=["Inbox"])
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])
notices_router = APIRouter(prefix="/notices", tags=["Notices"])
superadmin_notice_router = APIRouter(prefix="/superadmin/notices", tags=["Superadmin Notices"])
tenant_admin_notice_router = APIRouter(
    prefix="/tenant-admin/notices", tags=["Tenant Admin Notices"]
)
teacher_notice_router = APIRouter(prefix="/teacher/notices", tags=["Teacher Notices"])

CurrentCommunicationActor: TypeAlias = Annotated[CurrentActor, Depends(get_current_actor)]


async def _active_communication_actor(actor: CurrentCommunicationActor, db: DbSession):
    if isinstance(actor, SuperAdmin):
        return await get_current_superadmin(actor)
    if isinstance(actor, TenantAdmin):
        return await get_current_tenant_admin(actor, db)
    if isinstance(actor, Teacher):
        return await get_current_teacher(actor, db)
    if isinstance(actor, Parent):
        return await get_current_parent(actor, db)
    if isinstance(actor, Student):
        return await get_current_student(actor, db)
    raise ForbiddenException("A tenant membership or superadmin session is required")


def _name(*parts: str | None, fallback: str = "Unknown") -> str:
    value = " ".join(part for part in parts if part).strip()
    return value or fallback


def _label_with_identifier(name: str, identifier: str | None) -> str:
    return f"{name} - {identifier}" if identifier else name


async def _participant_labels(
    db: DbSession, participants
) -> dict[tuple[CommunicationActorType, uuid.UUID], str]:
    ids_by_type: dict[CommunicationActorType, set[uuid.UUID]] = {}
    for participant in participants:
        kind = (
            participant.actor_type
            if isinstance(participant.actor_type, CommunicationActorType)
            else CommunicationActorType(participant.actor_type)
        )
        ids_by_type.setdefault(kind, set()).add(participant.actor_id)

    labels: dict[tuple[CommunicationActorType, uuid.UUID], str] = {}
    student_ids = ids_by_type.get(CommunicationActorType.STUDENT, set())
    if student_ids:
        rows = (
            (await db.execute(select(Student).where(Student.id.in_(student_ids)))).scalars().all()
        )
        for row in rows:
            labels[(CommunicationActorType.STUDENT, row.id)] = _label_with_identifier(
                _name(row.first_name, row.last_name, fallback=row.admission_number),
                row.admission_number,
            )

    teacher_ids = ids_by_type.get(CommunicationActorType.TEACHER, set())
    if teacher_ids:
        rows = (
            await db.execute(
                select(
                    Teacher.id,
                    Teacher.staff_id,
                    TeacherAccount.first_name,
                    TeacherAccount.last_name,
                    TeacherAccount.email,
                )
                .join(TeacherAccount, Teacher.teacher_account_id == TeacherAccount.id)
                .where(Teacher.id.in_(teacher_ids))
            )
        ).all()
        for row in rows:
            labels[(CommunicationActorType.TEACHER, row.id)] = _label_with_identifier(
                _name(row.first_name, row.last_name, fallback=row.email), row.staff_id
            )

    parent_ids = ids_by_type.get(CommunicationActorType.PARENT, set())
    if parent_ids:
        rows = (
            await db.execute(
                select(
                    Parent.id,
                    ParentAccount.first_name,
                    ParentAccount.last_name,
                    ParentAccount.email,
                )
                .join(ParentAccount, Parent.parent_account_id == ParentAccount.id)
                .where(Parent.id.in_(parent_ids))
            )
        ).all()
        for row in rows:
            labels[(CommunicationActorType.PARENT, row.id)] = _label_with_identifier(
                _name(row.first_name, row.last_name, fallback=row.email), row.email
            )

    admin_ids = ids_by_type.get(CommunicationActorType.TENANT_ADMIN, set())
    if admin_ids:
        rows = (
            (await db.execute(select(TenantAdmin).where(TenantAdmin.id.in_(admin_ids))))
            .scalars()
            .all()
        )
        for row in rows:
            labels[(CommunicationActorType.TENANT_ADMIN, row.id)] = row.email

    superadmin_ids = ids_by_type.get(CommunicationActorType.SUPERADMIN, set())
    if superadmin_ids:
        rows = (
            (await db.execute(select(SuperAdmin).where(SuperAdmin.id.in_(superadmin_ids))))
            .scalars()
            .all()
        )
        for row in rows:
            labels[(CommunicationActorType.SUPERADMIN, row.id)] = row.email
    return labels


async def _conversation_response(
    db: DbSession, conversation, current_actor
) -> ConversationResponse:
    labels = await _participant_labels(db, conversation.participants)
    response = ConversationResponse.model_validate(conversation)
    response.participants = [
        ConversationParticipantResponse.model_validate(participant).model_copy(
            update={
                "label": labels.get(
                    (
                        participant.actor_type
                        if isinstance(participant.actor_type, CommunicationActorType)
                        else CommunicationActorType(participant.actor_type),
                        participant.actor_id,
                    )
                ),
                "group_label": str(
                    participant.actor_type.value
                    if hasattr(participant.actor_type, "value")
                    else participant.actor_type
                ).replace("_", " "),
            }
        )
        for participant in conversation.participants
    ]
    current_type = actor_type_for(current_actor)
    current_participant = next(
        (
            item
            for item in conversation.participants
            if item.actor_type == current_type
            and item.actor_id == current_actor.id
            and item.left_at is None
        ),
        None,
    )
    visible = [item for item in conversation.messages if item.deleted_at is None]
    start = 0
    if current_participant is not None and current_participant.last_read_message_id is not None:
        for index, message in enumerate(visible):
            if message.id == current_participant.last_read_message_id:
                start = index + 1
                break
    response.unread_count = sum(
        1
        for message in visible[start:]
        if not (
            message.sender_actor_type == current_type
            and message.sender_actor_id == current_actor.id
        )
    )
    response.can_reply = await MessagingService.can_reply(
        db, actor=current_actor, conversation=conversation
    )
    response.read_only_reason = (
        None
        if response.can_reply
        else "This conversation is historical. The current school relationship no longer permits replies."
    )
    return response


@router.get("/available-recipients", response_model=AvailableRecipientsResponse)
async def available_recipients(
    db: DbSession, actor: CurrentCommunicationActor
) -> AvailableRecipientsResponse:
    current = await _active_communication_actor(actor, db)
    recipients = await MessagingService.available_recipients(db, actor=current)
    groups: dict[str, list] = {}
    for recipient in recipients:
        groups.setdefault(recipient.group_label or "Recipients", []).append(recipient.as_schema())
    return AvailableRecipientsResponse(
        groups=[
            AvailableRecipientGroup(label=label, recipients=items)
            for label, items in groups.items()
        ]
    )


@messages_router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    db: DbSession,
    actor: CurrentCommunicationActor,
    search: str | None = Query(default=None, max_length=100),
    counterpart_type: CommunicationActorType | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationListResponse:
    current = await _active_communication_actor(actor, db)
    items, total = await MessagingService.list_conversations(
        db, actor=current, offset=skip, limit=limit,
        search=search, counterpart_type=counterpart_type
    )
    responses = [await _conversation_response(db, item, current) for item in items]
    return ConversationListResponse(
        items=responses,
        total=total,
        unread_count=sum(item.unread_count for item in responses),
    )


@messages_router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate, db: DbSession, actor: CurrentCommunicationActor
) -> ConversationResponse:
    current = await _active_communication_actor(actor, db)
    conversation = await MessagingService.create_conversation(db, actor=current, payload=payload)
    return await _conversation_response(db, conversation, current)


@messages_router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> ConversationResponse:
    current = await _active_communication_actor(actor, db)
    conversation = await MessagingService.get_conversation(
        db, actor=current, conversation_id=conversation_id
    )
    return await _conversation_response(db, conversation, current)


@messages_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: DbSession,
    actor: CurrentCommunicationActor,
) -> MessageResponse:
    current = await _active_communication_actor(actor, db)
    message = await MessagingService.add_message(
        db, actor=current, conversation_id=conversation_id, body=payload.body
    )
    return MessageResponse.model_validate(message)


@messages_router.post("/conversations/{conversation_id}/read", response_model=ConversationResponse)
async def mark_conversation_read(
    conversation_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> ConversationResponse:
    current = await _active_communication_actor(actor, db)
    conversation = await MessagingService.mark_read(
        db, actor=current, conversation_id=conversation_id
    )
    return await _conversation_response(db, conversation, current)


@inbox_router.get("", response_model=NotificationListResponse)
async def list_inbox(
    db: DbSession,
    actor: CurrentCommunicationActor,
    status_filter: NotificationStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> NotificationListResponse:
    current = await _active_communication_actor(actor, db)
    items, total, unread = await NotificationService.list_for_actor(
        db,
        actor=current,
        status=status_filter,
        source_type=None,
        offset=skip,
        limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in items],
        total=total,
        unread_count=unread,
    )


@inbox_router.get("/unread-count", response_model=UnreadCountResponse)
async def inbox_unread_count(
    db: DbSession, actor: CurrentCommunicationActor
) -> UnreadCountResponse:
    current = await _active_communication_actor(actor, db)
    _, _, unread = await NotificationService.list_for_actor(
        db,
        actor=current,
        status=None,
        source_type=None,
        offset=0,
        limit=1,
    )
    return UnreadCountResponse(unread_count=unread)


@inbox_router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_inbox_item_read(
    notification_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NotificationService.get_for_actor(
        db, actor=current, notification_id=notification_id
    )
    delivery = await NotificationService.update_status(
        db,
        actor=current,
        notification_id=notification_id,
        status=NotificationStatus.READ,
    )
    return NotificationResponse.model_validate(delivery)


@notifications_router.get("", response_model=NotificationListResponse)
async def list_notifications(
    db: DbSession,
    actor: CurrentCommunicationActor,
    status_filter: NotificationStatus | None = Query(default=None, alias="status"),
    source_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> NotificationListResponse:
    current = await _active_communication_actor(actor, db)
    items, total, unread = await NotificationService.list_for_actor(
        db,
        actor=current,
        status=status_filter,
        source_type=source_type,
        offset=skip,
        limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in items],
        total=total,
        unread_count=unread,
    )


@notifications_router.get("/unread-count", response_model=UnreadCountResponse)
async def notification_unread_count(
    db: DbSession, actor: CurrentCommunicationActor
) -> UnreadCountResponse:
    current = await _active_communication_actor(actor, db)
    _, _, unread = await NotificationService.list_for_actor(
        db, actor=current, status=None, source_type=None, offset=0, limit=1
    )
    return UnreadCountResponse(unread_count=unread)


@notifications_router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NotificationService.get_for_actor(
        db, actor=current, notification_id=notification_id
    )
    return NotificationResponse.model_validate(delivery)


@notifications_router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NotificationService.update_status(
        db, actor=current, notification_id=notification_id, status=NotificationStatus.READ
    )
    return NotificationResponse.model_validate(delivery)


@notifications_router.post("/{notification_id}/acknowledge", response_model=NotificationResponse)
async def acknowledge_notification(
    notification_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NotificationService.update_status(
        db,
        actor=current,
        notification_id=notification_id,
        status=NotificationStatus.ACKNOWLEDGED,
    )
    return NotificationResponse.model_validate(delivery)


@notifications_router.delete("/{notification_id}", response_model=NotificationResponse)
async def dismiss_notification(
    notification_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NotificationService.update_status(
        db,
        actor=current,
        notification_id=notification_id,
        status=NotificationStatus.DISMISSED,
    )
    return NotificationResponse.model_validate(delivery)


@notices_router.get("", response_model=ReceivedNoticeListResponse)
async def list_received_notices(
    db: DbSession,
    actor: CurrentCommunicationActor,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ReceivedNoticeListResponse:
    current = await _active_communication_actor(actor, db)
    rows, total, unread = await NoticeService.list_received(
        db, actor=current, offset=skip, limit=limit
    )
    return ReceivedNoticeListResponse(
        items=[
            ReceivedNoticeResponse(
                id=notice.id,
                tenant_id=notice.tenant_id,
                created_by_actor_type=notice.created_by_actor_type,
                created_by_actor_id=notice.created_by_actor_id,
                title=notice.title,
                body=notice.body,
                category=notice.category,
                priority=notice.priority,
                publish_at=notice.publish_at,
                expires_at=notice.expires_at,
                is_pinned=notice.is_pinned,
                delivery_id=delivery.id,
                delivery_status=delivery.status,
                delivered_at=delivery.delivered_at,
                read_at=delivery.read_at,
            )
            for notice, delivery in rows
        ],
        total=total,
        unread_count=unread,
    )


@notices_router.post("/{notice_id}/read", response_model=NotificationResponse)
async def mark_notice_read(
    notice_id: uuid.UUID, db: DbSession, actor: CurrentCommunicationActor
) -> NotificationResponse:
    current = await _active_communication_actor(actor, db)
    delivery = await NoticeService.mark_received_read(db, actor=current, notice_id=notice_id)
    return NotificationResponse.model_validate(delivery)


def _install_notice_management_routes(management_router: APIRouter, actor_dependency):
    @management_router.post("", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
    async def create_notice(payload: NoticeCreate, db: DbSession, actor=Depends(actor_dependency)):
        return NoticeResponse.model_validate(
            await NoticeService.create(db, actor=actor, payload=payload)
        )

    @management_router.get("", response_model=NoticeListResponse)
    async def list_notices(
        db: DbSession,
        actor=Depends(actor_dependency),
        status_filter: NoticeStatus | None = Query(default=None, alias="status"),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        items, total = await NoticeService.list_manageable(
            db, actor=actor, status=status_filter, offset=skip, limit=limit
        )
        return NoticeListResponse(
            items=[NoticeResponse.model_validate(item) for item in items], total=total
        )

    @management_router.post("/preview", response_model=RecipientPreviewResponse)
    async def preview_notice(payload: NoticeCreate, db: DbSession, actor=Depends(actor_dependency)):
        label, recipients, excluded = await NoticeService.preview(
            db, actor=actor, audiences=payload.audiences
        )
        return RecipientPreviewResponse(
            audience_label=label,
            recipient_count=len(recipients),
            excluded_count=len(excluded),
            excluded_reasons=excluded,
            recipients=[item.as_schema() for item in recipients[:50]],
        )

    @management_router.patch("/{notice_id}", response_model=NoticeResponse)
    async def update_notice(
        notice_id: uuid.UUID,
        payload: NoticeUpdate,
        db: DbSession,
        actor=Depends(actor_dependency),
    ):
        return NoticeResponse.model_validate(
            await NoticeService.update(db, actor=actor, notice_id=notice_id, payload=payload)
        )

    @management_router.post("/{notice_id}/publish", response_model=NoticeResponse)
    async def publish_notice(
        notice_id: uuid.UUID,
        payload: NoticePublishRequest,
        db: DbSession,
        actor=Depends(actor_dependency),
    ):
        return NoticeResponse.model_validate(
            await NoticeService.publish(
                db, actor=actor, notice_id=notice_id, publish_at=payload.publish_at
            )
        )

    @management_router.post("/{notice_id}/archive", response_model=NoticeResponse)
    async def archive_notice(notice_id: uuid.UUID, db: DbSession, actor=Depends(actor_dependency)):
        return NoticeResponse.model_validate(
            await NoticeService.archive(db, actor=actor, notice_id=notice_id)
        )

    @management_router.post("/{notice_id}/cancel", response_model=NoticeResponse)
    async def cancel_notice(notice_id: uuid.UUID, db: DbSession, actor=Depends(actor_dependency)):
        return NoticeResponse.model_validate(
            await NoticeService.cancel(db, actor=actor, notice_id=notice_id)
        )


_install_notice_management_routes(superadmin_notice_router, get_current_superadmin)
_install_notice_management_routes(tenant_admin_notice_router, get_current_tenant_admin)
_install_notice_management_routes(teacher_notice_router, get_current_teacher)
