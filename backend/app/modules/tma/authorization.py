"""Authoring and student eligibility guards for level-wide TMA assignments."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.classes.models import ClassRoom
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.models import AcademicTermStatus
from app.modules.students.models import Student
from app.modules.students.repository import StudentEnrollmentRepository
from app.modules.teachers.models import TeacherMembership, TeacherMembershipStatus
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.models import TMAActorType, TMAAssignment, TMAAssignmentStatus, TMAQuestion

TMAAuthor = TenantAdmin | TeacherMembership


class TMAAuthorizationService:
    """Only teacher assignment, curriculum and current enrollment grant access."""

    @staticmethod
    def actor_type(actor: TMAAuthor) -> TMAActorType:
        if isinstance(actor, TenantAdmin):
            return TMAActorType.TENANT_ADMIN
        if isinstance(actor, TeacherMembership):
            return TMAActorType.TEACHER
        raise ForbiddenException("TMA author must be a teacher or administrator.")

    @staticmethod
    async def require_authoring_access(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        academic_level_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> None:
        tenant_id = actor.tenant_id
        classrooms = list(
            (
                await db.execute(
                    select(ClassRoom).where(
                        ClassRoom.tenant_id == tenant_id,
                        ClassRoom.academic_level_id == academic_level_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not classrooms:
            raise ConflictException("No active classrooms exist for this level.")
        resolved = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=tenant_id,
            class_ids=[room.id for room in classrooms],
            academic_term_id=academic_term_id,
            skip_unresolvable=True,
        )
        eligible_ids = {
            room.id
            for room in classrooms
            if any(
                row.curriculum_subject_id == curriculum_subject_id
                for row in resolved.get(room.id, [])
            )
        }
        if not eligible_ids:
            raise ForbiddenException("This subject is not available to this level and term.")
        if isinstance(actor, TenantAdmin):
            return
        if actor.status != TeacherMembershipStatus.ACTIVE:
            raise ForbiddenException("An active teacher membership is required.")
        assignments = await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
            db,
            tenant_id,
            eligible_ids,
            curriculum_subject_id,
            date.today(),
        )
        if not any(row.teacher_membership_id == actor.id for row in assignments.values()):
            raise ForbiddenException("You do not currently teach this level and subject.")

    @staticmethod
    async def require_assignment_access(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment: TMAAssignment,
    ) -> None:
        if actor.tenant_id != assignment.tenant_id:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_authoring_access(
            db,
            actor=actor,
            academic_level_id=assignment.academic_level_id,
            curriculum_subject_id=assignment.curriculum_subject_id,
            academic_term_id=assignment.academic_term_id,
        )

    @staticmethod
    def require_draft_assignment(assignment: TMAAssignment) -> None:
        if assignment.status != TMAAssignmentStatus.DRAFT:
            raise ConflictException("Only draft assignments can be edited.")

    @staticmethod
    def require_assignment_management(actor: TMAAuthor, assignment: TMAAssignment) -> None:
        if actor.tenant_id != assignment.tenant_id:
            raise NotFoundException("Assignment not found.")
        if isinstance(actor, TenantAdmin):
            return
        lead_id = getattr(assignment, "lead_teacher_membership_id", None)
        if lead_id is None and assignment.created_by_actor_type == TMAActorType.TEACHER:
            # Backward compatibility for teacher-authored assignments created
            # before the lead-teacher migration.
            lead_id = assignment.created_by_actor_id
        if not isinstance(actor, TeacherMembership) or actor.id != lead_id:
            raise ForbiddenException(
                "Only the assigned lead teacher or an administrator may manage this TMA."
            )

    @staticmethod
    def require_question_edit_access(
        actor: TMAAuthor,
        assignment: TMAAssignment,
        question: TMAQuestion,
    ) -> None:
        if question.tenant_id != assignment.tenant_id or question.assignment_id != assignment.id:
            raise NotFoundException("Question not found.")
        if isinstance(actor, TenantAdmin):
            return
        if (
            question.author_actor_type == TMAActorType.TEACHER
            and question.author_actor_id == actor.id
        ):
            return
        TMAAuthorizationService.require_assignment_management(actor, assignment)

    @staticmethod
    async def require_student_eligibility(
        db: AsyncSession,
        *,
        student: Student,
        assignment: TMAAssignment,
    ):
        if student.tenant_id != assignment.tenant_id:
            raise NotFoundException("Assignment not found.")
        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db,
            student.tenant_id,
            student.id,
            assignment.academic_session_id,
        )
        if (
            enrollment is None
            or enrollment.class_id is None
            or enrollment.academic_level_id != assignment.academic_level_id
        ):
            raise ForbiddenException("You are not enrolled in the assignment's academic level.")
        subjects = await CurriculumResolutionService.resolve_student_subjects(
            db,
            tenant_id=student.tenant_id,
            student_id=student.id,
            academic_term_id=assignment.academic_term_id,
        )
        if assignment.curriculum_subject_id not in {
            subject.curriculum_subject_id for subject in subjects
        }:
            raise ForbiddenException("This assignment is not in your enrolled subjects.")
        return enrollment

    @staticmethod
    async def require_open_term(db: AsyncSession, assignment: TMAAssignment) -> None:
        term = await StudentAcademicRepository.get_term_by_id(
            db,
            assignment.tenant_id,
            assignment.academic_term_id,
        )
        if (
            term is None
            or term.status != AcademicTermStatus.OPEN
            or not term.is_current
            or term.academic_session_id != assignment.academic_session_id
        ):
            raise ConflictException("The current academic term must be open for TMA activity.")
