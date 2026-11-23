"""Same-level academic result continuity across immutable enrollment segments.

Assessment attempts and component scores remain untouched. Only canonical result
ownership is reconciled, after verifying the current-term curriculum and the
destination's effective teacher assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.classes.models import ClassRoom
from app.modules.student_academics.curriculum_models import StudentElectiveSelection
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicResultStatus,
    AcademicTerm,
    AcademicTermStatus,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.students.models import StudentEnrollment


@dataclass(frozen=True)
class ResultContinuityDecision:
    result: StudentSubjectResult
    action: str
    reason: str
    destination_teacher_assignment: object | None = None
    applied: bool = False


class AcademicResultContinuityService:
    """Make preview and execution use the same eligibility rules."""

    @staticmethod
    async def inspect(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        academic_session_id: UUID,
        source_level_id: UUID,
        target_class_id: UUID,
        effective_date: date,
        lock: bool = False,
        destination_enrollment_id: UUID | None = None,
    ) -> list[ResultContinuityDecision]:
        target = (
            await db.execute(
                select(ClassRoom).where(
                    ClassRoom.id == target_class_id,
                    ClassRoom.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if target is None or target.academic_level_id != source_level_id:
            # Academic-level changes NEVER forward scores.
            return []

        term = (
            await db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.academic_session_id == academic_session_id,
                    AcademicTerm.status == AcademicTermStatus.OPEN,
                    AcademicTerm.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        if term is None:
            return []

        query = (
            select(StudentSubjectResult)
            .where(
                StudentSubjectResult.tenant_id == tenant_id,
                StudentSubjectResult.student_id == student_id,
                StudentSubjectResult.academic_session_id == academic_session_id,
                StudentSubjectResult.academic_term_id == term.id,
            )
            .order_by(StudentSubjectResult.id)
        )
        if lock:
            query = query.with_for_update()
        results = list((await db.execute(query)).scalars())

        if not results:
            return []

        target_subjects = await CurriculumResolutionService.resolve_class_subjects(
            db,
            tenant_id=tenant_id,
            class_id=target_class_id,
            academic_term_id=term.id,
        )
        eligible_subject_ids = {row.curriculum_subject_id for row in target_subjects}
        elective_subject_ids = {
            row.curriculum_subject_id
            for row in target_subjects
            if row.is_elective and row.elective_group_id is not None
        }
        selected_elective_ids: set[UUID] = set()
        if elective_subject_ids:
            selected_elective_ids = set(
                (
                    await db.execute(
                        select(StudentElectiveSelection.curriculum_subject_id).where(
                            StudentElectiveSelection.tenant_id == tenant_id,
                            StudentElectiveSelection.student_id == student_id,
                            StudentElectiveSelection.curriculum_subject_id.in_(
                                elective_subject_ids
                            ),
                        )
                    )
                ).scalars()
            )
        active_scheme = await AssessmentRepository.get_active_scheme(db, tenant_id)

        decisions: list[ResultContinuityDecision] = []
        for result in results:
            if (
                destination_enrollment_id is not None
                and result.class_id == target_class_id
                and result.student_enrollment_id == destination_enrollment_id
            ):
                continue
            source_class = (
                await db.execute(
                    select(ClassRoom).where(
                        ClassRoom.id == result.class_id,
                        ClassRoom.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            original_enrollment = (
                (
                    await db.execute(
                        select(StudentEnrollment).where(
                            StudentEnrollment.id == result.student_enrollment_id,
                            StudentEnrollment.tenant_id == tenant_id,
                            StudentEnrollment.student_id == student_id,
                            StudentEnrollment.academic_session_id == academic_session_id,
                        )
                    )
                ).scalar_one_or_none()
                if result.student_enrollment_id is not None
                else None
            )

            if source_class is None or source_class.academic_level_id != source_level_id:
                decisions.append(
                    ResultContinuityDecision(result, "historical_only", "Different academic level")
                )
                continue
            if (
                original_enrollment is None
                or original_enrollment.class_id != result.class_id
                or original_enrollment.academic_level_id != source_level_id
            ):
                decisions.append(
                    ResultContinuityDecision(
                        result, "blocked", "Original result enrollment needs review"
                    )
                )
                continue
            if result.curriculum_subject_id not in eligible_subject_ids:
                decisions.append(
                    ResultContinuityDecision(
                        result, "historical_only", "Subject is not offered by destination"
                    )
                )
                continue
            if (
                result.curriculum_subject_id in elective_subject_ids
                and result.curriculum_subject_id not in selected_elective_ids
            ):
                decisions.append(
                    ResultContinuityDecision(
                        result, "historical_only", "Elective subject is not selected by student"
                    )
                )
                continue
            if active_scheme is None or active_scheme.id != result.assessment_scheme_id:
                decisions.append(
                    ResultContinuityDecision(result, "blocked", "Assessment scheme is incompatible")
                )
                continue

            owners = await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
                db,
                tenant_id,
                {target_class_id},
                result.curriculum_subject_id,
                effective_date,
            )
            teacher = owners.get(target_class_id)
            if teacher is None:
                decisions.append(
                    ResultContinuityDecision(result, "blocked", "No destination teacher assignment")
                )
                continue
            action = (
                "automatic"
                if result.status == AcademicResultStatus.DRAFT
                else "requires_confirmation"
            )
            decisions.append(ResultContinuityDecision(result, action, "", teacher))

        return decisions

    @staticmethod
    async def apply(
        db: AsyncSession,
        *,
        actor_id: UUID | None,
        tenant_id: UUID,
        student_id: UUID,
        academic_session_id: UUID,
        source_level_id: UUID,
        destination_enrollment: StudentEnrollment,
        effective_date: date,
        reason: str,
        carry_finalized_results: bool,
    ) -> list[ResultContinuityDecision]:
        decisions = await AcademicResultContinuityService.inspect(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            source_level_id=source_level_id,
            target_class_id=destination_enrollment.class_id,
            effective_date=effective_date,
            lock=True,
            destination_enrollment_id=destination_enrollment.id,
        )
        applied_ids: set[UUID] = set()
        for decision in decisions:
            if decision.action not in {"automatic", "requires_confirmation"}:
                continue
            if decision.action == "requires_confirmation" and not carry_finalized_results:
                continue
            result = decision.result
            teacher = decision.destination_teacher_assignment
            previous_class_id = result.class_id
            previous_enrollment_id = result.student_enrollment_id
            previous_teacher_assignment_id = result.teacher_assignment_id
            result.class_id = destination_enrollment.class_id
            result.student_enrollment_id = destination_enrollment.id
            result.teacher_assignment_id = teacher.id
            result.teacher_membership_id = teacher.teacher_membership_id
            db.add(result)
            applied_ids.add(result.id)
            await StudentAcademicRepository.add_academic_lifecycle_audit(
                db,
                AcademicLifecycleAudit(
                    tenant_id=tenant_id,
                    entity_type="academic_result",
                    entity_id=result.id,
                    action="result_placement_reconciled",
                    previous_status=result.status.value,
                    new_status=result.status.value,
                    acting_admin_id=actor_id,
                    reason=reason,
                    metadata_json={
                        "from_class_id": str(previous_class_id),
                        "to_class_id": str(destination_enrollment.class_id),
                        "from_enrollment_id": str(previous_enrollment_id)
                        if previous_enrollment_id
                        else None,
                        "to_enrollment_id": str(destination_enrollment.id),
                        "from_teacher_assignment_id": str(previous_teacher_assignment_id),
                        "to_teacher_assignment_id": str(teacher.id),
                        "marks_changed": False,
                        "finalized_authorized": bool(
                            decision.action == "requires_confirmation" and carry_finalized_results
                        ),
                    },
                ),
            )
        return [
            replace(decision, applied=decision.result.id in applied_ids) for decision in decisions
        ]
