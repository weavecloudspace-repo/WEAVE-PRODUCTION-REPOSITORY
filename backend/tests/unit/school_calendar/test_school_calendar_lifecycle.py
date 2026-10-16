from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.school_calendar.calendar_enums import (
    SchoolCalendarDaySource,
    SchoolCalendarDayType,
    SchoolCalendarStatus,
)
from app.modules.school_calendar.models import SchoolCalendar, SchoolCalendarDay
from app.modules.school_calendar.schemas import (
    SchoolCalendarArchiveRequest,
    SchoolCalendarConfigurationCreate,
    SchoolCalendarConfigurationUpdate,
    SchoolCalendarDayUpdate,
    SchoolCalendarEmergencyClosureRequest,
    SchoolCalendarGenerateRequest,
    SchoolCalendarResponse,
)
from app.modules.school_calendar.generation_service import (
    SchoolCalendarGenerationService,
)
from app.modules.school_calendar.service import SchoolCalendarService
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermName,
    AcademicTermStatus,
)


def test_calendar_configuration_rejects_duplicate_weekdays() -> None:
    with pytest.raises(ValueError):
        SchoolCalendarConfigurationCreate(instructional_weekdays=[0, 1, 1, 2])


def test_calendar_configuration_rejects_invalid_timezone() -> None:
    with pytest.raises(ValueError, match="invalid timezone"):
        SchoolCalendarConfigurationUpdate(timezone="Not/AZone")


def test_calendar_day_update_blocks_impossible_attendance_combination() -> None:
    with pytest.raises(ValueError):
        SchoolCalendarDayUpdate(
            school_open=False,
            student_activity_allowed=False,
            student_attendance_required=True,
        )


@pytest.mark.asyncio
async def test_term_calendar_readiness_requires_active_calendar() -> None:
    tenant_id = uuid.uuid4()
    term_id = uuid.uuid4()
    db = AsyncMock()

    with patch(
        "app.modules.school_calendar.service.SchoolCalendarRepository.get_calendar_by_term",
        new=AsyncMock(return_value=None),
    ):
        contribution = await SchoolCalendarService.term_calendar_readiness(
            db,
            tenant_id=tenant_id,
            term_id=term_id,
        )

    assert contribution["calendar_id"] is None
    assert contribution["blockers"] == ["Generate and activate a calendar for this term."]


@pytest.mark.asyncio
async def test_calendar_activation_preview_blocks_closed_session() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar = SchoolCalendar(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
    )
    session = AcademicSession(
        id=session_id,
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.CLOSED,
        is_current=False,
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.FIRST_TERM,
        start_date=date(2026, 1, 12),
        end_date=date(2026, 4, 10),
        status=AcademicTermStatus.DRAFT,
        is_current=False,
    )
    db = AsyncMock()

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_calendar_by_id",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.school_calendar.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_days",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_unresolved_days",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_missing_dates",
            new=AsyncMock(return_value=90),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_extra_dates",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_duplicate_dates",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_invalid_days",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(return_value=SimpleNamespace(revision=1)),
        ),
    ):
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db,
            tenant_id,
            calendar.id,
        )

    assert preview.can_activate is False
    assert (
        "Academic session must be open and current before calendar activation."
        in preview.blocker_messages
    )
    assert "SESSION_NOT_OPEN_CURRENT" in preview.blocker_codes
    assert preview.dependency_counts["missing_dates"] == 90


@pytest.mark.asyncio
async def test_build_calendar_response_merges_preview_without_duplicate_kwargs() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = AsyncMock()
    calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_at=now,
        created_at=now,
        updated_at=now,
    )
    preview = SimpleNamespace(
        can_activate=True,
        can_archive=False,
        can_edit=True,
        can_regenerate=True,
        blocker_messages=[],
        blocker_codes=[],
        missing_dates=0,
        extra_dates=0,
        duplicate_dates=0,
        invalid_days=0,
        configuration_outdated=False,
        dependency_counts={"days": 5, "missing_dates": 0, "unresolved_days": 0},
    )

    with patch(
        "app.modules.school_calendar.service.SchoolCalendarService.calendar_dependency_preview",
        new=AsyncMock(return_value=preview),
    ):
        response = await SchoolCalendarService.build_calendar_response(db, calendar)

    assert response.can_activate is True
    assert response.can_archive is False
    assert response.can_edit is True
    assert response.can_regenerate is True
    assert response.dependency_counts["days"] == 5


