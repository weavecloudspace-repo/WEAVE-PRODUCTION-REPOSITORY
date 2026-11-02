"""Regression coverage for basic TMA authoring, attempts and score integrity."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.student_academics.models import AcademicResultStatus
from app.modules.tma.authorization import TMAAuthorizationService
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.grading_service import TMAGradingService
from app.modules.tma.models import TMAActorType, TMAAssignmentStatus, TMAAttemptStatus


def _id():
    return uuid.uuid4()


def test_grading_counts_only_options_belonging_to_each_question() -> None:
    first, second = _id(), _id()
    first_correct, second_correct, second_wrong = _id(), _id(), _id()
    questions = [
        (SimpleNamespace(id=first), [SimpleNamespace(id=first_correct, is_correct=True)]),
        (
            SimpleNamespace(id=second),
            [
                SimpleNamespace(id=second_wrong, is_correct=False),
                SimpleNamespace(id=second_correct, is_correct=True),
            ],
        ),
    ]
    correct, total = TMAGradingService.calculate_raw_score(
        questions, {first: first_correct, second: second_wrong}
    )
    assert (correct, total) == (1, 2)
    assert TMAGradingService.scaled_component_score(correct, total, Decimal("15")) == Decimal(
        "7.50"
    )


def test_score_rounding_and_invalid_scores() -> None:
    assert TMAGradingService.scaled_component_score(2, 3, Decimal("10")) == Decimal("6.67")
    for correct, total in [(-1, 4), (5, 4), (0, 0)]:
        with pytest.raises(ConflictException):
            TMAGradingService.scaled_component_score(correct, total, Decimal("10"))


def test_only_author_or_lead_or_admin_can_edit_question() -> None:
    tenant_id, author_id, other_id = _id(), _id(), _id()
    assignment = SimpleNamespace(
        id=_id(),
        tenant_id=tenant_id,
        created_by_actor_type=TMAActorType.TEACHER,
        created_by_actor_id=author_id,
    )
    question = SimpleNamespace(
        tenant_id=tenant_id,
        assignment_id=assignment.id,
        author_actor_type=TMAActorType.TEACHER,
        author_actor_id=other_id,
    )
    outsider = SimpleNamespace(id=_id(), tenant_id=tenant_id)
    # Tests the permission rejection independent of ORM authentication.
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_assignment_management(outsider, assignment)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_question_edit_access(outsider, assignment, question)


def test_question_cannot_be_edited_after_activation() -> None:
    with pytest.raises(ConflictException):
        TMAAuthorizationService.require_draft_assignment(
            SimpleNamespace(status=TMAAssignmentStatus.ACTIVE)
        )
    TMAAuthorizationService.require_draft_assignment(
        SimpleNamespace(status=TMAAssignmentStatus.DRAFT)
    )


@pytest.mark.asyncio
async def test_submission_rejects_existing_component_score(monkeypatch) -> None:
    """Existing CA1 records are never replaced by TMA submissions."""
    from app.modules.tma import grading_service as mod

    tenant, student_id, component_id, result_id = _id(), _id(), _id(), _id()
    component = SimpleNamespace(
        id=component_id,
        assessment_scheme_id=_id(),
        is_active=True,
        is_hybrid=False,
        is_examinable=False,
        maximum_score=Decimal("20"),
    )
    scheme = SimpleNamespace(id=component.assessment_scheme_id, status="active")
    result = SimpleNamespace(
        id=result_id,
        status=AcademicResultStatus.DRAFT,
        assessment_scheme_id=scheme.id,
        class_id=_id(),
    )
    db = AsyncMock()
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=scheme)
    )
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_component", AsyncMock(return_value=component)
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_results_by_scope_batch",
        AsyncMock(return_value={student_id: result}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_component_scores_batch",
        AsyncMock(return_value={result_id: SimpleNamespace(score=Decimal("10"))}),
    )
    write = AsyncMock()
    monkeypatch.setattr(mod.StudentAcademicRepository, "add_component_scores_batch", write)
    enrollment = SimpleNamespace(class_id=result.class_id)
    assignment = SimpleNamespace(
        assessment_component_id=component_id,
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
    )
    with pytest.raises(ConflictException, match="already has a score"):
        await TMAGradingService.persist_component_score(
            db,
            tenant_id=tenant,
            student_id=student_id,
            enrollment=enrollment,
            assignment=assignment,
            correct=8,
            total=10,
        )
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_component_write_targets_only_selected_ca(monkeypatch) -> None:
    from app.modules.tma import grading_service as mod

    tenant, student_id, component_id, result_id, class_id = (_id() for _ in range(5))
    component = SimpleNamespace(
        id=component_id,
        assessment_scheme_id=_id(),
        is_active=True,
        is_hybrid=False,
        is_examinable=False,
        maximum_score=Decimal("15"),
    )
    scheme = SimpleNamespace(id=component.assessment_scheme_id, status="active")
    result = SimpleNamespace(
        id=result_id,
        status=AcademicResultStatus.DRAFT,
        assessment_scheme_id=scheme.id,
        class_id=class_id,
        total_score=Decimal("5"),
        grade=None,
        remark=None,
        grading_scale_id=None,
    )
    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=scheme)
    )
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_component", AsyncMock(return_value=component)
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_results_by_scope_batch",
        AsyncMock(return_value={student_id: result}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_component_scores_batch",
        AsyncMock(return_value={}),
    )
    save_scores = AsyncMock()
    monkeypatch.setattr(mod.StudentAcademicRepository, "add_component_scores_batch", save_scores)
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "list_result_component_scores",
        AsyncMock(
            return_value=[
                (SimpleNamespace(id=component_id), SimpleNamespace(score=Decimal("12"))),
                (SimpleNamespace(id=_id()), SimpleNamespace(score=Decimal("5"))),
            ]
        ),
    )
    monkeypatch.setattr(mod.StudentAcademicRepository, "upsert_result", AsyncMock())
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "find_grade_for_score",
        AsyncMock(return_value=None),
    )
    assignment = SimpleNamespace(
        assessment_component_id=component_id,
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
    )
    score = await TMAGradingService.persist_component_score(
        AsyncMock(),
        tenant_id=tenant,
        student_id=student_id,
        enrollment=SimpleNamespace(class_id=class_id),
        assignment=assignment,
        correct=4,
        total=5,
    )
    assert score == Decimal("12.00")
    new_scores = save_scores.await_args.args[1]
    assert len(new_scores) == 1
    assert new_scores[0].assessment_component_id == component_id
    assert new_scores[0].student_subject_result_id == result_id
    assert result.total_score == Decimal("17")


@pytest.mark.asyncio
async def test_submit_does_not_finalize_if_score_write_fails(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt = SimpleNamespace(
        id=_id(),
        participant_id=_id(),
        revision_id=_id(),
        status=TMAAttemptStatus.IN_PROGRESS,
        submitted_at=None,
        correct_answers=None,
        total_questions=None,
    )
    revision = SimpleNamespace(id=attempt.revision_id, assignment_id=_id())
    assignment = SimpleNamespace(id=revision.assignment_id)
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, SimpleNamespace(), revision)),
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
            return_value=[(SimpleNamespace(id=_id()), [SimpleNamespace(id=_id(), is_correct=True)])]
        ),
    )
    monkeypatch.setattr(mod.TMAAnswerRepository, "list_for_attempt", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        mod.TMAGradingService,
        "persist_component_score",
        AsyncMock(side_effect=ConflictException("CA1 locked")),
    )
    db = AsyncMock()
    with pytest.raises(ConflictException, match="CA1 locked"):
        await TMAAttemptService.submit_attempt(
            db,
            student=student,
            attempt_id=attempt.id,
        )
    assert attempt.status == TMAAttemptStatus.IN_PROGRESS
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submitted_attempt_does_not_grade_twice(monkeypatch) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt = SimpleNamespace(id=_id(), status=TMAAttemptStatus.SUBMITTED)
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "_load_owned_attempt",
        AsyncMock(return_value=(attempt, None, None)),
    )
    existing = SimpleNamespace(attempt_id=attempt.id)
    monkeypatch.setattr(
        mod.TMAAttemptService,
        "get_submission_result",
        AsyncMock(return_value=existing),
    )
    grade = AsyncMock()
    monkeypatch.setattr(mod.TMAGradingService, "persist_component_score", grade)
    result = await TMAAttemptService.submit_attempt(
        AsyncMock(),
        student=student,
        attempt_id=attempt.id,
    )
    assert result is existing
    grade.assert_not_awaited()
