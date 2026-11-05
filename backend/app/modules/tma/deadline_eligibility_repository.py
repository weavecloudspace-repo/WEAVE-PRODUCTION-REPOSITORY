"""Historical closure-time eligibility derived from enrollment dates.

Live TMA participation uses current enrollment independently. Deadline zero
grading derives its candidates from the effective enrollment at this specific
closure, not a one-time revision roster. Old immutable snapshot records remain
in PostgreSQL as historic evidence but do not grant/revoke eligibility.

Elective, classroom and curriculum state without historical versioning cannot
be reconstructed perfectly after later edits; the query is intentionally
conservative and excludes electives selected only *after* the closure.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.students.models import StudentEnrollment
from app.modules.tma.models import (
    TMAAttempt,
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
        cutoff = min(assignment.closes_at, assignment.closed_at) if assignment.closed_at else assignment.closes_at
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
    async def capture(db: AsyncSession, *, tenant_id: uuid.UUID, assignment_id: uuid.UUID):
        """Legacy compatibility hook; new closure processing never writes a roster."""
        return None

    @staticmethod
    async def enrollment(
        db: AsyncSession, *, tenant_id: uuid.UUID, revision_id: uuid.UUID,
        student_id: uuid.UUID, assignment=None,
    ):
        if assignment is None:
            raise ValueError("Historical grading requires the closure assignment scope")
        roster = TMADeadlineEligibilityRepository._roster(assignment)
        return (
            await db.execute(
                select(StudentEnrollment, roster.c.subject_id)
                .join(
                    roster,
                    and_(
                        roster.c.student_enrollment_id == StudentEnrollment.id,
                        StudentEnrollment.tenant_id == tenant_id,
                    ),
                )
                .where(
                    roster.c.student_id == student_id,
                )
                .limit(1)
            )
        ).one_or_none()

    @staticmethod
    async def pending(db: AsyncSession, *, assignment, revision_id: uuid.UUID, limit: int):
        roster = TMADeadlineEligibilityRepository._roster(assignment)
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
                    select(roster.c.student_id, failure)
                    .outerjoin(
                        failure,
                        and_(
                            failure.tenant_id == assignment.tenant_id,
                            failure.assignment_id == assignment.id,
                            failure.revision_number == assignment.current_revision_number,
                            failure.student_id == roster.c.student_id,
                        ),
                    )
                    .where(
                        roster.c.student_id.not_in(submitted),
                        failure.resolution.is_(None) | (failure.resolution != "exempt"),
                    )
                    .order_by(failure.last_failed_at.asc().nullsfirst(), roster.c.student_id)
                    .limit(limit)
                )
            ).all()
        )