@pytest.mark.asyncio
async def test_calendar_activation_preview_blocks_outdated_configuration() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar = SchoolCalendar(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_from_configuration_revision=1,
    )
    session = AcademicSession(
        id=session_id,
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.OPEN,
        is_current=True,
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.FIRST_TERM,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        status=AcademicTermStatus.DRAFT,
    )

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_calendar_by_id",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.school_calendar.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(return_value=SimpleNamespace(revision=2)),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_days",
            new=AsyncMock(return_value=5),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_unresolved_days",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_duplicate_dates",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_invalid_days",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_missing_dates",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.count_extra_dates",
            new=AsyncMock(return_value=0),
        ),
    ):
        preview = await SchoolCalendarService.calendar_dependency_preview(
            AsyncMock(), tenant_id, calendar.id
        )

    assert preview.can_activate is False
    assert preview.configuration_outdated is True
    assert "CONFIGURATION_OUTDATED" in preview.blocker_codes


@pytest.mark.asyncio
async def test_configuration_revision_does_not_increment_for_noop_save() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    config = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        timezone="Africa/Lagos",
        instructional_weekdays=[0, 1, 2, 3, 4],
        default_open_time=time(8, 0),
        default_close_time=time(15, 0),
        default_student_attendance_required=True,
        default_workforce_attendance_required=True,
        revision=3,
        created_at=now,
        updated_at=now,
    )

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(return_value=config),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.update_configuration",
            new=AsyncMock(),
        ) as update_config,
    ):
        response = await SchoolCalendarService.upsert_configuration(
            AsyncMock(),
            tenant_id=tenant_id,
            payload=SchoolCalendarConfigurationUpdate(
                timezone="Africa/Lagos",
                instructional_weekdays=[0, 1, 2, 3, 4],
                default_open_time=time(8, 0),
                default_close_time=time(15, 0),
                default_student_attendance_required=True,
                default_workforce_attendance_required=True,
            ),
            acting_admin_id=admin_id,
        )

    update_config.assert_not_awaited()
    assert response.revision == 3


@pytest.mark.asyncio
async def test_update_day_allows_selected_draft_calendar_day() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=uuid.uuid4(),
        academic_term_id=uuid.uuid4(),
        status=SchoolCalendarStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
    day = SchoolCalendarDay(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        academic_session_id=calendar.academic_session_id,
        academic_term_id=calendar.academic_term_id,
        calendar_date=date(2026, 9, 2),
        day_type=SchoolCalendarDayType.INSTRUCTIONAL_DAY,
        school_open=True,
        student_activity_allowed=True,
        student_attendance_required=True,
        workforce_attendance_required=True,
        source=SchoolCalendarDaySource.GENERATED,
        is_manual_override=False,
        created_at=now,
        updated_at=now,
    )

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_calendar_by_id",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_day_by_date",
            new=AsyncMock(return_value=day),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.tenant_today",
            new=AsyncMock(return_value=date(2026, 9, 1)),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.update_day",
            new=AsyncMock(return_value=day),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.add_audit",
            new=AsyncMock(),
        ),
    ):
        response = await SchoolCalendarService.update_day(
            AsyncMock(),
            tenant_id=tenant_id,
            calendar_date=day.calendar_date,
            payload=SchoolCalendarDayUpdate(
                calendar_id=calendar_id,
                day_type=SchoolCalendarDayType.PUBLIC_HOLIDAY,
                school_open=False,
                student_activity_allowed=False,
                student_attendance_required=False,
            ),
            acting_admin_id=admin_id,
        )

    assert response.day_type == SchoolCalendarDayType.PUBLIC_HOLIDAY
    assert response.is_manual_override is True


