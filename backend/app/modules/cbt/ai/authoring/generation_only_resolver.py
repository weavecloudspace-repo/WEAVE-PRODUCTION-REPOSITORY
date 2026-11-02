"""Direct Qwen image generation for CBT examination questions.

There is deliberately NO search, contact-sheet, secondary vision evaluation,
or alternate image-provider fallback in this resolver. The image is still
decoded, normalized and checked for safe binary transport.
"""

from __future__ import annotations

from time import perf_counter

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.cbt.ai.authoring.assessment_integrity import (
    assessment_safe_generation_prompt,
)
from app.modules.cbt.ai.authoring.flow_logging import get_question_generation_logger
from app.modules.cbt.ai.authoring.trace_logging import trace_event
from app.modules.cbt.ai.authoring.image_materializer import (
    ImageMaterializationError,
    ImageMaterializer,
)
from app.modules.cbt.ai.authoring.providers.base import (
    BaseImageGenerationProvider,
    ImageResolutionResult,
    ProviderImageInput,
    ProviderImageGenerationResult,
)
from app.modules.cbt.ai.authoring.providers.openrouter import OpenRouterProviderError


logger = get_question_generation_logger("image_generation")


class GenerationOnlyImageResolver:
    """Generate exactly one image through the configured provider.

    Transient HTTP 429 retries are owned by the OpenRouter transport.
    Other temporary provider/image-materialization failures get up to
    three attempts per image. Successful images remain untouched. Exhausted
    retries fail the complete batch without fallback or partial delivery.
    """

    MAX_GENERATION_ATTEMPTS = 3
    RETRY_DELAYS_SECONDS = (0.5, 1.0)
    _TRANSIENT_UPSTREAM_ERRORS = frozenset(
        {
            "OpenRouter request timed out.",
            "Unable to contact OpenRouter.",
            "OpenRouter returned invalid JSON.",
            "OpenRouter response was not a JSON object.",
            "OpenRouter returned no generated image bytes.",
            "OpenRouter returned invalid base64 image data.",
            "Unsupported generated image encoding.",
        }
    )

    @classmethod
    def _is_retryable_image_error(cls, exc: Exception) -> bool:
        if isinstance(exc, ImageMaterializationError):
            return True
        if not isinstance(exc, OpenRouterProviderError) or exc.quota_exhausted:
            return False
        if exc.status_code == 429:
            # The transport already retries this response with Retry-After.
            # A second retry layer would multiply Qwen requests and 429s.
            return False
        if exc.status_code is not None:
            return exc.status_code == 408 or 500 <= exc.status_code <= 599
        return str(exc) in cls._TRANSIENT_UPSTREAM_ERRORS

    def __init__(
        self,
        *,
        generation_provider: BaseImageGenerationProvider,
        materializer: ImageMaterializer | None = None,
    ) -> None:
        self.generation_provider = generation_provider
        self.materializer = materializer or ImageMaterializer()

    async def resolve(
        self,
        *,
        requirement: str,
        search_query: str | None = None,
        generation_prompt: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        reference_images: Sequence[ProviderImageInput] | None = None,
        assessment_context: str | None = None,
    ) -> ImageResolutionResult:
        del search_query  # Legacy field: image retrieval is intentionally disabled.
        visual_specification = (
            generation_prompt.strip()
            if isinstance(generation_prompt, str) and generation_prompt.strip()
            else requirement.strip()
        )
        if not visual_specification:
            raise ValueError("A substantive visual specification is required.")
        # The visual specification must be self-contained. Never forward the
        # hidden answer key or option correctness metadata to the image model.
        # Passing an empty context still prepends the mandatory exam policy.
        del assessment_context
        prompt = assessment_safe_generation_prompt(visual_specification, "")
        generated_attempts: list[ProviderImageGenerationResult] = []
        trace_event(
            "image.started",
            model=getattr(self.generation_provider, "model", None),
            max_attempts=self.MAX_GENERATION_ATTEMPTS,
        )
        for attempt in range(1, self.MAX_GENERATION_ATTEMPTS + 1):
            started = perf_counter()
            trace_event("image.attempt_started", attempt=attempt)
            try:
                generated = await self.generation_provider.generate_image(
                    prompt=prompt,
                    metadata=metadata,
                    reference_images=reference_images,
                )
                generated_attempts.append(generated)
                trace_event(
                    "image.provider_completed",
                    attempt=attempt,
                    duration_ms=(perf_counter() - started) * 1000,
                    input_tokens=generated.usage.input_tokens,
                    output_tokens=generated.usage.output_tokens,
                    provider_cost=generated.usage.provider_cost,
                )
                # Reject malformed assets; retry only temporary failures.
                materialized = await self.materializer.materialize_generated(
                    generated.image, label="generated_image"
                )
            except (OpenRouterProviderError, ImageMaterializationError) as exc:
                retryable = self._is_retryable_image_error(exc)
                trace_event(
                    "image.attempt_failed",
                    attempt=attempt,
                    max_attempts=self.MAX_GENERATION_ATTEMPTS,
                    duration_ms=(perf_counter() - started) * 1000,
                    error_type=type(exc).__name__,
                    http_status=getattr(exc, "status_code", None),
                    retryable=retryable,
                )
                logger.warning(
                    "cbt.ai.image_generation.attempt_failed",
                    extra={
                        "ai_image_attempt": attempt,
                        "ai_image_max_attempts": self.MAX_GENERATION_ATTEMPTS,
                        "ai_image_retryable": retryable,
                        "ai_image_error_type": type(exc).__name__,
                        "ai_image_http_status": getattr(exc, "status_code", None),
                        "ai_image_model": getattr(self.generation_provider, "model", None),
                    },
                )
                if not retryable or attempt == self.MAX_GENERATION_ATTEMPTS:
                    trace_event("image.exhausted", attempt=attempt, retryable=retryable)
                    raise
                trace_event(
                    "image.retry_scheduled",
                    attempt=attempt,
                    retry_delay_seconds=self.RETRY_DELAYS_SECONDS[attempt - 1],
                )
                await asyncio.sleep(self.RETRY_DELAYS_SECONDS[attempt - 1])
                continue

            trace_event(
                "image.materialized",
                attempt=attempt,
                duration_ms=(perf_counter() - started) * 1000,
                image_bytes=len(materialized.data),
                image_width=materialized.width,
                image_height=materialized.height,
            )
            if attempt > 1:
                logger.info(
                    "cbt.ai.image_generation.recovered",
                    extra={"ai_image_attempt": attempt},
                )
            return ImageResolutionResult(
                source="generated",
                image=materialized,
                generation=generated,
                generation_attempts=generated_attempts,
            )
        raise AssertionError("Image retry loop exhausted without a result.")
