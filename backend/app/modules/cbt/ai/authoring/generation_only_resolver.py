"""Direct Qwen image generation for CBT examination questions.

There is deliberately NO search, contact-sheet, secondary vision evaluation,
or alternate image-provider fallback in this resolver. The image is still
decoded, normalized and checked for safe binary transport.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.cbt.ai.authoring.assessment_integrity import (
    assessment_safe_generation_prompt,
)
from app.modules.cbt.ai.authoring.image_materializer import ImageMaterializer
from app.modules.cbt.ai.authoring.providers.base import (
    BaseImageGenerationProvider,
    ImageResolutionResult,
    ProviderImageInput,
)


class GenerationOnlyImageResolver:
    """Generate exactly one image through the configured provider.

    Transient HTTP 429 retries are owned by the OpenRouter transport.
    A failed provider request or invalid image causes the whole batch to
    fail, rather than searching the web or switching image models.
    """

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
        prompt = assessment_safe_generation_prompt(
            visual_specification, assessment_context
        )
        generated = await self.generation_provider.generate_image(
            prompt=prompt,
            metadata=metadata,
            reference_images=reference_images,
        )
        # Even without a second AI evaluator, malformed or unsafe binary
        # assets must never be admitted to the final question response.
        materialized = await self.materializer.materialize_generated(
            generated.image, label="generated_image"
        )
        return ImageResolutionResult(
            source="generated",
            image=materialized,
            generation=generated,
            generation_attempts=[generated],
        )
