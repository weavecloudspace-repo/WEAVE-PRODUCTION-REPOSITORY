from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestException, ConflictException
from app.modules.students.enrollment_schemas import (
    StudentAcademicLevelReassignmentRequest,
    StudentClassPlacementRequest,
    StudentClassReassignmentRequest,
)
from app.modules.students.models import AcademicStatus, StudentEnrollmentOutcome
from app.modules.students.placement_service import StudentPlacementService
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.students.schemas import StudentLifecycleReasonRequest
from app.modules.students.service import StudentService


@pytest.fixture
def actor():
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4())


@pytest.fixture
def db():
    return SimpleNamespace(commit=AsyncMock())


@pytest.fixture(autouse=True)
def no_existing_upcoming_enrollment(monkeypatch):
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_upcoming",
        AsyncMock(return_value=None),
    )


def test_reassignment_contracts_accept_future_dates():
    future_date = date.today() + timedelta(days=5)
    class_payload = StudentClassReassignmentRequest(
        target_class_id=uuid4(),
        academic_session_id=uuid4(),
        effective_date=future_date,
        reason="Schedule class move",
    )
    level_payload = StudentAcademicLevelReassignmentRequest(
        target_academic_level_id=uuid4(),
        target_class_id=uuid4(),
        academic_session_id=uuid4(),
        effective_date=future_date,
        reason="Schedule level move",
    )

    assert class_payload.effective_date == future_date
    assert level_payload.effective_date == future_date


@pytest.mark.asyncio
async def test_initial_class_placement_mutates_fresh_unassigned_segment(monkeypatch, actor, db):
    session_id = uuid4()
    level_id = uuid4()
    class_id = uuid4()
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        academic_session_id=session_id,
        academic_level_id=level_id,
        class_id=None,
        started_on=date.today(),
        entry_outcome=StudentEnrollmentOutcome.ENROLLED,
    )
    target_class = SimpleNamespace(id=class_id, academic_level_id=level_id)

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window",
        AsyncMock(),
    )
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
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_current",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(StudentEnrollmentRepository, "save", AsyncMock())
    create_segment = AsyncMock()
    close_segment = AsyncMock()
    monkeypatch.setattr(StudentPlacementService, "_create_segment", create_segment)
    monkeypatch.setattr(StudentPlacementService, "_close_segment", close_segment)

    response = await StudentPlacementService.place_class(
        db,
        actor=actor,
        payload=StudentClassPlacementRequest(
            academic_session_id=session_id,
            academic_level_id=level_id,
            target_class_id=class_id,
            student_ids=[student.id],
        ),
    )

    assert response.placed_student_ids == [student.id]
    assert response.placed_count == 1
    assert current.class_id == class_id
    assert current.entry_outcome == StudentEnrollmentOutcome.ENROLLED
    StudentEnrollmentRepository.save.assert_awaited_once_with(db, current)
    create_segment.assert_not_awaited()
    close_segment.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_initial_class_placement_preserves_real_unassigned_history(monkeypatch, actor, db):
    session_id = uuid4()
    level_id = uuid4()
    class_id = uuid4()
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        academic_session_id=session_id,
        academic_level_id=level_id,
        class_id=None,
        started_on=date.today() - timedelta(days=10),
    )
    target_class = SimpleNamespace(id=class_id, academic_level_id=level_id)

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window",
        AsyncMock(),
    )
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
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_current",
        AsyncMock(return_value=current),
    )
    close_segment = AsyncMock()
    create_segment = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(StudentPlacementService, "_close_segment", close_segment)
    monkeypatch.setattr(StudentPlacementService, "_create_segment", create_segment)

    await StudentPlacementService.place_class(
        db,
        actor=actor,
        payload=StudentClassPlacementRequest(
            academic_session_id=session_id,
            academic_level_id=level_id,
            target_class_id=class_id,
            student_ids=[student.id],
        ),
    )

    close_segment.assert_awaited_once()
    assert close_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.CLASS_PLACED
    assert close_segment.await_args.kwargs["ended_on"] == date.today() - timedelta(days=1)
    create_segment.assert_awaited_once()
    assert create_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.CLASS_PLACED
    assert create_segment.await_args.kwargs["academic_level_id"] == level_id
    assert create_segment.await_args.kwargs["class_id"] == class_id


