from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.providers.base import (
    ImageCandidate,
    ImageResolutionResult,
    ProviderGeneratedImage,
    ProviderImageEvaluationResult,
    ProviderImageGenerationResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
    ProviderQuestionRegenerationResult,
    ProviderUsage,
)
from app.modules.cbt.ai.authoring.service import QuestionAuthoringService
from app.modules.cbt.ai.authoring.validation import AIResponseValidationError


def _materialized(label: str = "image") -> ProviderImageInput:
    return ProviderImageInput(
        data=b"encoded-image",
        content_type="image/png",
        sha256="0" * 64,
        width=100,
        height=100,
        label=label,
    )


def _image(label: str = "triangle") -> dict[str, str]:
    return {
        "requirement": f"A clear {label} diagram",
        "search_query": f"{label} diagram",
        "generation_prompt": f"Generate a clear {label} diagram",
    }


def _single(
    prompt: str = "Which answer is correct?",
    *,
    visual: bool = False,
    option_visual: bool = False,
) -> dict:
    return {
        "question_type": "single_choice",
        "prompt": prompt,
        "instruction": None,
        "image": _image() if visual else None,
        "options": [
            {
                "text": "A",
                "image": _image("option A") if option_visual else None,
                "is_correct": True,
            },
            {"text": "B", "image": None, "is_correct": False},
        ],
    }


class FakeQuestionProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        generated: list[dict] | None = None,
        repaired: list[dict] | None = None,
        regenerated: dict | None = None,
        generation_usage: ProviderUsage | None = None,
        repair_usage: ProviderUsage | None = None,
        regeneration_usage: ProviderUsage | None = None,
    ) -> None:
        self.generated = generated or []
        self.repaired = repaired or []
        self.regenerated = regenerated or _single(visual=True)
        self.generation_usage = generation_usage or ProviderUsage()
        self.repair_usage = repair_usage or ProviderUsage()
        self.regeneration_usage = regeneration_usage or ProviderUsage()
        self.generate_calls = 0
        self.repair_calls = 0
        self.regenerate_calls = 0
        self.generate_request = None
        self.repair_request = None
        self.regenerate_request = None
        self.repair_reference_images = None
        self.regenerate_reference_images = None

    def is_configured(self) -> bool:
        return True

    async def generate_questions(self, *, request):
        self.generate_calls += 1
        self.generate_request = dict(request)
        return ProviderQuestionGenerationResult(
            questions=self.generated,
            usage=self.generation_usage,
        )

    async def repair_questions(self, *, request, reference_images=None):
        self.repair_calls += 1
        self.repair_request = dict(request)
        self.repair_reference_images = reference_images
        return ProviderQuestionGenerationResult(
            questions=self.repaired,
            usage=self.repair_usage,
        )

    async def regenerate_question(self, *, request, reference_images=None):
        self.regenerate_calls += 1
        self.regenerate_request = dict(request)
        self.regenerate_reference_images = reference_images
        return ProviderQuestionRegenerationResult(
            question=self.regenerated,
            usage=self.regeneration_usage,
        )


