from __future__ import annotations

import base64
import hashlib
from io import BytesIO

import pytest
from PIL import Image

from app.modules.cbt.ai.authoring.providers.base import (
    ImageCandidate,
    ImageResolutionResult,
    ProviderImageInput,
)
from app.modules.cbt.ai.schemas import AIRegenerateQuestionRequest
from app.modules.cbt.ai.service import CBTAIService


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _transport(raw: bytes) -> dict[str, object]:
    return {
        "content_type": "image/png",
        "data_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


@pytest.mark.asyncio
async def test_regeneration_decodes_images_before_authoring_provider_boundary() -> None:
    raw = _png_bytes()
    image = {
        **_transport(raw),
        "source": "search",
        "source_url": "https://example.com/source-page",
        "creator": "Example creator",
        "attribution_text": "Example attribution",
        "license_name": "Example license",
        "license_url": "https://example.com/license",
    }
    request = AIRegenerateQuestionRequest(
        subject="Biology",
        academic_level="SS1",
        generation_prompt="Keep the question focused on cell structures.",
        existing_question={
            "question_type": "single_choice",
            "prompt": "Identify the structure.",
            "image": image,
            "options": [
                {"text": None, "image": image, "is_correct": True},
                {"text": "Other", "is_correct": False},
            ],
        },
        instruction="Make the visual question harder",
        visual_mode="auto",
    )

    payload, reference_images = await CBTAIService._prepare_regeneration_request(request)

    assert len(reference_images) == 2
    assert reference_images[0].data == raw
    assert reference_images[0].label == "existing_question.image"
    assert reference_images[1].data == raw
    assert reference_images[1].label == "existing_question.options[0].image"
    assert payload["generation_prompt"] == "Keep the question focused on cell structures."

    question_image_marker = payload["existing_question"]["image"]
    assert "data_base64" not in question_image_marker
    assert question_image_marker["reference_image_label"] == "existing_question.image"
    option_marker = payload["existing_question"]["options"][0]["image"]
    assert "data_base64" not in option_marker
    assert option_marker["reference_image_label"] == "existing_question.options[0].image"


def test_resolved_image_response_contains_bytes_not_operational_url() -> None:
    raw = _png_bytes()
    canonical = ProviderImageInput(
        data=raw,
        content_type="image/png",
        sha256=hashlib.sha256(raw).hexdigest(),
        width=16,
        height=12,
        alt_text="cell diagram",
    )
    resolution = ImageResolutionResult(
        source="search",
        image=canonical,
        candidate=ImageCandidate(
            source="ddgs",
            source_url="https://example.com/source-page",
            image_url="https://example.com/transient-image.png",
            creator="Example creator",
        ),
    )

    response = CBTAIService._build_image_response(resolution)

    assert response is not None
    assert base64.b64decode(response.data_base64) == raw
    assert response.sha256 == canonical.sha256
    assert response.content_type == "image/png"
    assert response.source_url == "https://example.com/source-page"
    assert not hasattr(response, "url")