@pytest.mark.asyncio
async def test_emergency_closure_updates_only_active_calendar_range() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = AsyncMock()
    active_calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.ACTIVE,
        generated_at=now,
        activated_at=now,
        created_at=now,
        updated_at=now,
    )
    days = [
        SchoolCalendarDay(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            academic_session_id=session_id,
            academic_term_id=term_id,
            calendar_date=date(2026, 2, 2),
            day_type=SchoolCalendarDayType.INSTRUCTIONAL_DAY,
            school_open=True,
            student_activity_allowed=True,
            student_attendance_required=True,
            workforce_attendance_required=True,
            created_at=now,
            updated_at=now,
        ),
        SchoolCalendarDay(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            academic_session_id=session_id,
            academic_term_id=term_id,
            calendar_date=date(2026, 2, 3),
            day_type=SchoolCalendarDayType.INSTRUCTIONAL_DAY,
            school_open=True,
            student_activity_allowed=True,
            student_attendance_required=True,
            workforce_attendance_required=True,
            created_at=now,
            updated_at=now,
        ),
    ]

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_active_calendar_for_date",
            new=AsyncMock(return_value=active_calendar),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.list_days_by_range",
            new=AsyncMock(return_value=days),
        ) as list_days,
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.bulk_update_date_range",
            new=AsyncMock(return_value=days),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.add_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.tenant_today",
            new=AsyncMock(return_value=date(2026, 1, 1)),
        ),
    ):
        response = await SchoolCalendarService.emergency_closure(
            db,
            tenant_id=tenant_id,
            payload=SchoolCalendarEmergencyClosureRequest(
                start_date=date(2026, 2, 2),
                end_date=date(2026, 2, 3),
                reason="Flood warning",
            ),
            acting_admin_id=admin_id,
        )

    list_days.assert_awaited_once()
    assert list_days.await_args.kwargs["calendar_id"] == calendar_id
    assert response.total == 2
    assert all(item.day_type == SchoolCalendarDayType.EMERGENCY_CLOSURE for item in response.items)
    assert all(item.school_open is False for item in response.items)


@pytest.mark.asyncio
async def test_list_days_can_scope_actor_range_to_active_calendars() -> None:
    tenant_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    db = AsyncMock()

    with patch(
        "app.modules.school_calendar.service.SchoolCalendarRepository.list_days_by_range",
        new=AsyncMock(return_value=[]),
    ) as list_days:
        response = await SchoolCalendarService.list_days(
            db,
            tenant_id,
            start_date=date(2026, 2, 2),
            end_date=date(2026, 2, 3),
            active_only=True,
        )

    assert response.total == 0
    list_days.assert_awaited_once_with(
        db,
        tenant_id,
        calendar_id=None,
        start_date=date(2026, 2, 2),
        end_date=date(2026, 2, 3),
        active_only=True,
    )

    with patch(
        "app.modules.school_calendar.service.SchoolCalendarRepository.list_days_by_range",
        new=AsyncMock(return_value=[]),
    ) as list_days:
        await SchoolCalendarService.list_days(
            db,
            tenant_id,
            calendar_id=calendar_id,
            start_date=date(2026, 2, 2),
            end_date=date(2026, 2, 3),
        )

    list_days.assert_awaited_once_with(
        db,
        tenant_id,
        calendar_id=calendar_id,
        start_date=date(2026, 2, 2),
        end_date=date(2026, 2, 3),
        active_only=False,
    )


@pytest.mark.asyncio
async def test_emergency_closure_requires_selected_active_calendar_to_match_range() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    selected_calendar = SchoolCalendar(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=uuid.uuid4(),
        academic_term_id=uuid.uuid4(),
        status=SchoolCalendarStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    range_calendar = SchoolCalendar(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        academic_session_id=uuid.uuid4(),
        academic_term_id=uuid.uuid4(),
        status=SchoolCalendarStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_calendar_by_id",
            new=AsyncMock(return_value=selected_calendar),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_active_calendar_for_date",
            new=AsyncMock(return_value=range_calendar),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.tenant_today",
            new=AsyncMock(return_value=date(2026, 1, 1)),
        ),
    ):
        with pytest.raises(ConflictException):
            await SchoolCalendarService.emergency_closure(
                AsyncMock(),
                tenant_id=tenant_id,
                payload=SchoolCalendarEmergencyClosureRequest(
                    calendar_id=selected_calendar.id,
                    start_date=date(2026, 2, 2),
                    end_date=date(2026, 2, 3),
                    reason="Flood warning",
                ),
                acting_admin_id=admin_id,
            )


