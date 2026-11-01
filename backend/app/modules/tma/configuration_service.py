"""Authoring choices shared by tenant admins and authorized teachers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException
from app.modules.classes.models import AcademicLevel, ClassRoom
from sqlalchemy.orm import selectinload
from app.modules.subjects.models import Subject
from app.modules.student_academics.curriculum_models import Curriculum, CurriculumSubject
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.models import AssessmentComponent
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService


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
    return {
        "academic_session_id": term.academic_session_id if term else None,
        "academic_term_id": term.id if term else None,
        "term_name": term.name.value if term else None,
        "term_open": bool(term and term.status.value == "open"),
        "scopes": scopes,
        "components": components,
        "classes": classes,
    }
