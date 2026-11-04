"""Hierarchy-authorized direct messaging service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.communications.enums import (
    CommunicationActorType,
    ConversationType,
    NotificationSourceType,
    NotificationStatus,
)
from app.modules.communications.hierarchy_policy import HierarchyMessagingPolicy
from app.modules.communications.models import (
    Conversation,
    ConversationParticipant,
    Message,
    NotificationDelivery,
)
from app.modules.communications.notification_service import NotificationService
from app.modules.communications.recipient_resolver import (
    ResolvedRecipient,
    actor_tenant_id,
    actor_type_for,
)
from app.modules.communications.repository import CommunicationRepository
from app.modules.realtime.publisher import RealtimePublisher

_MESSAGE_PATHS = {
    CommunicationActorType.SUPERADMIN: "/superadmin/messages",
    CommunicationActorType.TENANT_ADMIN: "/admin/messages",
    CommunicationActorType.TEACHER: "/teacher/messages",
    CommunicationActorType.STUDENT: "/student/messages",
    CommunicationActorType.PARENT: "/parent/messages",
}


def _message_action_path(actor_type: CommunicationActorType, conversation_id: uuid.UUID) -> str:
    base_path = _MESSAGE_PATHS[actor_type]
    return f"{base_path}?conversation={conversation_id}"


class MessagingService:
    @staticmethod
    async def available_recipients(db: AsyncSession, *, actor) -> list[ResolvedRecipient]:
        return await HierarchyMessagingPolicy.available_recipients(db, actor)

    @staticmethod
    async def create_conversation(db: AsyncSession, *, actor, payload) -> Conversation:
        sender_type = actor_type_for(actor)
        sender_tenant_id = actor_tenant_id(actor)
        recipient = await HierarchyMessagingPolicy.resolve_target(db, actor, payload.recipient)
        tenant_id = sender_tenant_id or recipient.tenant_id
        existing = await CommunicationRepository.find_direct_conversation(
            db,
            sender_type=sender_type,
            sender_id=actor.id,
            recipient_type=recipient.actor_type,
            recipient_id=recipient.actor_id,
            tenant_id=tenant_id,
        )
        if existing is not None:
            conversation = existing
            participants = list(conversation.participants)
        else:
            conversation = Conversation(
                tenant_id=tenant_id,
                conversation_type=(
                    ConversationType.SUPPORT
                    if CommunicationActorType.SUPERADMIN in {sender_type, recipient.actor_type}
                    else ConversationType.DIRECT
                ),
                created_by_actor_type=sender_type,
                created_by_actor_id=actor.id,
                subject=payload.subject,
            )
            db.add(conversation)
            await db.flush()
            participants = [
                ConversationParticipant(
                    conversation_id=conversation.id,
                    tenant_id=sender_tenant_id,
                    actor_type=sender_type,
                    actor_id=actor.id,
                ),
                ConversationParticipant(
                    conversation_id=conversation.id,
                    tenant_id=recipient.tenant_id,
                    actor_type=recipient.actor_type,
                    actor_id=recipient.actor_id,
                ),
            ]
            db.add_all(participants)
            await db.flush()
        await MessagingService._append_message(
            db,
            actor=actor,
            conversation=conversation,
            participants=participants,
            body=payload.body,
            notify=True,
            enforce_current_relationship=False,
        )
        return await CommunicationRepository.get_conversation_for_actor(
            db,
            conversation_id=conversation.id,
            actor_type=sender_type,
            actor_id=actor.id,
            tenant_id=sender_tenant_id,
        )

    @staticmethod
    async def list_conversations(
        db: AsyncSession, *, actor, offset: int, limit: int,
        search: str | None = None,
        counterpart_type: CommunicationActorType | None = None,
    ):
        return await CommunicationRepository.list_conversations_for_actor(
            db,
            actor_type=actor_type_for(actor),
            actor_id=actor.id,
            tenant_id=actor_tenant_id(actor),
            offset=offset,
            limit=limit,
            search=search,
            counterpart_type=counterpart_type,
        )

    @staticmethod
    async def get_conversation(
        db: AsyncSession, *, actor, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await CommunicationRepository.get_conversation_for_actor(
            db,
            conversation_id=conversation_id,
            actor_type=actor_type_for(actor),
            actor_id=actor.id,
            tenant_id=actor_tenant_id(actor),
        )
        if conversation is None:
            raise NotFoundException("Conversation not found")
        return conversation

    @staticmethod
    async def can_reply(db: AsyncSession, *, actor, conversation: Conversation) -> bool:
        if conversation.closed_at is not None:
            return False
        return await HierarchyMessagingPolicy.can_continue_conversation(db, actor, conversation)

    @staticmethod
    async def _append_message(
        db: AsyncSession,
        *,
        actor,
        conversation: Conversation,
        body: str,
        notify: bool = True,
        participants: list[ConversationParticipant] | None = None,
        enforce_current_relationship: bool = True,
    ) -> Message:
        sender_type = actor_type_for(actor)
        active_participants = (
            participants if participants is not None else list(conversation.participants)
        )
        sender_participant = next(
            (
                participant
                for participant in active_participants
                if participant.actor_type == sender_type
                and participant.actor_id == actor.id
                and participant.left_at is None
            ),
            None,
        )
        if sender_participant is None:
            raise ForbiddenException("You are not a participant in this conversation")
        if conversation.closed_at is not None:
            raise ForbiddenException("This conversation is closed")
        if enforce_current_relationship:
            await HierarchyMessagingPolicy.ensure_can_continue_conversation(
                db,
                actor,
                conversation,
            )

        message = Message(
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            sender_actor_type=sender_type,
            sender_actor_id=actor.id,
            body=body,
        )
        db.add(message)
        conversation.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(message)
        sender_participant.last_read_message_id = message.id

        recipients = [
            ResolvedRecipient(
                actor_type=participant.actor_type,
                actor_id=participant.actor_id,
                tenant_id=participant.tenant_id,
                label="Conversation participant",
            )
            for participant in active_participants
            if not (participant.actor_type == sender_type and participant.actor_id == actor.id)
            and participant.left_at is None
        ]
        if notify:
            for recipient in recipients:
                await NotificationService.deliver(
                    db,
                    recipients=[recipient],
                    source_type=NotificationSourceType.MESSAGE,
                    source_id=message.id,
                    title="New direct message",
                    preview=body,
                    action_path=_message_action_path(recipient.actor_type, conversation.id),
                    tenant_id=conversation.tenant_id,
                )

        created_at = getattr(message, "created_at", None) or datetime.now(timezone.utc)
        realtime_payload = {
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "sender_actor_type": sender_type.value,
            "sender_actor_id": str(actor.id),
            "body": message.body,
            "created_at": created_at.isoformat(),
        }
        for participant in active_participants:
            if participant.left_at is not None:
                continue
            RealtimePublisher.defer_to_actor(
                db,
                event_type="message.created",
                actor_type=participant.actor_type.value,
                actor_id=participant.actor_id,
                tenant_id=participant.tenant_id,
                data=realtime_payload,
            )

        return message

    @staticmethod
    async def add_message(
        db: AsyncSession,
        *,
        actor,
        conversation_id: uuid.UUID,
        body: str,
        notify: bool = True,
    ) -> Message:
        conversation = await MessagingService.get_conversation(
            db, actor=actor, conversation_id=conversation_id
        )
        return await MessagingService._append_message(
            db, actor=actor, conversation=conversation, body=body, notify=notify
        )

    @staticmethod
    async def mark_read(db: AsyncSession, *, actor, conversation_id: uuid.UUID) -> Conversation:
        conversation = await MessagingService.get_conversation(
            db, actor=actor, conversation_id=conversation_id
        )
        latest = max(
            (message for message in conversation.messages if message.deleted_at is None),
            key=lambda item: item.created_at,
            default=None,
        )
        current_actor_type = actor_type_for(actor)
        if latest is not None:
            for participant in conversation.participants:
                if (
                    participant.actor_type == current_actor_type
                    and participant.actor_id == actor.id
                    and participant.left_at is None
                ):
                    participant.last_read_message_id = latest.id
            message_ids = [
                message.id for message in conversation.messages if message.deleted_at is None
            ]
            if message_ids:
                await db.execute(
                    update(NotificationDelivery)
                    .where(
                        NotificationDelivery.recipient_actor_type == current_actor_type,
                        NotificationDelivery.recipient_actor_id == actor.id,
                        NotificationDelivery.source_type == NotificationSourceType.MESSAGE,
                        NotificationDelivery.source_id.in_(message_ids),
                        NotificationDelivery.status == NotificationStatus.UNREAD,
                    )
                    .values(
                        status=NotificationStatus.READ,
                        read_at=datetime.now(timezone.utc),
                    )
                )
        await db.flush()

        for participant in conversation.participants:
            if participant.left_at is not None:
                continue
            RealtimePublisher.defer_to_actor(
                db,
                event_type="message.read",
                actor_type=participant.actor_type.value,
                actor_id=participant.actor_id,
                tenant_id=participant.tenant_id,
                data={
                    "conversation_id": str(conversation.id),
                    "reader_actor_type": current_actor_type.value,
                    "reader_actor_id": str(actor.id),
                    "last_read_message_id": str(latest.id) if latest is not None else None,
                },
            )
        return conversation