class FakeImageResolver:
    def __init__(self, result: ImageResolutionResult | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result or ImageResolutionResult(
            source="search",
            image=_materialized(),
            candidate=ImageCandidate(
                source="fake",
                source_url="https://example.com/source",
                image_url="https://example.com/image.png",
            ),
        )

    async def resolve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.result


def _service(provider: FakeQuestionProvider, resolver: FakeImageResolver | None = None):
    resolver = resolver or FakeImageResolver()
    return QuestionAuthoringService(question_provider=provider, image_resolver=resolver), resolver


@pytest.mark.asyncio
async def test_missing_visual_mode_defaults_to_auto_and_is_sent_to_provider() -> None:
    provider = FakeQuestionProvider(generated=[_single(visual=True)])
    service, _ = _service(provider)
    result = await service.generate_questions(request={"topic": "Geometry"}, expected_count=1)
    assert result.repaired is False
    assert provider.generate_request["visual_mode"] == "auto"


@pytest.mark.asyncio
async def test_invalid_visual_mode_fails_before_provider_call() -> None:
    provider = FakeQuestionProvider(generated=[_single(visual=True)])
    service, _ = _service(provider)
    with pytest.raises(ValueError, match="Unsupported visual mode"):
        await service.generate_questions(request={"visual_mode": "prefer_visuals"})
    assert provider.generate_calls == 0


@pytest.mark.asyncio
async def test_valid_generation_does_not_repair_and_resolves_images_after_validation() -> None:
    provider = FakeQuestionProvider(generated=[_single(visual=True)])
    service, resolver = _service(provider)
    result = await service.generate_questions(
        request={"visual_mode": "auto"},
        expected_count=1,
        expected_type_counts={"single_choice": 1},
    )
    assert provider.repair_calls == 0
    assert len(resolver.calls) == 1
    assert result.questions[0].question_image is not None
    assert result.repaired is False


@pytest.mark.asyncio
async def test_invalid_generation_gets_exactly_one_repair_then_images_resolve() -> None:
    provider = FakeQuestionProvider(generated=[_single()], repaired=[_single(visual=True)])
    service, resolver = _service(provider)
    result = await service.generate_questions(
        request={"visual_mode": "auto", "topic": "Geometry"},
        expected_count=1,
    )
    assert provider.repair_calls == 1
    assert len(resolver.calls) == 1
    assert result.repaired is True
    assert provider.repair_request["operation"] == "generation"
    assert provider.repair_request["original_request"]["visual_mode"] == "auto"
    assert provider.repair_request["invalid_questions"] == [_single()]
    assert provider.repair_request["validation_feedback"]["issues"]


@pytest.mark.asyncio
async def test_invalid_repair_is_not_repaired_twice_and_never_resolves_images() -> None:
    provider = FakeQuestionProvider(generated=[_single()], repaired=[_single()])
    service, resolver = _service(provider)
    with pytest.raises(AIResponseValidationError):
        await service.generate_questions(request={"visual_mode": "auto"}, expected_count=1)
    assert provider.repair_calls == 1
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_text_only_generation_never_invokes_image_resolver() -> None:
    provider = FakeQuestionProvider(generated=[_single()])
    service, resolver = _service(provider)
    result = await service.generate_questions(
        request={"visual_mode": "text_only"},
        expected_count=1,
    )
    assert result.questions[0].question.image is None
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_question_and_option_directives_are_resolved_separately() -> None:
    provider = FakeQuestionProvider(generated=[_single(visual=True, option_visual=True)])
    service, resolver = _service(provider)
    result = await service.generate_questions(request={"visual_mode": "auto"}, expected_count=1)
    assert len(resolver.calls) == 2
    assert result.questions[0].question_image is not None
    assert 0 in result.questions[0].option_images


@pytest.mark.asyncio
async def test_usage_aggregates_generation_repair_image_evaluation_and_generation() -> None:
    provider = FakeQuestionProvider(
        generated=[_single()],
        repaired=[_single(visual=True)],
        generation_usage=ProviderUsage(
            input_tokens=10, output_tokens=20, provider_cost=0.10, currency="USD"
        ),
        repair_usage=ProviderUsage(
            input_tokens=5, output_tokens=7, provider_cost=0.05, currency="USD"
        ),
    )
    image_result = ImageResolutionResult(
        source="generated",
        image=_materialized("generated"),
        evaluation=ProviderImageEvaluationResult(
            decision="generate_image",
            usage=ProviderUsage(
                input_tokens=3, output_tokens=2, provider_cost=0.02, currency="USD"
            ),
        ),
        generation=ProviderImageGenerationResult(
            image=ProviderGeneratedImage(content_type="image/png", data_base64="abc"),
            usage=ProviderUsage(
                input_tokens=4, output_tokens=1, provider_cost=0.03, currency="USD"
            ),
        ),
    )
    service, _ = _service(provider, FakeImageResolver(image_result))
    result = await service.generate_questions(request={"visual_mode": "auto"}, expected_count=1)
    assert result.usage.input_tokens == 22
    assert result.usage.output_tokens == 30
    assert result.usage.provider_cost == pytest.approx(0.20)
    assert result.usage.currency == "USD"


def test_usage_does_not_mix_provider_cost_across_currencies() -> None:
    usage = QuestionAuthoringService._combine_usage(
        ProviderUsage(input_tokens=2, provider_cost=1.0, currency="USD"),
        ProviderUsage(output_tokens=3, provider_cost=2.0, currency="NGN"),
    )
    assert usage.input_tokens == 2
    assert usage.output_tokens == 3
    assert usage.provider_cost is None
    assert usage.currency is None


@pytest.mark.asyncio
async def test_regeneration_valid_path_preserves_expected_type_and_resolves_visual() -> None:
    provider = FakeQuestionProvider(regenerated=_single("Regenerated", visual=True))
    service, resolver = _service(provider)
    reference = _materialized("existing_question.image")
    result = await service.regenerate_question(
        request={"visual_mode": "auto"},
        expected_question_type="single_choice",
        reference_images=[reference],
    )
    assert result.repaired is False
    assert provider.repair_calls == 0
    assert provider.regenerate_reference_images == [reference]
    assert len(resolver.calls) == 1
    assert result.question.question.question_type == "single_choice"


@pytest.mark.asyncio
async def test_regeneration_repairs_once_and_keeps_reference_images() -> None:
    provider = FakeQuestionProvider(
        regenerated=_single("Missing visual"),
        repaired=[_single("Repaired", visual=True)],
    )
    service, resolver = _service(provider)
    reference = _materialized("existing_question.image")
    result = await service.regenerate_question(
        request={"visual_mode": "auto", "instruction": "make clearer"},
        expected_question_type="single_choice",
        reference_images=[reference],
    )
    assert result.repaired is True
    assert provider.repair_calls == 1
    assert provider.repair_request["operation"] == "regeneration"
    assert provider.repair_request["original_request"]["visual_mode"] == "auto"
    assert provider.repair_reference_images == [reference]
    assert len(resolver.calls) == 1


@pytest.mark.asyncio
async def test_regeneration_repair_cannot_change_expected_question_type() -> None:
    invalid_multiple = {
        "question_type": "multiple_choice",
        "prompt": "Changed type",
        "instruction": None,
        "image": _image(),
        "options": [
            {"text": "A", "image": None, "is_correct": True},
            {"text": "B", "image": None, "is_correct": True},
            {"text": "C", "image": None, "is_correct": False},
        ],
    }
    provider = FakeQuestionProvider(
        regenerated=_single("Initial", visual=False),
        repaired=[invalid_multiple],
    )
    service, resolver = _service(provider)
    with pytest.raises(AIResponseValidationError):
        await service.regenerate_question(
            request={"visual_mode": "auto"},
            expected_question_type="single_choice",
        )
    assert provider.repair_calls == 1
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_allow_images_target_is_passed_to_model_and_repair() -> None:
    generated = [
        _single(f"Question {index}", visual=index == 0)
        for index in range(15)
    ]
    corrected = [
        _single(f"Question {index}", visual=index < 6)
        for index in range(15)
    ]
    provider = FakeQuestionProvider(generated=generated, repaired=corrected)
    service, resolver = _service(provider)

    result = await service.generate_questions(
        request={"visual_mode": "auto", "question_count": 15},
        expected_count=15,
    )

    assert result.repaired is True
    assert provider.generate_request["visual_question_target"] == 6
    assert provider.repair_request["original_request"]["visual_question_target"] == 6
    assert provider.repair_request["validation_feedback"]["issues"][0]["code"] == (
        "visual_distribution_mismatch"
    )
    assert len(result.questions) == 15
    assert len(resolver.calls) == 6
    assert provider.repair_calls == 1


@pytest.mark.asyncio
async def test_text_only_batch_does_not_add_visual_target_or_resolve_images() -> None:
    generated = [_single(f"Question {index}") for index in range(15)]
    provider = FakeQuestionProvider(generated=generated)
    service, resolver = _service(provider)
    result = await service.generate_questions(
        request={"visual_mode": "text_only", "question_count": 15},
        expected_count=15,
    )
    assert result.repaired is False
    assert "visual_question_target" not in provider.generate_request
    assert resolver.calls == []
