"""Lightweight TMA submissions roster; no analytics or new tables."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.classes.models import ClassRoom
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.repository import TMAAssignmentRepository
from app.modules.tma.reporting_repository import TMAReportingRepository
from app.modules.tma.schemas import (
    TMAParticipationStatus,
    TMASubmissionListResponse,
    TMASubmissionStudentResponse,
)


class TMAReportingService:
    @staticmethod
    async def list_assignment_participation(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        search: str | None = None,
        class_id: uuid.UUID | None = None,
        participation_status: TMAParticipationStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> TMASubmissionListResponse:
        assignment = await TMAAssignmentRepository.get_by_id(
            db, actor.tenant_id, assignment_id,
        )
        if assignment is None:
            raise NotFoundException("TMA assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment,
        )

        classrooms = set(
            (await db.execute(
                select(ClassRoom.id).where(
                    ClassRoom.tenant_id == actor.tenant_id,
                    ClassRoom.academic_level_id == assignment.academic_level_id,
                    ClassRoom.is_active.is_(True),
                    ClassRoom.archived_at.is_(None),
                )
            )).scalars().all()
        )
        subjects_by_class = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=actor.tenant_id,
            class_ids=classrooms,
            academic_term_id=assignment.academic_term_id,
            skip_unresolvable=True,
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db, actor.tenant_id, assignment.academic_term_id,
        )
        regular_classes: set[uuid.UUID] = set()
        grouped_elective_classes: set[uuid.UUID] = set()
        for current_class_id, subjects in subjects_by_class.items():
            for subject in subjects:
                if subject.curriculum_subject_id != assignment.curriculum_subject_id:
                    continue
                if (
                    term is not None and term.is_current
                    and subject.is_elective and subject.elective_group_id is not None
                ):
                    grouped_elective_classes.add(current_class_id)
                else:
                    regular_classes.add(current_class_id)
                break

        students, total = await TMAReportingRepository.list_participation(
            db,
            assignment=assignment,
            regular_class_ids=regular_classes,
            grouped_elective_class_ids=grouped_elective_classes,
            search=search,
            class_id=class_id,
            participation_status=participation_status,
            offset=offset,
            limit=limit,
        )
        return TMASubmissionListResponse(
            assignment_id=assignment.id,
            items=[TMASubmissionStudentResponse.model_validate(row) for row in students],
            total=total,
            offset=offset,
            limit=limit,
        )
