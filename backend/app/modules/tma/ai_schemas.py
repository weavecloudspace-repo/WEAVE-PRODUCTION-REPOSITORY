"""TMA-specific adapters around the existing CBT AI contracts."""

from __future__ import annotations

import uuid
from pydantic import Field

from app.modules.cbt.ai.authoring.schemas import AIQuestionDifficulty, AIVisualMode
from app.modules.cbt.ai.schemas import (
    AIExistingQuestion,
    AIQuestionResponse,
    CBTAISchemaBase,
)


class TMAAIGenerateRequest(CBTAISchemaBase):
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    question_count: int = Field(ge=1, le=50)
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)


class TMAAIRegenerateRequest(CBTAISchemaBase):
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    existing_question: AIExistingQuestion
    instruction: str = Field(min_length=1, max_length=10_000)
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)


class TMAAIImportRequest(CBTAISchemaBase):
    """A single previewed AI question; teachers can review before saving."""

    question: AIQuestionResponse


class TMAAIBulkImportRequest(CBTAISchemaBase):
    draft_id: uuid.UUID
    revision_number: int = Field(ge=1)
    questions: list[AIQuestionResponse] = Field(min_length=1, max_length=50)


class TMAAIBulkImportResponse(CBTAISchemaBase):
    imported_count: int
