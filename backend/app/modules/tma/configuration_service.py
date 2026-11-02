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
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicTerm,
    AcademicTermStatus,
    AssessmentComponent,
)
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
    scopes, classes, lead_teachers = [], [], []
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
        classrooms = (
            list(
                (
                    await db.execute(
                        select(ClassRoom)
                        .options(
                            selectinload(ClassRoom.academic_level),
                            selectinload(ClassRoom.arm_label_ref),
                        )
                        .where(
                            ClassRoom.tenant_id == actor.tenant_id,
                            ClassRoom.academic_level_id.in_({level.id for level, _, _ in rows}),
                            ClassRoom.is_active.is_(True),
                            ClassRoom.archived_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if rows
            else []
        )
        resolved = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=actor.tenant_id,
            class_ids={room.id for room in classrooms},
            academic_term_id=term.id,
            skip_unresolvable=True,
        )
        owners = await StudentAcademicRepository.get_teacher_assignments_for_subjects_on_date(
            db,
            actor.tenant_id,
            {room.id for room in classrooms},
            {subject.id for _, subject, _ in rows},
            date.today(),
        )
        eligible_by_scope = {}
        for room in classrooms:
            for subject in resolved.get(room.id, []):
                eligible_by_scope.setdefault(
                    (room.academic_level_id, subject.curriculum_subject_id), set()
                ).add(room.id)
        teachers_by_scope = {}
        rooms_by_id = {room.id: room for room in classrooms}
        for owner in owners:
            key = (rooms_by_id[owner.class_id].academic_level_id, owner.curriculum_subject_id)
            if owner.class_id in eligible_by_scope.get(key, set()):
                teachers_by_scope.setdefault(key, set()).add(owner.teacher_membership_id)
        for level, subject, pool in rows:
            key = (level.id, subject.id)
            if not eligible_by_scope.get(key):
                continue
            if not isinstance(actor, TenantAdmin) and (
                not isinstance(actor, TeacherMembership)
                or actor.status != TeacherMembershipStatus.ACTIVE
                or actor.id not in teachers_by_scope.get(key, set())
            ):
                continue
            scopes.append(
                {
                    "academic_level_id": level.id,
                    "curriculum_subject_id": subject.id,
                    "level_name": level.name,
                    "subject_name": pool.name,
                }
            )
        visible_levels = {scope["academic_level_id"] for scope in scopes}
        classes = [
            {"id": room.id, "name": room.display_name, "academic_level_id": room.academic_level_id}
            for room in classrooms
            if room.academic_level_id in visible_levels
        ]
        if isinstance(actor, TenantAdmin):
            teacher_ids = set().union(*teachers_by_scope.values()) if teachers_by_scope else set()
            memberships = (
                (
                    await db.execute(
                        select(TeacherMembership, TeacherAccount)
                        .join(
                            TeacherAccount,
                            TeacherAccount.id == TeacherMembership.teacher_account_id,
                        )
                        .where(
                            TeacherMembership.tenant_id == actor.tenant_id,
                            TeacherMembership.id.in_(teacher_ids),
                            TeacherMembership.status == TeacherMembershipStatus.ACTIVE,
                        )
                    )
                ).all()
                if teacher_ids
                else []
            )
            teachers = {
                membership.id: (
                    " ".join(
                        part for part in (account.first_name, account.last_name) if part
                    ).strip()
                    or account.email
                )
                for membership, account in memberships
            }
            for scope in scopes:
                key = (scope["academic_level_id"], scope["curriculum_subject_id"])
                for teacher_id in sorted(
                    teachers_by_scope.get(key, set()),
                    key=lambda value: (teachers.get(value, "").casefold(), str(value)),
                ):
                    if teacher_id in teachers:
                        lead_teachers.append(
                            {
                                "teacher_membership_id": teacher_id,
                                "academic_level_id": key[0],
                                "curriculum_subject_id": key[1],
                                "display_name": teachers[teacher_id],
                            }
                        )
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


async def list_authoring_terms(db: AsyncSession, actor: TMAAuthor) -> list[dict]:
    """Return school term history for both teacher and admin TMA dashboards."""
    rows = (
        await db.execute(
            select(AcademicTerm, AcademicSession)
            .join(
                AcademicSession,
                AcademicSession.id == AcademicTerm.academic_session_id,
            )
            .where(
                AcademicTerm.tenant_id == actor.tenant_id,
                AcademicSession.tenant_id == actor.tenant_id,
                AcademicTerm.status != AcademicTermStatus.DRAFT,
            )
            .order_by(AcademicTerm.created_at.desc(), AcademicTerm.id.desc())
        )
    ).all()
    return [
        {
            "id": term.id,
            "name": term.name.value,
            "session_name": session.name,
            "status": term.status.value,
            "is_current": bool(term.is_current),
        }
        for term, session in rows
    ]
