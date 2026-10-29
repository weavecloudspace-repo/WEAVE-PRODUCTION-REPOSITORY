from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from app.modules.cbt.ai.authoring.contact_sheet_resolver import ContactSheetImageResolver
from app.modules.cbt.ai.authoring.image_contact_sheet import (
    build_candidate_contact_sheet,
    contact_sheet_candidate_count,
)
from app.modules.cbt.ai.authoring.providers.base import (
    ImageCandidate,
    ProviderGeneratedImage,
    ProviderImageEvaluationResult,
    ProviderImageGenerationResult,
    ProviderImageInput,
)


def _image(label: str, *, width: int = 96, height: int = 72) -> ProviderImageInput:
    image = Image.new("RGB", (width, height), "white")
    output = BytesIO()
    image.save(output, format="JPEG", quality=80)
    data = output.getvalue()
    return ProviderImageInput(
        data=data,
        content_type="image/jpeg",
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        label=label,
    )


class FakeSearchProvider:
    provider_name = "combined"

    def __init__(self, candidates):
        self.candidates = list(candidates)

    def is_configured(self):
        return True

    async def search(self, **kwargs):
        return list(self.candidates)


class ContactSheetEvaluator:
    provider_name = "eval"
    supports_contact_sheet_selection = True

    def __init__(self, selected_index: int):
        self.selected_index = selected_index
        self.images = []
        self.calls = 0

    def is_configured(self):
        return True

    async def evaluate_images(self, *, requirement, images):
        self.calls += 1
        self.images = list(images)
        return ProviderImageEvaluationResult(
            decision="use_candidate",
            selected_index=self.selected_index,
            reason="best numbered tile",
        )


class RecordingMaterializer:
    def __init__(self):
        self.preview_calls: list[str] = []
        self.full_calls: list[str] = []

    async def materialize_candidate_preview(self, candidate, *, label=None):
        self.preview_calls.append(candidate.source)
        return _image(label or f"preview-{candidate.source}")

    async def materialize_candidate(self, candidate, *, label=None):
        self.full_calls.append(candidate.source)
        return _image(label or f"full-{candidate.source}", width=640, height=480)

    async def materialize_generated(self, image, *, label=None):
        return _image(label or "generated")


class Generator:
    provider_name = "generation"

    def __init__(self):
        self.calls = 0

    def is_configured(self):
        return True

    async def generate_image(self, **kwargs):
        self.calls += 1
        return ProviderImageGenerationResult(
            image=ProviderGeneratedImage(
                content_type="image/jpeg",
                data_base64="unused",
            )
        )


def test_contact_sheet_contains_twelve_numbered_candidates() -> None:
    previews = [_image(f"preview-{index}") for index in range(12)]
    sheet = build_candidate_contact_sheet(previews)

    assert contact_sheet_candidate_count([sheet]) == 12
    assert sheet.content_type == "image/jpeg"
    assert sheet.width > 1000
    assert sheet.height > 700
    assert len(sheet.data) > 0


@pytest.mark.asyncio
async def test_resolver_sends_one_contact_sheet_and_full_downloads_only_selection() -> None:
    candidates = [
        ImageCandidate(
            source=f"candidate-{index}",
            source_url=f"https://example.com/source/{index}",
            external_id=str(index),
            image_url=f"https://example.com/image/{index}.jpg",
            thumbnail_url=f"https://example.com/thumb/{index}.jpg",
            title=f"Atom candidate {index}",
        )
        for index in range(12)
    ]
    evaluator = ContactSheetEvaluator(selected_index=7)
    materializer = RecordingMaterializer()
    generator = Generator()
    resolver = ContactSheetImageResolver(
        search_provider=FakeSearchProvider(candidates),
        evaluation_provider=evaluator,
        generation_provider=generator,
        materializer=materializer,
    )

    result = await resolver.resolve(
        requirement="A Bohr-style atom with a nucleus and orbiting electrons",
        search_query="bohr atom electrons nucleus",
    )

    assert evaluator.calls == 1
    assert len(evaluator.images) == 1
    assert contact_sheet_candidate_count(evaluator.images) == 12
    assert len(materializer.preview_calls) == 12
    assert materializer.full_calls == ["candidate-7"]
    assert result.source == "search"
    assert result.candidate is candidates[7]
    assert result.image.width == 640
    assert result.image.height == 480
    assert generator.calls == 0


class AnswerLeakageEvaluator:
    """Fake Qwen: select thumbnail, reject answer-bearing full size, inspect replacement."""

    provider_name = "openrouter"
    supports_contact_sheet_selection = True

    def __init__(self):
        self.requirements = []
        self.calls = 0

    def is_configured(self):
        return True

    async def evaluate_images(self, *, requirement, images):
        self.requirements.append(requirement)
        self.calls += 1
        if self.calls == 1:
            assert contact_sheet_candidate_count(images) == 2
            return ProviderImageEvaluationResult(
                decision="use_candidate",
                selected_index=0,
            )
        if self.calls == 2:
            assert len(images) == 1
            assert images[0].width == 640
            return ProviderImageEvaluationResult(
                decision="generate_image",
                reason="Visible title 'Flat Felled Seams' gives away option A.",
            )
        assert len(images) == 1
        assert images[0].label == "generated"
        return ProviderImageEvaluationResult(decision="use_candidate", selected_index=0)


@pytest.mark.asyncio
async def test_answer_revealing_full_size_image_falls_back_to_audited_generation():
    candidates = [
        ImageCandidate(
            source=f"candidate-{index}",
            source_url=f"https://example.com/{index}",
            image_url=f"https://example.com/{index}.jpg",
        )
        for index in range(2)
    ]
    evaluator = AnswerLeakageEvaluator()
    generator = Generator()
    resolver = ContactSheetImageResolver(
        search_provider=FakeSearchProvider(candidates),
        evaluation_provider=evaluator,
        generation_provider=generator,
        materializer=RecordingMaterializer(),
    )

    result = await resolver.resolve(
        requirement="A seam with enclosed raw edges",
        search_query="flat felled seam",
        assessment_context=(
            '{"question":"Which kind of seam is this?",'
            '"correct_answer_text":["Flat-felled seam"],'
            '"answer_options":["Flat-felled seam","French seam"]}'
        ),
    )

    assert result.source == "generated"
    assert generator.calls == 1
    assert evaluator.calls == 3
    assert all("Flat-felled seam" in requirement for requirement in evaluator.requirements)
    assert len(result.integrity_review_usages) == 2
