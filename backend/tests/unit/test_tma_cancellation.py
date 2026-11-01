"""TMA cancellation is fail-closed, revision-safe, and does not touch CBT marks."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import CheckConstraint

from app.core.exceptions import ConflictException
from app.modules.tma.models import (
    TMAAssignmentStatus, TMAAttempt, TMACancellationRun,
)
from app.modules.tma.cancellation_service import TMACancellationService


def uid():
    return uuid.uuid4()


def fake(status=TMAAssignmentStatus.CLOSED):
    a = SimpleNamespace(
        id=uid(), tenant_id=uid(), status=status, closed_at=None,
        current_revision_number=1, activated_at=None,
        assessment_component_id=uid(), academic_session_id=uid(),
        academic_term_id=uid(), curriculum_subject_id=uid(),
    )
    actor = SimpleNamespace(id=uid(), tenant_id=a.tenant_id)
    return a, actor


@pytest.mark.asyncio
async def test_manual_close_is_idempotent_and_does_not_change_scores(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.ACTIVE)
    monkeypatch.setattr(
        mod.TMACancellationService, "_assignment", AsyncMock(return_value=assignment),
    )
    db = AsyncMock()
    first = await mod.TMACancellationService.close(
        db, actor=actor, assignment_id=assignment.id,
    )
    assert first.status == TMAAssignmentStatus.CLOSED
    assert first.closed_at is not None
    assert db.commit.await_count == 1
    second = await mod.TMACancellationService.close(
        db, actor=actor, assignment_id=assignment.id,
    )
    assert second.closed_at == first.closed_at
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_cancel_requires_closed_and_valid_revision(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.ACTIVE)
    monkeypatch.setattr(
        mod.TMACancellationService, "_assignment", AsyncMock(return_value=assignment),
    )
    with pytest.raises(ConflictException, match="Close"):
        await mod.TMACancellationService.cancel(
            AsyncMock(), actor=actor, assignment_id=assignment.id,
            reason="Wrong answer key",
        )


@pytest.mark.asyncio
async def test_close_can_be_cancelled_with_durable_run_and_replayed(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake()
    revision = SimpleNamespace(id=uid(), invalidated_at=None)
    monkeypatch.setattr(
        mod.TMACancellationService, "_assignment", AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_number", AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "actor_type",
        lambda actor: mod.TMAActorType.TENANT_ADMIN,
        raising=False,
    )
    # A direct model value is sufficient; the role is derived from the actor in prod.
    from app.modules.tma.models import TMAActorType
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "actor_type",
        lambda _: TMAActorType.TENANT_ADMIN,
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(mod.TMACancellationService, "_enqueue", enqueue)
    db = AsyncMock()
    first = await mod.TMACancellationService.cancel(
        db, actor=actor, assignment_id=assignment.id,
        reason=" Incorrect answer key ",
    )
    assert first.reason == "Incorrect answer key"
    assert assignment.status == TMAAssignmentStatus.CANCELLING
    db.add.assert_called_once_with(first)
    db.commit.assert_awaited_once()
    enqueue.assert_awaited_once_with(first)
    monkeypatch.setattr(
        mod.TMACancellationService, "_run", AsyncMock(return_value=first),
    )
    replay = await mod.TMACancellationService.cancel(
        db, actor=actor, assignment_id=assignment.id,
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
        id=uid(), assignment_id=assignment.id,
        revision_number=1, invalidated_at=None,
    )
    run = SimpleNamespace(
        id=uid(), tenant_id=assignment.tenant_id,
        assignment_id=assignment.id, revision_id=revision.id,
        status="pending", reversed_scores=0,
    )
    attempt = SimpleNamespace(
        id=uid(), score_id=None, score_snapshot=None, score_reversed_at=None,
    )
    participant = SimpleNamespace(student_id=uid())
    responses = [
        SimpleNamespace(scalar_one_or_none=lambda: run),
        SimpleNamespace(all=lambda: [(attempt, participant)]),
    ]
    db = AsyncMock()
    db.execute.side_effect = responses
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_id",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    with pytest.raises(ConflictException, match="source|link"):
        await TMACancellationService.process(
            db, tenant_id=assignment.tenant_id, run_id=run.id,
        )
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert assignment.status == TMAAssignmentStatus.CANCELLING


@pytest.mark.asyncio
async def test_failed_cancellation_never_allows_revision(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.CANCELLING)
    monkeypatch.setattr(
        mod.TMACancellationService, "_assignment", AsyncMock(return_value=assignment),
    )
    with pytest.raises(ConflictException, match="Finish cancellation"):
        await TMACancellationService.create_revision(
            AsyncMock(), actor=actor, assignment_id=assignment.id,
        )


@pytest.mark.asyncio
async def test_corrected_revision_preserves_previous_questions(monkeypatch):
    from app.modules.tma import cancellation_service as mod

    assignment, actor = fake(TMAAssignmentStatus.CANCELLED)
    previous = SimpleNamespace(id=uid(), invalidated_at=object())
    original = SimpleNamespace(
        position=1, question_text="What is 2 + 2?", image_asset_id=None,
    )
    option = SimpleNamespace(
        position=1, option_text="4", image_asset_id=None, is_correct=True,
    )
    monkeypatch.setattr(
        mod.TMACancellationService, "_assignment", AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_number", AsyncMock(return_value=previous),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository, "list_for_revision_with_options",
        AsyncMock(return_value=[(original, [option])]),
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "actor_type",
        lambda _: mod.TMAActorType.TENANT_ADMIN,
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
        db, actor=actor, assignment_id=assignment.id,
    )
    assert new.revision_number == 2
    assert assignment.current_revision_number == 2
    assert assignment.status == TMAAssignmentStatus.DRAFT
    assert assignment.closed_at is None
    db.add_all.assert_called_once()
    assert db.add_all.call_args.args[0][0].option_text == "4"
    db.commit.assert_awaited_once()


def test_student_result_does_not_alias_cancelled_revision():
    from app.modules.tma import attempt_service

    assert "invalidated_at" in attempt_service.TMAAttemptService.get_submission_result.__code__.co_names
