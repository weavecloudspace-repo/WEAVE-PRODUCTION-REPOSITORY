"""Closure-scoped immutable eligibility; current enrollment is used only at capture.

Each closure records its own roster. Retained revision-wide snapshots are audit
history only and cannot be silently attributed to a later reopening cycle.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select, text
from app.core.exceptions import ConflictException
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.students.models import StudentEnrollment
from app.modules.tma.models import (
    TMAAttempt,
    TMAAssignment,
    TMAClosureRun,
    TMAClosureEligibility,
    TMAAttemptStatus,
    TMAParticipant,
    TMAZeroGradingFailure,
)

# Shares the original deadline eligibility predicates; unlike
# tma_capture_deadline, does not persist a frozen revision-wide roster.
_CLOSURE_ELIGIBILITY_SQL = """
    SELECT e.student_id, e.id AS student_enrollment_id, cs.subject_id
    FROM public.student_enrollments e
    JOIN public.students s ON s.tenant_id = :tenant AND s.id = e.student_id
    JOIN public.classes c ON c.tenant_id = :tenant AND c.id = e.class_id
    JOIN public.academic_levels l ON l.tenant_id = :tenant AND l.id = c.academic_level_id
    JOIN public.curricula cu ON cu.tenant_id = :tenant AND cu.academic_level_id = l.id
    JOIN public.curriculum_subjects cs ON cs.tenant_id = :tenant AND cs.curriculum_id = cu.id
    JOIN public.subjects sub ON sub.tenant_id = :tenant AND sub.id = cs.subject_id
    JOIN public.academic_terms t ON t.tenant_id = :tenant AND t.id = :term
    LEFT JOIN public.class_term_department_assignments cd
        ON cd.tenant_id = :tenant AND cd.class_id = c.id AND cd.academic_term_id = t.id
    LEFT JOIN public.academic_level_departments ld
        ON ld.tenant_id = :tenant AND ld.id = cd.academic_level_department_id
        AND ld.academic_level_id = l.id AND ld.is_active AND ld.archived_at IS NULL
    LEFT JOIN public.departments d
        ON d.tenant_id = :tenant AND d.id = ld.department_id
        AND d.is_active AND d.archived_at IS NULL
    WHERE e.tenant_id = :tenant
        AND e.academic_session_id = :session
        AND e.academic_level_id = :level
        AND e.started_on <= (CAST(:cutoff AS timestamptz) AT TIME ZONE 'UTC')::date
        AND (e.ended_on IS NULL OR e.ended_on >=
            (CAST(:cutoff AS timestamptz) AT TIME ZONE 'UTC')::date)
        AND e.created_at <= CAST(:cutoff AS timestamptz)
        AND s.status::text = 'active' AND s.is_active AND NOT s.is_archived
        AND c.is_active AND c.archived_at IS NULL
        AND l.status::text = 'active'
        AND cs.id = :curriculum_subject AND cs.is_active
        AND sub.is_active AND sub.archived_at IS NULL
        AND (NOT cs.is_elective OR cs.elective_group_id IS NULL OR EXISTS (
            SELECT 1 FROM public.student_elective_selections es
            WHERE es.tenant_id = :tenant AND es.student_id = s.id
                AND es.curriculum_subject_id = cs.id
        ))
        AND (l.specialization_required_from_term_position IS NULL
            OR (CASE t.name::text WHEN 'first_term' THEN 1
                WHEN 'second_term' THEN 2 ELSE 3 END)
                < l.specialization_required_from_term_position
            OR (d.id IS NOT NULL AND (
                NOT EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                    WHERE sd.tenant_id = :tenant AND sd.curriculum_subject_id = cs.id)
                OR EXISTS (SELECT 1 FROM public.curriculum_subject_departments sd
                    WHERE sd.tenant_id = :tenant AND sd.curriculum_subject_id = cs.id
                        AND sd.academic_level_department_id = ld.id))))
