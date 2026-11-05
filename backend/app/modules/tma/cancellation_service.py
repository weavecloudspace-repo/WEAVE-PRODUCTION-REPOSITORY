"""Manual close, durable cancellation, score reversal, and clean revision publishing.

Cancelling invalidates only CA component rows explicitly attributed to submitted
TMA attempts. If any score is ambiguous, modified, or no longer a DRAFT result,
the entire transaction aborts and the assignment stays CANCELLING.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache.events import flush_cache_invalidation_events

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.student_academics.hybrid_scores import component_is_complete
from app.modules.student_academics.models import (
    AcademicResultStatus,
    GradingScale,
    StudentAssessmentScore,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.tma.academic_guard import TMAAcademicGuard
from app.modules.tma.deadline_eligibility_repository import TMADeadlineEligibilityRepository
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import (
    TMAAssignmentRevision,
    TMAAssignmentStatus,
    TMAClosureRun,
    TMAAttempt,
    TMAAttemptStatus,
    TMACancellationRun,
    TMAParticipant,
    TMAQuestion,
    TMAQuestionOption,
)
from app.modules.tma.repository import (
    TMAAssignmentRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)

logger = logging.getLogger(__name__)


class TMACancellationService:
    @staticmethod
    async def _assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ):
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            actor.tenant_id,
            assignment_id,
            lock=True,
        )
        if assignment is None:
            raise NotFoundException("TMA assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db,
            actor=actor,
            assignment=assignment,
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        return assignment

    @staticmethod
    async def _run(db: AsyncSession, *, tenant_id: uuid.UUID, assignment_id: uuid.UUID):
        return (
            (
                await db.execute(
                    select(TMACancellationRun)
                    .where(
                        TMACancellationRun.tenant_id == tenant_id,
                        TMACancellationRun.assignment_id == assignment_id,
                    )
                    .order_by(TMACancellationRun.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

    @classmethod
    async def close(
        cls,
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ):
        assignment = await cls._assignment(db, actor=actor, assignment_id=assignment_id)
        if assignment.status == TMAAssignmentStatus.CLOSED:
            return assignment
        if assignment.status != TMAAssignmentStatus.ACTIVE:
            raise ConflictException("Only an active TMA can be closed.")
        if assignment.closes_at is None:
            raise ConflictException("Cannot close a TMA without a submission deadline.")
        revision = await TMARevisionRepository.get_by_number(
            db, actor.tenant_id, assignment.id, assignment.current_revision_number
        )
        if revision is None:
            raise ConflictException("Published TMA revision was not found.")
        closed_at = datetime.now(timezone.utc)
        assignment.status = TMAAssignmentStatus.CLOSED
        assignment.closed_at = closed_at
        assignment.zero_grading_requested_at = closed_at
        assignment.zero_grading_completed_at = None
        db.add(
            TMAClosureRun(
                tenant_id=assignment.tenant_id,
                assignment_id=assignment.id,
                revision_id=revision.id,
                closed_at=closed_at,
                cutoff_at=min(assignment.closes_at, closed_at),
                original_deadline_at=assignment.closes_at,
                kind="manual",
            )
        )
        await db.flush()
        await TMADeadlineEligibilityRepository.capture(
            db, tenant_id=assignment.tenant_id, assignment_id=assignment.id
        )
        await db.commit()
        await flush_cache_invalidation_events(db)
        return assignment

    @classmethod
    async def cancel(
        cls,
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        reason: str,
    ) -> TMACancellationRun:
        # Shared lock blocks concurrent result finalization while cancellation starts.
        await TMAAcademicGuard.lock(db, actor.tenant_id)
        assignment = await cls._assignment(db, actor=actor, assignment_id=assignment_id)
        if assignment.status == TMAAssignmentStatus.CANCELLING:
            run = await cls._run(
                db,
                tenant_id=actor.tenant_id,
                assignment_id=assignment_id,
            )
            if run is None:
                raise ConflictException("Cancellation record is missing.")
            return run
        if assignment.status != TMAAssignmentStatus.CLOSED:
            raise ConflictException("Close the assignment before cancelling it.")
        if (
            assignment.zero_grading_requested_at is not None
            and assignment.zero_grading_completed_at is None
        ):
            raise ConflictException(
                "Wait for missed-deadline grading to finish or resolve its errors "
                "before cancelling this assignment."
            )
        await TMAAcademicGuard.require_draft_results(db, assignment)
        revision = await TMARevisionRepository.get_by_number(
            db,
            actor.tenant_id,
            assignment_id,
            assignment.current_revision_number,
        )
        if revision is None or revision.invalidated_at is not None:
            raise ConflictException("Current revision cannot be cancelled.")
        run = TMACancellationRun(
            tenant_id=actor.tenant_id,
            assignment_id=assignment_id,
            revision_id=revision.id,
            status="pending",
            reason=reason.strip(),
            requested_by_actor_type=TMAAuthorizationService.actor_type(actor),
            requested_by_actor_id=actor.id,
            reversed_scores=0,
        )
        if not run.reason:
            raise ConflictException("A cancellation reason is required.")
        assignment.status = TMAAssignmentStatus.CANCELLING
        db.add(run)
        await db.commit()
        await flush_cache_invalidation_events(db)
        await cls._enqueue(run)
        return run

    @staticmethod
    async def _enqueue(run: TMACancellationRun) -> None:
        from app.core.queue.arq import enqueue_tma_cancellation_job

        try:
            queued = await enqueue_tma_cancellation_job(
                run_id=str(run.id),
                tenant_id=str(run.tenant_id),
            )
            if not queued:
                logger.warning("TMA cancellation enqueue deferred to recovery poll: %s", run.id)
        except Exception:
            # The committed pending record is the source of truth; scheduled
            # worker polling recovers from Redis downtime or enqueue failure.
            logger.exception("TMA cancellation enqueue deferred: %s", run.id)

    @classmethod
    async def get_status(
        cls,
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> TMACancellationRun:
        await cls._assignment(db, actor=actor, assignment_id=assignment_id)
        run = await cls._run(db, tenant_id=actor.tenant_id, assignment_id=assignment_id)
        if run is None:
            raise NotFoundException("TMA cancellation does not exist.")
        return run

    @classmethod
    async def retry(
        cls,
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> TMACancellationRun:
        assignment = await cls._assignment(db, actor=actor, assignment_id=assignment_id)
        if assignment.status != TMAAssignmentStatus.CANCELLING:
            raise ConflictException("Assignment is not awaiting cancellation.")
        run = await cls._run(db, tenant_id=actor.tenant_id, assignment_id=assignment_id)
        if run is None or run.status != "failed":
            raise ConflictException("There is no failed cancellation to retry.")
        run.status = "pending"
        run.error_message = None
        await db.commit()
        await flush_cache_invalidation_events(db)
        await cls._enqueue(run)
        return run

    @staticmethod
    async def process(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> dict[str, int | str]:
        run = (
            await db.execute(
                select(TMACancellationRun)
                .where(TMACancellationRun.tenant_id == tenant_id, TMACancellationRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundException("TMA cancellation job not found.")
        if run.status == "completed":
            return {"status": "completed", "reversed_scores": run.reversed_scores}
        if run.status != "pending":
            return {"status": run.status, "reversed_scores": run.reversed_scores}

        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            tenant_id,
            run.assignment_id,
            lock=True,
        )
        if assignment is None or assignment.status != TMAAssignmentStatus.CANCELLING:
            raise ConflictException("TMA is not in a cancellable state.")
        if assignment.current_revision_number < 1:
            raise ConflictException("Assignment revision is invalid.")
        revision = await TMARevisionRepository.get_by_id(
            db,
            tenant_id,
            run.revision_id,
            lock=True,
        )
        if (
            revision is None
            or revision.assignment_id != assignment.id
            or revision.revision_number != assignment.current_revision_number
            or revision.invalidated_at is not None
        ):
            raise ConflictException("The cancellation revision no longer matches.")

        # Refuse to alter results outside their permitted academic write window.
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        attempts = (
            await db.execute(
                select(TMAAttempt, TMAParticipant)
                .join(
                    TMAParticipant,
                    and_(
                        TMAParticipant.id == TMAAttempt.participant_id,
                        TMAParticipant.tenant_id == tenant_id,
                        TMAParticipant.revision_id == run.revision_id,
                    ),
                )
                .where(
                    TMAAttempt.tenant_id == tenant_id,
                    TMAAttempt.revision_id == run.revision_id,
                    TMAAttempt.status == TMAAttemptStatus.SUBMITTED,
                )
                .order_by(TMAAttempt.id)
            )
        ).all()
        pending_attempts = [
            (attempt, participant)
            for attempt, participant in attempts
            if attempt.score_reversed_at is None
        ]
        score_ids = set()
        for attempt, _ in pending_attempts:
            if attempt.score_id is None or attempt.score_snapshot is None:
                raise ConflictException(
                    "Cannot safely reverse a historical submission without "
                    "a TMA-owned score link. Manual reconciliation is required."
                )
            if attempt.score_id in score_ids:
                raise ConflictException("Duplicate TMA score ownership detected.")
            score_ids.add(attempt.score_id)
        score_rows = (
            (
                await db.execute(
                    select(StudentAssessmentScore, StudentSubjectResult)
                    .join(
                        StudentSubjectResult,
                        and_(
                            StudentSubjectResult.id
                            == StudentAssessmentScore.student_subject_result_id,
                            StudentSubjectResult.tenant_id == tenant_id,
                        ),
                    )
                    .where(
                        StudentAssessmentScore.tenant_id == tenant_id,
                        StudentAssessmentScore.id.in_(score_ids),
                        StudentAssessmentScore.assessment_component_id
                        == assignment.assessment_component_id,
                        StudentSubjectResult.academic_session_id == assignment.academic_session_id,
                        StudentSubjectResult.academic_term_id == assignment.academic_term_id,
                        StudentSubjectResult.curriculum_subject_id
                        == assignment.curriculum_subject_id,
                    )
                    .order_by(StudentAssessmentScore.id)
                    .with_for_update()
                )
            ).all()
            if score_ids
            else []
        )
        scores_by_id = {score.id: (score, result) for score, result in score_rows}
        to_reverse = []
        for attempt, participant in pending_attempts:
            row = scores_by_id.get(attempt.score_id)
            if row is None or row[1].student_id != participant.student_id:
                raise ConflictException("TMA-owned academic score is missing or was moved.")
            score, result = row
            if (
                result.status != AcademicResultStatus.DRAFT
                or score.score != attempt.score_snapshot
                or score.cbt_score is not None
                or score.theory_score is not None
                or score.source_exam_id is not None
            ):
                raise ConflictException(
                    "An academic score was edited, submitted, locked, or linked to CBT. "
                    "Cancellation requires manual reconciliation."
                )
            to_reverse.append((attempt, score, result))

        now = datetime.now(timezone.utc)
        results = {}
        for attempt, score, result in to_reverse:
            await db.delete(score)
            attempt.score_reversed_at = now
            results[result.id] = result
        await db.flush()
        components_by_result = await StudentAcademicRepository.list_result_component_scores_batch(
            db, tenant_id, list(results.values())
        )
        complete_results = []
        for result in results.values():
            components = components_by_result.get(result.id, [])
            result.total_score = sum(
                (row.score for _, row in components if row is not None), Decimal("0")
            )
            if components and all(
                component_is_complete(component, row) for component, row in components
            ):
                complete_results.append(result)
            else:
                result.grade = result.remark = result.grading_scale_id = None
        if complete_results:
            scales = (
                (
                    await db.execute(
                        select(GradingScale).where(
                            GradingScale.tenant_id == tenant_id,
                            GradingScale.is_active.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for result in complete_results:
                matches = [
                    scale
                    for scale in scales
                    if scale.min_score <= result.total_score <= scale.max_score
                ]
                if len(matches) > 1:
                    raise ConflictException(
                        "Overlapping grading scales require academic reconciliation."
                    )
                scale = matches[0] if matches else None
                result.grade = scale.grade if scale else None
                result.remark = scale.remark if scale else None
                result.grading_scale_id = scale.id if scale else None

        revision.invalidated_at = now
        revision.invalidated_by_actor_type = run.requested_by_actor_type
        revision.invalidated_by_actor_id = run.requested_by_actor_id
        revision.invalidation_reason = run.reason
        assignment.status = TMAAssignmentStatus.CANCELLED
        run.status = "completed"
        run.reversed_scores = len(to_reverse)
        run.error_message = None
        run.completed_at = now
        await db.commit()
        await flush_cache_invalidation_events(db)
        return {"status": "completed", "reversed_scores": len(to_reverse)}

    @staticmethod
    async def mark_failed(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        message: str,
    ) -> None:
        run = (
            await db.execute(
                select(TMACancellationRun)
                .where(
                    TMACancellationRun.tenant_id == tenant_id,
                    TMACancellationRun.id == run_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is not None and run.status == "pending":
            run.status = "failed"
            run.error_message = message[:1500]
            await db.commit()
            await flush_cache_invalidation_events(db)

    @classmethod
    async def create_revision(
        cls,
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> TMAAssignmentRevision:
        assignment = await cls._assignment(db, actor=actor, assignment_id=assignment_id)
        if assignment.status != TMAAssignmentStatus.CANCELLED:
            raise ConflictException("Finish cancellation before creating a revision.")
        previous = await TMARevisionRepository.get_by_number(
            db,
            actor.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if previous is None or previous.invalidated_at is None:
            raise ConflictException("Previous revision is not invalidated.")
        prior_questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            actor.tenant_id,
            previous.id,
        )
        revision = TMAAssignmentRevision(
            tenant_id=actor.tenant_id,
            assignment_id=assignment.id,
            revision_number=assignment.current_revision_number + 1,
        )
        await TMARevisionRepository.add(db, revision)
        for original, originals_options in prior_questions:
            cloned = TMAQuestion(
                tenant_id=actor.tenant_id,
                assignment_id=assignment.id,
                revision_id=revision.id,
                position=original.position,
                question_text=original.question_text,
                image_asset_id=original.image_asset_id,
                author_actor_type=TMAAuthorizationService.actor_type(actor),
                author_actor_id=actor.id,
                version=1,
            )
            await TMAQuestionRepository.add_question(db, cloned)
            db.add_all(
                [
                    TMAQuestionOption(
                        tenant_id=actor.tenant_id,
                        assignment_id=assignment.id,
                        question_id=cloned.id,
                        position=opt.position,
                        option_text=opt.option_text,
                        image_asset_id=opt.image_asset_id,
                        is_correct=opt.is_correct,
                    )
                    for opt in originals_options
                ]
            )
        previous.zero_grading_requested_at = assignment.zero_grading_requested_at
        previous.zero_grading_completed_at = assignment.zero_grading_completed_at
        previous.zero_grading_error = assignment.zero_grading_error
        assignment.zero_grading_requested_at = None
        assignment.zero_grading_completed_at = None
        assignment.zero_grading_error = None
        assignment.current_revision_number = revision.revision_number
        assignment.status = TMAAssignmentStatus.DRAFT
        assignment.activated_at = None
        assignment.closed_at = None
        await db.commit()
        await flush_cache_invalidation_events(db)
        return revision
