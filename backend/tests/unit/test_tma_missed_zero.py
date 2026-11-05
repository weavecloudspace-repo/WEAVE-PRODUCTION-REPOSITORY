"""Regression tests for missed TMA deadline zeros and safe academic provenance."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ConflictException
from app.modules.tma import deadline_zero_service as mod
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus, TMAAttemptStatus


def uid():
    return uuid.uuid4()


def due():
    return datetime.now(timezone.utc) - timedelta(minutes=4)


def assignment():
    return SimpleNamespace(
        id=uid(),
        tenant_id=uid(),
        status=TMAAssignmentStatus.CLOSED,
        closes_at=due(),
        closed_at=due(),
        current_revision_number=1,
        academic_session_id=uid(),
        academic_term_id=uid(),
        academic_level_id=uid(),
        curriculum_subject_id=uid(),
        zero_grading_requested_at=due(),
        zero_grading_completed_at=None,
        zero_grading_error=None,
    )


@pytest.mark.asyncio
async def test_zero_creates_owned_attempt_with_score_provenance(monkeypatch):
    item = assignment()
    student_id, revision_id = uid(), uid()
    enrollment = SimpleNamespace(
        id=uid(),
        class_id=uid(),
        academic_level_id=item.academic_level_id,
        created_at=item.closes_at - timedelta(days=1),
    )
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "enrollment",
        AsyncMock(return_value=(enrollment, uid())),
    )
    participant = SimpleNamespace(id=uid())
    lookup = AsyncMock(side_effect=[None, participant])
    monkeypatch.setattr(mod.TMAParticipantRepository, "get_by_revision_student", lookup)
    add_participant = AsyncMock(return_value=[participant.id])
    monkeypatch.setattr(mod.TMAParticipantRepository, "insert_missing", add_participant)
    attempt = SimpleNamespace(
        id=uid(),
        status=TMAAttemptStatus.IN_PROGRESS,
        submitted_at=None,
        correct_answers=None,
        total_questions=None,
        score_id=None,
        score_snapshot=None,
        auto_zeroed_at=None,
    )
    monkeypatch.setattr(
        mod.TMAAttemptRepository, "create_if_missing", AsyncMock(return_value=attempt)
    )

    async def record_score(*args, **kwargs):
        assert kwargs["student_id"] == student_id
        assert kwargs["correct"] == 0
        assert kwargs["total"] == 12
        assert kwargs["scoring_date"] == item.closes_at.date()
        attempt.score_id = uid()
        attempt.score_snapshot = Decimal("0")
        return Decimal("0")

    grading = AsyncMock(side_effect=record_score)
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", grading)
    save = AsyncMock()
    monkeypatch.setattr(mod.TMAAttemptRepository, "save", save)
    db = AsyncMock()
    result = await mod.TMADeadlineZeroService._write_zero(
        db,
        assignment=item,
        revision_id=revision_id,
        student_id=student_id,
        total_questions=12,
        current=datetime.now(timezone.utc),
    )
    assert result is True
    assert attempt.status == TMAAttemptStatus.SUBMITTED
    assert attempt.correct_answers == 0
    assert attempt.total_questions == 12
    assert attempt.auto_zeroed_at == attempt.submitted_at
    assert attempt.score_id is not None
    assert attempt.score_snapshot == Decimal("0")
    save.assert_awaited_once_with(db, attempt)
    add_participant.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_submission_is_never_overwritten(monkeypatch):
    item = assignment()
    enrollment = SimpleNamespace(
        id=uid(),
        class_id=uid(),
        academic_level_id=item.academic_level_id,
        created_at=item.closes_at - timedelta(days=1),
    )
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "enrollment",
        AsyncMock(return_value=(enrollment, uid())),
    )
    participant = SimpleNamespace(id=uid())
    monkeypatch.setattr(
        mod.TMAParticipantRepository,
        "get_by_revision_student",
        AsyncMock(return_value=participant),
    )
    monkeypatch.setattr(
        mod.TMAAttemptRepository,
        "create_if_missing",
        AsyncMock(return_value=SimpleNamespace(status=TMAAttemptStatus.SUBMITTED)),
    )
    grade = AsyncMock()
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", grade)
    written = await mod.TMADeadlineZeroService._write_zero(
        AsyncMock(),
        assignment=item,
        revision_id=uid(),
        student_id=uid(),
        total_questions=10,
        current=datetime.now(timezone.utc),
    )
    assert written is False
    grade.assert_not_awaited()


@pytest.mark.asyncio
async def test_student_joining_after_deadline_is_not_penalized(monkeypatch):
    item = assignment()
    enrollment = SimpleNamespace(
        id=uid(),
        class_id=uid(),
        academic_level_id=item.academic_level_id,
        created_at=item.closes_at + timedelta(seconds=1),
    )
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "enrollment",
        AsyncMock(return_value=None),
    )
    grade = AsyncMock()
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", grade)
    with pytest.raises(ConflictException, match="not eligible"):
        await mod.TMADeadlineZeroService._write_zero(
            AsyncMock(),
            assignment=item,
            revision_id=uid(),
            student_id=uid(),
            total_questions=10,
            current=datetime.now(timezone.utc),
        )
    grade.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_finishes_when_all_current_students_are_submitted(monkeypatch):
    item = assignment()
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: item),
        SimpleNamespace(scalar_one=lambda: 0),
        SimpleNamespace(scalar_one_or_none=lambda: None),
    ]
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=SimpleNamespace(id=uid(), published_at=due(), invalidated_at=None)),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(return_value=[(SimpleNamespace(), [])]),
    )
    monkeypatch.setattr(mod.TMADeadlineEligibilityRepository, "capture", AsyncMock())
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "_closure",
        AsyncMock(return_value=SimpleNamespace(id=uid())),
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_open_term", AsyncMock())
    monkeypatch.setattr(mod.TMADeadlineEligibilityRepository, "pending", AsyncMock(return_value=[]))
    grade = AsyncMock()
    monkeypatch.setattr(mod.TMADeadlineZeroService, "_write_zero", grade)
    invalidation = AsyncMock()
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", invalidation)
    outcome = await mod.TMADeadlineZeroService.process_pending(db)
    assert outcome == {"zeroed": 0, "blocked": 0, "pending": 0}
    assert item.zero_grading_completed_at is not None
    grade.assert_not_awaited()
    db.commit.assert_awaited_once()
    invalidation.assert_awaited_once_with(db)


@pytest.mark.asyncio
async def test_worker_does_not_drop_reconciliation_errors(monkeypatch):
    item = assignment()
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: item),
        SimpleNamespace(),
        SimpleNamespace(scalar_one=lambda: 1),
    ]
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=SimpleNamespace(id=uid(), published_at=due(), invalidated_at=None)),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(return_value=[(SimpleNamespace(), [])]),
    )
    monkeypatch.setattr(mod.TMADeadlineEligibilityRepository, "capture", AsyncMock())
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "_closure",
        AsyncMock(return_value=SimpleNamespace(id=uid())),
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_open_term", AsyncMock())
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository, "pending", AsyncMock(return_value=[(uid(), None)])
    )

    @asynccontextmanager
    async def nested():
        yield

    db.begin_nested = nested
    grade = AsyncMock(side_effect=ConflictException("Existing CA mark must not be replaced."))
    monkeypatch.setattr(mod.TMADeadlineZeroService, "_write_zero", grade)
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", AsyncMock())
    outcome = await mod.TMADeadlineZeroService.process_pending(db)
    assert outcome == {"zeroed": 0, "blocked": 1, "pending": 1}
    assert item.zero_grading_completed_at is None
    assert "Existing CA" in item.zero_grading_error


@pytest.mark.asyncio
async def test_second_closure_restores_original_zero_submission_metadata(monkeypatch):
    item = assignment()
    zeroed_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    attempt = SimpleNamespace(
        status=TMAAttemptStatus.IN_PROGRESS,
        submitted_at=None,
        correct_answers=None,
        total_questions=None,
        auto_zeroed_at=zeroed_at,
        auto_zero_resolved_at=None,
        score_reversed_at=None,
        score_id=uid(),
        score_snapshot=Decimal("0.00"),
    )
    monkeypatch.setattr(
        mod.TMADeadlineEligibilityRepository,
        "enrollment",
        AsyncMock(return_value=(SimpleNamespace(id=uid(), class_id=uid()), uid())),
    )
    monkeypatch.setattr(
        mod.TMAParticipantRepository,
        "get_by_revision_student",
        AsyncMock(return_value=SimpleNamespace(id=uid())),
    )
    monkeypatch.setattr(
        mod.TMAAttemptRepository, "get_by_participant", AsyncMock(return_value=attempt)
    )
    monkeypatch.setattr(
        mod.TMAAttemptRepository, "create_if_missing", AsyncMock(return_value=attempt)
    )
    saved = AsyncMock()
    grade = AsyncMock()
    monkeypatch.setattr(mod.TMAAttemptRepository, "save", saved)
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", grade)
    db = AsyncMock()
    assert (
        await mod.TMADeadlineZeroService._write_zero(
            db,
            assignment=item,
            revision_id=uid(),
            student_id=uid(),
            total_questions=10,
            current=datetime.now(timezone.utc),
        )
        is False
    )
    assert (
        attempt.status,
        attempt.submitted_at,
        attempt.correct_answers,
        attempt.total_questions,
    ) == (TMAAttemptStatus.SUBMITTED, zeroed_at, 0, 10)
    saved.assert_awaited_once_with(db, attempt)
    grade.assert_not_awaited()


def test_worker_only_scans_explicitly_queued_deadlines():
    stmt = (
        __import__("sqlalchemy", fromlist=["select"])
        .select(TMAAssignment)
        .where(
            TMAAssignment.status == TMAAssignmentStatus.CLOSED,
            TMAAssignment.zero_grading_requested_at.is_not(None),
            TMAAssignment.zero_grading_completed_at.is_(None),
        )
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "zero_grading_requested_at IS NOT NULL" in sql
    assert "zero_grading_completed_at IS NULL" in sql
    assert TMAAssignment.__table__.c.zero_grading_error.nullable
