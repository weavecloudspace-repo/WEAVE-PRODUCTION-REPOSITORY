from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.providers.base import (
    ImageResolutionResult,
    ProviderImageInput,
    ProviderQuestionGenerationResult,
)
from app.modules.cbt.ai.authoring.service import (
    AuthoringImageBudgetExceededError,
    QuestionAuthoringService,
)


class FakeQuestionProvider:
    provider_name = "fake"

    def is_configured(self) -> bool:
        return True

    async def generate_questions(self, *, request):
        return ProviderQuestionGenerationResult(
            questions=[
                {
                    "question_type": "single_choice",
                    "prompt": "Identify the image.",
                    "instruction": None,
                    "image": {
                        "requirement": "A diagram",
                        "search_query": "diagram",
                        "generation_prompt": "Generate a diagram",
                    },
                    "options": [
                        {"text": "A", "image": None, "is_correct": True},
                        {"text": "B", "image": None, "is_correct": False},
                        {"text": "C", "image": None, "is_correct": False},
                        {"text": "D", "image": None, "is_correct": False},
                    ],
                }
            ]
        )

    async def repair_questions(self, *, request, reference_images=None):
        raise AssertionError("repair should not run")

    async def regenerate_question(self, *, request, reference_images=None):
        raise AssertionError("regeneration should not run")


class OversizedImageResolver:
    async def resolve(self, **kwargs):
        return ImageResolutionResult(
            source="generated",
            image=ProviderImageInput(
                data=b"x" * 11,
                content_type="image/png",
                sha256="0" * 64,
                width=10,
                height=10,
            ),
        )


@pytest.mark.asyncio
async def test_authoring_rejects_total_materialized_images_over_budget(monkeypatch) -> None:
    monkeypatch.setattr(QuestionAuthoringService, "MAX_MATERIALIZED_IMAGE_BYTES", 10)
    service = QuestionAuthoringService(
        question_provider=FakeQuestionProvider(),
        image_resolver=OversizedImageResolver(),
    )

    with pytest.raises(AuthoringImageBudgetExceededError):
        await service.generate_questions(
            request={"visual_mode": "auto"},
            expected_count=1,
        )
