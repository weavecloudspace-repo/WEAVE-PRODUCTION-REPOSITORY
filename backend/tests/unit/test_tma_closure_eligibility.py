"""Regression coverage for repeated closure without a frozen roster."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.tma.deadline_eligibility_repository import TMADeadlineEligibilityRepository


def _assignment(*, closed_at, closes_at):
    return SimpleNamespace(
        tenant_id=uuid4(),
        academic_session_id=uuid4(),
        academic_level_id=uuid4(),
        academic_term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        closed_at=closed_at,
        closes_at=closes_at,
    )


def test_manual_closure_uses_actual_early_cutoff():
    closed_at = datetime(2026, 11, 5, 11, tzinfo=timezone.utc)
    deadline = closed_at + timedelta(days=2)
    roster = TMADeadlineEligibilityRepository._roster(
        _assignment(closed_at=closed_at, closes_at=deadline)
    )
    statement = roster.element.compile(dialect=postgresql.dialect())
    assert statement.params["cutoff"] == closed_at


def test_automatic_closure_uses_published_deadline():
    deadline = datetime(2026, 11, 5, 11, tzinfo=timezone.utc)
    roster = TMADeadlineEligibilityRepository._roster(
        _assignment(closed_at=deadline + timedelta(minutes=2), closes_at=deadline)
    )
    statement = roster.element.compile(dialect=postgresql.dialect())
    assert statement.params["cutoff"] == deadline


def test_roster_query_uses_enrollment_timestamps_not_revision_snapshot():
    sql = TMADeadlineEligibilityRepository._roster(
        _assignment(
            closed_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
            closes_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )
    ).element.text.text
    assert "e.created_at <= CAST(:cutoff AS timestamptz)" in sql
    assert "tma_deadline_eligibility" not in sql
    assert "e.started_on" in sql
