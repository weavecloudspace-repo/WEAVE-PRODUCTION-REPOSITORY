"""Authenticated TMA AI routes reusing the stable CBT generation pipeline."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.core.dependencies.db import DbSession
from app.modules.cbt.ai.schemas import (
    AIGenerateQuestionsResponse,
    AIRegenerateQuestionResponse,
)
from app.modules.cbt.ai.transport import CBTGZipRoute
from app.modules.tma.ai_schemas import (
    TMAAIGenerateRequest,
    TMAAIImportRequest,
    TMAAIRegenerateRequest,
    TMAAIBulkImportRequest,
    TMAAIBulkImportResponse,
)
from app.modules.tma.ai_service import TMAAIService
from app.modules.tma.router import Author
from app.modules.tma.schemas import TMAQuestionAdminResponse
from app.modules.tma.question_service import TMAQuestionService

router = APIRouter(prefix="/tma", tags=["TMA AI"], route_class=CBTGZipRoute)


@router.post(
    "/assignments/{assignment_id}/ai/questions/import-bulk",
    response_model=TMAAIBulkImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_tma_ai_questions(
    assignment_id: uuid.UUID,
    payload: TMAAIBulkImportRequest,
    db: DbSession,
    actor: Author,
) -> TMAAIBulkImportResponse:
    count = await TMAAIService.import_questions(
        db, actor=actor, assignment_id=assignment_id, payload=payload
    )
    return TMAAIBulkImportResponse(imported_count=count)


@router.post(
    "/assignments/{assignment_id}/ai/questions/generate",
    response_model=AIGenerateQuestionsResponse,
)
async def generate_tma_questions(
    assignment_id: uuid.UUID,
    payload: TMAAIGenerateRequest,
    db: DbSession,
    actor: Author,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)],
) -> AIGenerateQuestionsResponse:
    return await TMAAIService.generate(
        db,
        actor=actor,
        assignment_id=assignment_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/assignments/{assignment_id}/ai/questions/regenerate",
    response_model=AIRegenerateQuestionResponse,
)
async def regenerate_tma_question(
    assignment_id: uuid.UUID,
    payload: TMAAIRegenerateRequest,
    db: DbSession,
    actor: Author,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)],
) -> AIRegenerateQuestionResponse:
    return await TMAAIService.regenerate(
        db,
        actor=actor,
        assignment_id=assignment_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/assignments/{assignment_id}/ai/questions/import",
    response_model=TMAQuestionAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_tma_ai_question(
    assignment_id: uuid.UUID,
    payload: TMAAIImportRequest,
    db: DbSession,
    actor: Author,
) -> TMAQuestionAdminResponse:
    saved = await TMAAIService.import_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question=payload.question,
    )
    row, options = await TMAQuestionService.get_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question_id=saved.id,
    )
    return TMAQuestionAdminResponse(
        id=row.id,
        assignment_id=row.assignment_id,
        revision_id=row.revision_id,
        position=row.position,
        version=row.version,
        question_text=row.question_text,
        image_asset_id=row.image_asset_id,
        author_actor_type=row.author_actor_type,
        author_actor_id=row.author_actor_id,
        options=[
            {
                "id": opt.id,
                "question_id": row.id,
                "position": opt.position,
                "option_text": opt.option_text,
                "image_asset_id": opt.image_asset_id,
                "is_correct": opt.is_correct,
            }
            for opt in options
        ],
    )
