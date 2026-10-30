"""Public application contracts for CBT AI routes."""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.cbt.ai.authoring.schemas import AIQuestionDifficulty, AIVisualMode


AIQuestionType = Literal["single_choice", "multiple_choice"]

MAX_PUBLIC_QUESTION_COUNT = 50
MAX_PUBLIC_TEXT_LENGTH = 20_000
MAX_PUBLIC_GENERATION_PROMPT_LENGTH = 10_000
MAX_PUBLIC_INSTRUCTION_LENGTH = 10_000
MAX_PUBLIC_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PUBLIC_IMAGE_BASE64_LENGTH = ((MAX_PUBLIC_IMAGE_BYTES + 2) // 3) * 4
ALLOWED_PUBLIC_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class CBTAISchemaBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AIImageBinaryEnvelope(CBTAISchemaBase):
    """Common JSON representation of complete encoded image-file bytes."""

    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=MAX_PUBLIC_IMAGE_BASE64_LENGTH)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    alt_text: str | None = Field(default=None, max_length=2_000)


class AIImageTransportPayload(AIImageBinaryEnvelope):
    """Untrusted CBT→Weave image payload validated at the HTTP boundary."""

    @model_validator(mode="after")
    def validate_binary_transport(self) -> Self:
        normalized_type = self.content_type.casefold()
        if normalized_type not in ALLOWED_PUBLIC_IMAGE_TYPES:
            raise ValueError("Unsupported image content type")
        self.content_type = normalized_type

        try:
            decoded = base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ValueError("data_base64 must contain valid Base64 image data") from exc
        if not decoded or len(decoded) > MAX_PUBLIC_IMAGE_BYTES:
            raise ValueError("Image payload exceeds the maximum allowed size")
        if hashlib.sha256(decoded).hexdigest().casefold() != self.sha256.casefold():
            raise ValueError("Image SHA-256 does not match data_base64")
        self.sha256 = self.sha256.casefold()
        return self


class AIExistingImagePayload(AIImageTransportPayload):
    """Regeneration image input.

    Attribution/source metadata is optional so CBT may either send the minimal
    binary envelope or pass back the complete image object Weave returned from a
    prior generation response without stripping fields first.
    """

    source: Literal["search", "generated"] | None = None
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class AIGenerateQuestionsRequest(CBTAISchemaBase):
    """Generate a validated batch of questions from a natural-language authoring brief."""

    subject: str = Field(min_length=1, max_length=200)
    academic_level: str = Field(min_length=1, max_length=200)
    generation_prompt: str = Field(
        min_length=1,
        max_length=MAX_PUBLIC_GENERATION_PROMPT_LENGTH,
        description=(
            "Natural-language authoring brief describing the content to assess, including "
            "topics, emphasis, exclusions, examples, or other generation guidance."
        ),
    )
    question_count: int = Field(ge=1, le=MAX_PUBLIC_QUESTION_COUNT)
    question_type_counts: dict[AIQuestionType, int] | None = None
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=MAX_PUBLIC_TEXT_LENGTH)

    @model_validator(mode="after")
    def validate_generation_shape(self) -> Self:
        if self.question_type_counts is not None:
            if any(
                type(count) is not int or count < 0 for count in self.question_type_counts.values()
            ):
                raise ValueError("question_type_counts values must be non-negative integers")
            if sum(self.question_type_counts.values()) != self.question_count:
                raise ValueError("question_type_counts must sum to question_count")
        return self


class AIExistingQuestionOption(CBTAISchemaBase):
    text: str | None = Field(default=None, max_length=10_000)
    image: AIExistingImagePayload | None = None
    is_correct: bool

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.text and self.image is None:
            raise ValueError("Existing question options must contain text, an image, or both")
        return self


class AIExistingQuestion(CBTAISchemaBase):
    question_type: AIQuestionType
    prompt: str = Field(min_length=1, max_length=MAX_PUBLIC_TEXT_LENGTH)
    instruction: str | None = Field(default=None, max_length=MAX_PUBLIC_INSTRUCTION_LENGTH)
    image: AIExistingImagePayload | None = None
    options: list[AIExistingQuestionOption] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def validate_correct_answers(self) -> Self:
        correct_count = sum(1 for option in self.options if option.is_correct)
        if self.question_type == "single_choice" and correct_count != 1:
            raise ValueError("A single-choice question must have exactly one correct option")
        if self.question_type == "multiple_choice":
            if correct_count < 2:
                raise ValueError(
                    "A multiple-choice question must have at least two correct options"
                )
            if correct_count == len(self.options):
                raise ValueError(
                    "A multiple-choice question must have at least one incorrect option"
                )
        return self


class AIRegenerateQuestionRequest(CBTAISchemaBase):
    """Regenerate one existing CBT question while preserving its question type."""

    subject: str = Field(min_length=1, max_length=200)
    academic_level: str = Field(min_length=1, max_length=200)
    generation_prompt: str = Field(
        min_length=1,
        max_length=MAX_PUBLIC_GENERATION_PROMPT_LENGTH,
        description=(
            "Natural-language content brief defining the subject scope and authoring intent "
            "that the regenerated question must remain within."
        ),
    )
    existing_question: AIExistingQuestion
    instruction: str = Field(
        min_length=1,
        max_length=MAX_PUBLIC_INSTRUCTION_LENGTH,
        description="Transformation instruction describing how to rewrite the existing question.",
    )
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=MAX_PUBLIC_TEXT_LENGTH)


class AIResolvedImageResponse(AIImageBinaryEnvelope):
    """Trusted materialized image returned to CBT; no fetch URL is required."""

    source: Literal["search", "generated"]
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class AIQuestionOptionResponse(CBTAISchemaBase):
    text: str | None = None
    is_correct: bool
    image: AIResolvedImageResponse | None = None


class AIQuestionResponse(CBTAISchemaBase):
    question_type: AIQuestionType
    prompt: str
    instruction: str | None = None
    image: AIResolvedImageResponse | None = None
    options: list[AIQuestionOptionResponse]


class AICreditChargeResponse(CBTAISchemaBase):
    reservation_id: UUID
    credits_charged: int = Field(ge=0)
    credits_released: int = Field(ge=0)


class AIGenerateQuestionsResponse(CBTAISchemaBase):
    questions: list[AIQuestionResponse]
    repaired: bool
    charge: AICreditChargeResponse


class AIRegenerateQuestionResponse(CBTAISchemaBase):
    question: AIQuestionResponse
    repaired: bool
    charge: AICreditChargeResponse