@pytest.mark.asyncio
async def test_emergency_closure_requires_active_calendar_range() -> None:
    db = AsyncMock()

    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.get_active_calendar_for_date",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.tenant_today",
            new=AsyncMock(return_value=date(2026, 1, 1)),
        ),
    ):
        with pytest.raises(NotFoundException):
            await SchoolCalendarService.emergency_closure(
                db,
                tenant_id=uuid.uuid4(),
                payload=SchoolCalendarEmergencyClosureRequest(
                    start_date=date(2026, 2, 2),
                    end_date=date(2026, 2, 3),
                    reason="Flood warning",
                ),
                acting_admin_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_emergency_closure_rejects_past_dates() -> None:
    with patch(
        "app.modules.school_calendar.service.SchoolCalendarService.tenant_today",
        new=AsyncMock(return_value=date(2026, 9, 10)),
    ):
        with pytest.raises(ConflictException):
            await SchoolCalendarService.emergency_closure(
                AsyncMock(),
                tenant_id=uuid.uuid4(),
                payload=SchoolCalendarEmergencyClosureRequest(
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 9, 2),
                    reason="Already happened",
                ),
                acting_admin_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_calendar_generation_serializes_slotted_counts() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = AsyncMock()
    audit_records = []

    session = AcademicSession(
        id=session_id,
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.OPEN,
        is_current=True,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.FIRST_TERM,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        status=AcademicTermStatus.DRAFT,
        is_current=False,
    )
    calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_at=now,
        created_at=now,
        updated_at=now,
    )
    calendar_response = SchoolCalendarResponse(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_at=now,
        activated_at=None,
        activated_by_admin_id=None,
        archived_at=None,
        archived_by_admin_id=None,
        created_at=now,
        updated_at=now,
    )

    async def capture_audit(_db, audit):
        audit_records.append(audit)
        return audit

    with (
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    instructional_weekdays=[0, 1, 2, 3, 4],
                    default_open_time=time(8, 0),
                    default_close_time=time(15, 0),
                    default_student_attendance_required=True,
                    default_workforce_attendance_required=True,
                )
            ),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.get_calendar_by_term",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.save_calendar",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.list_days_by_range",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.bulk_insert_days",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.add_audit",
            new=AsyncMock(side_effect=capture_audit),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.build_calendar_response",
            new=AsyncMock(return_value=calendar_response),
        ),
    ):
        response = await SchoolCalendarGenerationService.generate(
            db,
            tenant_id=tenant_id,
            payload=SchoolCalendarGenerateRequest(
                academic_session_id=session_id,
                academic_term_id=term_id,
            ),
            acting_admin_id=admin_id,
        )

    assert response.total_days == 5
    assert response.instructional_days == 5
    assert response.generated_days_created == 5
    assert audit_records[0].metadata_json["counts"]["total_days"] == 5