"""


class TMADeadlineEligibilityRepository:
    @staticmethod
    def _roster(assignment):
        # Automatic closure uses the published deadline; manual close must
        # persist the actual early cutoff in closes_at.
        cutoff = (
            min(assignment.closes_at, assignment.closed_at)
            if assignment.closed_at
            else assignment.closes_at
        )
        if cutoff is None:
            raise ValueError("TMA closure has no effective cutoff")
        return (
            text(_CLOSURE_ELIGIBILITY_SQL)
            .bindparams(
                tenant=assignment.tenant_id,
                session=assignment.academic_session_id,
                level=assignment.academic_level_id,
                term=assignment.academic_term_id,
                curriculum_subject=assignment.curriculum_subject_id,
                cutoff=cutoff,
            )
            .columns(
                student_id=UUID(as_uuid=True),
                student_enrollment_id=UUID(as_uuid=True),
                subject_id=UUID(as_uuid=True),
            )
            .subquery("closure_eligible")
        )

    @staticmethod
    async def _closure(db: AsyncSession, assignment) -> TMAClosureRun:
        if assignment.closed_at is None:
            raise ConflictException("TMA has no recorded closure.")
        closure = (
            await db.execute(
                select(TMAClosureRun).where(
                    TMAClosureRun.tenant_id == assignment.tenant_id,
                    TMAClosureRun.assignment_id == assignment.id,
                    TMAClosureRun.closed_at == assignment.closed_at,
                )
            )
        ).scalar_one_or_none()
        if closure is None or closure.eligibility_captured_at is None:
            raise ConflictException(
                "Closure eligibility tracking is missing or predates the deadline; "
                "administrator reconciliation is required."
            )
        return closure

    @staticmethod
    async def capture(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        closure_id: uuid.UUID | None = None,
    ) -> None:
        """Freeze one closure's roster before subsequent eligibility changes.

        Caller must hold the assignment row lock and commit this capture
        in the same transaction as the CLOSED lifecycle transition.
        """
        if closure_id is None:
            closure_id = (
                await db.execute(
                    select(TMAClosureRun.id)
                    .join(
                        TMAAssignment,
                        and_(
                            TMAClosureRun.tenant_id == TMAAssignment.tenant_id,
                            TMAClosureRun.assignment_id == TMAAssignment.id,
                            TMAClosureRun.closed_at == TMAAssignment.closed_at,
                        ),
                    )
                    .where(
                        TMAClosureRun.tenant_id == tenant_id,
                        TMAClosureRun.assignment_id == assignment_id,
                    )
                )
            ).scalar_one_or_none()
        if closure_id is None:
            raise ConflictException("Closure event is missing; cannot freeze eligibility.")
        captured = (
            await db.execute(
                text("SELECT public.tma_capture_closure_eligibility(:tenant, :closure)"),
                {"tenant": tenant_id, "closure": closure_id},
            )
        ).scalar_one()
        if not captured:
            raise ConflictException(
                "Deadline eligibility tracking predates this closure; "
                "administrator reconciliation is required."
            )

    @staticmethod
    async def enrollment(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
        student_id: uuid.UUID,
        assignment=None,
    ):
        if assignment is None:
            raise ValueError("Historical grading requires a specific closure")
        closure = await TMADeadlineEligibilityRepository._closure(db, assignment)
        if closure.revision_id != revision_id:
            raise ConflictException("Closure revision differs from requested revision.")
        roster = TMAClosureEligibility
        return (
            await db.execute(
                select(StudentEnrollment, roster.subject_id)
                .join(
                    roster,
                    and_(
                        roster.tenant_id == StudentEnrollment.tenant_id,
                        roster.student_enrollment_id == StudentEnrollment.id,
                        roster.class_id == StudentEnrollment.class_id,
                    ),
                )
                .where(
                    roster.tenant_id == tenant_id,
                    roster.closure_run_id == closure.id,
                    roster.student_id == student_id,
                )
            )
        ).one_or_none()

    @staticmethod
    async def pending(db: AsyncSession, *, assignment, revision_id: uuid.UUID, limit: int):
        closure = await TMADeadlineEligibilityRepository._closure(db, assignment)
        if closure.revision_id != revision_id:
            raise ConflictException("Closure refers to a different published revision.")
        roster = TMAClosureEligibility
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
                            failure.tenant_id == assignment.tenant_id,
                            failure.assignment_id == assignment.id,
                            failure.revision_number == assignment.current_revision_number,
                            failure.student_id == roster.student_id,
                        ),
                    )
                    .where(
                        roster.tenant_id == assignment.tenant_id,
                        roster.closure_run_id == closure.id,
                        roster.student_id.not_in(submitted),
                        failure.resolution.is_(None) | (failure.resolution != "exempt"),
                    )
                    .order_by(failure.last_failed_at.asc().nullsfirst(), roster.student_id)
                    .limit(limit)
                )
            ).all()
        )
