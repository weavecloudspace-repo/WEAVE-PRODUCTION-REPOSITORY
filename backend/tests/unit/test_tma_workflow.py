"""Service-level contract regression tests for the initial TMA end-to-end flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.exceptions import ConflictException, ForbiddenException
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.teachers.models import TeacherMembership
from app.modules.tma.models import TMAActorType, TMAAssignmentStatus, TMAAttemptStatus
from app.modules.tma.schemas import (
    TMAAnswerSaveRequest,
    TMAAssignmentCreate,
    TMAQuestionCreate,
)


def _id():
    return uuid.uuid4()


def _admin():
    return TenantAdmin(id=_id(), tenant_id=_id())


def _creation_payload():
    return TMAAssignmentCreate(
        academic_level_id=_id(),
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
        assessment_component_id=_id(),
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
    )


@pytest.mark.asyncio
async def test_create_assignment_initializes_exactly_one_revision(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    admin = _admin()
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_component_scope",
        AsyncMock(return_value=None),
    )

    async def add_assignment(db, assignment):
        assignment.id = _id()
        return assignment

    monkeypatch.setattr(mod.TMAAssignmentRepository, "add", add_assignment)
    revision_add = AsyncMock()
    monkeypatch.setattr(mod.TMARevisionRepository, "add", revision_add)
    db = AsyncMock()
    created = await mod.TMAAssignmentService.create_assignment(
        db,
        actor=admin,
        payload=_creation_payload(),
    )
    assert created.current_revision_number == 1
    assert created.created_by_actor_type == TMAActorType.TENANT_ADMIN
    revision = revision_add.await_args.args[1]
    assert revision.assignment_id == created.id
    assert revision.revision_number == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_assignment_does_not_create_revision(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_component_scope",
        AsyncMock(return_value=SimpleNamespace(id=_id())),
    )
    add = AsyncMock()
    monkeypatch.setattr(mod.TMARevisionRepository, "add", add)
    with pytest.raises(ConflictException, match="already have a TMA"):
        await mod.TMAAssignmentService.create_assignment(
            AsyncMock(),
            actor=_admin(),
            payload=_creation_payload(),
        )
    add.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_question_creation_creates_four_options_atomically(monkeypatch) -> None:
    from app.modules.tma import question_service as mod

    admin = _admin()
    assignment = SimpleNamespace(id=_id(), tenant_id=admin.tenant_id)
    revision = SimpleNamespace(id=_id())
    monkeypatch.setattr(
        mod.TMAQuestionService,
        "_draft_context",
        AsyncMock(return_value=(assignment, revision)),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(mod.TMAQuestionService, "_validate_media", AsyncMock())

    async def add_question(db, question):
        question.id = _id()
        return question

    monkeypatch.setattr(mod.TMAQuestionRepository, "add_question", add_question)
    db = SimpleNamespace(add_all=Mock(), flush=AsyncMock(), commit=AsyncMock())
    payload = TMAQuestionCreate(
        position=1,
        question_text="What is 2 + 2?",
        options=[{"position": i, "option_text": str(i), "is_correct": i == 4} for i in range(1, 5)],
    )
    question = await mod.TMAQuestionService.add_question(
        db,
        actor=admin,
        assignment_id=assignment.id,
        payload=payload,
    )
    assert question.author_actor_type == TMAActorType.TENANT_ADMIN
    options = db.add_all.call_args.args[0]
    assert len(options) == 4
    assert {option.position for option in options} == {1, 2, 3, 4}
    assert sum(option.is_correct for option in options) == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_activation_publishes_revision_only_after_readiness(monkeypatch) -> None:
    from app.modules.tma import lifecycle_service as mod

    admin = _admin()
    monkeypatch.setattr(mod.TMAAcademicGuard, "lock", AsyncMock())
    monkeypatch.setattr(mod.TMAAcademicGuard, "require_draft_results", AsyncMock())
    assignment = SimpleNamespace(
        id=_id(),
        tenant_id=admin.tenant_id,
        status=TMAAssignmentStatus.DRAFT,
        activated_at=None,
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    revision = SimpleNamespace(published_at=None, invalidated_at=None)
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    monkeypatch.setattr(
        mod.TMALifecycleService,
        "_readiness_errors",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=revision),
    )
    monkeypatch.setattr(mod.TMARevisionRepository, "save", AsyncMock())
    monkeypatch.setattr(mod.TMAAssignmentRepository, "save", AsyncMock())
    db = AsyncMock()
    assignment.current_revision_number = 1
    result = await mod.TMALifecycleService.activate_assignment(
        db,
        actor=admin,
        assignment_id=assignment.id,
    )
    assert result.status == TMAAssignmentStatus.ACTIVE
    assert revision.published_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_student_start_uses_existing_participant_and_attempt(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    assignment, revision = SimpleNamespace(id=_id()), SimpleNamespace(id=_id())
    participant = SimpleNamespace(id=_id())
    existing = SimpleNamespace(id=_id(), status=TMAAttemptStatus.IN_PROGRESS, student_started_at=None)
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_active_assignment",
        AsyncMock(return_value=(assignment, revision, SimpleNamespace(class_id=_id()))),
    )
    monkeypatch.setattr(
        mod.TMAParticipantRepository,
        "get_by_revision_student",
        AsyncMock(return_value=participant),
    )
    insert = AsyncMock()
    monkeypatch.setattr(mod.TMAParticipantRepository, "insert_missing", insert)
    attempt_create = AsyncMock(return_value=existing)
    monkeypatch.setattr(mod.TMAAttemptRepository, "create_if_missing", attempt_create)
    response = SimpleNamespace()
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_build_start_response",
        AsyncMock(return_value=response),
    )
    db = AsyncMock()
    returned = await mod.TMAAttemptService.start_or_resume_attempt(
        db,
        student=student,
        assignment_id=assignment.id,
    )
    assert returned is response
    insert.assert_not_awaited()
    attempt_create.assert_awaited_once_with(
        db,
        student.tenant_id,
        participant.id,
        revision.id,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_answer_from_another_question_is_rejected(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt = SimpleNamespace(
        id=_id(),
        status=TMAAttemptStatus.IN_PROGRESS,
        revision_id=_id(),
    )
    revision = SimpleNamespace(id=attempt.revision_id, assignment_id=_id())
    question_id = _id()
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, None, revision)),
    )
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_locked_active_attempt",
        AsyncMock(
            return_value=(
                attempt,
                SimpleNamespace(),
                revision,
                SimpleNamespace(),
                SimpleNamespace(),
            )
        ),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(
            return_value=[
                (
                    SimpleNamespace(id=question_id),
                    [SimpleNamespace(id=_id())],
                )
            ]
        ),
    )
    save = AsyncMock()
    monkeypatch.setattr(mod.TMAAnswerRepository, "save_selection", save)
    db = AsyncMock()
    with pytest.raises(ConflictException, match="belongs to another"):
        await mod.TMAAttemptService.save_answer(
            db,
            student=student,
            attempt_id=attempt.id,
            payload=TMAAnswerSaveRequest(
                question_id=question_id,
                selected_option_id=_id(),
            ),
        )
    save.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_student_submission_commits_score_and_attempt_once(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt = SimpleNamespace(
        id=_id(),
        revision_id=_id(),
        status=TMAAttemptStatus.IN_PROGRESS,
        submitted_at=None,
        correct_answers=None,
        total_questions=None,
        auto_zeroed_at=None,
    )
    revision = SimpleNamespace(id=attempt.revision_id, assignment_id=_id())
    assignment = SimpleNamespace(id=revision.assignment_id)
    question_id, option_id = _id(), _id()
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, None, revision)),
    )
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_locked_active_attempt",
        AsyncMock(
            return_value=(attempt, SimpleNamespace(), revision, assignment, SimpleNamespace())
        ),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(
            return_value=[
                (
                    SimpleNamespace(id=question_id),
                    [SimpleNamespace(id=option_id, is_correct=True)],
                )
            ]
        ),
    )
    monkeypatch.setattr(
        mod.TMAAnswerRepository,
        "list_for_attempt",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    question_id=question_id,
                    selected_option_id=option_id,
                )
            ]
        ),
    )
    persist = AsyncMock(return_value=Decimal("20.00"))
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", persist)
    monkeypatch.setattr(mod.TMAAttemptRepository, "save", AsyncMock())
    db = AsyncMock()
    response = await mod.TMAAttemptService.submit_attempt(
        db,
        student=student,
        attempt_id=attempt.id,
    )
    assert (attempt.correct_answers, attempt.total_questions) == (1, 1)
    assert attempt.status == TMAAttemptStatus.SUBMITTED
    assert response.component_score == Decimal("20.00")
    persist.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submission_result_reads_persisted_component_score(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt = SimpleNamespace(
        id=_id(),
        status=TMAAttemptStatus.SUBMITTED,
        correct_answers=3,
        total_questions=4,
        submitted_at=datetime.now(timezone.utc),
    )
    revision = SimpleNamespace(assignment_id=_id())
    assignment = SimpleNamespace(
        assessment_component_id=_id(),
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
    )
    result = SimpleNamespace(id=_id())
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, None, revision)),
    )
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_results_by_scope_batch",
        AsyncMock(return_value={student.id: result}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_component_scores_batch",
        AsyncMock(return_value={result.id: SimpleNamespace(score=Decimal("11.25"))}),
    )
    response = await mod.TMAAttemptService.get_submission_result(
        AsyncMock(),
        student=student,
        attempt_id=attempt.id,
    )
    assert response.component_score == Decimal("11.25")


@pytest.mark.asyncio
async def test_tma_list_is_empty_when_term_is_not_open(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod
    from app.modules.student_academics.models import AcademicTermStatus

    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_current_term",
        AsyncMock(
            return_value=SimpleNamespace(
                status=AcademicTermStatus.CLOSING,
                is_current=True,
            )
        ),
    )
    enrollment = AsyncMock()
    monkeypatch.setattr(
        mod.StudentEnrollmentRepository,
        "get_authoritative_for_session",
        enrollment,
    )
    results = await mod.TMAAttemptService.list_available_assignments(
        AsyncMock(),
        student=SimpleNamespace(id=_id(), tenant_id=_id()),
    )
    assert results == []
    enrollment.assert_not_awaited()
