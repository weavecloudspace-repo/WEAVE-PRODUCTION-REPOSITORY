"""Transactional collaborative question authoring for DRAFT TMAs."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache.events import flush_cache_invalidation_events
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.models import TMAQuestion, TMAQuestionOption
from app.modules.tma.repository import (
    TMAAssignmentRepository,
    TMAMediaAssetRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)
from app.modules.tma.schemas import TMAOptionInput, TMAQuestionCreate, TMAQuestionUpdate


class TMAQuestionService:
    @staticmethod
    async def _draft_context(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ):
        # Every writer locks the same assignment row before counting or
        # editing questions, so contribution order cannot race.
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
        TMAAuthorizationService.require_draft_assignment(assignment)
        revision = await TMARevisionRepository.get_by_number(
            db,
            actor.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if revision is None or revision.invalidated_at is not None:
            raise ConflictException("Current assignment revision is not editable.")
        return assignment, revision

    @staticmethod
    async def _validate_media(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        question_asset_id: uuid.UUID | None,
        options: list[TMAOptionInput],
    ) -> None:
        assets = {a for a in [question_asset_id, *(opt.image_asset_id for opt in options)] if a}
        for asset_id in assets:
            asset = await TMAMediaAssetRepository.get_by_id(db, tenant_id, asset_id)
            if asset is None or asset.assignment_id != assignment_id:
                raise BadRequestException("An image does not belong to this TMA.")

    @staticmethod
    async def add_question(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        payload: TMAQuestionCreate,
        commit: bool = True,
    ) -> TMAQuestion:
        assignment, revision = await TMAQuestionService._draft_context(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        existing = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            actor.tenant_id,
            revision.id,
        )
        next_position = max((row.position for row, _ in existing), default=0) + 1
        if payload.position != next_position:
            raise ConflictException(f"Next question position must be {next_position}.")
        await TMAQuestionService._validate_media(
            db,
            actor.tenant_id,
            assignment.id,
            payload.image_asset_id,
            payload.options,
        )
        question = TMAQuestion(
            tenant_id=actor.tenant_id,
            assignment_id=assignment.id,
            revision_id=revision.id,
            position=next_position,
            question_text=payload.question_text,
            image_asset_id=payload.image_asset_id,
            author_actor_type=TMAAuthorizationService.actor_type(actor),
            author_actor_id=actor.id,
            version=1,
        )
        try:
            await TMAQuestionRepository.add_question(db, question)
            db.add_all(
                [
                    TMAQuestionOption(
                        tenant_id=actor.tenant_id,
                        assignment_id=assignment.id,
                        question_id=question.id,
                        **item.model_dump(),
                    )
                    for item in payload.options
                ]
            )
            await db.flush()
            if commit:
                await db.commit()
                await flush_cache_invalidation_events(db)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Question position or option conflicts with another edit."
            ) from exc
        return question

    @staticmethod
    async def list_questions(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> list[tuple[TMAQuestion, list[TMAQuestionOption]]]:
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
        revision = await TMARevisionRepository.get_by_number(
            db,
            actor.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if revision is None:
            raise ConflictException("Assignment revision is missing.")
        return await TMAQuestionRepository.list_for_revision_with_options(
            db,
            actor.tenant_id,
            revision.id,
        )

    @staticmethod
    async def get_question(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> tuple[TMAQuestion, list[TMAQuestionOption]]:
        items = await TMAQuestionService.list_questions(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        for question, options in items:
            if question.id == question_id:
                return question, options
        raise NotFoundException("Question not found.")

    @staticmethod
    async def update_question(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        question_id: uuid.UUID,
        payload: TMAQuestionUpdate,
    ) -> TMAQuestion:
        assignment, revision = await TMAQuestionService._draft_context(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        question = await TMAQuestionRepository.get_question(
            db,
            actor.tenant_id,
            question_id,
            lock=True,
        )
        if question is None or question.revision_id != revision.id:
            raise NotFoundException("Question not found.")
        TMAAuthorizationService.require_question_edit_access(actor, assignment, question)
        if question.version != payload.version:
            raise ConflictException("Question changed. Reload before editing.")
        changes = payload.model_dump(exclude_unset=True, exclude={"version"})
        if "position" in changes and changes["position"] != question.position:
            raise ConflictException("Bulk question reordering is not supported yet.")
        if any(value is None for name, value in changes.items() if name == "position"):
            raise BadRequestException("Position must not be null.")
        new_text = changes.get("question_text", question.question_text)
        new_asset = changes.get("image_asset_id", question.image_asset_id)
        if not new_text and new_asset is None:
            raise BadRequestException("Question requires text or an image.")
        options = changes.pop("options", None)
        await TMAQuestionService._validate_media(
            db,
            actor.tenant_id,
            assignment.id,
            new_asset,
            [TMAOptionInput.model_validate(item) for item in options]
            if options is not None
            else [],
        )
        try:
            for name, value in changes.items():
                setattr(question, name, value)
            if options is not None:
                await TMAQuestionRepository.replace_options(
                    db,
                    actor.tenant_id,
                    question.id,
                    [
                        TMAQuestionOption(
                            tenant_id=actor.tenant_id,
                            assignment_id=assignment.id,
                            question_id=question.id,
                            **item,
                        )
                        for item in options
                    ],
                )
            question.version += 1
            await TMAQuestionRepository.save_question(db, question)
            await db.commit()
            await flush_cache_invalidation_events(db)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Concurrent question update failed.") from exc
        return question

    @staticmethod
    async def delete_question(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> None:
        assignment, revision = await TMAQuestionService._draft_context(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        question = await TMAQuestionRepository.get_question(
            db,
            actor.tenant_id,
            question_id,
            lock=True,
        )
        if question is None or question.revision_id != revision.id:
            raise NotFoundException("Question not found.")
        TMAAuthorizationService.require_question_edit_access(actor, assignment, question)
        try:
            await TMAQuestionRepository.delete_draft_question(
                db,
                actor.tenant_id,
                question.id,
            )
            await db.commit()
            await flush_cache_invalidation_events(db)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("This question has protected student answer evidence.") from exc
