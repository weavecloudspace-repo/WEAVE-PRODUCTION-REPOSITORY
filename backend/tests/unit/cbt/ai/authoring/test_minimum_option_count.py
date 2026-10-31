"""Minimum four answer options is a shared contract for every text model."""

from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.contracts import (
    build_question_generation_prompt,
    build_question_regeneration_prompt,
    build_question_repair_prompt,
    openrouter_question_response_format,
)
from app.modules.cbt.ai.authoring.schemas import (
    AIQuestionDraftBase,
    MIN_OPTIONS_PER_QUESTION,
)
from app.modules.cbt.ai.authoring.validation import (
    AIResponseValidationError,
    validate_generated_question_batch,
    validate_regenerated_question,
)


def _question(option_count: int, *, kind: str = "single_choice") -> dict:
    return {
        "question_type": kind,
        "prompt": "Which scientific principle is correct?",
        "instruction": None,
        "image": None,
        "options": [
            {
                "text": f"Distinct alternative {index + 1}",
                "image": None,
                "is_correct": index == 0 or (kind == "multiple_choice" and index == 1),
            }
            for index in range(option_count)
        ],
    }


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_generation_rejects_fewer_than_four_options(count: int) -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [_question(count)], expected_count=1, visual_mode="text_only"
        )
    assert any(
        issue.code == "too_short" and "options" in issue.path
        for issue in error.value.issues
    )


@pytest.mark.parametrize("kind", ["single_choice", "multiple_choice"])
@pytest.mark.parametrize("count", [4, 5, 6])
def test_generation_accepts_four_or_more_distinct_options(kind: str, count: int) -> None:
    questions = validate_generated_question_batch(
        [_question(count, kind=kind)],
        expected_count=1,
        expected_type_counts={kind: 1},
        visual_mode="text_only",
    )
    assert len(questions[0].options) == count


def test_regeneration_enforces_same_option_requirement() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_regenerated_question(_question(3), visual_mode="text_only")
    assert any(issue.code == "too_short" for issue in error.value.issues)

    good = validate_regenerated_question(_question(4), visual_mode="text_only")
    assert len(good.options) == 4


def test_provider_independent_prompts_cover_generation_regeneration_and_repair() -> None:
    assert MIN_OPTIONS_PER_QUESTION == 4
    for prompt in (
        build_question_generation_prompt(),
        build_question_regeneration_prompt(),
        build_question_repair_prompt(),
    ):
        assert "at least 4" in prompt
    assert AIQuestionDraftBase.model_fields["options"].metadata[0].min_length == 4


def test_openrouter_response_schema_remains_provider_compatible() -> None:
    # Strict provider schemas intentionally use only widely supported JSON
    # keywords. Pydantic validates the minimum count after receiving JSON.
    contract = openrouter_question_response_format()
    options = contract["json_schema"]["schema"]["properties"]["questions"]["items"][
        "properties"
    ]["options"]
    assert options["type"] == "array"
    assert options["items"]["properties"]["is_correct"]["type"] == "boolean"
