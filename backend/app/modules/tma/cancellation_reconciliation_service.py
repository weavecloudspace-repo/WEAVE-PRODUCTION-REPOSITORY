"""Read-only, tenant-safe diagnostics for protected TMA score cancellation.

Administrators resolve conflicts through the existing academic result workflow.
This module never overwrites approved, edited, CBT-linked, or locked marks.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.student_academics.models import (
    AcademicResultStatus,
    StudentAssessmentScore,
    StudentSubjectResult,
)
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import TMAAttempt, TMAAttemptStatus, TMAParticipant
from app.modules.tma.repository import TMAAssignmentRepository, TMARevisionRepository


class TMACancellationReconciliationService:
    @staticmethod
    async def conflicts(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> list[dict]:
        assignment = await TMAAssignmentRepository.get_by_id(db, actor.tenant_id, assignment_id)
        if assignment is None:
            raise NotFoundException("TMA assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        revision = await TMARevisionRepository.get_by_number(
            db, actor.tenant_id, assignment_id, assignment.current_revision_number
        )
        if revision is None:
            raise NotFoundException("Current assignment revision not found.")

        records = (
            await db.execute(
                select(
                    TMAAttempt,
                    TMAParticipant,
                    StudentAssessmentScore,
                    StudentSubjectResult,
                )
                .join(
                    TMAParticipant,
                    and_(
                        TMAParticipant.id == TMAAttempt.participant_id,
                        TMAParticipant.tenant_id == actor.tenant_id,
                        TMAParticipant.revision_id == revision.id,
                    ),
                )
                .outerjoin(
                    StudentAssessmentScore,
                    and_(
                        StudentAssessmentScore.id == TMAAttempt.score_id,
                        StudentAssessmentScore.tenant_id == actor.tenant_id,
                    ),
                )
                .outerjoin(
                    StudentSubjectResult,
                    and_(
                        StudentSubjectResult.id == StudentAssessmentScore.student_subject_result_id,
                        StudentSubjectResult.tenant_id == actor.tenant_id,
                    ),
                )
                .where(
                    TMAAttempt.tenant_id == actor.tenant_id,
                    TMAAttempt.revision_id == revision.id,
                    TMAAttempt.status == TMAAttemptStatus.SUBMITTED,
                    TMAAttempt.score_reversed_at.is_(None),
                )
                .order_by(TMAParticipant.student_id)
            )
        ).all()

        conflicts = []
        for attempt, participant, score, result in records:
            reason = None
            if attempt.score_id is None or attempt.score_snapshot is None:
                reason = "Submission lacks a linked TMA score. Review academic records."
            elif score is None or result is None:
                reason = "Linked academic score or result is missing."
            elif (
                score.assessment_component_id != assignment.assessment_component_id
                or result.student_id != participant.student_id
                or result.academic_session_id != assignment.academic_session_id
                or result.academic_term_id != assignment.academic_term_id
                or result.curriculum_subject_id != assignment.curriculum_subject_id
            ):
                reason = "Linked score no longer belongs to this student's TMA academic scope."
            elif result.status != AcademicResultStatus.DRAFT:
                reason = (
                    "Academic result is submitted, approved, or locked. "
                    "Use the normal result reopening process before retrying."
                )
            elif score.score != attempt.score_snapshot:
                reason = "Academic component was edited after TMA submission."
            elif (
                score.cbt_score is not None
                or score.theory_score is not None
                or score.source_exam_id is not None
            ):
                reason = "Academic component is linked to CBT/hybrid scoring."
            if reason is not None:
                conflicts.append(
                    {
                        "student_id": participant.student_id,
                        "attempt_id": attempt.id,
                        "score_id": attempt.score_id,
                        "reason": reason,
                    }
                )
        return conflicts
