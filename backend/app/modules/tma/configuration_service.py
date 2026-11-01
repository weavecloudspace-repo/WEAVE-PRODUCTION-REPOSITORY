"""Authoring choices shared by tenant admins and authorized teachers."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException
from app.modules.classes.models import AcademicLevel, ClassRoom
from sqlalchemy.orm import selectinload
from app.modules.subjects.models import Subject
from app.modules.student_academics.curriculum_models import Curriculum, CurriculumSubject
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.models import AssessmentComponent
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.teachers.models import TeacherAccount, TeacherMembership, TeacherMembershipStatus
from app.modules.tenant_admins.models import TenantAdmin


async def get_authoring_configuration(db: AsyncSession, actor: TMAAuthor) -> dict:
    term = await StudentAcademicRepository.get_current_term(db, actor.tenant_id)
    scheme = await AssessmentRepository.get_active_scheme(db, actor.tenant_id)

    components = []
    if scheme:
        rows = (
            (
                await db.execute(
                    select(AssessmentComponent).where(
                        AssessmentComponent.tenant_id == actor.tenant_id,
                        AssessmentComponent.assessment_scheme_id == scheme.id,
                        AssessmentComponent.is_active.is_(True),
                        AssessmentComponent.is_hybrid.is_(False),
                        AssessmentComponent.is_examinable.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        components = [
            {"id": row.id, "name": row.name, "maximum_score": row.maximum_score} for row in rows
        ]
    scopes = []
    if term:
        rows = (
            await db.execute(
                select(AcademicLevel, CurriculumSubject, Subject)
                .join(
                    Curriculum,
                    (Curriculum.academic_level_id == AcademicLevel.id)
                    & (Curriculum.tenant_id == actor.tenant_id),
                )
                .join(
                    CurriculumSubject,
                    (CurriculumSubject.curriculum_id == Curriculum.id)
                    & (CurriculumSubject.tenant_id == actor.tenant_id),
                )
                .join(
                    Subject,
                    (Subject.id == CurriculumSubject.subject_id)
                    & (Subject.tenant_id == actor.tenant_id),
                )
                .where(
                    AcademicLevel.tenant_id == actor.tenant_id,
                    CurriculumSubject.is_active.is_(True),
                )
                .order_by(AcademicLevel.position, Subject.name)
            )
        ).all()
        for level, subject, pool in rows:
            try:
                await TMAAuthorizationService.require_authoring_access(
                    db,
                    actor=actor,
                    academic_level_id=level.id,
                    curriculum_subject_id=subject.id,
                    academic_term_id=term.id,
                )
            except (ConflictException, ForbiddenException):
                continue
            scopes.append(
                {
                    "academic_level_id": level.id,
                    "curriculum_subject_id": subject.id,
                    "level_name": level.name,
                    "subject_name": pool.name,
                }
            )
    classes = []
    lead_teachers = []
    level_ids = {scope["academic_level_id"] for scope in scopes}
    if level_ids:
        classrooms = (
            (
                await db.execute(
                    select(ClassRoom)
                    .options(
                        selectinload(ClassRoom.academic_level),
                        selectinload(ClassRoom.arm_label_ref),
                    )
                    .where(
                        ClassRoom.tenant_id == actor.tenant_id,
                        ClassRoom.academic_level_id.in_(level_ids),
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        classes = [
            {"id": room.id, "name": room.display_name, "academic_level_id": room.academic_level_id}
            for room in classrooms
        ]
    if term and isinstance(actor, TenantAdmin) and classes:
        classroom_ids_by_level = {}
        for room in classrooms:
            classroom_ids_by_level.setdefault(room.academic_level_id, set()).add(room.id)
        eligible_by_scope = {}
        all_teacher_ids = set()
        for scope in scopes:
            level_id, subject_id = scope["academic_level_id"], scope["curriculum_subject_id"]
            class_ids = classroom_ids_by_level.get(level_id, set())
            resolved = await CurriculumResolutionService.resolve_classes_subjects(
                db,
                tenant_id=actor.tenant_id,
                class_ids=list(class_ids),
                academic_term_id=term.id,
                skip_unresolvable=True,
            )
            eligible_classes = {
                class_id for class_id, subjects in resolved.items()
                if any(row.curriculum_subject_id == subject_id for row in subjects)
            }
            assignments = await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
                db, actor.tenant_id, eligible_classes, subject_id, date.today()
            )
            teacher_ids = {row.teacher_membership_id for row in assignments.values()}
            eligible_by_scope[(level_id, subject_id)] = teacher_ids
            all_teacher_ids.update(teacher_ids)
        if all_teacher_ids:
            memberships = (
                await db.execute(
                    select(TeacherMembership, TeacherAccount)
                    .join(TeacherAccount, TeacherAccount.id == TeacherMembership.teacher_account_id)
                    .where(
                        TeacherMembership.tenant_id == actor.tenant_id,
                        TeacherMembership.id.in_(all_teacher_ids),
                        TeacherMembership.status == TeacherMembershipStatus.ACTIVE,
                    )
                )
            ).all()
            teachers = {
                membership.id: (
                    " ".join(part for part in (account.first_name, account.last_name) if part).strip()
                    or account.email
                )
                for membership, account in memberships
            }
            for (level_id, subject_id), teacher_ids in eligible_by_scope.items():
                for teacher_id in sorted(teacher_ids, key=lambda value: (teachers.get(value, "").casefold(), str(value))):
                    if teacher_id in teachers:
                        lead_teachers.append({
                            "teacher_membership_id": teacher_id,
                            "academic_level_id": level_id,
                            "curriculum_subject_id": subject_id,
                            "display_name": teachers[teacher_id],
                        })
    return {
        "academic_session_id": term.academic_session_id if term else None,
        "academic_term_id": term.id if term else None,
        "term_name": term.name.value if term else None,
        "term_open": bool(term and term.status.value == "open"),
        "scopes": scopes,
        "components": components,
        "classes": classes,
        "lead_teachers": lead_teachers,
    }
