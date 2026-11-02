"""API, revision and SQL authorization boundaries for production TMA fixes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.teachers.models import TeacherMembership, TeacherMembershipStatus
from app.modules.tma import router
from app.modules.tma import deadline_zero_service as worker
from app.modules.tma.models import TMAAssignmentStatus, TMAZeroGradingFailure
from app.modules.tma.reporting_repository import TMAReportingRepository


@pytest.mark.asyncio
async def test_teacher_api_total_is_authorized_total_not_current_page_length(monkeypatch):
    actor = TeacherMembership(id=uuid4(), tenant_id=uuid4(), status=TeacherMembershipStatus.ACTIVE)
    monkeypatch.setattr(
        router.TMAAssignmentService, "list_assignments", AsyncMock(return_value=([], 35))
    )
    cache = AsyncMock(
        side_effect=AssertionError("authorization-sensitive listing used stale cache")
    )
    monkeypatch.setattr(router, "cached_staff_read", cache)
    response = await router.list_assignments(db=AsyncMock(), actor=actor, offset=40, limit=10)
    assert response.total == 35 and response.items == [] and response.offset == 40
    cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_delayed_failed_worker_cannot_mark_a_new_revision(monkeypatch):
    item = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        current_revision_number=1,
        status=TMAAssignmentStatus.CLOSED,
        zero_grading_error=None,
    )
    db = AsyncMock()
    db.execute.side_effect = [SimpleNamespace(scalar_one_or_none=lambda: item)] * 2
    monkeypatch.setattr(
        worker.TMARevisionRepository,
        "get_by_number",
        AsyncMock(side_effect=RuntimeError("old revision failed")),
    )

    async def after_rollback():
        item.current_revision_number = 2

    db.rollback.side_effect = after_rollback
    await worker.TMADeadlineZeroService.process_pending(db)
    assert item.zero_grading_error is None
    db.commit.assert_not_awaited()


def test_reporting_scope_constrains_live_roster_history_and_deadline_snapshot():
    allowed = uuid4()
    assignment = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        academic_session_id=uuid4(),
        academic_term_id=uuid4(),
        academic_level_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_component_id=uuid4(),
        current_revision_number=2,
    )
    query = TMAReportingRepository._query(
        assignment,
        regular_class_ids={allowed, uuid4()},
        grouped_elective_class_ids=set(),
        authorized_class_ids={allowed},
    )
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "tma_participants.class_id IN" in sql
    assert "tma_deadline_eligibility.class_id IN" in sql
    assert "student_enrollments.class_id IN" in sql
    assert "revision_number" in sql
    assert assignment.tenant_id in compiled.params.values()


def test_failure_uniqueness_and_foreign_key_include_revision():
    table = TMAZeroGradingFailure.__table__
    unique = next(c for c in table.constraints if c.name == "uq_tma_zero_failure_revision_student")
    assert {c.name for c in unique.columns} == {
        "tenant_id",
        "assignment_id",
        "revision_number",
        "student_id",
    }
    foreign = next(c for c in table.constraints if c.name == "fk_tma_zero_failure_revision")
    assert {c.name for c in foreign.columns} == {"tenant_id", "assignment_id", "revision_number"}
