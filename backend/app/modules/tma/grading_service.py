"""Objective TMA grading and strictly scoped academic-component score writes."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AssessmentSchemeStatus,
    StudentAssessmentScore,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.students.models import StudentEnrollment
from app.modules.tma.models import TMAAssignment, TMAQuestion, TMAQuestionOption


class TMAGradingService:
    """Never replace other assessment components or a pre-existing CA1 score."""

    @staticmethod
    def calculate_raw_score(
        questions: list[tuple[TMAQuestion, list[TMAQuestionOption]]],
        selections: dict[uuid.UUID, uuid.UUID],
    ) -> tuple[int, int]:
        correct = 0
        for question, options in questions:
            selected = selections.get(question.id)
            if selected is not None and any(
                option.id == selected and option.is_correct for option in options
            ):
                correct += 1
        return correct, len(questions)

    @staticmethod
    def scaled_component_score(correct: int, total: int, maximum: Decimal) -> Decimal:
        if total <= 0 or not 0 <= correct <= total or maximum <= 0:
            raise ConflictException("Invalid TMA score or assessment allocation.")
        return (
            Decimal(correct) * maximum / Decimal(total)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    async def persist_component_score(
        db: AsyncSession, *, tenant_id: uuid.UUID,
        student_id: uuid.UUID, enrollment: StudentEnrollment,
        assignment: TMAAssignment, correct: int, total: int,
    ) -> Decimal:
        """Write only this TMA's component in the academic DRAFT result.

        Caller owns the transaction and holds the TMA attempt lock. Failures
        abort submission. Existing component scores are never overwritten.
        """
        await __import__(
            "app.modules.student_academics.write_guard",
            fromlist=["ensure_academic_write_window"],
        ).ensure_academic_write_window(db, tenant_id=tenant_id)
        scheme = await AssessmentRepository.get_active_scheme(db, tenant_id)
        component = await AssessmentRepository.get_component(
            db, tenant_id, assignment.assessment_component_id,
        )
        if (
            scheme is None or scheme.status != AssessmentSchemeStatus.ACTIVE
            or component is None or not component.is_active
            or component.assessment_scheme_id != scheme.id
            or component.is_hybrid
        ):
            raise ConflictException("TMA requires an active non-hybrid assessment component.")
        if enrollment.class_id is None:
            raise ConflictException("Student has no active classroom.")
        score = TMAGradingService.scaled_component_score(
            correct, total, component.maximum_score,
        )
        results = await StudentAcademicRepository.get_results_by_scope_batch(
            db, tenant_id, {student_id}, assignment.curriculum_subject_id,
            assignment.academic_session_id, assignment.academic_term_id, lock=True,
        )
        result = results.get(student_id)
        if result is not None:
            if result.status != AcademicResultStatus.DRAFT:
                raise ConflictException("The academic result is already submitted or locked.")
            if result.assessment_scheme_id != scheme.id:
                raise ConflictException("Result uses a different assessment scheme.")
            if result.class_id != enrollment.class_id:
                raise ConflictException("Result enrollment/class scope does not match.")
            existing = await StudentAcademicRepository.get_component_scores_batch(
                db, tenant_id, {result.id}, component.id, lock=True,
            )
            if result.id in existing:
                raise ConflictException(
                    "CA component already has a score. TMA will not overwrite it."
                )
        else:
            owners = await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
                db, tenant_id, {enrollment.class_id},
                assignment.curriculum_subject_id, date.today(),
            )
            teacher_assignment = owners.get(enrollment.class_id)
            if teacher_assignment is None:
                raise ConflictException("No current teacher assignment can own the academic result.")
            curricula = await CurriculumResolutionService.resolve_student_subjects(
                db, tenant_id=tenant_id, student_id=student_id,
                academic_term_id=assignment.academic_term_id,
            )
            subject = next(
                (row for row in curricula if row.curriculum_subject_id == assignment.curriculum_subject_id),
                None,
            )
            if subject is None:
                raise ConflictException("Student is no longer eligible for this subject.")
            result = StudentSubjectResult(
                tenant_id=tenant_id, student_id=student_id,
                class_id=enrollment.class_id, subject_id=subject.subject_id,
                curriculum_subject_id=assignment.curriculum_subject_id,
                teacher_membership_id=teacher_assignment.teacher_membership_id,
                teacher_assignment_id=teacher_assignment.id,
                student_enrollment_id=enrollment.id,
                academic_session_id=assignment.academic_session_id,
                academic_term_id=assignment.academic_term_id,
                assessment_scheme_id=scheme.id,
                total_score=Decimal("0"),
                status=AcademicResultStatus.DRAFT,
                recorded_by_actor_type="tma", recorded_by_actor_id=student_id,
            )
            await StudentAcademicRepository.upsert_result(db, result)
        await StudentAcademicRepository.add_component_scores_batch(
            db, [
                StudentAssessmentScore(
                    tenant_id=tenant_id,
                    student_subject_result_id=result.id,
                    assessment_component_id=component.id,
                    score=score,
                )
            ],
        )
        components = await StudentAcademicRepository.list_result_component_scores(
            db, tenant_id, result,
        )
        persisted = [row.score for _, row in components if row is not None]
        result.total_score = sum(persisted, Decimal("0"))
        complete = bool(components) and all(row is not None for _, row in components)
        if complete:
            scale = await StudentAcademicRepository.find_grade_for_score(
                db, tenant_id, result.total_score,
            )
            result.grade = scale.grade if scale else None
            result.remark = scale.remark if scale else None
            result.grading_scale_id = scale.id if scale else None
        else:
            result.grade = None
            result.remark = None
            result.grading_scale_id = None
        await StudentAcademicRepository.upsert_result(db, result)
        return score
