"""The CBT contract stays synchronous while GPT-OSS works in small chunks."""

from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.providers.base import (
    ImageResolutionResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
    ProviderUsage,
)
from app.modules.cbt.ai.authoring.service import QuestionAuthoringService
from app.modules.cbt.ai.authoring.validation import AIResponseValidationError


def _question(prompt: str, *, visual: bool, kind: str = "single_choice") -> dict:
    options = [
        {"text": "A", "image": None, "is_correct": True},
        {"text": "B", "image": None, "is_correct": kind == "multiple_choice"},
        {"text": "C", "image": None, "is_correct": False},
    ]
    return {
        "question_type": kind,
        "prompt": prompt,
        "instruction": None,
        "image": (
            {
                "requirement": f"Scientific diagram for {prompt}",
                "generation_prompt": f"Draw an unlabelled scientific diagram for {prompt}.",
            }
            if visual
            else None
        ),
        "options": options,
    }


class ChunkAwareProvider:
    provider_name = "fake"

    def __init__(self, *, duplicate_second_chunk=False, fail_chunk=None, repeat_on_repair=False):
        self.requests: list[dict] = []
        self.repairs: list[dict] = []
        self.duplicate_second_chunk = duplicate_second_chunk
        self.fail_chunk = fail_chunk
        self.repeat_on_repair = repeat_on_repair

    def is_configured(self) -> bool:
        return True

    async def generate_questions(self, *, request):
        chunk = int(request.get("batch_index", 1))
        self.requests.append(dict(request))
        if chunk == self.fail_chunk:
            raise RuntimeError("Simulated upstream provider outage.")
        target = int(request.get("visual_question_target", 0))
        type_counts = request.get("question_type_counts") or {
            "single_choice": request.get("question_count", 1)
        }
        types = [kind for kind, amount in type_counts.items() for _ in range(amount)]
        questions = [
            _question(
                f"Assessment item {chunk}-{index}",
                visual=index < target,
                kind=types[index],
            )
            for index in range(request["question_count"])
        ]
        if self.duplicate_second_chunk and chunk == 2:
            # Reproduce the same full question fingerprint, including image
            # directive; merely sharing prompt text is not sufficient.
            questions[0] = _question(
                "Assessment item 1-0",
                visual=target > 0,
                kind=types[0],
            )
        return ProviderQuestionGenerationResult(
            questions=questions,
            usage=ProviderUsage(input_tokens=10, output_tokens=20),
        )

    async def repair_questions(self, *, request, reference_images=None):
        self.repairs.append(dict(request))
        original = request["original_request"]
        result = await self.generate_questions_for_repair(original)
        return ProviderQuestionGenerationResult(
            questions=result,
            usage=ProviderUsage(input_tokens=3, output_tokens=4),
        )

    async def generate_questions_for_repair(self, request):
        # Repair only the offending chunk, not the entire original batch.
        target = int(request.get("visual_question_target", 0))
        types = [
            kind
            for kind, amount in (
                request.get("question_type_counts") or {"single_choice": request["question_count"]}
            ).items()
            for _ in range(amount)
        ]
        chunk = int(request.get("batch_index", 1))
        return [
            _question(
                "Assessment item 1-0"
                if self.repeat_on_repair and index == 0
                else f"Replacement {chunk}-{index}",
                visual=index < target,
                kind=types[index],
            )
            for index in range(request["question_count"])
        ]


class FakeImageResolver:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def resolve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return ImageResolutionResult(
            source="generated",
            image=ProviderImageInput(
                data=b"image",
                content_type="image/png",
                sha256="0" * 64,
                width=100,
                height=100,
            ),
        )


