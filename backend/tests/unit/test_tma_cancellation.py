"""TMA cancellation is fail-closed, revision-safe, and does not touch CBT marks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import CheckConstraint

from app.core.exceptions import ConflictException
from app.modules.tma.models import (
    TMAActorType,
    TMAAssignmentStatus,
    TMAAttempt,
    TMACancellationRun,
)
from app.modules.tma.cancellation_service import TMACancellationService


def uid():
    return uuid.uuid4()


def fake(status=TMAAssignmentStatus.CLOSED):
    a = SimpleNamespace(
        id=uid(),
        tenant_id=uid(),
        status=status,
        closed_at=None,
        current_revision_number=1,
        activated_at=None,
        zero_grading_requested_at=None,
        zero_grading_completed_at=None,
        zero_grading_error=None,
        assessment_component_id=uid(),
        academic_session_id=uid(),
        academic_term_id=uid(),
        curriculum_subject_id=uid(),
    )
    actor = SimpleNamespace(id=uid(), tenant_id=a.tenant_id)
    return a, actor


@pytest.mark.asyncio
async def test_manual_close_is_idempotent_and_does_not_change_scores(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.ACTIVE)
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_assignment",
        AsyncMock(return_value=assignment),
    )
    db = AsyncMock()
    first = await mod.TMACancellationService.close(
        db,
        actor=actor,
        assignment_id=assignment.id,
    )
    assert first.status == TMAAssignmentStatus.CLOSED
    assert first.closed_at is not None
    assert db.commit.await_count == 1
    second = await mod.TMACancellationService.close(
        db,
        actor=actor,
        assignment_id=assignment.id,
    )
    assert second.closed_at == first.closed_at
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_cancel_requires_closed_and_valid_revision(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.ACTIVE)
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_assignment",
        AsyncMock(return_value=assignment),
    )
    with pytest.raises(ConflictException, match="Close"):
        await mod.TMACancellationService.cancel(
            AsyncMock(),
            actor=actor,
            assignment_id=assignment.id,
            reason="Wrong answer key",
        )


@pytest.mark.asyncio
async def test_close_can_be_cancelled_with_durable_run_and_replayed(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake()
    revision = SimpleNamespace(id=uid(), invalidated_at=None)
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_assignment",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService,
        "actor_type",
        lambda actor: mod.TMAActorType.TENANT_ADMIN,
        raising=False,
    )
    # A direct model value is sufficient; the role is derived from the actor in prod.
    from app.modules.tma.models import TMAActorType

    monkeypatch.setattr(
        mod.TMAAuthorizationService,
        "actor_type",
        lambda _: TMAActorType.TENANT_ADMIN,
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(mod.TMACancellationService, "_enqueue", enqueue)
    db = AsyncMock()
    first = await mod.TMACancellationService.cancel(
        db,
        actor=actor,
        assignment_id=assignment.id,
        reason=" Incorrect answer key ",
    )
    assert first.reason == "Incorrect answer key"
    assert assignment.status == TMAAssignmentStatus.CANCELLING
    db.add.assert_called_once_with(first)
    db.commit.assert_awaited_once()
    enqueue.assert_awaited_once_with(first)
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_run",
        AsyncMock(return_value=first),
    )
    replay = await mod.TMACancellationService.cancel(
        db,
        actor=actor,
        assignment_id=assignment.id,
        reason="Incorrect answer key",
    )
    assert replay is first
    assert db.commit.await_count == 1


def test_ownership_fields_and_failure_tracking_exist():
    table = TMAAttempt.__table__
    assert table.c.score_id.nullable is True
    assert table.c.score_snapshot.nullable is True
    assert table.c.score_reversed_at.nullable is True
    runs = TMACancellationRun.__table__
    assert any(
        isinstance(c, CheckConstraint) and c.name == "ck_tma_cancellation_status"
        for c in runs.constraints
    )


@pytest.mark.asyncio
async def test_worker_rejects_legacy_attempt_without_provenance(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, _ = fake(TMAAssignmentStatus.CANCELLING)
    revision = SimpleNamespace(
        id=uid(),
        assignment_id=assignment.id,
        revision_number=1,
        invalidated_at=None,
    )
    run = SimpleNamespace(
        id=uid(),
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        revision_id=revision.id,
        status="pending",
        reversed_scores=0,
    )
    attempt = SimpleNamespace(
        id=uid(),
        score_id=None,
        score_snapshot=None,
        score_reversed_at=None,
    )
    participant = SimpleNamespace(student_id=uid())
    responses = [
        SimpleNamespace(scalar_one_or_none=lambda: run),
        SimpleNamespace(all=lambda: [(attempt, participant)]),
    ]
    db = AsyncMock()
    db.execute.side_effect = responses
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_id",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    with pytest.raises(ConflictException, match="source|link"):
        await TMACancellationService.process(
            db,
            tenant_id=assignment.tenant_id,
            run_id=run.id,
        )
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert assignment.status == TMAAssignmentStatus.CANCELLING


@pytest.mark.asyncio
async def test_failed_cancellation_never_allows_revision(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.CANCELLING)
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_assignment",
        AsyncMock(return_value=assignment),
    )
    with pytest.raises(ConflictException, match="Finish cancellation"):
        await TMACancellationService.create_revision(
            AsyncMock(),
            actor=actor,
            assignment_id=assignment.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("zero_state", ["completed", "failed"])
async def test_corrected_revision_preserves_previous_questions(monkeypatch, zero_state):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.CANCELLED)
    assignment.zero_grading_requested_at = datetime.now(timezone.utc)
    assignment.zero_grading_completed_at = (
        assignment.zero_grading_requested_at if zero_state == "completed" else None
    )
    assignment.zero_grading_error = "old failure" if zero_state == "failed" else None
    previous = SimpleNamespace(id=uid(), invalidated_at=object())
    original = SimpleNamespace(
        position=1,
        question_text="What is 2 + 2?",
        image_asset_id=None,
    )
    option = SimpleNamespace(
        position=1,
        option_text="4",
        image_asset_id=None,
        is_correct=True,
    )
    monkeypatch.setattr(
        mod.TMACancellationService,
        "_assignment",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=previous),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(return_value=[(original, [option])]),
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService,
        "actor_type",
        lambda _: TMAActorType.TENANT_ADMIN,
        raising=False,
    )

    async def add_rev(db, revision):
        revision.id = uid()
        return revision

    async def add_question(db, question):
        question.id = uid()
        return question

    monkeypatch.setattr(mod.TMARevisionRepository, "add", add_rev)
    monkeypatch.setattr(mod.TMAQuestionRepository, "add_question", add_question)
    db = AsyncMock()
    new = await mod.TMACancellationService.create_revision(
        db,
        actor=actor,
        assignment_id=assignment.id,
    )
    assert previous.zero_grading_requested_at is not None
    assert previous.zero_grading_error == ("old failure" if zero_state == "failed" else None)
    assert assignment.zero_grading_requested_at is None
    assert assignment.zero_grading_completed_at is None
    assert assignment.zero_grading_error is None
    assert new.revision_number == 2
    assert assignment.current_revision_number == 2
    assert assignment.status == TMAAssignmentStatus.DRAFT
    assert assignment.closed_at is None
    db.add_all.assert_called_once()
    assert db.add_all.call_args.args[0][0].option_text == "4"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_student_cannot_read_cancelled_revision_result(monkeypatch):
    from app.modules.tma import attempt_service as mod

    attempt = SimpleNamespace(score_reversed_at=None)
    revision = SimpleNamespace(invalidated_at=datetime.now(timezone.utc))
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, None, revision)),
    )
    with pytest.raises(ConflictException, match="cancelled"):
        await mod.TMAAttemptService.get_submission_result(
            AsyncMock(),
            student=SimpleNamespace(id=uid(), tenant_id=uid()),
            attempt_id=uid(),
        )


@pytest.mark.asyncio
async def test_verified_tma_score_is_reversed_without_touching_other_components(monkeypatch):
    from app.modules.tma import cancellation_service as mod
    from app.modules.student_academics.models import AcademicResultStatus

    assignment, _ = fake(TMAAssignmentStatus.CANCELLING)
    revision = SimpleNamespace(
        id=uid(),
        assignment_id=assignment.id,
        revision_number=1,
        invalidated_at=None,
    )
    run = SimpleNamespace(
        id=uid(),
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        revision_id=revision.id,
        status="pending",
        reversed_scores=0,
        requested_by_actor_type=TMAActorType.TENANT_ADMIN,
        requested_by_actor_id=uid(),
        reason="Incorrect key",
        error_message=None,
        completed_at=None,
    )
    student_id = uid()
    score_id = uid()
    attempt = SimpleNamespace(
        id=uid(),
        score_id=score_id,
        score_snapshot=Decimal("15.00"),
        score_reversed_at=None,
    )
    participant = SimpleNamespace(student_id=student_id)
    score = SimpleNamespace(
        id=score_id,
        score=Decimal("15.00"),
        cbt_score=None,
        theory_score=None,
        source_exam_id=None,
    )
    result = SimpleNamespace(
        id=uid(),
        status=AcademicResultStatus.DRAFT,
        student_id=student_id,
        total_score=Decimal("24.00"),
        grade="A",
        remark="Good",
        grading_scale_id=uid(),
    )
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: run),
        SimpleNamespace(all=lambda: [(attempt, participant)]),
        SimpleNamespace(all=lambda: [(score, result)]),
    ]
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_id",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    other_score = SimpleNamespace(score=Decimal("9.00"))
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "list_result_component_scores_batch",
        AsyncMock(
            return_value={result.id: [
                (SimpleNamespace(), None),
                (SimpleNamespace(), other_score),
            ]}
        ),
    )
    response = await TMACancellationService.process(
        db,
        tenant_id=assignment.tenant_id,
        run_id=run.id,
    )
    assert response == {"status": "completed", "reversed_scores": 1}
    db.delete.assert_awaited_once_with(score)
    assert result.total_score == Decimal("9.00")
    assert result.grade is None
    assert attempt.score_reversed_at is not None
    assert revision.invalidated_at is not None
    assert revision.invalidation_reason == "Incorrect key"
    assert assignment.status == TMAAssignmentStatus.CANCELLED
    assert run.status == "completed"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reversal_never_deletes_modified_or_submitted_academic_result(monkeypatch):
    from app.modules.tma import cancellation_service as mod
    from app.modules.student_academics.models import AcademicResultStatus

    assignment, _ = fake(TMAAssignmentStatus.CANCELLING)
    revision = SimpleNamespace(
        id=uid(),
        assignment_id=assignment.id,
        revision_number=1,
        invalidated_at=None,
    )
    run = SimpleNamespace(
        id=uid(),
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        revision_id=revision.id,
        status="pending",
        reversed_scores=0,
    )
    score_id, student_id = uid(), uid()
    attempt = SimpleNamespace(
        score_id=score_id,
        score_snapshot=Decimal("14.00"),
        score_reversed_at=None,
    )
    score = SimpleNamespace(
        id=score_id,
        score=Decimal("14.00"),
        source_exam_id=None,
        cbt_score=None,
        theory_score=None,
    )
    result = SimpleNamespace(
        status=AcademicResultStatus.SUBMITTED,
        student_id=student_id,
    )
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: run),
        SimpleNamespace(all=lambda: [(attempt, SimpleNamespace(student_id=student_id))]),
        SimpleNamespace(all=lambda: [(score, result)]),
    ]
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_id",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    with pytest.raises(ConflictException, match="submitted|locked|edited"):
        await TMACancellationService.process(
            db,
            tenant_id=assignment.tenant_id,
            run_id=run.id,
        )
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert run.status == "pending"
    assert assignment.status == TMAAssignmentStatus.CANCELLING
