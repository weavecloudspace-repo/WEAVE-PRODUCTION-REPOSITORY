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

from app.core.cache.events import flush_cache_invalidation_events
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException
from app.modules.classes.models import ClassRoom
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.models import AcademicTermStatus
from app.modules.students.repository import StudentEnrollmentRepository
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
from app.modules.tma.reporting_repository import TMAReportingRepository

logger = logging.getLogger(__name__)


class TMADeadlineZeroService:
    """One assignment with at most 25 score writes per scheduled tick."""

    PAGE_SIZE = 100
    MAX_WRITES = 25

    @staticmethod
    async def _eligible_classes(
        db: AsyncSession, assignment: TMAAssignment
    ) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        classrooms = set(
            (
                await db.execute(
                    select(ClassRoom.id).where(
                        ClassRoom.tenant_id == assignment.tenant_id,
                        ClassRoom.academic_level_id == assignment.academic_level_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        subjects = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=assignment.tenant_id,
            class_ids=classrooms,
            academic_term_id=assignment.academic_term_id,
            skip_unresolvable=True,
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db, assignment.tenant_id, assignment.academic_term_id
        )
        if term is None or term.status != AcademicTermStatus.OPEN or not term.is_current:
            raise ConflictException("Academic term is not open for missed-deadline scoring.")
        regular: set[uuid.UUID] = set()
        elective: set[uuid.UUID] = set()
        for class_id, class_subjects in subjects.items():
            for subject in class_subjects:
                if subject.curriculum_subject_id != assignment.curriculum_subject_id:
                    continue
                if subject.is_elective and subject.elective_group_id is not None:
                    elective.add(class_id)
                else:
                    regular.add(class_id)
                break
        return regular, elective

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
        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db, tenant_id, student_id, assignment.academic_session_id
        )
        if (
            enrollment is None
            or enrollment.class_id is None
            or enrollment.academic_level_id != assignment.academic_level_id
            or enrollment.created_at > assignment.closes_at
        ):
            raise ConflictException(
                "Student enrollment changed after the deadline; manual review required."
            )
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
    ) -> dict[str, int]:
        current = now or datetime.now(timezone.utc)
        # Existing CLOSED TMAs are not backfilled: only assignments closed by
        # the new deadline-aware lifecycle receive a requested timestamp.
        assignment = (
            await db.execute(
                select(TMAAssignment)
                .where(
                    TMAAssignment.status == TMAAssignmentStatus.CLOSED,
                    TMAAssignment.zero_grading_requested_at.is_not(None),
                    TMAAssignment.zero_grading_completed_at.is_(None),
                    TMAAssignment.closes_at.is_not(None),
                    TMAAssignment.closes_at <= current,
                )
                .order_by(
                    TMAAssignment.zero_grading_error.is_not(None),
                    TMAAssignment.zero_grading_requested_at,
                    TMAAssignment.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
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
            regular, elective = await cls._eligible_classes(db, assignment)
            processed = 0
            blocked = 0
            error = ""
            offset = 0
            more = True
            while more and processed < cls.MAX_WRITES:
                students, total = await TMAReportingRepository.list_participation(
                    db,
                    assignment=assignment,
                    regular_class_ids=regular,
                    grouped_elective_class_ids=elective,
                    search=None,
                    class_id=None,
                    participation_status=None,
                    offset=offset,
                    limit=cls.PAGE_SIZE,
                )
                student_ids = [item["student_id"] for item in students]
                existing_failures = (
                    (
                        await db.execute(
                            select(TMAZeroGradingFailure).where(
                                TMAZeroGradingFailure.tenant_id == assignment.tenant_id,
                                TMAZeroGradingFailure.assignment_id == assignment.id,
                                TMAZeroGradingFailure.student_id.in_(student_ids),
                            )
                        )
                    ).scalars().all()
                    if student_ids else []
                )
                failures_by_student = {record.student_id: record for record in existing_failures}
                for row in students:
                    failure = failures_by_student.get(row["student_id"])
                    if failure is not None and failure.resolution == "exempt":
                        continue
                    if not row["is_currently_eligible"] or row["participation_status"] in {
                        "submitted",
                        "missed",
                    }:
                        continue
                    try:
                        async with db.begin_nested():
                            written = await cls._write_zero(
                                db,
                                assignment=assignment,
                                revision_id=revision.id,
                                student_id=row["student_id"],
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
                            student_id=row["student_id"],
                            reason=error,
                            attempts=1,
                            last_failed_at=current,
                        )
                        stmt = stmt.on_conflict_do_update(
                            constraint="uq_tma_zero_failure_tenant_assignment_student",
                            set_={
                                "reason": error,
                                "attempts": TMAZeroGradingFailure.attempts + 1,
                                "last_failed_at": current,
                                "resolved_at": None,
                                "resolution": None,
                                "resolution_note": None,
                            },
                        )
                        await db.execute(stmt)
                        logger.warning(
                            "tma.deadline_zero.blocked",
                            extra={
                                "tenant_id": str(assignment.tenant_id),
                                "assignment_id": str(assignment.id),
                                "student_id": str(row["student_id"]),
                                "reason": error,
                            },
                        )
                        continue
                    if written:
                        processed += 1
                        if failure is not None and failure.resolved_at is None:
                            failure.resolved_at = current
                            failure.resolution = "graded"
                            failure.resolution_note = "Academic zero recorded successfully."
                    if processed >= cls.MAX_WRITES:
                        break
                offset += len(students)
                more = bool(students) and offset < total
            # Do not claim completion while previously reported students
            # remain unresolved, even if a transfer makes them disappear from
            # today's eligible roster. Administrators must resolve/exempt them.
            unresolved = (
                await db.execute(
                    select(func.count(TMAZeroGradingFailure.id)).where(
                        TMAZeroGradingFailure.tenant_id == assignment.tenant_id,
                        TMAZeroGradingFailure.assignment_id == assignment.id,
                        TMAZeroGradingFailure.resolved_at.is_(None),
                    )
                )
            ).scalar_one()
            if not more and processed < cls.MAX_WRITES and not blocked and not unresolved:
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
            if row is not None and row.status == TMAAssignmentStatus.CLOSED:
                row.zero_grading_error = str(exc)[:1500]
                await db.commit()
                await flush_cache_invalidation_events(db)
            logger.exception("tma.deadline_zero.failed")
            return {"zeroed": 0, "blocked": 1, "pending": 1}
