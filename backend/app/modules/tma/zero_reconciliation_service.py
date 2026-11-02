"""Reconciliation of missed TMA zeros without overwriting academic results."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.events import flush_cache_invalidation_events
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import (
    TMADeadlineEligibility,
    TMAAssignmentStatus,
    TMAAssignmentRevision,
    TMAAttempt,
    TMAAttemptStatus,
    TMAParticipant,
    TMAZeroGradingFailure,
)
from app.modules.tma.repository import TMAAssignmentRepository


class TMAZeroReconciliationService:
    @staticmethod
    async def list_conflicts(
        db: AsyncSession, *, actor: TMAAuthor, assignment_id: uuid.UUID
    ) -> list[TMAZeroGradingFailure]:
        assignment = await TMAAssignmentRepository.get_by_id(db, actor.tenant_id, assignment_id)
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        authorized_classes = await TMAAuthorizationService.authorized_classroom_ids(
            db, actor=actor, assignment=assignment
        )
        scope = []
        if authorized_classes is not None:
            revisions = select(TMAAssignmentRevision.id).where(
                TMAAssignmentRevision.tenant_id == actor.tenant_id,
                TMAAssignmentRevision.assignment_id == assignment.id,
                TMAAssignmentRevision.revision_number == assignment.current_revision_number,
            )
            students = union(
                select(TMADeadlineEligibility.student_id).where(
                    TMADeadlineEligibility.tenant_id == actor.tenant_id,
                    TMADeadlineEligibility.revision_id.in_(revisions),
                    TMADeadlineEligibility.class_id.in_(authorized_classes),
                ),
                select(TMAParticipant.student_id).where(
                    TMAParticipant.tenant_id == actor.tenant_id,
                    TMAParticipant.revision_id.in_(revisions),
                    TMAParticipant.class_id.in_(authorized_classes),
                ),
            )
            scope.append(TMAZeroGradingFailure.student_id.in_(students))
        return list(
            (
                await db.execute(
                    select(TMAZeroGradingFailure)
                    .where(
                        *scope,
                        TMAZeroGradingFailure.tenant_id == actor.tenant_id,
                        TMAZeroGradingFailure.assignment_id == assignment_id,
                        TMAZeroGradingFailure.revision_number == assignment.current_revision_number,
                        TMAZeroGradingFailure.resolved_at.is_(None),
                    )
                    .order_by(
                        TMAZeroGradingFailure.last_failed_at,
                        TMAZeroGradingFailure.student_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def exempt(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        student_id: uuid.UUID,
        reason: str,
    ) -> TMAZeroGradingFailure:
        if not isinstance(actor, TenantAdmin):
            raise ForbiddenException("Only the school administrator can exempt a missed TMA.")
        assignment = await TMAAssignmentRepository.get_by_id(
            db, actor.tenant_id, assignment_id, lock=True
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment
        )
        if (
            assignment.status != TMAAssignmentStatus.CLOSED
            or assignment.zero_grading_requested_at is None
            or assignment.zero_grading_completed_at is not None
        ):
            raise ConflictException("There is no pending missed-deadline grading to reconcile.")
        failure = (
            await db.execute(
                select(TMAZeroGradingFailure)
                .where(
                    TMAZeroGradingFailure.tenant_id == actor.tenant_id,
                    TMAZeroGradingFailure.assignment_id == assignment_id,
                    TMAZeroGradingFailure.revision_number == assignment.current_revision_number,
                    TMAZeroGradingFailure.student_id == student_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if failure is None:
            raise NotFoundException("No missed-deadline grading conflict exists for this student.")
        if failure.resolution == "exempt":
            return failure
        if failure.resolved_at is not None:
            raise ConflictException("This student has already been graded or reconciled.")

        existing = (
            await db.execute(
                select(TMAAttempt.id)
                .join(
                    TMAParticipant,
                    and_(
                        TMAParticipant.id == TMAAttempt.participant_id,
                        TMAParticipant.tenant_id == actor.tenant_id,
                    ),
                )
                .join(
                    TMAAssignmentRevision,
                    and_(
                        TMAAssignmentRevision.id == TMAParticipant.revision_id,
                        TMAAssignmentRevision.tenant_id == actor.tenant_id,
                    ),
                )
                .where(
                    TMAAttempt.tenant_id == actor.tenant_id,
                    TMAAssignmentRevision.assignment_id == assignment_id,
                    TMAAssignmentRevision.revision_number == assignment.current_revision_number,
                    TMAParticipant.student_id == student_id,
                    TMAAttempt.status == TMAAttemptStatus.SUBMITTED,
                    TMAAttempt.score_reversed_at.is_(None),
                )
                .limit(1)
            )
        ).first()
        if existing:
            raise ConflictException("A TMA submission already has a score; exemption is unsafe.")

        failure.resolved_at = datetime.now(timezone.utc)
        failure.resolution = "exempt"
        failure.resolution_note = reason.strip()
        failure.resolved_by_actor_id = actor.id
        await db.commit()
        await flush_cache_invalidation_events(db)
        return failure
