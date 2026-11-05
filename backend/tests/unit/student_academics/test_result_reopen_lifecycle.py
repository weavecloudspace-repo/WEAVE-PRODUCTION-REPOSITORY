"""Admin result correction transitions must be auditable and safe for TMA workflows."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestException, ConflictException
from app.modules.report_cards.service import ReportCardService
from app.modules.student_academics import service as mod
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSessionStatus,
    AcademicTermStatus,
)
from app.modules.student_academics.schemas import StudentSubjectResultReopenRequest
from app.modules.tenant_admins.models import TenantAdmin


def context(status: AcademicResultStatus):
    actor = TenantAdmin(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    result = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=actor.tenant_id,
        student_id=uuid.uuid4(),
        academic_session_id=uuid.uuid4(),
        academic_term_id=uuid.uuid4(),
        status=status,
        submitted_at=object(),
        submitted_by_actor_type="tenant_admin",
        submitted_by_actor_id=actor.id,
        approved_at=object(),
        approved_by_admin_id=actor.id,
        locked_at=object(),
        locked_by_admin_id=actor.id,
    )
    return actor, result


def prepare(monkeypatch, result, *, session_open=True):
    lock = AsyncMock()
    load_result = AsyncMock(return_value=result)
    audit = AsyncMock()
    outdated = AsyncMock()
    save = AsyncMock(side_effect=lambda _db, row: row)
    monkeypatch.setattr(mod.TMAAcademicGuard, "lock", lock)
    monkeypatch.setattr(mod.StudentAcademicRepository, "get_result_by_id", load_result)
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_academic_session_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                is_current=True,
                status=AcademicSessionStatus.OPEN if session_open else AcademicSessionStatus.CLOSED,
            )
        ),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository,
        "get_term_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                is_current=True,
                status=AcademicTermStatus.OPEN,
            )
        ),
    )
    monkeypatch.setattr(mod.StudentAcademicRepository, "upsert_result", save)
    monkeypatch.setattr(mod.StudentAcademicService, "_record_academic_lifecycle", audit)
    monkeypatch.setattr(
        mod.StudentAcademicService,
        "_build_result_response",
        AsyncMock(return_value="updated"),
    )
    monkeypatch.setattr(ReportCardService, "mark_outdated_for_score_change", outdated)
    return lock, load_result, audit, outdated, save


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "starting_status",
    [
        AcademicResultStatus.SUBMITTED,
        AcademicResultStatus.APPROVED,
        AcademicResultStatus.LOCKED,
    ],
)
async def test_admin_can_return_a_non_draft_result_to_draft_with_audit(
    monkeypatch, starting_status
):
    actor, result = context(starting_status)
    lock, load_result, audit, outdated, save = prepare(monkeypatch, result)
    db = AsyncMock()

    response = await mod.StudentAcademicService.reopen_result(
        db,
        actor,
        result.id,
        StudentSubjectResultReopenRequest(reason="Correct a recorded score"),
    )

    assert response == "updated"
    assert result.status == AcademicResultStatus.DRAFT
    assert result.submitted_at is None
    assert result.submitted_by_actor_type is None
    assert result.submitted_by_actor_id is None
    assert result.approved_at is None
    assert result.approved_by_admin_id is None
    assert result.locked_at is None
    assert result.locked_by_admin_id is None
    lock.assert_awaited_once_with(db, actor.tenant_id)
    load_result.assert_awaited_once_with(db, actor.tenant_id, result.id)
    outdated.assert_awaited_once_with(
        db,
        result.tenant_id,
        result.student_id,
        result.academic_session_id,
        result.academic_term_id,
    )
    save.assert_awaited_once_with(db, result)
    assert audit.await_args.kwargs["previous_status"] == starting_status.value
    assert audit.await_args.kwargs["new_status"] == "draft"
    assert audit.await_args.kwargs["reason"] == "Correct a recorded score"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_cannot_be_reopened_or_emit_an_audit(monkeypatch):
    actor, result = context(AcademicResultStatus.DRAFT)
    _lock, _load_result, audit, outdated, save = prepare(monkeypatch, result)
    db = AsyncMock()
    with pytest.raises(BadRequestException, match="submitted, approved or locked"):
        await mod.StudentAcademicService.reopen_result(
            db,
            actor,
            result.id,
            StudentSubjectResultReopenRequest(reason="Incorrect attempt"),
        )
    audit.assert_not_awaited()
    outdated.assert_not_awaited()
    save.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_return_to_draft_rejected_outside_current_open_period(monkeypatch):
    actor, result = context(AcademicResultStatus.SUBMITTED)
    _lock, _load_result, audit, outdated, save = prepare(monkeypatch, result, session_open=False)
    db = AsyncMock()
    with pytest.raises(ConflictException, match="current open session"):
        await mod.StudentAcademicService.reopen_result(
            db,
            actor,
            result.id,
            StudentSubjectResultReopenRequest(reason="Correction requested"),
        )
    audit.assert_not_awaited()
    outdated.assert_not_awaited()
    save.assert_not_awaited()
    db.commit.assert_not_awaited()
