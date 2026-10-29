from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


@dataclass(slots=True)
class ProviderUsage:
    """Normalized usage/cost metadata returned by a provider call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    provider_cost: float | None = None
    currency: str | None = "USD"


@dataclass(frozen=True, slots=True)
class ProviderImageInput:
    """Canonical provider-agnostic image representation used inside Weave.

    `data` contains complete encoded image-file bytes (PNG/JPEG/WebP), never
    raw Pillow pixel buffers, URLs, local file paths, or Base64 transport text.
    Concrete provider adapters translate this contract only at their own API
    boundary.
    """

    data: bytes
    content_type: str
    sha256: str
    width: int
    height: int
    label: str | None = None
    alt_text: str | None = None


@dataclass(slots=True)
class ProviderQuestionGenerationResult:
    """Result returned when a provider generates a batch of draft questions."""

    questions: list[dict[str, Any]]
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_response: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderQuestionRegenerationResult:
    """Result returned when a provider regenerates/transforms one draft question."""

    question: dict[str, Any]
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_response: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderGeneratedImage:
    """Normalized image returned directly by an image-generation provider.

    Providers may return Base64 data or a temporary URL. ImageResolver must
    materialize this into ProviderImageInput before the result can leave the
    authoring layer.
    """

    content_type: str
    data_base64: str | None = None
    url: str | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None


@dataclass(slots=True)
class ProviderImageGenerationResult:
    """Result returned when a provider generates one image."""

    image: ProviderGeneratedImage
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_response: dict[str, Any] | None = None


@dataclass(slots=True)
class ImageCandidate:
    """Normalized sourced-image candidate returned by a search provider."""

    source: str
    source_url: str
    external_id: str | None = None
    title: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class ProviderImageEvaluationResult:
    """Decision returned after a vision-capable provider reviews image candidates."""

    decision: Literal["use_candidate", "generate_image"]
    selected_index: int | None = None
    reason: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_response: dict[str, Any] | None = None


@dataclass(slots=True)
class ImageResolutionResult:
    """Final result produced by the provider-agnostic image resolver.

    A successful resolution always contains fully materialized, validated
    encoded image bytes in `image`. Candidate/generation objects are retained
    only for attribution and provider usage metadata. `generation_attempts`
    records every billable generation call when materialization required a
    controlled retry.
    """

    source: Literal["search", "generated"]
    image: ProviderImageInput
    candidate: ImageCandidate | None = None
    generation: ProviderImageGenerationResult | None = None
    generation_attempts: list[ProviderImageGenerationResult] = field(default_factory=list)
    evaluation: ProviderImageEvaluationResult | None = None
    integrity_review_usages: list[ProviderUsage] = field(default_factory=list)


class BaseProvider(ABC):
    """Base provider class for all CBT AI providers."""

    provider_name: str

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError


class BaseQuestionGenerationProvider(BaseProvider, ABC):
    """Contract for providers that generate or transform CBT question drafts."""

    @abstractmethod
    async def generate_questions(
        self,
        *,
        request: Mapping[str, Any],
    ) -> ProviderQuestionGenerationResult:
        raise NotImplementedError

    @abstractmethod
    async def regenerate_question(
        self,
        *,
        request: Mapping[str, Any],
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ProviderQuestionRegenerationResult:
        raise NotImplementedError

    @abstractmethod
    async def repair_questions(
        self,
        *,
        request: Mapping[str, Any],
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ProviderQuestionGenerationResult:
        raise NotImplementedError


class BaseImageGenerationProvider(BaseProvider, ABC):
    """Contract for providers that generate new visual assets."""

    @abstractmethod
    async def generate_image(
        self,
        *,
        prompt: str,
        metadata: Mapping[str, Any] | None = None,
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ProviderImageGenerationResult:
        raise NotImplementedError


class BaseImageSearchProvider(BaseProvider, ABC):
    """Contract for providers that retrieve existing image candidates."""

    @abstractmethod
    async def search(
        self,
        *,
        query: str,
        limit: int = 10,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[ImageCandidate]:
        raise NotImplementedError


class BaseImageEvaluationProvider(BaseProvider, ABC):
    """Contract for vision-capable providers that judge materialized images."""

    @abstractmethod
    async def evaluate_images(
        self,
        *,
        requirement: str,
        images: Sequence[ProviderImageInput],
    ) -> ProviderImageEvaluationResult:
        raise NotImplementedError
