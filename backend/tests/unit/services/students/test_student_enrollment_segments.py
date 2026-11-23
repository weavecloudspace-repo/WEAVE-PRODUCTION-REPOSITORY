from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.students.enrollment_schemas import StudentClassReassignmentRequest
from app.modules.students.models import (
    AcademicStatus,
    StudentEnrollment,
    StudentEnrollmentOutcome,
)
from app.modules.students.placement_service import StudentPlacementService
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.students.schemas import StudentEnrollmentDetailResponse
from app.modules.students.service import StudentService


def _segment(*, ended_on: date | None = None) -> StudentEnrollment:
    return StudentEnrollment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        academic_level_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        academic_session_id=uuid.uuid4(),
        started_on=date(2026, 8, 1),
        ended_on=ended_on,
        entry_outcome=StudentEnrollmentOutcome.ENROLLED,
        entry_reason="Initial admission",
        exit_outcome=(StudentEnrollmentOutcome.RECLASSIFIED if ended_on else None),
        exit_reason=("Moved class" if ended_on else None),
    )


def test_current_state_is_derived_and_not_writable() -> None:
    current = _segment()
    ended = _segment(ended_on=date(2026, 8, 10))

    assert current.is_current is True
    assert ended.is_current is False
    with pytest.raises(AttributeError):
        current.is_current = False

    assert not hasattr(StudentEnrollment, "outcome")
    assert not hasattr(StudentEnrollment, "reason")
    assert not hasattr(StudentEnrollment, "changed_by_admin_id")


def test_reassign_class_contract_rejects_legacy_outcome_field() -> None:
    with pytest.raises(ValidationError):
        StudentClassReassignmentRequest.model_validate(
            {
                "target_class_id": str(uuid.uuid4()),
                "academic_session_id": str(uuid.uuid4()),
                "effective_date": "2026-08-20",
                "reason": "Correct arm placement",
                "outcome": "repeated",
            }
        )


def test_enrollment_history_schema_exposes_entry_exit_metadata_and_level_name() -> None:
    now = datetime.now(timezone.utc)
    response = StudentEnrollmentDetailResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        academic_level_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        academic_session_id=uuid.uuid4(),
        started_on=date(2026, 8, 1),
        ended_on=date(2026, 8, 10),
        entry_outcome=StudentEnrollmentOutcome.ENROLLED,
        exit_outcome=StudentEnrollmentOutcome.RECLASSIFIED,
        entry_reason="Initial admission",
        exit_reason="Correct arm placement",
        created_by_admin_id=uuid.uuid4(),
        ended_by_admin_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        academic_level_name="JSS 1",
    )

    dumped = response.model_dump()
    assert dumped["academic_level_name"] == "JSS 1"
    assert dumped["entry_outcome"] == "enrolled"
    assert dumped["exit_outcome"] == "reclassified"
    assert "outcome" not in dumped
    assert "is_current" not in dumped


@pytest.mark.asyncio
async def test_reassign_class_splits_placement_on_effective_date(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    level_id = uuid.uuid4()
    old_class_id = uuid.uuid4()
    target_class_id = uuid.uuid4()
    session_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    student = SimpleNamespace(id=student_id, tenant_id=tenant_id, status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        id=uuid.uuid4(),
        student_id=student_id,
        academic_level_id=level_id,
        class_id=old_class_id,
        academic_session_id=session_id,
        started_on=date(2026, 8, 1),
    )
    target_class = SimpleNamespace(id=target_class_id, academic_level_id=level_id)
    actor = SimpleNamespace(id=admin_id, tenant_id=tenant_id)
    payload = StudentClassReassignmentRequest(
        target_class_id=target_class_id,
        academic_session_id=session_id,
        effective_date=date(2026, 8, 20),
        reason="Correct arm placement",
    )

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window",
        AsyncMock(),
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_open_session",
        AsyncMock(return_value=SimpleNamespace(id=session_id)),
    )
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_target_class",
        AsyncMock(return_value=target_class),
    )
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_current",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_upcoming",
        AsyncMock(return_value=None),
    )
    close_segment = AsyncMock()
    create_segment = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    invalidate = AsyncMock()
    monkeypatch.setattr(StudentPlacementService, "_close_segment", close_segment)
    monkeypatch.setattr(StudentPlacementService, "_create_segment", create_segment)
    monkeypatch.setattr(
        "app.modules.students.placement_service.AcademicResultContinuityService.apply",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(StudentPlacementService, "_invalidate_derived_context", invalidate)
    monkeypatch.setattr(
        StudentService,
        "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=student_id)),
    )

    db = SimpleNamespace(commit=AsyncMock())
    await StudentPlacementService.reassign_class(
        db,
        actor=actor,
        student_id=student_id,
        payload=payload,
    )

    assert close_segment.await_args.kwargs["ended_on"] == date(2026, 8, 19)
    assert close_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.RECLASSIFIED
    assert create_segment.await_args.kwargs["started_on"] == date(2026, 8, 20)
    assert create_segment.await_args.kwargs["class_id"] == target_class_id
    assert create_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.RECLASSIFIED
    invalidate.assert_awaited_once_with(
        db,
        tenant_id=tenant_id,
        student_id=student_id,
        academic_session_id=session_id,
    )
    db.commit.assert_awaited_once()
