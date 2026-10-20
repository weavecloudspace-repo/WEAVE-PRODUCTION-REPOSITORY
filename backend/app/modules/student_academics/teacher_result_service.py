"""Teacher-owned manual assessment score entry.

Teachers may record only non-examinable assessment components. Examinable
components remain immutable from the teacher workspace because they are owned
by CBT/admin workflows. Tenant administrators continue to use the canonical
result service and may edit every component.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.student_academics.hybrid_scores import component_is_complete
from app.modules.student_academics.assessment_examinability import (
    is_assessment_component_examinable,
)
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSessionStatus,
    AcademicTermStatus,
    AssessmentSchemeStatus,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.schemas import (
    StudentSubjectResultResponse,
    StudentSubjectResultUpsert,
)
from app.modules.student_academics.service import StudentAcademicService
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.teachers.models import TeacherMembership


class TeacherResultService:
    """Persist teacher-entered scores without allowing exam-score mutation."""

    @classmethod
    async def upsert_manual_scores(
        cls,
        db: AsyncSession,
        *,
        teacher: TeacherMembership,
        payload: StudentSubjectResultUpsert,
    ) -> StudentSubjectResultResponse:
        tenant_id = teacher.tenant_id
        await ensure_academic_write_window(db, tenant_id=tenant_id)

        if payload.status != AcademicResultStatus.DRAFT:
            raise ForbiddenException(
                "Teachers may record manual component scores only while the result is a draft."
            )
        if not payload.component_scores:
            raise BadRequestException("Provide at least one manual assessment component score.")

        assignment, curriculum_subject = await StudentAcademicService._resolve_assignment_context(
            db,
            tenant_id,
            payload,
        )
        if assignment.teacher_membership_id != teacher.id:
            raise ForbiddenException(
                "Teachers may record scores only for their own active subject assignments."
            )

        student = await StudentRepository.get_by_id(db, tenant_id, payload.student_id)
        if student is None:
            raise NotFoundException("Student not found.")

        session = await StudentAcademicRepository.get_academic_session_by_id(
            db,
            tenant_id,
            payload.academic_session_id,
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db,
            tenant_id,
            payload.academic_term_id,
        )
        if session is None or term is None or term.academic_session_id != session.id:
            raise NotFoundException("Academic session or term is invalid.")
        if not session.is_current or session.status != AcademicSessionStatus.OPEN:
            raise ConflictException("Results can only be modified in the current open session.")
        if not term.is_current or term.status != AcademicTermStatus.OPEN:
            raise ConflictException("Results can only be modified in the current open term.")

        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db,
            tenant_id,
            student.id,
            session.id,
        )
        if enrollment is None or enrollment.class_id != assignment.class_id:
            raise ForbiddenException(
                "Student is not enrolled in the assigned class for this session."
            )

        resolved_subjects = await CurriculumResolutionService.resolve_student_subjects(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_term_id=term.id,
        )
        if curriculum_subject.id not in {item.curriculum_subject_id for item in resolved_subjects}:
            raise ForbiddenException(
                "This subject is not available to the student's class specialization for this term."
            )

        if (
            assignment.effective_from
            and term.end_date
            and assignment.effective_from > term.end_date
        ):
            raise ConflictException("Teacher assignment starts after the term ends.")
        if (
            assignment.effective_to
            and term.start_date
            and assignment.effective_to < term.start_date
        ):
            raise ConflictException("Teacher assignment ends before the term starts.")

        existing = await StudentAcademicRepository.get_result_by_scope(
            db,
            tenant_id,
            student.id,
            assignment.id,
            session.id,
            term.id,
            lock=True,
        )
        if existing is not None and existing.status != AcademicResultStatus.DRAFT:
            raise ConflictException("Only draft scores can be edited by teachers.")

        scheme = await AssessmentRepository.get_active_scheme(db, tenant_id)
        if scheme is None or scheme.status != AssessmentSchemeStatus.ACTIVE:
            raise ConflictException("An active assessment scheme is required before score entry.")

        components = await AssessmentRepository.list_components(db, tenant_id, scheme.id)
        if not components or sum(
            (component.maximum_score for component in components), Decimal("0")
        ) != Decimal("100"):
            raise ConflictException("The active assessment scheme must total 100.")

        component_by_id = {component.id: component for component in components}
        requested_ids = {item.assessment_component_id for item in payload.component_scores}
        invalid_ids = requested_ids - set(component_by_id)
        if invalid_ids:
            raise BadRequestException(
                "One or more scores reference an invalid assessment component."
            )

        protected = [
            component_by_id[component_id].name
            for component_id in requested_ids
            if is_assessment_component_examinable(component_by_id[component_id])
            and not component_by_id[component_id].is_hybrid
        ]
        if protected:
            raise ForbiddenException(
                "Teachers cannot change examinable component scores. "
                "Those scores are managed by CBT or a tenant administrator."
            )

        merged_scores: dict = {}
        existing_by_component = {}
        if existing is not None:
            existing_rows = await StudentAcademicRepository.list_result_component_scores(
                db, tenant_id, existing,
            )
            existing_by_component = {
                component.id: score for component, score in existing_rows if score is not None
            }
            merged_scores = {
                component_id: score.score for component_id, score in existing_by_component.items()
            }

        for score_input in payload.component_scores:
            component = component_by_id[score_input.assessment_component_id]
            if component.is_hybrid:
                if score_input.cbt_score is not None or score_input.score is not None:
                    raise ForbiddenException("Teachers cannot edit the CBT portion of hybrid scores.")
                if "theory_score" not in score_input.model_fields_set:
                    raise BadRequestException("Provide theory_score for a hybrid component.")
                record = existing_by_component.get(component.id)
                if record is None or record.cbt_score is None or record.cbt_maximum_score is None:
                    raise ConflictException("Theory entry requires a synchronized CBT result.")
                theory_max = component.maximum_score - record.cbt_maximum_score
                if theory_max <= 0:
                    raise ConflictException("This examination allocated all marks to CBT.")
                if score_input.theory_score is not None and score_input.theory_score > theory_max:
                    raise BadRequestException(f"Theory score cannot exceed {theory_max}.")
                record.theory_score = score_input.theory_score
                merged_scores[component.id] = record.cbt_score + (record.theory_score or Decimal("0"))
                continue
            if score_input.theory_score is not None or score_input.cbt_score is not None:
                raise BadRequestException("CBT and theory portions require a hybrid component.")
            if score_input.score is None:
                merged_scores.pop(component.id, None)
                continue
            if score_input.score > component.maximum_score:
                raise BadRequestException(
                    f"{component.name} score cannot exceed {component.maximum_score}."
                )
            merged_scores[component.id] = score_input.score

        if existing is None and not merged_scores:
            raise BadRequestException("At least one manual component must contain a score.")

        total = sum(merged_scores.values(), Decimal("0"))
        complete = len(merged_scores) == len(components) and all(
            not component.is_hybrid or component_is_complete(component, existing_by_component.get(component.id))
            for component in components
        )
        grade = remark = None
        grading_scale_id = None
        if complete:
            scale = await StudentAcademicRepository.find_grade_for_score(db, tenant_id, total)
            if scale is not None:
                grade = scale.grade
                remark = scale.remark
                grading_scale_id = scale.id

        is_new = existing is None
        if existing is None:
            result = StudentSubjectResult(
                tenant_id=tenant_id,
                student_id=student.id,
                class_id=assignment.class_id,
                subject_id=curriculum_subject.subject_id,
                teacher_membership_id=assignment.teacher_membership_id,
                curriculum_subject_id=curriculum_subject.id,
                teacher_assignment_id=assignment.id,
                student_enrollment_id=enrollment.id,
                academic_session_id=session.id,
                academic_term_id=term.id,
                assessment_scheme_id=scheme.id,
                grading_scale_id=grading_scale_id,
                total_score=total,
                grade=grade,
                remark=remark,
                status=AcademicResultStatus.DRAFT,
                recorded_by_actor_type="teacher",
                recorded_by_actor_id=teacher.id,
            )
        else:
            result = existing
            if result.assessment_scheme_id != scheme.id:
                raise ConflictException(
                    "This result belongs to a different assessment scheme and cannot be edited."
                )
            result.teacher_assignment_id = assignment.id
            result.teacher_membership_id = assignment.teacher_membership_id
            result.total_score = total
            result.grade = grade
            result.remark = remark
            result.grading_scale_id = grading_scale_id
            result.recorded_by_actor_type = "teacher"
            result.recorded_by_actor_id = teacher.id

        try:
            result = await StudentAcademicRepository.upsert_result(db, result)
            await StudentAcademicRepository.replace_result_scores(db, result, merged_scores)
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Concurrent modification of this result.") from exc

        await StudentAcademicService._record_academic_lifecycle(
            db,
            tenant_id=tenant_id,
            entity_type="student_result",
            entity_id=result.id,
            action="create" if is_new else "edit_manual_components",
            previous_status=None if is_new else AcademicResultStatus.DRAFT.value,
            new_status=AcademicResultStatus.DRAFT.value,
            acting_admin_id=None,
            metadata={"source": "teacher_manual_components"},
        )
        await db.commit()
        return await StudentAcademicService._build_result_response(db, result)
