"""Question-authoring orchestration for CBT AI."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.modules.cbt.ai.authoring.assessment_integrity import assessment_context
from app.modules.cbt.ai.authoring.flow_logging import get_question_generation_logger
from app.modules.cbt.ai.authoring.generation_only_resolver import GenerationOnlyImageResolver
from app.modules.cbt.ai.authoring.image_resolver import ImageResolver
from app.modules.cbt.ai.authoring.providers.base import (
    BaseQuestionGenerationProvider,
    ImageResolutionResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
    ProviderUsage,
)
from app.modules.cbt.ai.authoring.schemas import (
    AIQuestionDifficulty,
    AIQuestionDraft,
    AIVisualMode,
)
from app.modules.cbt.ai.authoring.visual_policy import target_visual_question_count
from app.modules.cbt.ai.authoring.validation import (
    AIResponseValidationError,
    SUPPORTED_VISUAL_MODES,
    validate_generated_question_batch,
    validate_regenerated_question,
)


QuestionType = Literal["single_choice", "multiple_choice"]
AuthoringOperation = Literal["generation", "regeneration"]
DEFAULT_QUESTION_DIFFICULTY: AIQuestionDifficulty = "medium"
SUPPORTED_QUESTION_DIFFICULTIES = frozenset({"easy", "medium", "difficult"})
DEFAULT_VISUAL_MODE: AIVisualMode = "auto"

REPAIRABLE_STRUCTURED_OUTPUT_ERROR_MARKERS = (
    "malformed structured json",
    "structured output must be a json object",
    "question-generation response does not contain a valid 'questions' array",
    "regeneration response does not contain a valid 'question' object",
)

logger = get_question_generation_logger("service")


class AuthoringImageBudgetExceededError(RuntimeError):
    """Raised when one authoring response would contain too many image bytes."""


@dataclass(slots=True)
class AuthoredQuestion:
    """One trusted CBT question together with resolved visual assets."""

    question: AIQuestionDraft
    question_image: ImageResolutionResult | None = None
    option_images: dict[int, ImageResolutionResult] = field(default_factory=dict)


@dataclass(slots=True)
class QuestionGenerationResult:
    questions: list[AuthoredQuestion]
    usage: ProviderUsage
    repaired: bool = False


@dataclass(slots=True)
class QuestionRegenerationResult:
    question: AuthoredQuestion
    usage: ProviderUsage
    repaired: bool = False


class QuestionAuthoringService:
    """Coordinate validated question authoring and image resolution."""

    MAX_MATERIALIZED_IMAGE_BYTES = 24 * 1024 * 1024

    def __init__(
        self,
        *,
        question_provider: BaseQuestionGenerationProvider,
        image_resolver: ImageResolver | GenerationOnlyImageResolver,
    ) -> None:
        self.question_provider = question_provider
        self.image_resolver = image_resolver

    async def generate_questions(
        self,
        *,
        request: Mapping[str, Any],
        expected_count: int | None = None,
        expected_type_counts: Mapping[str, int] | None = None,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> QuestionGenerationResult:
        if progress_callback is not None:
            await progress_callback("generating_questions")
        request_payload, visual_mode = self._prepare_authoring_request(request)
        # This internal hint is never part of the public CBT request schema.
        # It ensures both initial generation and one-shot repair use the
        # same count, while Text-only mode remains unaffected.
        count = (
            expected_count if expected_count is not None else request_payload.get("question_count")
        )
        if visual_mode == "auto" and type(count) is int and count > 0:
            request_payload["visual_question_target"] = target_visual_question_count(count)
        repaired = False

        try:
            provider_result = await self.question_provider.generate_questions(
                request=request_payload,
            )
        except RuntimeError as provider_error:
            if not self._is_repairable_structured_output_error(provider_error):
                raise
            repaired_result = await self._repair_unparseable_questions(
                original_request=request_payload,
                provider_error=provider_error,
                operation="generation",
            )
            questions = validate_generated_question_batch(
                repaired_result.questions,
                expected_count=expected_count,
                expected_type_counts=expected_type_counts,
                visual_mode=visual_mode,
            )
            question_usage = repaired_result.usage
            repaired = True
        else:
            question_usage = provider_result.usage
            try:
                questions = validate_generated_question_batch(
                    provider_result.questions,
                    expected_count=expected_count,
                    expected_type_counts=expected_type_counts,
                    visual_mode=visual_mode,
                )
            except AIResponseValidationError as validation_error:
                repaired_result = await self._repair_questions(
                    original_request=request_payload,
                    invalid_questions=provider_result.questions,
                    validation_error=validation_error,
                    operation="generation",
                )
                questions = validate_generated_question_batch(
                    repaired_result.questions,
                    expected_count=expected_count,
                    expected_type_counts=expected_type_counts,
                    visual_mode=visual_mode,
                )
                question_usage = self._combine_usage(
                    provider_result.usage,
                    repaired_result.usage,
                )
                repaired = True

        if progress_callback is not None:
            await progress_callback("generating_images")

        # Image operations are independent after the question batch has passed
        # validation. Bound concurrency, retain question order, and never return
        # a partial batch if any required image fails.
        semaphore = asyncio.Semaphore(2)

        async def resolve_one(
            question: AIQuestionDraft,
        ) -> tuple[AuthoredQuestion, list[ProviderUsage]]:
            async with semaphore:
                return await self._resolve_question_images(question)

        tasks = [asyncio.create_task(resolve_one(question)) for question in questions]
        try:
            resolved = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        authored_questions: list[AuthoredQuestion] = []
        image_usages: list[ProviderUsage] = []
        materialized_image_bytes = 0
        for authored_question, usages in resolved:
            materialized_image_bytes += self._authored_question_image_bytes(authored_question)
            self._enforce_image_budget(materialized_image_bytes)
            authored_questions.append(authored_question)
            image_usages.extend(usages)

        if progress_callback is not None:
            await progress_callback("finalizing")

        return QuestionGenerationResult(
            questions=authored_questions,
            usage=self._combine_usage(question_usage, *image_usages),
            repaired=repaired,
        )

    async def regenerate_question(
        self,
        *,
        request: Mapping[str, Any],
        expected_question_type: QuestionType | None = None,
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> QuestionRegenerationResult:
        """Regenerate one question with optional canonical binary reference images."""

        request_payload, visual_mode = self._prepare_authoring_request(request)
        repaired = False

        try:
            provider_result = await self.question_provider.regenerate_question(
                request=request_payload,
                reference_images=reference_images,
            )
        except RuntimeError as provider_error:
            if not self._is_repairable_structured_output_error(provider_error):
                raise
            repaired_result = await self._repair_unparseable_questions(
                original_request=request_payload,
                provider_error=provider_error,
                operation="regeneration",
                reference_images=reference_images,
            )
            repaired_questions = validate_generated_question_batch(
                repaired_result.questions,
                expected_count=1,
                expected_type_counts=self._single_question_type_counts(expected_question_type),
                visual_mode=visual_mode,
            )
            question = validate_regenerated_question(
                repaired_questions[0].model_dump(),
                expected_question_type=expected_question_type,
                visual_mode=visual_mode,
            )
            question_usage = repaired_result.usage
            repaired = True
        else:
            question_usage = provider_result.usage
            try:
                question = validate_regenerated_question(
                    provider_result.question,
                    expected_question_type=expected_question_type,
                    visual_mode=visual_mode,
                )
            except AIResponseValidationError as validation_error:
                repaired_result = await self._repair_questions(
                    original_request=request_payload,
                    invalid_questions=[provider_result.question],
                    validation_error=validation_error,
                    operation="regeneration",
                    reference_images=reference_images,
                )
                repaired_questions = validate_generated_question_batch(
                    repaired_result.questions,
                    expected_count=1,
                    expected_type_counts=self._single_question_type_counts(expected_question_type),
                    visual_mode=visual_mode,
                )
                question = validate_regenerated_question(
                    repaired_questions[0].model_dump(),
                    expected_question_type=expected_question_type,
                    visual_mode=visual_mode,
                )
                question_usage = self._combine_usage(
                    provider_result.usage,
                    repaired_result.usage,
                )
                repaired = True

        authored_question, image_usages = await self._resolve_question_images(question)
        self._enforce_image_budget(self._authored_question_image_bytes(authored_question))
        return QuestionRegenerationResult(
            question=authored_question,
            usage=self._combine_usage(question_usage, *image_usages),
            repaired=repaired,
        )

    async def _repair_questions(
        self,
        *,
        original_request: Mapping[str, Any],
        invalid_questions: list[dict[str, Any]],
        validation_error: AIResponseValidationError,
        operation: AuthoringOperation,
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ProviderQuestionGenerationResult:
        repair_request = self._build_repair_request(
            original_request=original_request,
            invalid_questions=invalid_questions,
            validation_error=validation_error,
            operation=operation,
        )
        return await self.question_provider.repair_questions(
            request=repair_request,
            reference_images=reference_images,
        )

    async def _repair_unparseable_questions(
        self,
        *,
        original_request: Mapping[str, Any],
        provider_error: RuntimeError,
        operation: AuthoringOperation,
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ProviderQuestionGenerationResult:
        logger.warning(
            "cbt.ai.question_generation.structured_output.repair_started",
            extra={
                "ai_operation": operation,
                "ai_provider": getattr(self.question_provider, "provider_name", "unknown"),
                "ai_error_type": type(provider_error).__name__,
                "ai_error_message": str(provider_error)[:500],
                "ai_repair_attempt": 1,
                "ai_repair_max_attempts": 1,
            },
        )
        repair_request = self._build_unparseable_repair_request(
            original_request=original_request,
            provider_error=provider_error,
            operation=operation,
        )
        repaired_result = await self.question_provider.repair_questions(
            request=repair_request,
            reference_images=reference_images,
        )
        logger.info(
            "cbt.ai.question_generation.structured_output.repair_completed",
            extra={
                "ai_operation": operation,
                "ai_provider": getattr(self.question_provider, "provider_name", "unknown"),
                "ai_repair_attempt": 1,
            },
        )
        return repaired_result

    async def _resolve_question_images(
        self,
        question: AIQuestionDraft,
    ) -> tuple[AuthoredQuestion, list[ProviderUsage]]:
        question_image: ImageResolutionResult | None = None
        option_images: dict[int, ImageResolutionResult] = {}
        usages: list[ProviderUsage] = []
        review_context = assessment_context(question)

        if question.image is not None:
            question_image = await self.image_resolver.resolve(
                requirement=question.image.requirement,
                search_query=question.image.search_query,
                generation_prompt=question.image.generation_prompt,
                assessment_context=review_context,
            )
            usages.extend(self._image_resolution_usages(question_image))

        for index, option in enumerate(question.options):
            if option.image is None:
                continue
            resolution = await self.image_resolver.resolve(
                requirement=option.image.requirement,
                search_query=option.image.search_query,
                generation_prompt=option.image.generation_prompt,
                assessment_context=review_context,
            )
            option_images[index] = resolution
            usages.extend(self._image_resolution_usages(resolution))

        return (
            AuthoredQuestion(
                question=question,
                question_image=question_image,
                option_images=option_images,
            ),
            usages,
        )

    @staticmethod
    def _authored_question_image_bytes(question: AuthoredQuestion) -> int:
        total = len(question.question_image.image.data) if question.question_image else 0
        total += sum(len(resolution.image.data) for resolution in question.option_images.values())
        return total

    @classmethod
    def _enforce_image_budget(cls, image_bytes: int) -> None:
        if image_bytes > cls.MAX_MATERIALIZED_IMAGE_BYTES:
            raise AuthoringImageBudgetExceededError(
                "CBT AI image payload exceeds the maximum materialized response budget."
            )

    @staticmethod
    def _image_resolution_usages(resolution: ImageResolutionResult) -> list[ProviderUsage]:
        usages: list[ProviderUsage] = []
        if resolution.evaluation is not None:
            usages.append(resolution.evaluation.usage)
        usages.extend(resolution.integrity_review_usages)
        if resolution.generation_attempts:
            usages.extend(attempt.usage for attempt in resolution.generation_attempts)
        elif resolution.generation is not None:
            # Backward-compatible path for tests/alternate resolvers constructing
            # a final generation result without the attempt history.
            usages.append(resolution.generation.usage)
        return usages

    @staticmethod
    def _prepare_authoring_request(
        request: Mapping[str, Any],
    ) -> tuple[dict[str, Any], AIVisualMode]:
        request_payload = dict(request)

        raw_difficulty = request_payload.get("difficulty", DEFAULT_QUESTION_DIFFICULTY)
        if raw_difficulty not in SUPPORTED_QUESTION_DIFFICULTIES:
            raise ValueError(f"Unsupported question difficulty: {raw_difficulty!r}.")
        difficulty = cast(AIQuestionDifficulty, raw_difficulty)
        request_payload["difficulty"] = difficulty

        raw_visual_mode = request_payload.get("visual_mode", DEFAULT_VISUAL_MODE)
        if raw_visual_mode not in SUPPORTED_VISUAL_MODES:
            raise ValueError(f"Unsupported visual mode: {raw_visual_mode!r}.")
        visual_mode = cast(AIVisualMode, raw_visual_mode)
        request_payload["visual_mode"] = visual_mode
        return request_payload, visual_mode

    @staticmethod
    def _build_repair_request(
        *,
        original_request: Mapping[str, Any],
        invalid_questions: list[dict[str, Any]],
        validation_error: AIResponseValidationError,
        operation: AuthoringOperation,
    ) -> dict[str, Any]:
        return {
            "operation": operation,
            "original_request": dict(original_request),
            "invalid_questions": invalid_questions,
            "validation_feedback": validation_error.to_repair_feedback(),
        }

    @staticmethod
    def _build_unparseable_repair_request(
        *,
        original_request: Mapping[str, Any],
        provider_error: RuntimeError,
        operation: AuthoringOperation,
    ) -> dict[str, Any]:
        return {
            "operation": operation,
            "original_request": dict(original_request),
            "invalid_questions": [],
            "validation_feedback": {
                "error": "malformed_structured_output",
                "message": (
                    "The provider response could not be parsed as the required structured "
                    "question output. Regenerate the complete response once from the original request."
                ),
                "issues": [
                    {
                        "path": "$",
                        "code": "unparseable_structured_output",
                        "message": str(provider_error)[:500],
                    }
                ],
            },
        }

    @staticmethod
    def _is_repairable_structured_output_error(error: RuntimeError) -> bool:
        message = str(error).casefold()
        return any(marker in message for marker in REPAIRABLE_STRUCTURED_OUTPUT_ERROR_MARKERS)

    @staticmethod
    def _single_question_type_counts(
        expected_question_type: QuestionType | None,
    ) -> dict[str, int] | None:
        if expected_question_type is None:
            return None
        return {expected_question_type: 1}

    @staticmethod
    def _combine_usage(*usages: ProviderUsage) -> ProviderUsage:
        input_tokens = sum(usage.input_tokens for usage in usages)
        output_tokens = sum(usage.output_tokens for usage in usages)
        cache_read_tokens = sum(usage.cache_read_tokens for usage in usages)

        provider_cost: float | None = None
        currency: str | None = None
        cost_usages = [usage for usage in usages if usage.provider_cost is not None]
        if cost_usages:
            currencies = {usage.currency for usage in cost_usages}
            if len(currencies) == 1:
                currency = next(iter(currencies))
                provider_cost = sum(usage.provider_cost or 0 for usage in cost_usages)

        return ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            provider_cost=provider_cost,
            currency=currency,
        )
