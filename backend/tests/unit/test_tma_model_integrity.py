"""Regression tests for WEAVE TMA persistence integrity.

These tests inspect SQLAlchemy metadata without connecting to a database.
"""

from __future__ import annotations

import app.models  # noqa: F401 - registers all mapped models with SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.modules.tma.models import TMAAttemptStatus
from app.shared.base_model import Base


TABLES = (
    "tma_assignments",
    "tma_assignment_revisions",
    "tma_media_assets",
    "tma_questions",
    "tma_question_options",
    "tma_participants",
    "tma_attempts",
    "tma_answers",
)


def _table(name: str):
    return Base.metadata.tables[f"public.{name}"]


def _foreign_key(name: str, constraint_name: str):
    constraint = next(
        c
        for c in _table(name).constraints
        if isinstance(c, ForeignKeyConstraint) and c.name == constraint_name
    )
    # Accessing .column forces SQLAlchemy to resolve target columns.
    return (
        tuple(c.name for c in constraint.columns),
        tuple(f"{fk.column.table.name}.{fk.column.name}" for fk in constraint.elements),
    )


def _has_unique(name: str, columns: tuple[str, ...]) -> bool:
    return any(
        isinstance(c, UniqueConstraint) and tuple(col.name for col in c.columns) == columns
        for c in _table(name).constraints
    )


def test_all_tma_tables_are_registered() -> None:
    for name in TABLES:
        assert f"public.{name}" in Base.metadata.tables


def test_all_tma_foreign_keys_resolve() -> None:
    for name in TABLES:
        for constraint in _table(name).foreign_key_constraints:
            for element in constraint.elements:
                assert element.column.table.name  # FK target exists and resolves


def test_answer_cannot_refer_to_question_in_a_different_revision() -> None:
    assert _foreign_key("tma_answers", "fk_tma_answers_tenant_attempt")[0] == (
        "tenant_id",
        "attempt_id",
        "revision_id",
    )
    assert _foreign_key("tma_answers", "fk_tma_answers_tenant_question")[0] == (
        "tenant_id",
        "question_id",
        "revision_id",
    )
    assert _foreign_key("tma_answers", "fk_tma_answers_tenant_question_option")[0] == (
        "tenant_id",
        "question_id",
        "selected_option_id",
    )
    assert _has_unique(
        "tma_answers",
        ("tenant_id", "attempt_id", "question_id"),
    )


def test_images_are_limited_to_the_owning_assignment() -> None:
    assert _foreign_key("tma_questions", "fk_tma_questions_tenant_media")[0] == (
        "tenant_id",
        "assignment_id",
        "image_asset_id",
    )
    assert _foreign_key(
        "tma_question_options",
        "fk_tma_question_options_tenant_media",
    )[0] == ("tenant_id", "assignment_id", "image_asset_id")
    assert _foreign_key("tma_questions", "fk_tma_questions_tenant_revision")[0] == (
        "tenant_id",
        "revision_id",
        "assignment_id",
    )
    assert _foreign_key(
        "tma_question_options",
        "fk_tma_question_options_tenant_question",
    )[0] == ("tenant_id", "question_id", "assignment_id")


def test_participation_belongs_to_student_and_original_class() -> None:
    assert _foreign_key(
        "tma_participants",
        "fk_tma_participants_student_enrollment",
    )[0] == (
        "tenant_id",
        "student_enrollment_id",
        "student_id",
        "class_id",
    )


def test_only_one_attempt_per_participant_and_one_answer_per_question() -> None:
    assert _has_unique("tma_attempts", ("tenant_id", "participant_id"))
    assert _has_unique("tma_answers", ("tenant_id", "attempt_id", "question_id"))
    assert _has_unique(
        "tma_assignments",
        (
            "tenant_id",
            "academic_level_id",
            "curriculum_subject_id",
            "academic_session_id",
            "academic_term_id",
            "assessment_component_id",
        ),
    )


def test_single_correct_option_index_and_attempt_defaults() -> None:
    options = _table("tma_question_options")
    correct = next(
        index for index in options.indexes if index.name == "uq_tma_question_options_one_correct"
    )
    assert correct.unique
    assert correct.dialect_options["postgresql"]["where"] is not None

    attempts = _table("tma_attempts")
    assert {status.value for status in TMAAttemptStatus} == {
        "in_progress",
        "submitted",
    }
    assert attempts.c.status.server_default.arg == "in_progress"
    assert not attempts.c.started_at.nullable
    assert any(
        isinstance(c, CheckConstraint) and c.name == "ck_tma_attempts_submission_consistency"
        for c in attempts.constraints
    )
