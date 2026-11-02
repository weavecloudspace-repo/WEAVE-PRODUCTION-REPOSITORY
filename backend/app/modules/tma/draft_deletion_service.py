"""Permanently remove never-published TMA drafts and retry storage cleanup.

SQL deletion is atomic. Media objects are queued in the same transaction and
removed later, so an R2 outage cannot break database consistency.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.events import (
    flush_cache_invalidation_events,
    queue_cache_key_invalidation,
)
from app.core.exceptions import ConflictException, NotFoundException
from app.core.storage.factory import get_media_storage
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.cache import generation_key
from app.modules.tma.models import (
    TMAAssignment,
    TMAAssignmentRevision,
    TMAAssignmentStatus,
    TMAAttempt,
    TMACancellationRun,
    TMADraftMediaCleanup,
    TMAMediaAsset,
    TMAParticipant,
    TMAQuestion,
    TMAQuestionOption,
)
from app.modules.tma.repository import TMAAssignmentRepository

logger = logging.getLogger(__name__)


class TMADraftDeletionService:
    @staticmethod
    async def delete_draft(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> None:
        """Delete only Revision 1 drafts without any published/student history."""
        assignment = await TMAAssignmentRepository.get_by_id(
            db, actor.tenant_id, assignment_id, lock=True
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        if (
            assignment.status != TMAAssignmentStatus.DRAFT
            or assignment.current_revision_number != 1
            or assignment.activated_at is not None
            or assignment.closed_at is not None
            or getattr(assignment, "zero_grading_requested_at", None) is not None
        ):
            raise ConflictException("Only an original, never-published draft TMA can be deleted.")
        revisions = list(
            (
                await db.execute(
                    select(TMAAssignmentRevision).where(
                        TMAAssignmentRevision.tenant_id == actor.tenant_id,
                        TMAAssignmentRevision.assignment_id == assignment_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if (
            len(revisions) != 1
            or revisions[0].revision_number != 1
            or revisions[0].published_at is not None
            or revisions[0].invalidated_at is not None
        ):
            raise ConflictException("Assignment revision history cannot be permanently deleted.")
        participant_exists = (
            await db.execute(
                select(TMAParticipant.id)
                .where(
                    TMAParticipant.tenant_id == actor.tenant_id,
                    TMAParticipant.revision_id == revisions[0].id,
                )
                .limit(1)
            )
        ).first()
        cancellation_exists = (
            await db.execute(
                select(TMACancellationRun.id)
                .where(
                    TMACancellationRun.tenant_id == actor.tenant_id,
                    TMACancellationRun.assignment_id == assignment_id,
                )
                .limit(1)
            )
        ).first()
        # A participant implies the possibility of attempts, answer data and
        # academic score provenance; reject rather than deleting student work.
        if participant_exists or cancellation_exists:
            raise ConflictException(
                "This TMA contains student or cancellation history and cannot be deleted."
            )

        media = list(
            (
                await db.execute(
                    select(TMAMediaAsset.object_key).where(
                        TMAMediaAsset.tenant_id == actor.tenant_id,
                        TMAMediaAsset.assignment_id == assignment_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        try:
            db.add_all(
                [
                    TMADraftMediaCleanup(
                        tenant_id=actor.tenant_id,
                        assignment_id=assignment_id,
                        object_key=object_key,
                    )
                    for object_key in media
                ]
            )
            await db.flush()
            for model in (TMAQuestionOption, TMAQuestion, TMAMediaAsset):
                await db.execute(
                    delete(model).where(
                        model.tenant_id == actor.tenant_id,
                        model.assignment_id == assignment_id,
                    )
                )
            await db.execute(
                delete(TMAAssignmentRevision).where(
                    TMAAssignmentRevision.tenant_id == actor.tenant_id,
                    TMAAssignmentRevision.assignment_id == assignment_id,
                )
            )
            await db.execute(
                delete(TMAAssignment).where(
                    TMAAssignment.tenant_id == actor.tenant_id,
                    TMAAssignment.id == assignment_id,
                    TMAAssignment.status == TMAAssignmentStatus.DRAFT,
                )
            )
            queue_cache_key_invalidation(db, generation_key(actor.tenant_id))
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Assignment has dependent records and cannot be deleted."
            ) from exc
        except Exception:
            await db.rollback()
            raise
        await flush_cache_invalidation_events(db)

    @staticmethod
    async def cleanup_media(db: AsyncSession, *, limit: int = 12) -> dict[str, int]:
        """Retry durable R2 deletions without losing failed cleanup records."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        pending = list(
            (
                await db.execute(
                    select(TMADraftMediaCleanup)
                    .order_by(
                        TMADraftMediaCleanup.attempts,
                        TMADraftMediaCleanup.created_at,
                        TMADraftMediaCleanup.id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        deleted = failed = 0
        for item in pending:
            try:
                await get_media_storage().delete_object(object_key=item.object_key)
            except Exception as exc:
                item.attempts += 1
                item.last_error = str(exc)[:1000]
                failed += 1
                logger.warning(
                    "tma.draft_media_cleanup.retry",
                    extra={
                        "tenant_id": str(item.tenant_id),
                        "assignment_id": str(item.assignment_id),
                        "cleanup_id": str(item.id),
                        "attempts": item.attempts,
                    },
                    exc_info=True,
                )
            else:
                await db.delete(item)
                deleted += 1
        if pending:
            await db.commit()
        return {"deleted": deleted, "failed": failed}