@pytest.mark.asyncio
async def test_regeneration_keeps_calendar_outdated_when_generated_days_are_skipped() -> None:
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    calendar_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = AsyncMock()
    session = AcademicSession(
        id=session_id,
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.OPEN,
        is_current=True,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.FIRST_TERM,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        status=AcademicTermStatus.DRAFT,
        is_current=False,
    )
    calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_at=now,
        generated_from_configuration_revision=1,
        created_at=now,
        updated_at=now,
    )
    existing_day = SchoolCalendarDay(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        calendar_date=date(2026, 1, 5),
        day_type=SchoolCalendarDayType.INSTRUCTIONAL_DAY,
        school_open=True,
        student_activity_allowed=True,
        student_attendance_required=True,
        workforce_attendance_required=True,
        source=SchoolCalendarDaySource.GENERATED,
        is_manual_override=False,
        created_at=now,
        updated_at=now,
    )
    calendar_response = SchoolCalendarResponse(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.DRAFT,
        generated_at=now,
        generated_from_configuration_revision=1,
        activated_at=None,
        activated_by_admin_id=None,
        archived_at=None,
        archived_by_admin_id=None,
        configuration_outdated=True,
        created_at=now,
        updated_at=now,
    )

    with (
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    revision=2,
                    instructional_weekdays=[0, 1, 2, 3, 4],
                    default_open_time=time(8, 0),
                    default_close_time=time(15, 0),
                    default_student_attendance_required=True,
                    default_workforce_attendance_required=True,
                )
            ),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.get_calendar_by_term",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.save_calendar",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.list_days_by_range",
            new=AsyncMock(return_value=[existing_day]),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.bulk_insert_days",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.add_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarService.build_calendar_response",
            new=AsyncMock(return_value=calendar_response),
        ),
    ):
        response = await SchoolCalendarGenerationService.generate(
            db,
            tenant_id=tenant_id,
            payload=SchoolCalendarGenerateRequest(
                academic_session_id=session_id,
                academic_term_id=term_id,
                overwrite_generated_days=False,
            ),
            acting_admin_id=admin_id,
        )

    assert response.generated_days_updated == 0
    assert calendar.generated_from_configuration_revision == 1
    assert response.calendar.configuration_outdated is True
    assert response.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "term_status",
    [AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING, AcademicTermStatus.CLOSED],
)
async def test_calendar_generation_rejects_terms_that_are_no_longer_draft(
    term_status: AcademicTermStatus,
) -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    term_id = uuid.uuid4()
    session = AcademicSession(
        id=session_id,
        tenant_id=tenant_id,
        name="2026/2027",
        status=AcademicSessionStatus.OPEN,
        is_current=True,
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.SECOND_TERM,
        start_date=date(2026, 4, 11),
        end_date=date(2026, 8, 10),
        status=term_status,
        is_current=term_status in {AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING},
    )
    db = AsyncMock()
    with (
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_academic_session_by_id",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.modules.school_calendar.generation_service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.generation_service.SchoolCalendarRepository.get_configuration",
            new=AsyncMock(),
        ) as get_configuration,
    ):
        with pytest.raises(ConflictException, match="Only draft academic terms"):
            await SchoolCalendarGenerationService.generate(
                db,
                tenant_id=tenant_id,
                payload=SchoolCalendarGenerateRequest(
                    academic_session_id=session_id,
                    academic_term_id=term_id,
                ),
                acting_admin_id=uuid.uuid4(),
            )

    get_configuration.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("term_status", [AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING])
async def test_force_archive_cannot_remove_operational_term_calendar(
    term_status: AcademicTermStatus,
) -> None:
    tenant_id, session_id, term_id, calendar_id = (uuid.uuid4() for _ in range(4))
    calendar = SchoolCalendar(
        id=calendar_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        status=SchoolCalendarStatus.ACTIVE,
    )
    term = AcademicTerm(
        id=term_id,
        tenant_id=tenant_id,
        academic_session_id=session_id,
        name=AcademicTermName.SECOND_TERM,
        status=term_status,
        is_current=True,
    )
    db = AsyncMock()
    with (
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.lock_calendar",
            new=AsyncMock(return_value=calendar),
        ),
        patch(
            "app.modules.school_calendar.service.StudentAcademicRepository.get_term_by_id",
            new=AsyncMock(return_value=term),
        ),
        patch(
            "app.modules.school_calendar.service.SchoolCalendarRepository.save_calendar",
            new=AsyncMock(),
        ) as save_calendar,
    ):
        with pytest.raises(ConflictException, match="retain its active calendar"):
            await SchoolCalendarService.archive_calendar(
                db,
                tenant_id=tenant_id,
                calendar_id=calendar_id,
                payload=SchoolCalendarArchiveRequest(
                    confirmation="ARCHIVE_SCHOOL_CALENDAR",
                    force_replacement=True,
                    reason="Attempt to replace calendar",
                ),
                acting_admin_id=uuid.uuid4(),
            )

    assert calendar.status == SchoolCalendarStatus.ACTIVE
    save_calendar.assert_not_awaited()
    db.commit.assert_not_awaited()
