"""Revision deadline snapshots and bounded pending-zero queries."""

from __future__ import annotations

import uuid
from sqlalchemy import and_, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ConflictException
from app.modules.students.models import StudentEnrollment
from app.modules.tma.models import (
    TMADeadlineEligibility,
    TMAAttempt,
    TMAParticipant,
    TMAAttemptStatus,
    TMAZeroGradingFailure,
)


class TMADeadlineEligibilityRepository:
    @staticmethod
    async def capture(db: AsyncSession, *, tenant_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
        captured = (
            await db.execute(
                text("SELECT public.tma_capture_deadline(:tenant, :assignment)"),
                {"tenant": tenant_id, "assignment": assignment_id},
            )
        ).scalar_one()
        if not captured:
            raise ConflictException(
                "Deadline eligibility predates reliable tracking; administrator review is required."
            )

    @staticmethod
    async def enrollment(
        db: AsyncSession, *, tenant_id: uuid.UUID, revision_id: uuid.UUID, student_id: uuid.UUID
    ):
        return (
            await db.execute(
                select(StudentEnrollment, TMADeadlineEligibility.subject_id)
                .join(
                    TMADeadlineEligibility,
                    and_(
                        TMADeadlineEligibility.tenant_id == StudentEnrollment.tenant_id,
                        TMADeadlineEligibility.student_enrollment_id == StudentEnrollment.id,
                    ),
                )
                .where(
                    TMADeadlineEligibility.tenant_id == tenant_id,
                    TMADeadlineEligibility.revision_id == revision_id,
                    TMADeadlineEligibility.student_id == student_id,
                )
            )
        ).one_or_none()

    @staticmethod
    async def pending(db: AsyncSession, *, assignment, revision_id: uuid.UUID, limit: int):
        roster = TMADeadlineEligibility
        # An uncorrelated tenant/revision set lets PostgreSQL hash the submitted
        # IDs once. A per-roster correlated join degenerates badly on fresh stats.
        submitted = (
            select(TMAParticipant.student_id)
            .join(
                TMAAttempt,
                and_(
                    TMAAttempt.participant_id == TMAParticipant.id,
                    TMAAttempt.tenant_id == assignment.tenant_id,
                    TMAAttempt.revision_id == revision_id,
                    TMAAttempt.status == TMAAttemptStatus.SUBMITTED,
                ),
            )
            .where(
                TMAParticipant.tenant_id == assignment.tenant_id,
                TMAParticipant.revision_id == revision_id,
            )
        )
        failure = TMAZeroGradingFailure
        return list(
            (
                await db.execute(
                    select(roster.student_id, failure)
                    .outerjoin(
                        failure,
                        and_(
                            failure.tenant_id == roster.tenant_id,
                            failure.assignment_id == assignment.id,
                            failure.revision_number == assignment.current_revision_number,
                            failure.student_id == roster.student_id,
                        ),
                    )
                    .where(
                        roster.tenant_id == assignment.tenant_id,
                        roster.revision_id == revision_id,
                        roster.student_id.not_in(submitted),
                        failure.resolution.is_(None) | (failure.resolution != "exempt"),
                    )
                    .order_by(failure.last_failed_at.asc().nullsfirst(), roster.student_id)
                    .limit(limit)
                )
            ).all()
        )
