from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.cbt.ai.authoring.schemas import (
    AIMultipleChoiceQuestionDraft,
    AIQuestionOptionDraft,
    AISingleChoiceQuestionDraft,
)
from app.modules.cbt.ai.authoring.visual_policy import target_visual_question_count
from app.modules.cbt.ai.authoring.validation import (
    AIResponseValidationError,
    validate_generated_question_batch,
    validate_regenerated_question,
)


def _image(label: str = "cell") -> dict[str, str]:
    return {
        "requirement": f"A clear educational {label} image",
        "search_query": f"{label} educational image",
        "generation_prompt": f"Generate a clear educational {label} image",
    }


def _single(
    prompt: str = "What is 2 + 2?",
    *,
    visual: bool = False,
    option_visual: bool = False,
) -> dict:
    return {
        "question_type": "single_choice",
        "prompt": prompt,
        "instruction": None,
        "image": _image("number line") if visual else None,
        "options": [
            {
                "text": "4",
                "image": _image("four dots") if option_visual else None,
                "is_correct": True,
            },
            {"text": "5", "image": None, "is_correct": False},
        ],
    }


def _multiple(prompt: str = "Select the prime numbers.", *, visual: bool = False) -> dict:
    return {
        "question_type": "multiple_choice",
        "prompt": prompt,
        "instruction": None,
        "image": _image("number chart") if visual else None,
        "options": [
            {"text": "2", "image": None, "is_correct": True},
            {"text": "3", "image": None, "is_correct": True},
            {"text": "4", "image": None, "is_correct": False},
        ],
    }


def _issue_codes(exc: AIResponseValidationError) -> set[str]:
    return {issue.code for issue in exc.issues}


def test_single_choice_requires_exactly_one_correct_option() -> None:
    raw = _single()
    raw["options"][1]["is_correct"] = True
    with pytest.raises(ValidationError, match="exactly one correct option"):
        AISingleChoiceQuestionDraft.model_validate(raw)


def test_multiple_choice_requires_two_correct_and_one_incorrect() -> None:
    too_few = _multiple()
    too_few["options"][1]["is_correct"] = False
    with pytest.raises(ValidationError, match="at least two correct"):
        AIMultipleChoiceQuestionDraft.model_validate(too_few)

    all_correct = _multiple()
    all_correct["options"][2]["is_correct"] = True
    with pytest.raises(ValidationError, match="at least one incorrect"):
        AIMultipleChoiceQuestionDraft.model_validate(all_correct)


def test_option_requires_text_image_or_both() -> None:
    with pytest.raises(ValidationError, match="must include text, an image, or both"):
        AIQuestionOptionDraft.model_validate({"text": None, "image": None, "is_correct": False})


def test_question_rejects_normalized_duplicate_options() -> None:
    raw = _single()
    raw["options"] = [
        {"text": " Lagos ", "image": None, "is_correct": True},
        {"text": "lagos", "image": None, "is_correct": False},
    ]
    with pytest.raises(ValidationError, match="options must be unique"):
        AISingleChoiceQuestionDraft.model_validate(raw)


def test_schema_forbids_provider_invented_fields_and_coercion() -> None:
    raw = _single()
    raw["provider_note"] = "invented"
    with pytest.raises(ValidationError):
        AISingleChoiceQuestionDraft.model_validate(raw)

    raw = _single()
    raw["options"][0]["is_correct"] = "true"
    with pytest.raises(ValidationError):
        AISingleChoiceQuestionDraft.model_validate(raw)


def test_valid_generated_batch_enforces_count_and_type_distribution() -> None:
    result = validate_generated_question_batch(
        [_single(visual=True), _multiple("Select all factors of 6.")],
        expected_count=2,
        expected_type_counts={"single_choice": 1, "multiple_choice": 1},
        visual_mode="auto",
    )
    assert [item.question_type for item in result] == [
        "single_choice",
        "multiple_choice",
    ]


def test_generated_batch_rejects_invalid_container() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch("not-a-list")
    assert "invalid_questions_container" in _issue_codes(error.value)


def test_generated_batch_rejects_question_count_mismatch() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [_single(visual=True)],
            expected_count=2,
            visual_mode="auto",
        )
    assert "question_count_mismatch" in _issue_codes(error.value)


def test_generated_batch_rejects_type_distribution_mismatch() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [_single(visual=True)],
            expected_type_counts={"single_choice": 0, "multiple_choice": 1},
            visual_mode="auto",
        )
    assert "question_type_count_mismatch" in _issue_codes(error.value)


