"""Direct Qwen image generation and bounded complete-batch semantics."""

from __future__ import annotations

import asyncio
import base64
from io import BytesIO

import pytest
from PIL import Image

from app.modules.cbt.ai.authoring.generation_only_resolver import GenerationOnlyImageResolver
from app.modules.cbt.ai.authoring.providers.base import (
    ImageResolutionResult,
    ProviderGeneratedImage,
    ProviderImageGenerationResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
)
from app.modules.cbt.ai.authoring.service import QuestionAuthoringService


class FakeImageGenerator:
    provider_name = "openrouter"

    def __init__(self, *, error: Exception | None = None):
        self.prompts: list[str] = []
        self.error = error

    def is_configured(self) -> bool:
        return True

    async def generate_image(self, *, prompt, metadata=None, reference_images=None):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        memory = BytesIO()
        Image.new("RGB", (64, 64), (255, 255, 255)).save(memory, format="PNG")
        return ProviderImageGenerationResult(
            image=ProviderGeneratedImage(
                content_type="image/png",
                data_base64=base64.b64encode(memory.getvalue()).decode(),
            )
        )


@pytest.mark.asyncio
async def test_direct_resolver_never_searches_or_validates_via_vision() -> None:
    provider = FakeImageGenerator()
    resolver = GenerationOnlyImageResolver(generation_provider=provider)
    result = await resolver.resolve(
        requirement="Human stomach",
        generation_prompt="An anatomically accurate unlabelled human stomach.",
        assessment_context='{"correct_answer_text":["Stomach"]}',
    )
    assert result.source == "generated"
    assert result.image.width == 64
    assert "anatomically accurate" in provider.prompts[0]
    assert "NO written answers" in provider.prompts[0]
    assert "correct_answer_text" not in provider.prompts[0]
    assert result.evaluation is None
    assert result.candidate is None
    assert len(result.generation_attempts) == 1


@pytest.mark.asyncio
async def test_direct_resolver_has_no_fallback_when_qwen_fails() -> None:
    provider = FakeImageGenerator(error=RuntimeError("Qwen unavailable"))
    resolver = GenerationOnlyImageResolver(generation_provider=provider)
    with pytest.raises(RuntimeError, match="Qwen unavailable"):
        await resolver.resolve(requirement="A biology diagram")
    assert len(provider.prompts) == 1


class FakeBatchProvider:
    async def generate_questions(self, *, request):
        return ProviderQuestionGenerationResult(
            questions=[
                {
                    "question_type": "single_choice",
                    "prompt": f"Which structure is shown in figure {index}?",
                    "image": (
                        {
                            "requirement": "A precise unlabeled digestive organ",
                            "generation_prompt": f"An accurate digestive organ for figure {index}",
                        }
                        if index < 6
                        else None
                    ),
                    "options": [
                        {"text": "Stomach", "is_correct": True},
                        {"text": "Liver", "is_correct": False},
                    ],
                }
                for index in range(15)
            ]
        )

    async def repair_questions(self, *, request, reference_images=None):
        raise AssertionError("This batch should not require repair.")


class ConcurrentImageResolver:
    def __init__(self, *, fail: bool = False):
        self.active = 0
        self.peak = 0
        self.calls = 0
        self.fail = fail

    async def resolve(self, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls += 1
        try:
            await asyncio.sleep(0.025)
            if self.fail:
                raise RuntimeError("Qwen image failed")
            return ImageResolutionResult(
                source="generated",
                image=ProviderImageInput(
                    data=b"encoded",
                    content_type="image/png",
                    sha256="0" * 64,
                    width=64,
                    height=64,
                ),
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_hybrid_batch_resolves_images_concurrently_and_returns_all_at_once() -> None:
    resolver = ConcurrentImageResolver()
    service = QuestionAuthoringService(
        question_provider=FakeBatchProvider(),
        image_resolver=resolver,
    )
    result = await service.generate_questions(
        request={"question_count": 15, "visual_mode": "auto"},
        expected_count=15,
    )
    assert len(result.questions) == 15
    assert resolver.calls == 6
    assert resolver.peak == 2
    assert [item.question.prompt for item in result.questions] == [
        f"Which structure is shown in figure {i}?" for i in range(15)
    ]
    assert sum(item.question_image is not None for item in result.questions) == 6


@pytest.mark.asyncio
async def test_hybrid_batch_fails_atomically_if_one_image_cannot_generate() -> None:
    resolver = ConcurrentImageResolver(fail=True)
    service = QuestionAuthoringService(
        question_provider=FakeBatchProvider(),
        image_resolver=resolver,
    )
    with pytest.raises(RuntimeError, match="Qwen image failed"):
        await service.generate_questions(
            request={"question_count": 15, "visual_mode": "auto"},
            expected_count=15,
        )
    assert resolver.active == 0
