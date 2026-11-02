from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.providers.base import (
    ProviderQuestionGenerationResult,
    ProviderQuestionRegenerationResult,
    ProviderUsage,
)
from app.modules.cbt.ai.authoring.service import QuestionAuthoringService


def _single_question(prompt: str = "Which particle has a positive charge?") -> dict:
    return {
        "question_type": "single_choice",
        "prompt": prompt,
        "instruction": None,
        "image": None,
        "options": [
            {"text": "Proton", "image": None, "is_correct": True},
            {"text": "Electron", "image": None, "is_correct": False},
            {"text": "Neutron", "image": None, "is_correct": False},
            {"text": "Photon", "image": None, "is_correct": False},
        ],
    }


class NoopImageResolver:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve(self, **kwargs):
        self.calls += 1
        raise AssertionError("text_only recovery must not invoke image resolution")


class MalformedThenRepairProvider:
    provider_name = "gemini"

    def __init__(self, *, repair_error: RuntimeError | None = None) -> None:
        self.generate_calls = 0
        self.regenerate_calls = 0
        self.repair_calls = 0
        self.repair_request = None
        self.repair_error = repair_error

    def is_configured(self) -> bool:
        return True

    async def generate_questions(self, *, request):
        self.generate_calls += 1
        raise RuntimeError("Gemini returned malformed structured JSON.")

    async def regenerate_question(self, *, request, reference_images=None):
        self.regenerate_calls += 1
        raise RuntimeError("Gemini returned malformed structured JSON.")

    async def repair_questions(self, *, request, reference_images=None):
        self.repair_calls += 1
        self.repair_request = dict(request)
        if self.repair_error is not None:
            raise self.repair_error
        return ProviderQuestionGenerationResult(
            questions=[_single_question()],
            usage=ProviderUsage(input_tokens=7, output_tokens=11),
        )


class NonRepairableFailureProvider(MalformedThenRepairProvider):
    async def generate_questions(self, *, request):
        self.generate_calls += 1
        raise RuntimeError("Gemini request timed out")


@pytest.mark.asyncio
async def test_malformed_generation_gets_exactly_one_repair_attempt() -> None:
    provider = MalformedThenRepairProvider()
    resolver = NoopImageResolver()
    service = QuestionAuthoringService(question_provider=provider, image_resolver=resolver)

    result = await service.generate_questions(
        request={"visual_mode": "text_only", "question_count": 1},
        expected_count=1,
        expected_type_counts={"single_choice": 1},
    )

    assert provider.generate_calls == 1
    assert provider.repair_calls == 1
    assert result.repaired is True
    assert result.questions[0].question.prompt == "Which particle has a positive charge?"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 11
    assert resolver.calls == 0
    assert provider.repair_request["operation"] == "generation"
    assert provider.repair_request["invalid_questions"] == []
    assert provider.repair_request["validation_feedback"]["error"] == "malformed_structured_output"


@pytest.mark.asyncio
async def test_malformed_generation_does_not_retry_a_failed_repair() -> None:
    repair_error = RuntimeError("Gemini returned malformed structured JSON.")
    provider = MalformedThenRepairProvider(repair_error=repair_error)
    service = QuestionAuthoringService(
        question_provider=provider,
        image_resolver=NoopImageResolver(),
    )

    with pytest.raises(RuntimeError, match="malformed structured JSON"):
        await service.generate_questions(
            request={"visual_mode": "text_only", "question_count": 1},
            expected_count=1,
        )

    assert provider.generate_calls == 1
    assert provider.repair_calls == 1


@pytest.mark.asyncio
async def test_non_structured_provider_failure_is_not_repaired() -> None:
    provider = NonRepairableFailureProvider()
    service = QuestionAuthoringService(
        question_provider=provider,
        image_resolver=NoopImageResolver(),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        await service.generate_questions(
            request={"visual_mode": "text_only", "question_count": 1},
            expected_count=1,
        )

    assert provider.generate_calls == 1
    assert provider.repair_calls == 0


@pytest.mark.asyncio
async def test_malformed_regeneration_gets_exactly_one_repair_attempt() -> None:
    provider = MalformedThenRepairProvider()
    resolver = NoopImageResolver()
    service = QuestionAuthoringService(question_provider=provider, image_resolver=resolver)

    result = await service.regenerate_question(
        request={"visual_mode": "text_only"},
        expected_question_type="single_choice",
    )

    assert provider.regenerate_calls == 1
    assert provider.repair_calls == 1
    assert provider.repair_request["operation"] == "regeneration"
    assert result.repaired is True
    assert result.question.question.question_type == "single_choice"
    assert resolver.calls == 0
