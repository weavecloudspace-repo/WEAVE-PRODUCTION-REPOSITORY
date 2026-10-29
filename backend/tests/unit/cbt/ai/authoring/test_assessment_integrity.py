"""Question-aware image acceptance tests: visual relevance cannot reveal answers."""

from __future__ import annotations

from app.modules.cbt.ai.authoring.assessment_integrity import (
    assessment_context,
    assessment_review_requirement,
    assessment_safe_generation_prompt,
)
from app.modules.cbt.ai.authoring.schemas import AISingleChoiceQuestionDraft


def _seam_question() -> AISingleChoiceQuestionDraft:
    return AISingleChoiceQuestionDraft.model_validate(
        {
            "question_type": "single_choice",
            "prompt": "Which kind of seam is shown in the photograph?",
            "instruction": "Study the seam carefully.",
            "image": None,
            "options": [
                {"text": "Flat-felled seam", "image": None, "is_correct": True},
                {"text": "French seam", "image": None, "is_correct": False},
                {"text": "Lapped seam", "image": None, "is_correct": False},
            ],
        }
    )


def test_review_receives_correct_answer_and_blocks_answer_text() -> None:
    context = assessment_context(_seam_question())
    review = assessment_review_requirement("Photograph of a finished seam", context)
    assert '"correct_answer_text": ["Flat-felled seam"]' in review
    assert "REJECT every image" in review
    assert "'Flat Felled Seams'" in review
    assert "decision='generate_image'" in review
    assert "Which kind of seam" in review


def test_generation_fallback_prohibits_answer_bearing_titles() -> None:
    context = assessment_context(_seam_question())
    prompt = assessment_safe_generation_prompt("Show the fabric seam", context)
    assert "Do NOT write the correct" in prompt
    assert "avoid" in prompt.lower()
    assert "Flat-felled seam" in prompt


def test_without_assessment_context_other_image_calls_unchanged() -> None:
    assert assessment_review_requirement("An orange", None) == "An orange"
    assert assessment_safe_generation_prompt("An orange", None) == "An orange"
