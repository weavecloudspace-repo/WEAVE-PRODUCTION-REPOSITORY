"""TMA -> existing CBT AI authoring adapter; no changes to CBT generation."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.cache.events import flush_cache_invalidation_events
from app.core.storage.factory import get_media_storage
from app.modules.cbt.ai.idempotency.models import AIIdempotencyRecord, AI_IDEMPOTENCY_SUCCEEDED
from app.modules.cbt.ai.idempotency.repository import AIIdempotencyRepository
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
from app.modules.tma.ai_schemas import (
    TMAAIGenerateRequest,
    TMAAIRegenerateRequest,
    TMAAIBulkImportRequest,
)
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.media_service import TMAMediaService
from app.modules.tma.question_service import TMAQuestionService
from app.modules.tma.schemas import TMAOptionInput, TMAQuestionCreate
from app.modules.tma.repository import TMAQuestionRepository


class TMAAIService:
    @staticmethod
    async def import_questions(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        payload: TMAAIBulkImportRequest,
    ) -> int:
        # The assignment lock serializes every import, including response-loss retries.
        assignment, _ = await TMAQuestionService._draft_context(
            db, actor=actor, assignment_id=assignment_id
        )
        if assignment.current_revision_number != payload.revision_number:
            raise ConflictException("This AI draft belongs to an older assignment revision.")
        key = f"{assignment_id}:{payload.draft_id}"
        request_hash = hashlib.sha256(
            json.dumps(
                payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        scope = dict(
            tenant_id=actor.tenant_id,
            actor_type=TMAAuthorizationService.actor_type(actor).value,
            actor_id=actor.id,
            operation="tma_import",
            idempotency_key=key,
        )
        existing = await AIIdempotencyRepository.get_by_scope(db, **scope, lock=True)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictException("This draft was already added with different questions.")
            if existing.status != AI_IDEMPOTENCY_SUCCEEDED:
                raise ConflictException("This import has not completed.")
            return len(payload.questions)
        for question in payload.questions:
            TMAAIService._validate_preview(question)
            TMAAIService._validated_images(question)
        uploaded_keys: list[str] = []
        committing = False
        try:
            for question in payload.questions:
                await TMAAIService.import_question(
                    db,
                    actor=actor,
                    assignment_id=assignment_id,
                    question=question,
                    commit=False,
                    uploaded_keys=uploaded_keys,
                )
            await AIIdempotencyRepository.create(
                db,
                AIIdempotencyRecord(
                    **scope,
                    request_hash=request_hash,
                    status=AI_IDEMPOTENCY_SUCCEEDED,
                    completed_at=datetime.now(timezone.utc),
                ),
            )
            committing = True
            await db.commit()
        except Exception:
            await db.rollback()
            # A disconnected commit may have succeeded. Retain media until its
            # result can be confirmed rather than deleting potentially live images.
            for object_key in [] if committing else uploaded_keys:
                try:
                    await get_media_storage().delete_object(object_key=object_key)
                except Exception:
                    pass
            raise
        await flush_cache_invalidation_events(db)
        return len(payload.questions)

    @staticmethod
    def _validated_images(question: AIQuestionResponse):
        return [
            AIImageTransportPayload.model_validate(
                image.model_dump(
                    include={
                        "content_type",
                        "data_base64",
                        "sha256",
                        "width",
                        "height",
                        "alt_text",
                    }
                )
            )
            if image is not None
            else None
            for image in [question.image, *(option.image for option in question.options)]
        ]

    @staticmethod
    async def _context(db: AsyncSession, *, actor: TMAAuthor, assignment_id: uuid.UUID):
        assignment, revision = await TMAQuestionService._draft_context(
            db,
            actor=actor,
            assignment_id=assignment_id,
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
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        payload: TMAAIGenerateRequest,
        idempotency_key: str,
    ) -> AIGenerateQuestionsResponse:
        _, _, subject, level = await TMAAIService._context(
            db,
            actor=actor,
            assignment_id=assignment_id,
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
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        payload: TMAAIRegenerateRequest,
        idempotency_key: str,
    ) -> AIRegenerateQuestionResponse:
        _, _, subject, level = await TMAAIService._context(
            db,
            actor=actor,
            assignment_id=assignment_id,
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
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        question: AIQuestionResponse,
        commit: bool = True,
        uploaded_keys: list[str] | None = None,
    ):
        """Review/accept one generated question; persist its images in R2.

        A single-question import avoids partial question-bank batch commits.
        """
        TMAAIService._validate_preview(question)
        assignment, revision, _, _ = await TMAAIService._context(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )

        # Validate every image before writing anything to storage.
        validated = TMAAIService._validated_images(question)
        created_assets: list[uuid.UUID] = []

        async def upload(image: AIImageTransportPayload | None) -> uuid.UUID | None:
            if image is None:
                return None
            raw = base64.b64decode(image.data_base64, validate=True)
            extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
                image.content_type
            ]
            file = UploadFile(
                filename=f"ai-question.{extension}",
                file=io.BytesIO(raw),
                headers=Headers({"content-type": image.content_type}),
            )
            asset = await TMAMediaService.upload_image(
                db,
                actor=actor,
                assignment_id=assignment.id,
                file=file,
                **({"commit": False} if not commit else {}),
            )
            created_assets.append(asset.id)
            if uploaded_keys is not None:
                uploaded_keys.append(asset.object_key)
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
                db,
                actor.tenant_id,
                revision.id,
            )
            next_position = max((item.position for item, _ in existing), default=0) + 1
            payload = TMAQuestionCreate(
                position=next_position,
                question_text="\n\n".join(
                    part.strip()
                    for part in [question.instruction, question.prompt]
                    if part and part.strip()
                )
                or None,
                image_asset_id=question_image,
                options=options,
            )
            return await TMAQuestionService.add_question(
                db,
                actor=actor,
                assignment_id=assignment_id,
                payload=payload,
                **({"commit": False} if not commit else {}),
            )
        except Exception:
            if not commit:
                raise
            await db.rollback()
            # Image rows are deliberately unreferenced until the question is
            # saved; best-effort cleanup prevents orphaned storage objects.
            for asset_id in created_assets:
                try:
                    await TMAMediaService.delete_unused_image(
                        db,
                        actor=actor,
                        assignment_id=assignment_id,
                        asset_id=asset_id,
                    )
                except Exception:
                    pass
            raise