@pytest.mark.asyncio
async def test_twenty_hybrid_questions_have_two_model_calls_and_eight_images() -> None:
    provider = ChunkAwareProvider()
    resolver = FakeImageResolver()
    service = QuestionAuthoringService(question_provider=provider, image_resolver=resolver)

    result = await service.generate_questions(
        request={
            "subject": "Biology",
            "generation_prompt": "Generate 20 questions on cells and cell theory.",
            "visual_mode": "auto",
            "question_count": 20,
            "question_type_counts": {"single_choice": 12, "multiple_choice": 8},
        },
        expected_count=20,
        expected_type_counts={"single_choice": 12, "multiple_choice": 8},
    )
    assert len(result.questions) == 20
    assert len(provider.requests) == 2
    assert [r["question_count"] for r in provider.requests] == [10, 10]
    assert [r["visual_question_target"] for r in provider.requests] == [4, 4]
    assert [r["question_type_counts"] for r in provider.requests] == [
        {"single_choice": 6, "multiple_choice": 4},
        {"single_choice": 6, "multiple_choice": 4},
    ]
    assert provider.requests[1]["avoid_question_prompts"]
    assert len(resolver.calls) == 8
    assert sum(q.question_image is not None for q in result.questions) == 8
    assert sum(q.question.question_type == "multiple_choice" for q in result.questions) == 8
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 40
    assert result.repaired is False


@pytest.mark.asyncio
async def test_twenty_text_only_questions_do_not_request_images() -> None:
    provider = ChunkAwareProvider()
    resolver = FakeImageResolver()
    result = await QuestionAuthoringService(
        question_provider=provider, image_resolver=resolver
    ).generate_questions(
        request={"visual_mode": "text_only", "question_count": 20},
        expected_count=20,
    )
    assert len(result.questions) == 20
    assert len(provider.requests) == 2
    assert all("visual_question_target" not in r for r in provider.requests)
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_existing_small_requests_still_take_one_model_call() -> None:
    provider = ChunkAwareProvider()
    resolver = FakeImageResolver()
    result = await QuestionAuthoringService(
        question_provider=provider, image_resolver=resolver
    ).generate_questions(
        request={"visual_mode": "auto", "question_count": 10},
        expected_count=10,
    )
    assert len(result.questions) == 10
    assert len(provider.requests) == 1
    assert "batch_index" not in provider.requests[0]
    assert len(resolver.calls) == 4


@pytest.mark.asyncio
async def test_second_chunk_failure_stops_before_creating_images() -> None:
    provider = ChunkAwareProvider(fail_chunk=2)
    resolver = FakeImageResolver()
    service = QuestionAuthoringService(question_provider=provider, image_resolver=resolver)
    with pytest.raises(RuntimeError, match="Simulated upstream"):
        await service.generate_questions(
            request={"visual_mode": "auto", "question_count": 20},
            expected_count=20,
        )
    assert len(provider.requests) == 2
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_cross_chunk_duplicate_repairs_only_the_second_chunk() -> None:
    provider = ChunkAwareProvider(duplicate_second_chunk=True)
    resolver = FakeImageResolver()
    result = await QuestionAuthoringService(
        question_provider=provider, image_resolver=resolver
    ).generate_questions(
        request={"visual_mode": "auto", "question_count": 20},
        expected_count=20,
    )
    assert len(result.questions) == 20
    assert result.repaired is True
    assert len(provider.requests) == 2
    assert len(provider.repairs) == 1
    assert provider.repairs[0]["original_request"]["question_count"] == 10
    assert len(resolver.calls) == 8
    assert len({q.question.prompt for q in result.questions}) == 20
    assert result.usage.input_tokens == 23


@pytest.mark.asyncio
async def test_unfixed_cross_chunk_duplicate_fails_without_materializing_images() -> None:
    provider = ChunkAwareProvider(duplicate_second_chunk=True, repeat_on_repair=True)
    resolver = FakeImageResolver()
    with pytest.raises(AIResponseValidationError):
        await QuestionAuthoringService(
            question_provider=provider, image_resolver=resolver
        ).generate_questions(
            request={"visual_mode": "auto", "question_count": 20},
            expected_count=20,
        )
    assert len(provider.repairs) == 1
    assert resolver.calls == []
