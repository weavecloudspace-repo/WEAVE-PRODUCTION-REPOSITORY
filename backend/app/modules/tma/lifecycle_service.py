"""Explicit TMA publication and reopening workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.cache.events import flush_cache_invalidation_events

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.classes.models import ClassRoom
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.models import AcademicSessionStatus
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.tma.academic_guard import TMAAcademicGuard
from app.modules.tma.assignment_service import TMAAssignmentService
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus
from app.modules.tma.repository import (
    TMAAssignmentRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)


class TMALifecycleService:
    @staticmethod
    async def reopen_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        closes_at: datetime,
    ) -> TMAAssignment:
        # Serialize with result finalization before locking the TMA row.
        await TMAAcademicGuard.lock(db, actor.tenant_id)
        assignment = await TMAAssignmentRepository.get_by_id(
            db, actor.tenant_id, assignment_id, lock=True
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db, actor=actor, assignment=assignment
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        if assignment.status != TMAAssignmentStatus.CLOSED:
            raise ConflictException("Only a closed TMA can be reopened.")
        if (
            getattr(assignment, "zero_grading_requested_at", None) is not None
            and getattr(assignment, "zero_grading_completed_at", None) is None
        ):
            raise ConflictException(
                "Missed-deadline grading is still processing. Wait for grading "
                "to complete or ask an administrator to resolve blocked students "
                "before reopening this TMA."
            )
        if closes_at <= datetime.now(timezone.utc):
            raise ConflictException("Choose a future deadline before reopening this TMA.")
        await TMAAcademicGuard.require_draft_results(db, assignment)
        # Readiness validates the deadline on the assignment object. The
        # submitted deadline and the ACTIVE transition commit atomically.
        assignment.closes_at = closes_at
        errors = await TMALifecycleService._readiness_errors(db, assignment)
        if errors:
            raise ConflictException("TMA cannot be reopened: " + "; ".join(errors))
        revision = await TMARevisionRepository.get_by_number(
            db, actor.tenant_id, assignment.id, assignment.current_revision_number
        )
        if revision is None or revision.published_at is None:
            raise ConflictException("A published revision is required to reopen TMA.")
        assignment.status = TMAAssignmentStatus.ACTIVE
        assignment.closed_at = None
        assignment.zero_grading_error = None
        assignment.zero_grading_requested_at = None
        assignment.zero_grading_completed_at = None
        await TMAAssignmentRepository.save(db, assignment)
        await db.commit()
        await flush_cache_invalidation_events(db)
        return assignment

    @staticmethod
    async def _readiness_errors(db: AsyncSession, assignment: TMAAssignment) -> list[str]:
        errors: list[str] = []
        deadline = getattr(assignment, "closes_at", None)
        if deadline is None:
            errors.append("Set a submission deadline before publishing this TMA.")
        elif deadline <= datetime.now(timezone.utc):
            errors.append("Set a future submission deadline before publishing this TMA.")
        session = await StudentAcademicRepository.get_academic_session_by_id(
            db,
            assignment.tenant_id,
            assignment.academic_session_id,
        )
        if (
            session is None
            or session.status != AcademicSessionStatus.OPEN
            or not session.is_current
        ):
            errors.append("Current academic session is not open.")
        try:
            await TMAAuthorizationService.require_open_term(db, assignment)
        except ConflictException as exc:
            errors.append(exc.detail)
        scheme = await AssessmentRepository.get_active_scheme(db, assignment.tenant_id)
        component = await AssessmentRepository.get_component(
            db,
            assignment.tenant_id,
            assignment.assessment_component_id,
        )
        if (
            scheme is None
            or component is None
            or not component.is_active
            or component.assessment_scheme_id != scheme.id
            or component.is_hybrid
            or component.is_examinable
        ):
            errors.append(
                "TMA requires an active, non-examinable, non-hybrid assessment component."
            )
        revision = await TMARevisionRepository.get_by_number(
            db,
            assignment.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if revision is None or revision.invalidated_at is not None:
            errors.append("A valid current revision is required.")
            return errors
        # A TMA covers the entire level. Every classroom offering this
        # subject must have grading ownership BEFORE the TMA is published.
        classrooms = list(
            (
                await db.execute(
                    select(ClassRoom)
                    .options(
                        selectinload(ClassRoom.academic_level),
                        selectinload(ClassRoom.arm_label_ref),
                    )
                    .where(
                        ClassRoom.tenant_id == assignment.tenant_id,
                        ClassRoom.academic_level_id == assignment.academic_level_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not classrooms:
            errors.append("No active classroom exists for this academic level.")
        else:
            curriculum = await CurriculumResolutionService.resolve_classes_subjects(
                db,
                tenant_id=assignment.tenant_id,
                class_ids=[room.id for room in classrooms],
                academic_term_id=assignment.academic_term_id,
                skip_unresolvable=True,
            )
            eligible = {
                room.id
                for room in classrooms
                if any(
                    item.curriculum_subject_id == assignment.curriculum_subject_id
                    for item in curriculum.get(room.id, [])
                )
            }
            if not eligible:
                errors.append("No classroom offers this subject in the selected term.")
            else:
                teachers = (
                    await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
                        db,
                        assignment.tenant_id,
                        eligible,
                        assignment.curriculum_subject_id,
                        date.today(),
                    )
                )
                room_names = {
                    room.id: getattr(room, "display_name", "This classroom") for room in classrooms
                }
                for room_id in sorted(eligible.difference(teachers), key=str):
                    errors.append(
                        f"{room_names[room_id]} has no assigned subject teacher. "
                        "Assign a teacher before publishing this TMA."
                    )
        questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            assignment.tenant_id,
            revision.id,
        )
        if not questions:
            errors.append("Add questions before activation.")
        for question, options in questions:
            if not question.question_text and question.image_asset_id is None:
                errors.append(f"Question {question.position} has no content.")
            if len(options) < 4 or sum(option.is_correct for option in options) != 1:
                errors.append(
                    f"Question {question.position} requires at least 4 options and one correct."
                )
        return errors

    @staticmethod
    async def get_assignment_readiness(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> list[str]:
        assignment = await TMAAssignmentService.get_assignment(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        return await TMALifecycleService._readiness_errors(db, assignment)

    @staticmethod
    async def activate_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> TMAAssignment:
        await TMAAcademicGuard.lock(db, actor.tenant_id)
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            actor.tenant_id,
            assignment_id,
            lock=True,
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db,
            actor=actor,
            assignment=assignment,
        )
        TMAAuthorizationService.require_assignment_management(actor, assignment)
        TMAAuthorizationService.require_draft_assignment(assignment)
        if assignment.closes_at is None or assignment.closes_at <= datetime.now(timezone.utc):
            raise ConflictException("Set a future submission deadline before publishing.")
        errors = await TMALifecycleService._readiness_errors(db, assignment)
        if errors:
            raise ConflictException("TMA is not ready: " + "; ".join(errors))
        revision = await TMARevisionRepository.get_by_number(
            db,
            actor.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if revision is None:
            raise ConflictException("Revision missing.")
        revision.published_at = datetime.now(timezone.utc)
        revision.eligibility_tracking_started_at = revision.published_at
        assignment.status = TMAAssignmentStatus.ACTIVE
        assignment.activated_at = datetime.now(timezone.utc)
        await TMARevisionRepository.save(db, revision)
        await TMAAssignmentRepository.save(db, assignment)
        await db.commit()
        await flush_cache_invalidation_events(db)
        return assignment
