"""TMA -> existing CBT AI authoring adapter; no changes to CBT generation."""

from __future__ import annotations

import base64
import hashlib
import io
import uuid

from fastapi import UploadFile
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.cbt.ai.idempotency.service import CBTAIIdempotentAuthoringService
from app.modules.cbt.ai.schemas import (
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIImageTransportPayload,
    AIQuestionResponse,
    AIRegenerateQuestionRequest,
    AIRegenerateQuestionResponse,
)
from app.modules.classes.models import AcademicLevel
from app.modules.student_academics.curriculum_models import CurriculumSubject
from app.modules.subjects.models import Subject
from app.modules.tma.ai_actor import to_existing_ai_actor
from app.modules.tma.ai_schemas import TMAAIGenerateRequest, TMAAIRegenerateRequest
from app.modules.tma.authorization import TMAAuthor
from app.modules.tma.media_service import TMAMediaService
from app.modules.tma.question_service import TMAQuestionService
from app.modules.tma.schemas import TMAOptionInput, TMAQuestionCreate
from app.modules.tma.repository import TMAQuestionRepository


class TMAAIService:
    @staticmethod
    async def _context(db: AsyncSession, *, actor: TMAAuthor, assignment_id: uuid.UUID):
        assignment, revision = await TMAQuestionService._draft_context(
            db, actor=actor, assignment_id=assignment_id,
        )
        subject_name = await db.scalar(
            select(Subject.name)
            .join(
                CurriculumSubject,
                and_(
                    CurriculumSubject.subject_id == Subject.id,
                    CurriculumSubject.tenant_id == actor.tenant_id,
                ),
            )
            .where(
                CurriculumSubject.tenant_id == actor.tenant_id,
                CurriculumSubject.id == assignment.curriculum_subject_id,
                Subject.tenant_id == actor.tenant_id,
            )
        )
        level_name = await db.scalar(
            select(AcademicLevel.name).where(
                AcademicLevel.tenant_id == actor.tenant_id,
                AcademicLevel.id == assignment.academic_level_id,
            )
        )
        if not subject_name or not level_name:
            raise NotFoundException("Assignment subject or academic level not found.")
        return assignment, revision, subject_name, level_name

    @staticmethod
    async def generate(
        db: AsyncSession, *, actor: TMAAuthor,
        assignment_id: uuid.UUID, payload: TMAAIGenerateRequest,
        idempotency_key: str,
    ) -> AIGenerateQuestionsResponse:
        _, _, subject, level = await TMAAIService._context(
            db, actor=actor, assignment_id=assignment_id,
        )
        # TMA supports one correct answer, unlike CBT's optional multi-answer types.
        request = AIGenerateQuestionsRequest(
            subject=subject,
            academic_level=level,
            generation_prompt=payload.generation_prompt,
            question_count=payload.question_count,
            question_type_counts={"single_choice": payload.question_count},
            difficulty=payload.difficulty,
            visual_mode=payload.visual_mode,
            context=payload.context,
        )
        return await CBTAIIdempotentAuthoringService.generate_questions(
            db,
            actor=to_existing_ai_actor(actor),
            request=request,
            idempotency_key=hashlib.sha256(
                f"tma:{assignment_id}:{idempotency_key}".encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    async def regenerate(
        db: AsyncSession, *, actor: TMAAuthor,
        assignment_id: uuid.UUID, payload: TMAAIRegenerateRequest,
        idempotency_key: str,
    ) -> AIRegenerateQuestionResponse:
        _, _, subject, level = await TMAAIService._context(
            db, actor=actor, assignment_id=assignment_id,
        )
        if payload.existing_question.question_type != "single_choice":
            raise BadRequestException("TMA only supports single-correct-answer questions.")
        request = AIRegenerateQuestionRequest(
            subject=subject,
            academic_level=level,
            generation_prompt=payload.generation_prompt,
            existing_question=payload.existing_question,
            instruction=payload.instruction,
            difficulty=payload.difficulty,
            visual_mode=payload.visual_mode,
            context=payload.context,
        )
        return await CBTAIIdempotentAuthoringService.regenerate_question(
            db,
            actor=to_existing_ai_actor(actor),
            request=request,
            idempotency_key=f"tma:{idempotency_key}",
        )

    @staticmethod
    def _validate_preview(question: AIQuestionResponse) -> None:
        if question.question_type != "single_choice":
            raise BadRequestException("TMA only supports single-correct-answer questions.")
        if len(question.options) < 4:
            raise BadRequestException("TMA questions require at least four options.")
        if sum(option.is_correct for option in question.options) != 1:
            raise BadRequestException("TMA questions require exactly one correct answer.")
        if not question.prompt and question.image is None:
            raise BadRequestException("A TMA question needs text or an image.")
        if any(not option.text and option.image is None for option in question.options):
            raise BadRequestException("Every option needs text or an image.")

    @staticmethod
    async def import_question(
        db: AsyncSession, *, actor: TMAAuthor,
        assignment_id: uuid.UUID, question: AIQuestionResponse,
    ):
        """Review/accept one generated question; persist its images in R2.

        A single-question import avoids partial question-bank batch commits.
        """
        TMAAIService._validate_preview(question)
        assignment, revision, _, _ = await TMAAIService._context(
            db, actor=actor, assignment_id=assignment_id,
        )

        # Validate every image before writing anything to storage.
        images = [question.image, *(option.image for option in question.options)]
        validated = [
            AIImageTransportPayload.model_validate(
                image.model_dump(
                    include={"content_type", "data_base64", "sha256", "width", "height", "alt_text"}
                )
            )
            if image is not None else None
            for image in images
        ]
        created_assets: list[uuid.UUID] = []

        async def upload(image: AIImageTransportPayload | None) -> uuid.UUID | None:
            if image is None:
                return None
            raw = base64.b64decode(image.data_base64, validate=True)
            extension = {"image/png": "png", "image/jpeg": "jpg",
                         "image/webp": "webp"}[image.content_type]
            file = UploadFile(
                filename=f"ai-question.{extension}",
                file=io.BytesIO(raw),
                headers=Headers({"content-type": image.content_type}),
            )
            asset = await TMAMediaService.upload_image(
                db, actor=actor, assignment_id=assignment.id, file=file,
            )
            created_assets.append(asset.id)
            return asset.id

        try:
            question_image = await upload(validated[0])
            options = [
                TMAOptionInput(
                    position=i,
                    option_text=option.text or None,
                    image_asset_id=await upload(validated[i]),
                    is_correct=option.is_correct,
                )
                for i, option in enumerate(question.options, start=1)
            ]
            existing = await TMAQuestionRepository.list_for_revision_with_options(
                db, actor.tenant_id, revision.id,
            )
            next_position = max((item.position for item, _ in existing), default=0) + 1
            payload = TMAQuestionCreate(
                position=next_position,
                question_text=question.prompt or None,
                image_asset_id=question_image,
                options=options,
            )
            return await TMAQuestionService.add_question(
                db, actor=actor, assignment_id=assignment_id, payload=payload,
            )
        except Exception:
            await db.rollback()
            # Image rows are deliberately unreferenced until the question is
            # saved; best-effort cleanup prevents orphaned storage objects.
            for asset_id in created_assets:
                try:
                    await TMAMediaService.delete_unused_image(
                        db, actor=actor, assignment_id=assignment_id, asset_id=asset_id,
                    )
                except Exception:
                    pass
            raise