@pytest.mark.asyncio
async def test_initial_class_placement_rejects_cross_level_target(monkeypatch, actor, db):
    selected_level_id = uuid4()
    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window",
        AsyncMock(),
    )
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_open_session",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_target_class",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), academic_level_id=uuid4())),
    )

    with pytest.raises(BadRequestException, match="selected academic level"):
        await StudentPlacementService.place_class(
            db,
            actor=actor,
            payload=StudentClassPlacementRequest(
                academic_session_id=uuid4(),
                academic_level_id=selected_level_id,
                target_class_id=uuid4(),
                student_ids=[uuid4()],
            ),
        )


@pytest.mark.asyncio
async def test_initial_class_placement_rejects_already_classed_student(monkeypatch, actor, db):
    session_id = uuid4()
    level_id = uuid4()
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        academic_session_id=session_id,
        academic_level_id=level_id,
        class_id=uuid4(),
    )
    target_class = SimpleNamespace(id=uuid4(), academic_level_id=level_id)

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window",
        AsyncMock(),
    )
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
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=current))

    with pytest.raises(ConflictException, match="Reassign Class"):
        await StudentPlacementService.place_class(
            db,
            actor=actor,
            payload=StudentClassPlacementRequest(
                academic_session_id=session_id,
                academic_level_id=level_id,
                target_class_id=target_class.id,
                student_ids=[student.id],
            ),
        )


@pytest.mark.asyncio
async def test_same_level_reassignment_creates_new_segment_and_invalidates_derived_state(
    monkeypatch, actor, db
):
    session_id = uuid4()
    level_id = uuid4()
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        academic_session_id=session_id,
        academic_level_id=level_id,
        class_id=uuid4(),
        started_on=date.today() - timedelta(days=20),
    )
    target_class = SimpleNamespace(id=uuid4(), academic_level_id=level_id)
    effective_date = date.today() - timedelta(days=2)

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
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=current))
    close_segment = AsyncMock()
    create_segment = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
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
        AsyncMock(return_value=SimpleNamespace(id=student.id)),
    )

    await StudentPlacementService.reassign_class(
        db,
        actor=actor,
        student_id=student.id,
        payload=StudentClassReassignmentRequest(
            target_class_id=target_class.id,
            academic_session_id=session_id,
            effective_date=effective_date,
            reason="Move to another arm",
        ),
    )

    close_segment.assert_awaited_once()
    assert close_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.RECLASSIFIED
    assert close_segment.await_args.kwargs["ended_on"] == effective_date - timedelta(days=1)
    create_segment.assert_awaited_once()
    assert create_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.RECLASSIFIED
    assert create_segment.await_args.kwargs["academic_level_id"] == level_id
    invalidate.assert_awaited_once_with(
        db,
        tenant_id=actor.tenant_id,
        student_id=student.id,
        academic_session_id=session_id,
    )


@pytest.mark.asyncio
async def test_cross_level_reassignment_creates_level_reassigned_segment(monkeypatch, actor, db):
    session_id = uuid4()
    old_level_id = uuid4()
    new_level_id = uuid4()
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    current = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        academic_session_id=session_id,
        academic_level_id=old_level_id,
        class_id=uuid4(),
        started_on=date.today() - timedelta(days=30),
    )
    target_class = SimpleNamespace(id=uuid4(), academic_level_id=new_level_id)
    effective_date = date.today() - timedelta(days=1)

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
    monkeypatch.setattr(StudentEnrollmentRepository, "get_current", AsyncMock(return_value=current))
    close_segment = AsyncMock()
    create_segment = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(StudentPlacementService, "_close_segment", close_segment)
    monkeypatch.setattr(StudentPlacementService, "_create_segment", create_segment)
    monkeypatch.setattr(StudentPlacementService, "_invalidate_derived_context", AsyncMock())
    monkeypatch.setattr(
        StudentService,
        "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=student.id)),
    )

    await StudentPlacementService.reassign_academic_level(
        db,
        actor=actor,
        student_id=student.id,
        payload=StudentAcademicLevelReassignmentRequest(
            target_academic_level_id=new_level_id,
            target_class_id=target_class.id,
            academic_session_id=session_id,
            effective_date=effective_date,
            reason="Correct academic level",
        ),
    )

    assert close_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.LEVEL_REASSIGNED
    assert create_segment.await_args.kwargs["outcome"] == StudentEnrollmentOutcome.LEVEL_REASSIGNED
    assert create_segment.await_args.kwargs["academic_level_id"] == new_level_id
    assert create_segment.await_args.kwargs["class_id"] == target_class.id


