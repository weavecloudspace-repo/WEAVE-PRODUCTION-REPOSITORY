"""Provider factory for CBT AI question authoring."""

from __future__ import annotations

from app.config.settings import settings
from app.modules.cbt.ai.authoring.generation_only_resolver import GenerationOnlyImageResolver
from app.modules.cbt.ai.authoring.providers.base import (
    BaseImageEvaluationProvider,
    BaseImageGenerationProvider,
    BaseImageSearchProvider,
    BaseQuestionGenerationProvider,
)
from app.modules.cbt.ai.authoring.providers.gemini import (
    GeminiImageGenerationProvider,
    GeminiQuestionGenerationProvider,
)
from app.modules.cbt.ai.authoring.providers.gemini_contact_sheet import (
    GeminiContactSheetImageEvaluationProvider,
)
from app.modules.cbt.ai.authoring.providers.minimax import (
    MiniMaxImageGenerationProvider,
    MiniMaxQuestionGenerationProvider,
)
from app.modules.cbt.ai.authoring.providers.minimax_contact_sheet import (
    MiniMaxContactSheetImageEvaluationProvider,
)
from app.modules.cbt.ai.authoring.providers.ddgs import DDGSImageSearchProvider
from app.modules.cbt.ai.authoring.providers.openrouter import (
    OpenRouterQuestionGenerationProvider,
    OpenRouterImageGenerationProvider,
    OpenRouterImageEvaluationProvider,
)


class CBTProviderFactoryError(RuntimeError):
    """Raised when a configured CBT AI provider is unsupported."""


class CBTProviderFactory:
    """Build the configured providers used by CBT AI authoring."""

    @staticmethod
    def get_question_provider() -> BaseQuestionGenerationProvider:
        provider = settings.CBT_AI_QUESTION_PROVIDER
        if provider == "gemini":
            return GeminiQuestionGenerationProvider()
        if provider == "minimax":
            return MiniMaxQuestionGenerationProvider()
        if provider == "openrouter":
            return OpenRouterQuestionGenerationProvider()
        raise CBTProviderFactoryError(f"Unsupported CBT AI question provider: {provider!r}")

    @staticmethod
    def get_image_evaluation_provider() -> BaseImageEvaluationProvider:
        provider = settings.CBT_AI_IMAGE_EVALUATION_PROVIDER
        if provider == "gemini":
            return GeminiContactSheetImageEvaluationProvider()
        if provider == "minimax":
            return MiniMaxContactSheetImageEvaluationProvider()
        if provider == "openrouter":
            return OpenRouterImageEvaluationProvider()
        raise CBTProviderFactoryError(f"Unsupported CBT AI image evaluation provider: {provider!r}")

    @staticmethod
    def get_image_generation_provider() -> BaseImageGenerationProvider:
        provider = settings.CBT_AI_IMAGE_PROVIDER
        if provider == "gemini":
            return GeminiImageGenerationProvider()
        if provider == "minimax":
            return MiniMaxImageGenerationProvider()
        if provider == "openrouter":
            return OpenRouterImageGenerationProvider()
        raise CBTProviderFactoryError(f"Unsupported CBT AI image generation provider: {provider!r}")

    @staticmethod
    def get_image_search_provider() -> BaseImageSearchProvider:
        provider = settings.CBT_AI_IMAGE_SEARCH_PROVIDER
        if provider == "ddgs":
            return DDGSImageSearchProvider()
        raise CBTProviderFactoryError(f"Unsupported CBT AI image search provider: {provider!r}")

    @classmethod
    def get_image_resolver(cls) -> GenerationOnlyImageResolver:
        return GenerationOnlyImageResolver(
            generation_provider=OpenRouterImageGenerationProvider(),
        )
