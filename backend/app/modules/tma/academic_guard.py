"""Transaction-scoped guards between TMA activity and academic finalization.

Every TMA publish/reopen/cancel and result finalization path acquires the
same tenant-level advisory lock *before* loading rows FOR UPDATE. This prevents
a check/commit race without creating a permanent roster or schema dependency.
"""

from __future__ import annotations

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.modules.classes.models import ClassRoom
from app.modules.student_academics.models import AcademicResultStatus, StudentSubjectResult
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus


class TMAAcademicGuard:
    @staticmethod
    async def lock(db: AsyncSession, tenant_id) -> None:
        # Acquired before assignment/result row locks by all transition callers.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"weave:tma-academic-finalization:{tenant_id}"},
        )

    @staticmethod
    async def require_draft_results(db: AsyncSession, assignment: TMAAssignment) -> None:
        """Refuse to modify an assessment after any result for its scope is finalized."""
        protected = (
            await db.execute(
                select(StudentSubjectResult.id)
                .join(
                    ClassRoom,
                    and_(
                        ClassRoom.id == StudentSubjectResult.class_id,
                        ClassRoom.tenant_id == StudentSubjectResult.tenant_id,
                    ),
                )
                .where(
                    StudentSubjectResult.tenant_id == assignment.tenant_id,
                    StudentSubjectResult.academic_session_id == assignment.academic_session_id,
                    StudentSubjectResult.academic_term_id == assignment.academic_term_id,
                    StudentSubjectResult.curriculum_subject_id == assignment.curriculum_subject_id,
                    ClassRoom.academic_level_id == assignment.academic_level_id,
                    StudentSubjectResult.status != AcademicResultStatus.DRAFT,
                )
                .limit(1)
            )
        ).first()
        if protected:
            raise ConflictException(
                "This TMA cannot be published, reopened or cancelled because one or more "
                "results for this level and subject are already submitted, approved or "
                "locked. Ask the school administrator to reopen those results to DRAFT."
            )

    @staticmethod
    async def require_grading_finalized(db: AsyncSession, result: StudentSubjectResult) -> None:
        """Never finalize a result while its level/subject has unfinished TMA work."""
        level_id = (
            await db.execute(
                select(ClassRoom.academic_level_id).where(
                    ClassRoom.tenant_id == result.tenant_id,
                    ClassRoom.id == result.class_id,
                )
            )
        ).scalar_one_or_none()
        if level_id is None:
            raise ConflictException(
                "Cannot verify this student's academic level. Contact the administrator."
            )
        blocking = (
            await db.execute(
                select(TMAAssignment.id)
                .where(
                    TMAAssignment.tenant_id == result.tenant_id,
                    TMAAssignment.academic_level_id == level_id,
                    TMAAssignment.curriculum_subject_id == result.curriculum_subject_id,
                    TMAAssignment.academic_session_id == result.academic_session_id,
                    TMAAssignment.academic_term_id == result.academic_term_id,
                    (
                        (TMAAssignment.status == TMAAssignmentStatus.ACTIVE)
                        | (TMAAssignment.status == TMAAssignmentStatus.CANCELLING)
                        | (
                            (TMAAssignment.status == TMAAssignmentStatus.CLOSED)
                            & (TMAAssignment.zero_grading_completed_at.is_(None))
                        )
                    ),
                )
                .limit(1)
            )
        ).first()
        if blocking:
            raise ConflictException(
                "Cannot finalize this result while a TMA for this level and subject "
                "is active, cancelling or awaiting missed-deadline grading. "
                "Close the TMA and resolve its grading before submitting results."
            )