def test_class_placement_contract_rejects_duplicate_student_ids():
    student_id = uuid4()
    with pytest.raises(ValueError, match="duplicates"):
        StudentClassPlacementRequest(
            academic_session_id=uuid4(),
            academic_level_id=uuid4(),
            target_class_id=uuid4(),
            student_ids=[student_id, student_id],
        )


@pytest.mark.asyncio
async def test_cancel_upcoming_reassignment_reopens_only_its_predecessor(monkeypatch, actor):
    start_date = date.today() + timedelta(days=7)
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.ACTIVE)
    upcoming = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        started_on=start_date,
        entry_outcome=StudentEnrollmentOutcome.RECLASSIFIED,
    )
    predecessor = SimpleNamespace(
        id=uuid4(),
        started_on=date.today() - timedelta(days=20),
        ended_on=start_date - timedelta(days=1),
        exit_outcome=StudentEnrollmentOutcome.RECLASSIFIED,
        exit_reason="Scheduled class change",
        ended_by_admin_id=actor.id,
    )
    db = SimpleNamespace(delete=AsyncMock(), flush=AsyncMock(), commit=AsyncMock())
    save = AsyncMock()

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window", AsyncMock()
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_editable_upcoming",
        AsyncMock(return_value=upcoming),
    )
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "list_for_student",
        AsyncMock(return_value=[upcoming, predecessor]),
    )
    monkeypatch.setattr(StudentEnrollmentRepository, "save", save)
    monkeypatch.setattr(
        "app.modules.students.placement_service.StudentAcademicRepository.add_academic_lifecycle_audit",
        AsyncMock(),
    )
    monkeypatch.setattr(
        StudentService,
        "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=student.id)),
    )

    await StudentPlacementService.cancel_upcoming_enrollment(
        db,
        actor=actor,
        student_id=student.id,
        enrollment_id=upcoming.id,
        payload=StudentLifecycleReasonRequest(reason="Cancel planned class change"),
    )

    db.delete.assert_awaited_once_with(upcoming)
    assert predecessor.ended_on is None
    assert predecessor.exit_outcome is None
    assert predecessor.exit_reason is None
    assert predecessor.ended_by_admin_id is None
    save.assert_awaited_once_with(db, predecessor)


@pytest.mark.asyncio
async def test_cancel_future_formal_return_keeps_terminal_history_and_deactivates_identity(
    monkeypatch, actor
):
    student = SimpleNamespace(id=uuid4(), status=AcademicStatus.WITHDRAWN)
    upcoming = SimpleNamespace(
        id=uuid4(),
        student_id=student.id,
        started_on=date.today() + timedelta(days=7),
        entry_outcome=StudentEnrollmentOutcome.ENROLLED,
    )
    terminal_history = SimpleNamespace(
        id=uuid4(),
        started_on=date.today() - timedelta(days=60),
        ended_on=date.today() - timedelta(days=10),
        exit_outcome=StudentEnrollmentOutcome.WITHDRAWN,
    )
    db = SimpleNamespace(delete=AsyncMock(), flush=AsyncMock(), commit=AsyncMock())
    save = AsyncMock()
    deactivate = AsyncMock()
    invalidate = AsyncMock()

    monkeypatch.setattr(
        "app.modules.students.placement_service.ensure_academic_write_window", AsyncMock()
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentPlacementService,
        "_require_editable_upcoming",
        AsyncMock(return_value=upcoming),
    )
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "list_for_student",
        AsyncMock(return_value=[upcoming, terminal_history]),
    )
    monkeypatch.setattr(StudentEnrollmentRepository, "save", save)
    monkeypatch.setattr(
        "app.modules.students.placement_service.StudentAcademicRepository.add_academic_lifecycle_audit",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.modules.auth_identity.service.AuthIdentityService.deactivate_for_actor", deactivate
    )
    monkeypatch.setattr(
        "app.modules.auth_identity.service.AuthIdentityService.invalidate_after_commit", invalidate
    )
    monkeypatch.setattr(
        StudentService,
        "get_student_profile",
        AsyncMock(return_value=SimpleNamespace(id=student.id)),
    )

    await StudentPlacementService.cancel_upcoming_enrollment(
        db,
        actor=actor,
        student_id=student.id,
        enrollment_id=upcoming.id,
        payload=StudentLifecycleReasonRequest(reason="Cancel planned return"),
    )

    db.delete.assert_awaited_once_with(upcoming)
    save.assert_not_awaited()
    assert terminal_history.ended_on == date.today() - timedelta(days=10)
    deactivate.assert_awaited_once()
    invalidate.assert_awaited_once_with(db)
