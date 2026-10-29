"""Strict validation for untrusted CBT AI question output."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.modules.cbt.ai.authoring.schemas import (
    AIQuestionBatchDraft,
    AIQuestionDraft,
    AIRegeneratedQuestionDraft,
    AIVisualMode,
)
from app.modules.cbt.ai.authoring.visual_policy import target_visual_question_count


SUPPORTED_QUESTION_TYPES = frozenset(
    {
        "single_choice",
        "multiple_choice",
    }
)

SUPPORTED_VISUAL_MODES = frozenset(
    {
        "text_only",
        "auto",
    }
)

MAX_REPAIR_ISSUES = 50


@dataclass(frozen=True, slots=True)
class AIValidationIssue:
    """One provider-output validation problem."""

    path: str
    code: str
    message: str


class AIResponseValidationError(ValueError):
    """
    Raised when AI-generated output violates the trusted CBT contract.

    The original provider response is intentionally not embedded in this
    exception because provider output may be large and should not be
    copied unnecessarily into logs or repair prompts.
    """

    def __init__(
        self,
        message: str,
        *,
        issues: Sequence[AIValidationIssue] | None = None,
    ) -> None:
        super().__init__(message)
        self.issues = tuple(issues or ())

    def to_repair_feedback(self) -> dict[str, Any]:
        """Return bounded structured feedback suitable for one repair attempt."""
        return {
            "error": "invalid_generated_questions",
            "message": str(self),
            "issues": [
                {
                    "path": issue.path,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in self.issues[:MAX_REPAIR_ISSUES]
            ],
        }


def _format_location(location: Sequence[str | int]) -> str:
    """Convert Pydantic error locations into readable dotted paths."""
    if not location:
        return "$"
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def _issues_from_pydantic(exc: ValidationError) -> list[AIValidationIssue]:
    """Normalize Pydantic validation errors for repair feedback."""
    issues: list[AIValidationIssue] = []
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = error.get("loc") or ()
        message = str(error.get("msg") or "Invalid value.")
        code = str(error.get("type") or "validation_error")
        issues.append(
            AIValidationIssue(
                path=_format_location(location),
                code=code,
                message=message,
            )
        )
    return issues


def _normalized_text(value: str) -> str:
    """Normalize human-readable text for duplicate detection."""
    return " ".join(value.split()).casefold()


def _question_fingerprint(question: AIQuestionDraft) -> tuple[Any, ...]:
    """Build a semantic fingerprint used to reject duplicate questions."""
    option_fingerprints: list[tuple[Any, ...]] = []
    for option in question.options:
        image_fingerprint = None
        if option.image is not None:
            image_fingerprint = (
                _normalized_text(option.image.requirement),
                _normalized_text(option.image.search_query),
            )
        option_fingerprints.append(
            (
                _normalized_text(option.text) if option.text else None,
                image_fingerprint,
                option.is_correct,
            )
        )
    question_image = None
    if question.image is not None:
        question_image = (
            _normalized_text(question.image.requirement),
            _normalized_text(question.image.search_query),
        )
    return (
        question.question_type,
        _normalized_text(question.prompt),
        question_image,
        tuple(option_fingerprints),
    )


def _question_has_visual(question: AIQuestionDraft) -> bool:
    """Return whether a question contains any resolvable image directive."""
    if question.image is not None:
        return True
    return any(option.image is not None for option in question.options)


def _validate_expected_count(
    questions: Sequence[AIQuestionDraft],
    *,
    expected_count: int | None,
) -> list[AIValidationIssue]:
    issues: list[AIValidationIssue] = []
    if expected_count is None:
        return issues
    if type(expected_count) is not int or expected_count <= 0:
        raise ValueError("expected_count must be a positive integer.")
    actual_count = len(questions)
    if actual_count != expected_count:
        issues.append(
            AIValidationIssue(
                path="questions",
                code="question_count_mismatch",
                message=(
                    f"Expected exactly {expected_count} questions "
                    f"but provider returned {actual_count}."
                ),
            )
        )
    return issues


def _validate_expected_type_counts(
    questions: Sequence[AIQuestionDraft],
    *,
    expected_type_counts: Mapping[str, int] | None,
) -> list[AIValidationIssue]:
    issues: list[AIValidationIssue] = []
    if expected_type_counts is None:
        return issues
    normalized_expected: dict[str, int] = {}
    for question_type, count in expected_type_counts.items():
        if question_type not in SUPPORTED_QUESTION_TYPES:
            raise ValueError(f"Unsupported expected question type: {question_type!r}.")
        if type(count) is not int or count < 0:
            raise ValueError("Expected question-type counts must be non-negative integers.")
        normalized_expected[question_type] = count
    actual_counts = Counter(question.question_type for question in questions)
    for question_type in SUPPORTED_QUESTION_TYPES:
        expected = normalized_expected.get(question_type, 0)
        actual = actual_counts.get(question_type, 0)
        if actual != expected:
            issues.append(
                AIValidationIssue(
                    path="questions",
                    code="question_type_count_mismatch",
                    message=(
                        f"Expected {expected} {question_type} question(s) "
                        f"but provider returned {actual}."
                    ),
                )
            )
    return issues


def _validate_no_duplicate_questions(
    questions: Sequence[AIQuestionDraft],
) -> list[AIValidationIssue]:
    """Reject duplicate questions inside one generated batch."""
    issues: list[AIValidationIssue] = []
    seen: dict[tuple[Any, ...], int] = {}
    for index, question in enumerate(questions):
        fingerprint = _question_fingerprint(question)
        original_index = seen.get(fingerprint)
        if original_index is not None:
            issues.append(
                AIValidationIssue(
                    path=f"questions[{index}]",
                    code="duplicate_question",
                    message=(f"Generated question duplicates questions[{original_index}]."),
                )
            )
            continue
        seen[fingerprint] = index
    return issues


def _validate_visual_mode_value(visual_mode: AIVisualMode | None) -> None:
    if visual_mode is None:
        return
    if visual_mode not in SUPPORTED_VISUAL_MODES:
        raise ValueError(f"Unsupported visual mode: {visual_mode!r}.")


def _validate_question_visual_policy(
    question: AIQuestionDraft,
    *,
    visual_mode: AIVisualMode | None,
    path: str,
) -> list[AIValidationIssue]:
    """Validate per-question visual-policy rules."""
    _validate_visual_mode_value(visual_mode)
    if visual_mode != "text_only":
        return []
    issues: list[AIValidationIssue] = []
    if question.image is not None:
        issues.append(
            AIValidationIssue(
                path=f"{path}.image",
                code="visual_not_allowed",
                message=(
                    "Question-level image directives are not allowed "
                    "when visual_mode is 'text_only'."
                ),
            )
        )
    for option_index, option in enumerate(question.options):
        if option.image is None:
            continue
        issues.append(
            AIValidationIssue(
                path=f"{path}.options[{option_index}].image",
                code="visual_not_allowed",
                message=(
                    "Option-level image directives are not allowed when visual_mode is 'text_only'."
                ),
            )
        )
    return issues


def _validate_batch_visual_policy(
    questions: Sequence[AIQuestionDraft],
    *,
    visual_mode: AIVisualMode | None,
) -> list[AIValidationIssue]:
    """Validate visual policy across a complete generated batch."""
    _validate_visual_mode_value(visual_mode)
    issues: list[AIValidationIssue] = []
    if visual_mode == "text_only":
        for index, question in enumerate(questions):
            issues.extend(
                _validate_question_visual_policy(
                    question,
                    visual_mode=visual_mode,
                    path=f"questions[{index}]",
                )
            )
        return issues
    if visual_mode != "auto":
        return issues
    visual_count = sum(1 for question in questions if _question_has_visual(question))
    if visual_count == 0:
        issues.append(
            AIValidationIssue(
                path="questions",
                code="visual_required",
                message=(
                    "At least one visual-bearing question is required when visual_mode is 'auto'."
                ),
            )
        )
        return issues
    if len(questions) >= 3:
        text_only_count = len(questions) - visual_count
        if visual_count >= text_only_count:
            issues.append(
                AIValidationIssue(
                    path="questions",
                    code="text_questions_not_dominant",
                    message=(
                        "When visual_mode is 'auto', text-only questions "
                        "must outnumber visual-bearing questions."
                    ),
                )
            )
    target = target_visual_question_count(len(questions))
    if visual_count != target:
        issues.append(
            AIValidationIssue(
                path="questions",
                code="visual_distribution_mismatch",
                message=(
                    f"Allow-images mode requires exactly {target} visual-bearing "
                    f"question(s) and {len(questions) - target} text-only question(s) "
                    f"in a {len(questions)}-question batch; received "
                    f"{visual_count} visual-bearing question(s)."
                ),
            )
        )
    return issues


def validate_generated_question_batch(
    raw_questions: Sequence[Mapping[str, Any]],
    *,
    expected_count: int | None = None,
    expected_type_counts: Mapping[str, int] | None = None,
    visual_mode: AIVisualMode | None = None,
) -> list[AIQuestionDraft]:
    """Validate a provider-generated batch and return trusted question drafts."""
    if isinstance(raw_questions, (str, bytes)):
        raise AIResponseValidationError(
            "AI question output must be an array of question objects.",
            issues=[
                AIValidationIssue(
                    path="questions",
                    code="invalid_questions_container",
                    message="Expected an array of question objects.",
                )
            ],
        )
    if not isinstance(raw_questions, Sequence):
        raise AIResponseValidationError(
            "AI question output must be an array of question objects.",
            issues=[
                AIValidationIssue(
                    path="questions",
                    code="invalid_questions_container",
                    message="Expected an array of question objects.",
                )
            ],
        )
    raw_list = list(raw_questions)
    try:
        batch = AIQuestionBatchDraft.model_validate({"questions": raw_list})
    except ValidationError as exc:
        raise AIResponseValidationError(
            "AI-generated questions failed schema validation.",
            issues=_issues_from_pydantic(exc),
        ) from exc
    questions = list(batch.questions)
    issues: list[AIValidationIssue] = []
    issues.extend(_validate_expected_count(questions, expected_count=expected_count))
    issues.extend(
        _validate_expected_type_counts(
            questions,
            expected_type_counts=expected_type_counts,
        )
    )
    issues.extend(_validate_no_duplicate_questions(questions))
    issues.extend(_validate_batch_visual_policy(questions, visual_mode=visual_mode))
    if issues:
        raise AIResponseValidationError(
            "AI-generated questions failed contract validation.",
            issues=issues,
        )
    return questions


def validate_regenerated_question(
    raw_question: Mapping[str, Any],
    *,
    expected_question_type: Literal[
        "single_choice",
        "multiple_choice",
    ]
    | None = None,
    visual_mode: AIVisualMode | None = None,
) -> AIQuestionDraft:
    """Validate one regenerated question."""
    if not isinstance(raw_question, Mapping):
        raise AIResponseValidationError(
            "AI-regenerated question must be an object.",
            issues=[
                AIValidationIssue(
                    path="question",
                    code="invalid_question_container",
                    message="Expected a question object.",
                )
            ],
        )
    try:
        envelope = AIRegeneratedQuestionDraft.model_validate({"question": dict(raw_question)})
    except ValidationError as exc:
        raise AIResponseValidationError(
            "AI-regenerated question failed schema validation.",
            issues=_issues_from_pydantic(exc),
        ) from exc
    question = envelope.question
    issues: list[AIValidationIssue] = []
    if expected_question_type is not None and question.question_type != expected_question_type:
        issues.append(
            AIValidationIssue(
                path="question.question_type",
                code="question_type_changed",
                message=(
                    f"Expected {expected_question_type!r} "
                    f"but provider returned {question.question_type!r}."
                ),
            )
        )
    issues.extend(
        _validate_question_visual_policy(
            question,
            visual_mode=visual_mode,
            path="question",
        )
    )
    if visual_mode == "auto" and not _question_has_visual(question):
        issues.append(
            AIValidationIssue(
                path="question",
                code="visual_required",
                message=(
                    "A regenerated question must contain at least one "
                    "image directive when visual_mode is 'auto'."
                ),
            )
        )
    if issues:
        raise AIResponseValidationError(
            "AI-regenerated question failed contract validation.",
            issues=issues,
        )
    return question
