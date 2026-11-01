"""Regression checks for tenant-scoped lightweight TMA submissions reports."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.tma.reporting_repository import TMAReportingRepository
from app.modules.tma.reporting_service import TMAReportingService
from app.modules.tma.schemas import TMAParticipationStatus


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _assignment():
    return SimpleNamespace(
        id=_id(),
        tenant_id=_id(),
        academic_level_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
        curriculum_subject_id=_id(),
        assessment_component_id=_id(),
    )


def _compile(assignment, **kwargs):
    stmt = TMAReportingRepository._query(
        assignment,
        regular_class_ids=kwargs.get("regular_class_ids", {_id()}),
        grouped_elective_class_ids=kwargs.get("grouped_elective_class_ids", set()),
        search=kwargs.get("search"),
        class_id=kwargs.get("class_id"),
        participation_status=kwargs.get("participation_status"),
    )
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_roster_unions_live_eligibility_with_historical_participation() -> None:
    assignment = _assignment()
    sql, params = _compile(assignment)
    assert "UNION" in sql
    assert "tma_participants" in sql
    assert "tma_assignment_revisions" in sql
    assert "student_enrollments" in sql
    assert "is_current" not in sql or "started_on" in sql
    assert "student_assessment_scores" in sql
    assert "row_number()" in sql.lower()
    assert assignment.tenant_id in params.values()
    assert assignment.id in params.values()
    assert assignment.assessment_component_id in params.values()


def test_historical_scores_are_present_only_for_submitted_attempts() -> None:
    sql, params = _compile(_assignment())
    assert "CASE WHEN" in sql
    assert "student_assessment_scores.score" in sql
    assert "in_progress" in params.values()
    assert "submitted" in params.values()
    assert "not_started" in params.values()


def test_filters_restrict_class_status_and_literal_search() -> None:
    class_id = _id()
    sql, params = _compile(
        _assignment(),
        class_id=class_id,
        participation_status=TMAParticipationStatus.IN_PROGRESS,
        search=r"Ann_%\\",
    )
    assert class_id in params.values()
    assert "in_progress" in params.values()
    assert "ILIKE" in sql
    assert "ESCAPE" in sql
    assert any(r"Ann\\_\\%\\\\ "[:-1] in str(value) for value in params.values())


def test_elective_eligibility_is_student_specific() -> None:
    elective_class = _id()
    sql, params = _compile(
        _assignment(), regular_class_ids=set(),
        grouped_elective_class_ids={elective_class},
    )
    assert "student_elective_selections" in sql
    assert "EXISTS" in sql
    assert elective_class in params.values()


def test_no_active_classes_still_keeps_historical_roster() -> None:
    sql, _ = _compile(
        _assignment(), regular_class_ids=set(),
        grouped_elective_class_ids=set(),
    )
    assert "UNION" in sql
    assert "tma_participants" in sql


@pytest.mark.asyncio
async def test_repository_uses_database_count_and_page_limits() -> None:
    assignment = _assignment()
    fake_rows = [
        {
            "student_id": _id(),
            "admission_number": "WVS1001",
            "student_name": "Ada Ben",
            "class_id": _id(),
            "class_name": "JSS3 A",
            "participation_status": "submitted",
            "score": Decimal("11.00"),
            "submitted_at": None,
            "is_currently_eligible": True,
        }
    ]
    scalar = SimpleNamespace(scalar_one=lambda: 4)
    mapped = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: fake_rows))
    db = AsyncMock()
    db.execute.side_effect = [scalar, mapped]
    rows, total = await TMAReportingRepository.list_participation(
        db,
        assignment=assignment,
        regular_class_ids={_id()},
        grouped_elective_class_ids=set(),
        search=None,
        class_id=None,
        participation_status=None,
        offset=2,
        limit=1,
    )
    assert total == 4
    assert rows == fake_rows
    assert db.execute.await_count == 2
    statement = db.execute.await_args_list[1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert 2 in compiled.params.values()
    assert 1 in compiled.params.values()
    assert "ORDER BY" in str(compiled)


@pytest.mark.asyncio
async def test_service_applies_term_elective_policy_and_returns_scores(monkeypatch) -> None:
    from app.modules.tma import reporting_service as mod

    assignment = _assignment()
    actor = SimpleNamespace(tenant_id=assignment.tenant_id)
    general_class, grouped_class = _id(), _id()

    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id",
        AsyncMock(return_value=assignment),
    )
    allowed = AsyncMock()
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_access", allowed,
    )
    def _scalars():
        return SimpleNamespace(all=lambda: [general_class, grouped_class])
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=_scalars)
    monkeypatch.setattr(
        mod.CurriculumResolutionService, "resolve_classes_subjects",
        AsyncMock(return_value={
            general_class: [SimpleNamespace(
                curriculum_subject_id=assignment.curriculum_subject_id,
                is_elective=False, elective_group_id=None,
            )],
            grouped_class: [SimpleNamespace(
                curriculum_subject_id=assignment.curriculum_subject_id,
                is_elective=True, elective_group_id=_id(),
            )],
        }),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_term_by_id",
        AsyncMock(return_value=SimpleNamespace(is_current=True)),
    )
    student = {
        "student_id": _id(),
        "admission_number": "WVS1001",
        "student_name": "Ada Ben",
        "class_id": general_class,
        "class_name": "JSS3 A",
        "participation_status": "submitted",
        "score": Decimal("11.00"),
        "submitted_at": None,
        "is_currently_eligible": True,
    }
    read = AsyncMock(return_value=([student], 1))
    monkeypatch.setattr(mod.TMAReportingRepository, "list_participation", read)
    response = await TMAReportingService.list_assignment_participation(
        db,
        actor=actor, assignment_id=assignment.id, offset=0, limit=50,
        search="Ada", participation_status=TMAParticipationStatus.SUBMITTED,
    )
    assert response.total == 1
    assert response.items[0].score == Decimal("11.00")
    assert response.items[0].participation_status == TMAParticipationStatus.SUBMITTED
    assert read.await_args.kwargs["regular_class_ids"] == {general_class}
    assert read.await_args.kwargs["grouped_elective_class_ids"] == {grouped_class}
    assert read.await_args.kwargs["search"] == "Ada"
    allowed.assert_awaited_once()


@pytest.mark.asyncio
async def test_historical_terms_do_not_reuse_current_elective_choices(monkeypatch) -> None:
    from app.modules.tma import reporting_service as mod

    assignment = _assignment()
    classroom = _id()
    actor = SimpleNamespace(tenant_id=assignment.tenant_id)
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_access", AsyncMock(),
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [classroom])
    )
    monkeypatch.setattr(
        mod.CurriculumResolutionService, "resolve_classes_subjects",
        AsyncMock(return_value={classroom: [SimpleNamespace(
            curriculum_subject_id=assignment.curriculum_subject_id,
            is_elective=True, elective_group_id=_id(),
        )]}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_term_by_id",
        AsyncMock(return_value=SimpleNamespace(is_current=False)),
    )
    read = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(mod.TMAReportingRepository, "list_participation", read)
    await TMAReportingService.list_assignment_participation(
        db, actor=actor, assignment_id=assignment.id,
    )
    assert read.await_args.kwargs["regular_class_ids"] == {classroom}
    assert read.await_args.kwargs["grouped_elective_class_ids"] == set()


@pytest.mark.asyncio
async def test_missing_assignment_and_forbidden_teacher_do_not_read_roster(monkeypatch) -> None:
    from app.modules.tma import reporting_service as mod

    assignment = _assignment()
    actor = SimpleNamespace(tenant_id=assignment.tenant_id)
    read = AsyncMock()
    monkeypatch.setattr(mod.TMAReportingRepository, "list_participation", read)
    get = AsyncMock(return_value=None)
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", get)
    with pytest.raises(NotFoundException):
        await TMAReportingService.list_assignment_participation(
            AsyncMock(), actor=actor, assignment_id=assignment.id,
        )
    get.return_value = assignment
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_access",
        AsyncMock(side_effect=ForbiddenException("Not assigned")),
    )
    with pytest.raises(ForbiddenException):
        await TMAReportingService.list_assignment_participation(
            AsyncMock(), actor=actor, assignment_id=assignment.id,
        )
    read.assert_not_awaited()


def test_response_distinguishes_no_submission_from_zero_score() -> None:
    from app.modules.tma.schemas import TMASubmissionStudentResponse

    common = {
        "student_id": _id(), "admission_number": "WVS001",
        "student_name": "Ada Ben", "class_id": _id(),
        "class_name": "JSS3 A", "is_currently_eligible": True,
        "submitted_at": None,
    }
    pending = TMASubmissionStudentResponse(
        **common, participation_status="in_progress", score=None,
    )
    submitted_zero = TMASubmissionStudentResponse(
        **common, participation_status="submitted", score=Decimal("0"),
    )
    assert pending.score is None
    assert submitted_zero.score == Decimal("0")
