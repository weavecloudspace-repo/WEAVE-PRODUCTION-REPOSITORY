"""Process missed TMA deadlines in bounded, auditable, retry-safe batches.

Zero marks use the ordinary TMA submission provenance (attempt -> component
score). Staff-edited/approved components are never replaced. A failed student
does not prevent unrelated students from receiving their scores.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tma.authorization import TMAAuthorizationService
from app.config.settings import settings
from app.modules.tma.deadline_eligibility_repository import TMADeadlineEligibilityRepository
from app.core.cache.events import flush_cache_invalidation_events
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException
from app.modules.tma.grading_service import TMAGradingService
from app.modules.tma.models import (
    TMAAssignment,
    TMAAssignmentStatus,
    TMAAttemptStatus,
    TMAParticipant,
    TMAZeroGradingFailure,
)
from app.modules.tma.repository import (
    TMAAttemptRepository,
    TMAParticipantRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)

logger = logging.getLogger(__name__)


class TMADeadlineZeroService:
    """One locked assignment and a bounded number of student transactions."""

    MAX_WRITES = settings.TMA_ZERO_BATCH_SIZE

    @classmethod
    async def _write_zero(
        cls,
        db: AsyncSession,
        *,
        assignment: TMAAssignment,
        revision_id: uuid.UUID,
        student_id: uuid.UUID,
        total_questions: int,
        current: datetime,
    ) -> bool:
        tenant_id = assignment.tenant_id
        historical = await TMADeadlineEligibilityRepository.enrollment(
            db, tenant_id=tenant_id, revision_id=revision_id, student_id=student_id
        )
        if historical is None:
            raise ConflictException("Student was not eligible at this revision's deadline.")
        enrollment, subject_id = historical
        participant = await TMAParticipantRepository.get_by_revision_student(
            db, tenant_id, revision_id, student_id
        )
        if participant is None:
            await TMAParticipantRepository.insert_missing(
                db,
                tenant_id,
                [
                    TMAParticipant(
                        tenant_id=tenant_id,
                        revision_id=revision_id,
                        student_id=student_id,
                        student_enrollment_id=enrollment.id,
                        class_id=enrollment.class_id,
                    )
                ],
            )
            participant = await TMAParticipantRepository.get_by_revision_student(
                db, tenant_id, revision_id, student_id
            )
        if participant is None:
            raise ConflictException("Unable to register missed TMA participation.")
        attempt = await TMAAttemptRepository.create_if_missing(
            db, tenant_id, participant.id, revision_id
        )
        if attempt.status == TMAAttemptStatus.SUBMITTED:
            return False
        # This writes a genuine 0 CA component and captures the exact score ID
        # on the attempt for the existing cancellation worker to reverse.
        await TMAGradingService.persist_component_score(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            enrollment=enrollment,
            assignment=assignment,
            correct=0,
            total=total_questions,
            attempt=attempt,
            scoring_date=assignment.closes_at.date(),
            deadline_subject_id=subject_id,
        )
        attempt.status = TMAAttemptStatus.SUBMITTED
        graded_at = datetime.now(timezone.utc)
        attempt.submitted_at = graded_at
        attempt.correct_answers = 0
        attempt.total_questions = total_questions
        attempt.auto_zeroed_at = graded_at
        await TMAAttemptRepository.save(db, attempt)
        return True

    @classmethod
    async def process_pending(
        cls,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        tenant_ids: set[uuid.UUID] | None = None,
    ) -> dict[str, int]:
        current = now or datetime.now(timezone.utc)
        # Existing CLOSED TMAs are not backfilled: only assignments closed by
        # the new deadline-aware lifecycle receive a requested timestamp.
        tenant_turn = (
            select(
                TMAAssignment.tenant_id.label("tenant_id"),
                func.max(TMAAssignment.zero_grading_last_processed_at).label("last_processed"),
            )
            .group_by(TMAAssignment.tenant_id)
            .subquery()
        )
        assignment = (
            await db.execute(
                select(TMAAssignment)
                .join(tenant_turn, tenant_turn.c.tenant_id == TMAAssignment.tenant_id)
                .where(
                    *([TMAAssignment.tenant_id.in_(tenant_ids)] if tenant_ids is not None else []),
                    TMAAssignment.status == TMAAssignmentStatus.CLOSED,
                    TMAAssignment.zero_grading_requested_at.is_not(None),
                    TMAAssignment.zero_grading_completed_at.is_(None),
                    TMAAssignment.closes_at.is_not(None),
                    TMAAssignment.closes_at <= current,
                )
                .order_by(
                    tenant_turn.c.last_processed.asc().nullsfirst(),
                    TMAAssignment.zero_grading_last_processed_at.asc().nullsfirst(),
                    TMAAssignment.zero_grading_requested_at,
                    TMAAssignment.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True, of=TMAAssignment)
            )
        ).scalar_one_or_none()
        if assignment is None:
            return {"zeroed": 0, "blocked": 0, "pending": 0}

        try:
            revision = await TMARevisionRepository.get_by_number(
                db, assignment.tenant_id, assignment.id, assignment.current_revision_number
            )
            if (
                revision is None
                or revision.published_at is None
                or revision.invalidated_at is not None
            ):
                raise ConflictException("Published TMA revision is not valid.")
            questions = await TMAQuestionRepository.list_for_revision_with_options(
                db, assignment.tenant_id, revision.id
            )
            if not questions:
                raise ConflictException("Cannot record zero without published questions.")
            await TMAAuthorizationService.require_open_term(db, assignment)
            await TMADeadlineEligibilityRepository.capture(
                db, tenant_id=assignment.tenant_id, assignment_id=assignment.id
            )
            students = await TMADeadlineEligibilityRepository.pending(
                db, assignment=assignment, revision_id=revision.id, limit=cls.MAX_WRITES + 1
            )
            processed = 0
            blocked = 0
            error = ""
            more = len(students) > cls.MAX_WRITES
            for student_id, failure in students[: cls.MAX_WRITES]:
                try:
                    async with db.begin_nested():
                        written = await cls._write_zero(
                            db,
                            assignment=assignment,
                            revision_id=revision.id,
                            student_id=student_id,
                            total_questions=len(questions),
                            current=current,
                        )
                except (
                    ConflictException,
                    BadRequestException,
                    ForbiddenException,
                    IntegrityError,
                ) as exc:
                    blocked += 1
                    error = str(exc)[:500]
                    stmt = insert(TMAZeroGradingFailure).values(
                        id=uuid.uuid4(),
                        tenant_id=assignment.tenant_id,
                        assignment_id=assignment.id,
                        revision_number=assignment.current_revision_number,
                        student_id=student_id,
                        reason=error,
                        attempts=1,
                        last_failed_at=current,
                    )
                    await db.execute(
                        stmt.on_conflict_do_update(
                            constraint="uq_tma_zero_failure_revision_student",
                            set_={
                                "reason": error,
                                "attempts": TMAZeroGradingFailure.attempts + 1,
                                "last_failed_at": current,
                                "resolved_at": None,
                                "resolution": None,
                                "resolution_note": None,
                            },
                        )
                    )
                    logger.warning(
                        "tma.deadline_zero.blocked",
                        extra={
                            "tenant_id": str(assignment.tenant_id),
                            "assignment_id": str(assignment.id),
                            "revision_number": assignment.current_revision_number,
                        },
                    )
                    continue
                if written:
                    processed += 1
                if failure is not None and failure.resolved_at is None:
                    failure.resolved_at = current
                    failure.resolution = "graded"
                    failure.resolution_note = "Academic zero recorded successfully."
            # Flush successful reconciliations before counting remaining failures.
            await db.flush()
            # Do not claim completion while previously reported students
            # remain unresolved, even if a transfer makes them disappear from
            # today's eligible roster. Administrators must resolve/exempt them.
            unresolved = (
                await db.execute(
                    select(func.count(TMAZeroGradingFailure.id)).where(
                        TMAZeroGradingFailure.tenant_id == assignment.tenant_id,
                        TMAZeroGradingFailure.assignment_id == assignment.id,
                        TMAZeroGradingFailure.revision_number == assignment.current_revision_number,
                        TMAZeroGradingFailure.resolved_at.is_(None),
                    )
                )
            ).scalar_one()
            assignment.zero_grading_last_processed_at = datetime.now(timezone.utc)
            if not more and not blocked and not unresolved:
                assignment.zero_grading_completed_at = current
                assignment.zero_grading_error = None
            elif unresolved:
                assignment.zero_grading_error = (
                    f"{unresolved} student(s) require academic reconciliation. "
                    f"Most recent issue: {error}"
                )[:1500]
            elif blocked:
                assignment.zero_grading_error = (
                    f"{blocked} student(s) need reconciliation. Latest: {error}"
                )[:1500]
            logger.info(
                "tma.deadline_zero.batch",
                extra={
                    "tenant_id": str(assignment.tenant_id),
                    "assignment_id": str(assignment.id),
                    "revision_number": assignment.current_revision_number,
                    "zeroed": processed,
                    "blocked": blocked,
                    "more": more,
                },
            )
            await db.commit()
            await flush_cache_invalidation_events(db)
            return {
                "zeroed": processed,
                "blocked": blocked,
                "pending": int(assignment.zero_grading_completed_at is None),
            }
        except Exception as exc:
            assignment_id = assignment.id
            tenant_id = assignment.tenant_id
            revision_number = assignment.current_revision_number
            await db.rollback()
            # Make the processing problem visible to staff, while retaining
            # the pending marker so the next worker tick can safely retry.
            row = (
                await db.execute(
                    select(TMAAssignment)
                    .where(
                        TMAAssignment.tenant_id == tenant_id,
                        TMAAssignment.id == assignment_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                row is not None
                and row.status == TMAAssignmentStatus.CLOSED
                and row.current_revision_number == revision_number
            ):
                row.zero_grading_last_processed_at = datetime.now(timezone.utc)
                row.zero_grading_error = str(exc)[:1500]
                await db.commit()
                await flush_cache_invalidation_events(db)
            logger.exception("tma.deadline_zero.failed")
            return {"zeroed": 0, "blocked": 1, "pending": 1}
