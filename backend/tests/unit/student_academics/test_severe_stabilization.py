from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictException
from app.modules.cbt.sync.projectors.staff import project_teacher_assignment
from app.modules.student_academics.curriculum_v2_service import AcademicCurriculumService
from app.modules.student_academics.models import AcademicTermStatus, TeacherAssignment
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.service import StudentAcademicService
from app.modules.teachers.models import TeacherAccountStatus, TeacherMembershipStatus


def _assignment(*, effective_from: date, curriculum_subject_id: uuid.UUID | None = None):
    return TeacherAssignment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        curriculum_subject_id=curriculum_subject_id or uuid.uuid4(),
        teacher_membership_id=uuid.uuid4(),
        effective_from=effective_from,
        effective_to=None,
    )


def _scalar_result(rows):
    result = MagicMock()
    result.scalars.return_value = rows
    return result


@pytest.mark.asyncio
async def test_term_closure_preview_does_not_query_next_term_specialization() -> None:
    tenant_id = uuid.uuid4()
    term = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=uuid.uuid4(),
        status=AcademicTermStatus.OPEN,
        is_current=True,
    )
    # TMA closure blockers are now checked with three tenant-scoped counts;
    # those reads must not inspect future-term specialization.
    result = MagicMock()
    result.scalar_one.return_value = 0
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    with (
        patch.object(
            StudentAcademicRepository,
            "get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch.object(
            StudentAcademicRepository,
            "count_results",
            new=AsyncMock(return_value=0),
        ),
        patch.object(
            StudentAcademicRepository,
            "count_report_cards",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.inspect_term_closure_readiness",
            new=AsyncMock(return_value={"counts": {}, "blockers": []}),
        ),
    ):
        preview = await StudentAcademicService.academic_term_dependency_preview(
            db, tenant_id, term.id
        )

    assert preview.can_close is True
    assert preview.can_start_closing is True
    assert db.execute.await_count == 3
    assert all(
        "tma_assignments" in str(call.args[0])
        for call in db.execute.await_args_list
    )


@pytest.mark.asyncio
async def test_reconciliation_ends_started_assignment_at_transition_boundary_minus_one() -> None:
    boundary = date.today()
    assignment = _assignment(effective_from=boundary - timedelta(days=10))
    term = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=boundary - timedelta(days=30),
        end_date=boundary + timedelta(days=60),
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_scalar_result([assignment])),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    with patch(
        "app.modules.student_academics.curriculum_v2_service.CurriculumResolutionService.resolve_classes_subjects",
        new=AsyncMock(return_value={assignment.class_id: []}),
    ):
        result = await AcademicCurriculumService.reconcile_teacher_assignments_for_term(
            db,
            tenant_id=assignment.tenant_id,
            term=term,
            acting_admin_id=uuid.uuid4(),
            transition_boundary=boundary,
        )

    assert result["ended"] == 1
    assert assignment.effective_to == boundary - timedelta(days=1)
    assert assignment.effective_to >= assignment.effective_from
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_blocks_ineligible_scheduled_assignment_without_mutation() -> None:
    boundary = date.today()
    assignment = _assignment(effective_from=boundary + timedelta(days=5))
    term = SimpleNamespace(
        id=uuid.uuid4(),
        start_date=boundary - timedelta(days=30),
        end_date=boundary + timedelta(days=60),
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_scalar_result([assignment])),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    with patch(
        "app.modules.student_academics.curriculum_v2_service.CurriculumResolutionService.resolve_classes_subjects",
        new=AsyncMock(return_value={assignment.class_id: []}),
    ):
        with pytest.raises(ConflictException) as exc_info:
            await AcademicCurriculumService.reconcile_teacher_assignments_for_term(
                db,
                tenant_id=assignment.tenant_id,
                term=term,
                acting_admin_id=uuid.uuid4(),
                transition_boundary=boundary,
            )

    assert exc_info.value.payload["code"] == "SCHEDULED_TEACHER_ASSIGNMENT_CONFLICT"
    assert assignment.effective_to is None
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_class_departments_requires_draft_target() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    target = SimpleNamespace(
        id=uuid.uuid4(),
        academic_session_id=session_id,
        status=AcademicTermStatus.OPEN,
    )
    source = SimpleNamespace(
        id=uuid.uuid4(),
        academic_session_id=session_id,
        status=AcademicTermStatus.CLOSED,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("copy must stop before rows"))
    )

    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_term",
            new=AsyncMock(side_effect=[target, source]),
        ),
    ):
        with pytest.raises(ConflictException, match="draft academic term"):
            await AcademicCurriculumService.copy_class_departments(
                db,
                tenant_id=tenant_id,
                admin_id=uuid.uuid4(),
                target_term_id=target.id,
                source_term_id=source.id,
            )

    db.execute.assert_not_awaited()


def test_incremental_teacher_projector_requires_visible_underlying_subject() -> None:
    tenant_id = uuid.uuid4()
    assignment = SimpleNamespace(
        id=uuid.uuid4(),
        effective_to=None,
        class_id=uuid.uuid4(),
        curriculum_subject_id=uuid.uuid4(),
        teacher_membership_id=uuid.uuid4(),
    )
    membership = SimpleNamespace(status=TeacherMembershipStatus.ACTIVE)
    account = SimpleNamespace(account_status=TeacherAccountStatus.ACTIVE, is_active=True)
    first = MagicMock()
    first.first.return_value = (assignment, membership, account)
    second = MagicMock()
    second.first.return_value = None
    session = MagicMock()
    session.execute.side_effect = [first, second]

    assert project_teacher_assignment(session, tenant_id, assignment.id) is None

    context_statement = session.execute.call_args_list[1].args[0]
    sql = str(context_statement)
    assert "subjects.is_active" in sql
    assert "subjects.archived_at IS NULL" in sql
    assert "subjects.tenant_id" in sql
