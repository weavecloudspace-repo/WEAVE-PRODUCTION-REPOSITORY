from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ConflictException
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermName,
    AcademicTermStatus,
)
from app.modules.student_academics.service import StudentAcademicService


def _session(tenant_id: uuid.UUID) -> AcademicSession:
    return AcademicSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.OPEN,
        is_current=True,
    )


def _term(
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    name: AcademicTermName,
    status: AcademicTermStatus,
) -> AcademicTerm:
    return AcademicTerm(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=name,
        start_date=date(2026, 1, 12),
        end_date=date(2026, 4, 10),
        status=status,
        is_current=status in {AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING},
    )


@pytest.mark.asyncio
async def test_future_draft_term_cannot_open_while_another_term_is_current() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session = _session(tenant_id)
    first_term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.FIRST_TERM,
        status=AcademicTermStatus.OPEN,
    )
    second_term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.SECOND_TERM,
        status=AcademicTermStatus.DRAFT,
    )
    db = AsyncMock()
    ensure_plan = AsyncMock()

    with (
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=second_term),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_current_term",
            new=AsyncMock(return_value=first_term),
        ),
        patch(
            "app.modules.subscriptions.term_entitlement_service.TermPlanEntitlementService.ensure_open_eligible",
            new=ensure_plan,
        ),
    ):
        with pytest.raises(ConflictException, match="Another academic term is currently open"):
            await StudentAcademicService.open_academic_term(
                db=db,
                tenant_id=tenant_id,
                term_id=second_term.id,
                admin_id=admin_id,
            )

    ensure_plan.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert second_term.status == AcademicTermStatus.DRAFT
    assert second_term.is_current is False


@pytest.mark.asyncio
async def test_second_term_can_open_without_first_term_when_no_term_is_current() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session = _session(tenant_id)
    second_term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.SECOND_TERM,
        status=AcademicTermStatus.DRAFT,
    )
    db = AsyncMock()

    async def save_term(_db, term):
        return term

    with (
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=second_term),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_current_term",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.list_terms_by_session",
            new=AsyncMock(return_value=([second_term], 1)),
        ),
        patch(
            "app.modules.subscriptions.term_entitlement_service.TermPlanEntitlementService.ensure_open_eligible",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.term_calendar_readiness",
            new=AsyncMock(
                return_value={
                    "blockers": [],
                    "counts": {},
                    "calendar_id": str(uuid.uuid4()),
                }
            ),
        ),
        patch(
            "app.modules.student_academics.curriculum_v2_service.AcademicCurriculumService.specialization_readiness",
            new=AsyncMock(return_value=({}, [])),
        ),
        patch(
            "app.modules.student_academics.curriculum_v2_service.AcademicCurriculumService.reconcile_teacher_assignments_for_term",
            new=AsyncMock(return_value={"ended": 0, "deleted_scheduled": 0}),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.save_academic_term",
            new=AsyncMock(side_effect=save_term),
        ),
        patch(
            "app.modules.subscriptions.term_entitlement_service.TermPlanEntitlementService.mark_effective_for_open_term",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.add_academic_lifecycle_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.subscriptions.cache.invalidate_tenant_subscription_cache",
            new=AsyncMock(),
        ),
    ):
        opened = await StudentAcademicService.open_academic_term(
            db=db,
            tenant_id=tenant_id,
            term_id=second_term.id,
            admin_id=admin_id,
        )

    assert opened.status == AcademicTermStatus.OPEN
    assert opened.is_current is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("calendar_blockers", "can_open"),
    [
        (["Generate and activate a calendar for this term."], False),
        (["The term calendar must be active."], False),
        ([], True),
    ],
)
async def test_second_term_dependency_preview_requires_its_own_active_calendar(
    calendar_blockers: list[str], can_open: bool
) -> None:
    tenant_id = uuid.uuid4()
    session = _session(tenant_id)
    term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.SECOND_TERM,
        status=AcademicTermStatus.DRAFT,
    )
    db = AsyncMock()

    with (
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.count_results",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.count_report_cards",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.student_academics.curriculum_v2_service.AcademicCurriculumService.specialization_readiness",
            new=AsyncMock(return_value=({}, [])),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.term_calendar_readiness",
            new=AsyncMock(
                return_value={
                    "blockers": calendar_blockers,
                    "counts": {"calendar_days": 0 if calendar_blockers else 90},
                    "calendar_id": None if calendar_blockers else str(uuid.uuid4()),
                }
            ),
        ) as calendar_check,
    ):
        preview = await StudentAcademicService.academic_term_dependency_preview(
            db, tenant_id, term.id
        )

    assert preview.can_open is can_open
    assert preview.blocker_messages == calendar_blockers
    assert preview.dependency_counts["calendar_days"] == (0 if calendar_blockers else 90)
    calendar_check.assert_awaited_once_with(db, tenant_id=tenant_id, term_id=term.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calendar_blockers",
    [
        ["Generate and activate a calendar for this term."],
        ["The term calendar must be active."],
    ],
)
async def test_second_term_does_not_open_after_first_term_closes_without_active_calendar(
    calendar_blockers: list[str],
) -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session = _session(tenant_id)
    first_term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.FIRST_TERM,
        status=AcademicTermStatus.CLOSED,
    )
    second_term = _term(
        tenant_id,
        session.id,
        name=AcademicTermName.SECOND_TERM,
        status=AcademicTermStatus.DRAFT,
    )
    first_term.start_date, first_term.end_date = date(2026, 1, 12), date(2026, 4, 10)
    second_term.start_date, second_term.end_date = date(2026, 4, 11), date(2026, 8, 10)
    db = AsyncMock()

    with (
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=second_term),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.get_current_term",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.list_terms_by_session",
            new=AsyncMock(return_value=([first_term, second_term], 2)),
        ),
        patch(
            "app.modules.subscriptions.term_entitlement_service.TermPlanEntitlementService.ensure_open_eligible",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.term_calendar_readiness",
            new=AsyncMock(
                return_value={
                    "blockers": calendar_blockers,
                    "counts": {"calendar_days": 0},
                    "calendar_id": None,
                }
            ),
        ) as calendar_check,
        patch(
            "app.modules.student_academics.service.StudentAcademicRepository.save_academic_term",
            new=AsyncMock(),
        ) as save_term,
    ):
        with pytest.raises(ConflictException, match="calendar is ready") as exc_info:
            await StudentAcademicService.open_academic_term(
                db=db,
                tenant_id=tenant_id,
                term_id=second_term.id,
                admin_id=admin_id,
            )

    assert exc_info.value is not None
    calendar_check.assert_awaited_once_with(db, tenant_id=tenant_id, term_id=second_term.id)
    assert second_term.status == AcademicTermStatus.DRAFT
    assert second_term.is_current is False
    save_term.assert_not_awaited()
    db.commit.assert_not_awaited()
