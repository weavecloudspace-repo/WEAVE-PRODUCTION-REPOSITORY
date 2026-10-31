"""Qwen-only image retries: bounded, selective, concurrency-safe, no paid calls."""

from __future__ import annotations

import asyncio
import copy
import re
from collections import Counter

import pytest

from app.modules.cbt.ai.authoring.generation_only_resolver import (
    GenerationOnlyImageResolver,
)
from app.modules.cbt.ai.authoring.image_materializer import ImageMaterializationError
from app.modules.cbt.ai.authoring.providers.base import (
    ProviderGeneratedImage,
    ProviderImageGenerationResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
    ProviderUsage,
)
from app.modules.cbt.ai.authoring.providers.openrouter import OpenRouterProviderError
from app.modules.cbt.ai.authoring.service import QuestionAuthoringService


def _transient() -> OpenRouterProviderError:
    return OpenRouterProviderError("OpenRouter upstream_failure (HTTP 503).", status_code=503)


class FakeQwen:
    model = "qwen/qwen-image-2.1-turbo"

    def __init__(self, failures: dict[str, list[Exception]] | None = None) -> None:
        self.failures = failures or {}
        self.calls: Counter[str] = Counter()
        self.active = 0
        self.max_active = 0

    def is_configured(self) -> bool:
        return True

    async def generate_image(self, *, prompt, metadata=None, reference_images=None):
        match = re.search(r"diagram \d+", prompt)
        key = match.group() if match else "standalone"
        self.calls[key] += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            failures = self.failures.get(key, [])
            if len(failures) >= self.calls[key]:
                raise failures[self.calls[key] - 1]
            return ProviderImageGenerationResult(
                image=ProviderGeneratedImage(content_type="image/png", alt_text=key),
                usage=ProviderUsage(input_tokens=1, provider_cost=0.01),
            )
        finally:
            self.active -= 1


class FakeMaterializer:
    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    async def materialize_generated(self, image, *, label):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise ImageMaterializationError("Malformed transient provider image.")
        return ProviderImageInput(
            data=f"encoded:{image.alt_text}".encode(),
            content_type="image/png",
            sha256="0" * 64,
            width=256,
            height=256,
            label=label,
        )


class FakeQuestionProvider:
    provider_name = "fake"

    def __init__(self, questions) -> None:
        self.questions = questions
        self.generate_calls = 0

    async def generate_questions(self, *, request):
        self.generate_calls += 1
        count = request["question_count"]
        offset = (request.get("batch_index", 1) - 1) * 10
        visual_target = request.get("visual_question_target", 0)
        questions = copy.deepcopy(self.questions[offset : offset + count])
        for index, question in enumerate(questions):
            global_index = offset + index
            question["image"] = (
                {
                    "requirement": f"diagram {global_index}",
                    "generation_prompt": (
                        f"Create diagram {global_index} without answer labels."
                    ),
                }
                if index < visual_target
                else None
            )
        return ProviderQuestionGenerationResult(questions=questions)

    async def repair_questions(self, *, request, reference_images=None):
        raise AssertionError("Valid generated questions must not be regenerated.")


def _questions() -> list[dict]:
    return [
        {
            "question_type": "single_choice",
            "prompt": f"Identify the correct answer for item {index}.",
            "instruction": None,
            "image": (
                {
                    "requirement": f"diagram {index}",
                    "generation_prompt": f"Create diagram {index} without answer labels.",
                }
                if index < 6
                else None
            ),
            "options": [
                {"text": "Correct", "image": None, "is_correct": True},
                {"text": "Incorrect", "image": None, "is_correct": False},
            ],
        }
        for index in range(15)
    ]


@pytest.mark.asyncio
async def test_multiple_failed_images_retry_independently_without_regenerating_good_ones(
    monkeypatch,
) -> None:
    monkeypatch.setattr(GenerationOnlyImageResolver, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
    qwen = FakeQwen(
        failures={
            "diagram 2": [_transient()],
            "diagram 11": [_transient(), _transient()],
        }
    )
    question_provider = FakeQuestionProvider(_questions())
    service = QuestionAuthoringService(
        question_provider=question_provider,
        image_resolver=GenerationOnlyImageResolver(
            generation_provider=qwen, materializer=FakeMaterializer()
        ),
    )

    result = await service.generate_questions(
        request={"visual_mode": "auto", "question_count": 15},
        expected_count=15,
    )

    assert len(result.questions) == 15
    assert question_provider.generate_calls == 2
    assert {key: qwen.calls[key] for key in sorted(qwen.calls)} == {
        "diagram 0": 1,
        "diagram 1": 1,
        "diagram 2": 2,
        "diagram 3": 1,
        "diagram 10": 1,
        "diagram 11": 3,
    }
    assert qwen.max_active == 2
    assert all(
        result.questions[i].question_image is not None for i in [0, 1, 2, 3, 10, 11]
    )
    assert all(
        result.questions[i].question_image is None
        for i in [4, 5, 6, 7, 8, 9, 12, 13, 14]
    )
    assert result.usage.input_tokens == 6
    assert result.usage.provider_cost == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_materialization_failure_retries_only_that_image(monkeypatch) -> None:
    monkeypatch.setattr(GenerationOnlyImageResolver, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
    qwen = FakeQwen()
    resolver = GenerationOnlyImageResolver(
        generation_provider=qwen, materializer=FakeMaterializer(fail_once=True)
    )
    result = await resolver.resolve(requirement="diagram", generation_prompt="standalone")

    assert qwen.calls["standalone"] == 2
    assert len(result.generation_attempts) == 2
    assert result.image.data == b"encoded:standalone"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 429])
async def test_permanent_or_transport_exhausted_errors_are_not_retried(status) -> None:
    exc = OpenRouterProviderError(
        f"OpenRouter upstream_failure (HTTP {status}).",
        status_code=status,
        quota_exhausted=status == 402,
    )
    qwen = FakeQwen(failures={"standalone": [exc]})
    resolver = GenerationOnlyImageResolver(
        generation_provider=qwen, materializer=FakeMaterializer()
    )

    with pytest.raises(OpenRouterProviderError) as caught:
        await resolver.resolve(requirement="diagram", generation_prompt="standalone")
    assert caught.value is exc
    assert qwen.calls["standalone"] == 1


@pytest.mark.asyncio
async def test_all_three_temporary_image_failures_propagate_and_do_not_return_batch(
    monkeypatch,
) -> None:
    monkeypatch.setattr(GenerationOnlyImageResolver, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
    qwen = FakeQwen(failures={"diagram 2": [_transient(), _transient(), _transient()]})
    question_provider = FakeQuestionProvider(_questions())
    service = QuestionAuthoringService(
        question_provider=question_provider,
        image_resolver=GenerationOnlyImageResolver(
            generation_provider=qwen, materializer=FakeMaterializer()
        ),
    )
    with pytest.raises(OpenRouterProviderError):
        await service.generate_questions(
            request={"visual_mode": "auto", "question_count": 15},
            expected_count=15,
        )
    assert qwen.calls["diagram 2"] == 3
    assert question_provider.generate_calls == 2


@pytest.mark.asyncio
async def test_missing_api_key_is_not_retried() -> None:
    exc = OpenRouterProviderError("OpenRouter CBT AI provider is not configured.")
    qwen = FakeQwen(failures={"standalone": [exc]})
    resolver = GenerationOnlyImageResolver(
        generation_provider=qwen, materializer=FakeMaterializer()
    )
    with pytest.raises(OpenRouterProviderError):
        await resolver.resolve(requirement="diagram", generation_prompt="standalone")
    assert qwen.calls["standalone"] == 1
