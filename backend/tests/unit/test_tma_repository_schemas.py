"""Phase-one TMA repository contracts and safe client-facing schemas."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.tma.models import TMAAttemptStatus, TMAParticipant
from app.modules.tma.repository import (
    TMAAnswerRepository,
    TMAAssignmentRepository,
    TMAParticipantRepository,
    TMAQuestionRepository,
)
from app.modules.tma.schemas import (
    TMAAnswerSaveRequest,
    TMAOptionInput,
    TMAQuestionCreate,
    TMAQuestionUpdate,
    TMAStudentOptionResponse,
    TMAStudentQuestionResponse,
)


def _option(position: int, *, correct: bool = False) -> dict:
    return {"position": position, "option_text": f"Option {position}", "is_correct": correct}


def test_question_creation_requires_four_options_and_exactly_one_correct() -> None:
    base = {"position": 1, "question_text": "Choose the correct option"}
    with pytest.raises(ValidationError):
        TMAQuestionCreate(**base, options=[_option(i, correct=i == 1) for i in range(1, 4)])
    with pytest.raises(ValidationError):
        TMAQuestionCreate(**base, options=[_option(i, correct=i in (1, 2)) for i in range(1, 5)])
    with pytest.raises(ValidationError):
        TMAQuestionCreate(
            **base, options=[_option(1, correct=True), _option(1), _option(3), _option(4)]
        )
    valid = TMAQuestionCreate(**base, options=[_option(i, correct=i == 1) for i in range(1, 5)])
    assert len(valid.options) == 4


def test_text_or_image_is_required_for_questions_and_options() -> None:
    with pytest.raises(ValidationError):
        TMAOptionInput(position=1, option_text=" ")
    with pytest.raises(ValidationError):
        TMAQuestionCreate(position=1, options=[_option(i, correct=i == 1) for i in range(1, 5)])
    assert TMAOptionInput(position=1, image_asset_id=uuid.uuid4()).option_text is None


def test_question_update_validates_full_replacement_options() -> None:
    with pytest.raises(ValidationError):
        TMAQuestionUpdate(version=1, options=[_option(i) for i in range(1, 5)])
    with pytest.raises(ValidationError):
        TMAQuestionUpdate(version=0)
    assert TMAQuestionUpdate(version=1, question_text="New question").options is None


def test_student_question_schema_never_exposes_answer_key() -> None:
    option_id = uuid.uuid4()
    option = SimpleNamespace(
        id=option_id,
        question_id=uuid.uuid4(),
        position=1,
        option_text="Answer",
        image_asset_id=None,
        is_correct=True,
    )
    safe = TMAStudentOptionResponse.model_validate(option)
    question = TMAStudentQuestionResponse(
        id=uuid.uuid4(), question_text="Question?", image_asset_id=None, options=[safe]
    )
    assert safe.model_dump() == {"id": option_id, "option_text": "Answer", "image_asset_id": None}
    assert "is_correct" not in question.model_dump_json()
    with pytest.raises(ValidationError):
        TMAQuestionCreate(position=1, question_text="Question", options=[], tenant_id=uuid.uuid4())


def test_answer_save_allows_explicit_clear_but_no_client_identity() -> None:
    data = TMAAnswerSaveRequest(question_id=uuid.uuid4(), selected_option_id=None)
    assert data.selected_option_id is None
    with pytest.raises(ValidationError):
        TMAAnswerSaveRequest(
            question_id=uuid.uuid4(),
            selected_option_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )
    assert {state.value for state in TMAAttemptStatus} == {"in_progress", "submitted"}


@pytest.mark.asyncio
async def test_repository_rejects_cross_tenant_batch_participation() -> None:
    db = AsyncMock()
    participant = TMAParticipant(
        tenant_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        student_enrollment_id=uuid.uuid4(),
    )
    with pytest.raises(ValueError, match="specified tenant"):
        await TMAParticipantRepository.insert_missing(db, uuid.uuid4(), [participant])
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_question_and_attempt_empty_batch_reads_skip_database() -> None:
    db = AsyncMock()
    await TMAParticipantRepository.insert_missing(db, uuid.uuid4(), [])
    assert (
        await TMAQuestionRepository.list_for_revision_with_options(db, uuid.uuid4(), uuid.uuid4())
        == []
    )
    # A single empty question SELECT occurs, with no follow-up options query.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_invalid_assignment_pagination_rejected_before_database() -> None:
    db = AsyncMock()
    with pytest.raises(ValueError):
        await TMAAssignmentRepository.list_for_scope(db, uuid.uuid4(), limit=101)
    with pytest.raises(ValueError):
        await TMAAssignmentRepository.list_for_scope(db, uuid.uuid4(), offset=-1)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_upsert_uses_unique_attempt_question_constraint() -> None:
    db = AsyncMock()
    db.execute.return_value.scalar_one.return_value = SimpleNamespace(question_id=uuid.uuid4())
    await TMAAnswerRepository.save_selection(
        db, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    statement = db.execute.await_args.args[0]
    compiled = str(
        statement.compile(
            dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()
        )
    )
    assert "ON CONFLICT ON CONSTRAINT uq_tma_answers_attempt_question" in compiled
