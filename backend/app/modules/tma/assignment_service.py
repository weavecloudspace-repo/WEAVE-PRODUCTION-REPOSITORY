"""Basic level-wide TMA authoring services; student workflows live elsewhere."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.models import AcademicSessionStatus, AssessmentSchemeStatus
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import TMAAssignment, TMAAssignmentRevision, TMAAssignmentStatus
from app.modules.tma.repository import (
    TMAAssignmentRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)
from app.modules.tma.schemas import TMAAssignmentCreate, TMAAssignmentUpdate


class TMAAssignmentService:
    @staticmethod
    async def _validate_scope(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: TMAAssignmentCreate,
    ) -> None:
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
            raise BadRequestException("Academic session and term do not match.")
        if session.status != AcademicSessionStatus.OPEN or not session.is_current:
            raise ConflictException("The current academic session must be open.")
        scheme = await AssessmentRepository.get_active_scheme(db, tenant_id)
        component = await AssessmentRepository.get_component(
            db,
            tenant_id,
            payload.assessment_component_id,
        )
        if (
            scheme is None
            or scheme.status != AssessmentSchemeStatus.ACTIVE
            or component is None
            or not component.is_active
            or component.assessment_scheme_id != scheme.id
        ):
            raise ConflictException("Select an active component in the current assessment scheme.")
        if component.is_hybrid:
            raise ConflictException("The initial TMA flow cannot own hybrid/CBT components.")

    @staticmethod
    async def create_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        payload: TMAAssignmentCreate,
    ) -> TMAAssignment:
        try:
            await TMAAssignmentService._validate_scope(
                db,
                tenant_id=actor.tenant_id,
                payload=payload,
            )
            await TMAAuthorizationService.require_authoring_access(
                db,
                actor=actor,
                academic_level_id=payload.academic_level_id,
                curriculum_subject_id=payload.curriculum_subject_id,
                academic_term_id=payload.academic_term_id,
            )
            existing = await TMAAssignmentRepository.get_by_component_scope(
                db,
                actor.tenant_id,
                **payload.model_dump(exclude={"closes_at"}),
            )
            if existing is not None:
                raise ConflictException(
                    "This level, subject, term and component already have a TMA."
                )
            assignment = TMAAssignment(
                tenant_id=actor.tenant_id,
                **payload.model_dump(),
                created_by_actor_type=TMAAuthorizationService.actor_type(actor),
                created_by_actor_id=actor.id,
                current_revision_number=1,
            )
            await TMAAssignmentRepository.add(db, assignment)
            await TMARevisionRepository.add(
                db,
                TMAAssignmentRevision(
                    tenant_id=actor.tenant_id,
                    assignment_id=assignment.id,
                    revision_number=1,
                ),
            )
            await db.commit()
            await db.refresh(assignment)
            return assignment
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("A TMA already exists for this component scope.") from exc

    @staticmethod
    async def get_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> TMAAssignment:
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            actor.tenant_id,
            assignment_id,
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db,
            actor=actor,
            assignment=assignment,
        )
        return assignment

    @staticmethod
    async def list_assignments(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        academic_term_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TMAAssignment], int]:
        # Administrative listings include all subjects. Teachers see only
        # assignments for which they currently have authoring permission.
        rows, total = await TMAAssignmentRepository.list_for_scope(
            db,
            actor.tenant_id,
            academic_term_id=academic_term_id,
            offset=offset,
            limit=limit,
        )
        if TMAAuthorizationService.actor_type(actor).value == "tenant_admin":
            return rows, total
        allowed = []
        for assignment in rows:
            try:
                await TMAAuthorizationService.require_assignment_access(
                    db,
                    actor=actor,
                    assignment=assignment,
                )
            except (NotFoundException, ConflictException, BadRequestException):
                continue
            except Exception as exc:
                from app.core.exceptions import ForbiddenException

                if not isinstance(exc, ForbiddenException):
                    raise
                continue
            allowed.append(assignment)
        # Filtered teacher pagination needs a dedicated future query to return
        # an exact global count; returning the visible page count is honest.
        return allowed, len(allowed)

    @staticmethod
    async def update_draft_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        payload: TMAAssignmentUpdate,
    ) -> TMAAssignment:
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
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return assignment

        # Only staff action changes availability; this estimate is display-only.
        if assignment.status not in (TMAAssignmentStatus.DRAFT, TMAAssignmentStatus.ACTIVE):
            raise ConflictException("Only draft or active assignments can be updated.")

        scope_changes = {key: value for key, value in changes.items() if key != "closes_at"}
        if any(value is None for value in scope_changes.values()):
            raise BadRequestException("Academic configuration fields cannot be null.")
        if scope_changes:
            TMAAuthorizationService.require_assignment_management(actor, assignment)
            TMAAuthorizationService.require_draft_assignment(assignment)
            revision = await TMARevisionRepository.get_by_number(
                db,
                actor.tenant_id,
                assignment.id,
                assignment.current_revision_number,
            )
            if revision is None:
                raise ConflictException("The current assignment revision is missing.")
            questions = await TMAQuestionRepository.list_for_revision_with_options(
                db,
                actor.tenant_id,
                revision.id,
            )
            if questions:
                raise ConflictException("Cannot change academic scope after questions exist.")
            effective = TMAAssignmentCreate.model_validate(
                {
                    field: scope_changes.get(field, getattr(assignment, field))
                    for field in TMAAssignmentCreate.model_fields
                    if field != "closes_at"
                }
            )
            await TMAAssignmentService._validate_scope(
                db,
                tenant_id=actor.tenant_id,
                payload=effective,
            )
            await TMAAuthorizationService.require_authoring_access(
                db,
                actor=actor,
                academic_level_id=effective.academic_level_id,
                curriculum_subject_id=effective.curriculum_subject_id,
                academic_term_id=effective.academic_term_id,
            )

        for name, value in changes.items():
            setattr(assignment, name, value)
        try:
            await TMAAssignmentRepository.save(db, assignment)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("This TMA academic scope already exists.") from exc
        return assignment