def test_generated_batch_rejects_duplicate_questions() -> None:
    question = _single(visual=True)
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [question, dict(question)],
            visual_mode="auto",
        )
    assert "duplicate_question" in _issue_codes(error.value)


def test_text_only_rejects_question_level_visual() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch([_single(visual=True)], visual_mode="text_only")
    assert "visual_not_allowed" in _issue_codes(error.value)


def test_text_only_rejects_option_level_visual() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [_single(option_visual=True)],
            visual_mode="text_only",
        )
    assert "visual_not_allowed" in _issue_codes(error.value)


def test_auto_requires_at_least_one_visual_question() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [_single(), _multiple()],
            visual_mode="auto",
        )
    assert "visual_required" in _issue_codes(error.value)


def test_auto_requires_text_questions_to_dominate_batches_of_three_or_more() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(
            [
                _single("Question one", visual=True),
                _single("Question two", visual=True),
                _multiple("Question three"),
            ],
            visual_mode="auto",
        )
    assert "text_questions_not_dominant" in _issue_codes(error.value)


def test_auto_allows_one_visual_and_one_text_question_in_two_question_batch() -> None:
    questions = validate_generated_question_batch(
        [_single("Visual question", visual=True), _multiple("Text question")],
        visual_mode="auto",
    )
    assert len(questions) == 2


def test_auto_allows_text_dominant_larger_batch() -> None:
    questions = validate_generated_question_batch(
        [
            _single("Visual question", visual=True),
            _multiple("Text question one"),
            _single("Text question two"),
        ],
        visual_mode="auto",
    )
    assert len(questions) == 3


def test_regeneration_rejects_question_type_change() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_regenerated_question(
            _multiple(visual=True),
            expected_question_type="single_choice",
            visual_mode="auto",
        )
    assert "question_type_changed" in _issue_codes(error.value)


def test_regeneration_auto_requires_visual() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_regenerated_question(_single(), visual_mode="auto")
    assert "visual_required" in _issue_codes(error.value)


def test_regeneration_text_only_accepts_no_visual() -> None:
    question = validate_regenerated_question(
        _single(),
        expected_question_type="single_choice",
        visual_mode="text_only",
    )
    assert question.question_type == "single_choice"


def test_validation_feedback_is_structured_and_bounded() -> None:
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch([_single()], visual_mode="auto")
    feedback = error.value.to_repair_feedback()
    assert feedback["error"] == "invalid_generated_questions"
    assert feedback["issues"]
    assert all({"path", "code", "message"} <= set(item) for item in feedback["issues"])


@pytest.mark.parametrize(
    ("question_count", "visual_target"),
    [
        (1, 1),
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 2),
        (10, 4),
        (12, 5),
        (15, 6),
        (20, 8),
    ],
)
def test_allow_images_uses_deterministic_40_percent_visual_target(
    question_count: int, visual_target: int
) -> None:
    assert target_visual_question_count(question_count) == visual_target


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_visual_target_rejects_invalid_question_counts(count: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        target_visual_question_count(count)  # type: ignore[arg-type]


def test_fifteen_question_auto_batch_requires_six_visual_questions() -> None:
    questions = [_single(f"Question {index}", visual=index < 6) for index in range(15)]
    result = validate_generated_question_batch(questions, expected_count=15, visual_mode="auto")
    assert len(result) == 15


def test_one_visual_in_fifteen_triggers_structured_repair_feedback() -> None:
    questions = [_single(f"Question {index}", visual=index == 0) for index in range(15)]
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(questions, expected_count=15, visual_mode="auto")
    assert "visual_distribution_mismatch" in _issue_codes(error.value)
    feedback = error.value.to_repair_feedback()
    assert "exactly 6 visual-bearing" in feedback["issues"][0]["message"]


def test_more_than_six_visual_questions_also_misses_distribution() -> None:
    questions = [_single(f"Question {index}", visual=index < 7) for index in range(15)]
    with pytest.raises(AIResponseValidationError) as error:
        validate_generated_question_batch(questions, visual_mode="auto")
    assert "visual_distribution_mismatch" in _issue_codes(error.value)


def test_visual_question_with_option_images_counts_only_once() -> None:
    questions = [
        _single(f"Question {index}", visual=index < 5, option_visual=index == 5)
        for index in range(15)
    ]
    result = validate_generated_question_batch(questions, visual_mode="auto")
    assert len(result) == 15


def test_text_only_still_allows_fifteen_text_questions_without_images() -> None:
    questions = [_single(f"Question {index}") for index in range(15)]
    assert (
        len(
            validate_generated_question_batch(questions, expected_count=15, visual_mode="text_only")
        )
        == 15
    )
