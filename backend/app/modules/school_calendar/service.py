"""School calendar business rules and lifecycle orchestration."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.school_calendar.calendar_enums import (
    SchoolCalendarDaySource,
    SchoolCalendarDayType,
    SchoolCalendarEventAudience,
    SchoolCalendarEventStatus,
    SchoolCalendarStatus,
)
from app.modules.school_calendar.models import (
    SchoolCalendar,
    SchoolCalendarConfiguration,
    SchoolCalendarDay,
    SchoolCalendarEvent,
    SchoolCalendarLifecycleAudit,
)
from app.modules.school_calendar.repository import SchoolCalendarRepository
from app.modules.school_calendar.schemas import (
    SchoolCalendarArchiveRequest,
    SchoolCalendarConfigurationCreate,
    SchoolCalendarConfigurationResponse,
    SchoolCalendarConfigurationUpdate,
    SchoolCalendarDateRangeUpdate,
    SchoolCalendarDayResponse,
    SchoolCalendarDayUpdate,
    SchoolCalendarDependencyPreview,
    SchoolCalendarEmergencyClosureRequest,
    SchoolCalendarEventCancelRequest,
    SchoolCalendarEventCreate,
    SchoolCalendarEventListResponse,
    SchoolCalendarEventPublishRequest,
    SchoolCalendarEventResponse,
    SchoolCalendarEventUpdate,
    SchoolCalendarListResponse,
    SchoolCalendarRangeResponse,
    SchoolCalendarResponse,
    SchoolCalendarUpcomingResponse,
)
from app.modules.student_academics.models import (
    AcademicSessionStatus,
    AcademicTermStatus,
)
from app.modules.student_academics.repository import StudentAcademicRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_zoneinfo(value: str | None) -> ZoneInfo:
    # Runtime fallback is only for missing/legacy persisted configuration.
    try:
        return ZoneInfo(value or "Africa/Lagos")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Africa/Lagos")


CONFIGURATION_REVISION_FIELDS = {
    "instructional_weekdays",
    "timezone",
    "default_open_time",
    "default_close_time",
    "default_student_attendance_required",
    "default_workforce_attendance_required",
}


def _configuration_values(config: SchoolCalendarConfiguration) -> dict[str, object]:
    return {field: getattr(config, field) for field in CONFIGURATION_REVISION_FIELDS}


class LifecycleReadinessContribution(dict):
    """Simple contribution object used by future lifecycle blockers."""


class TermClosureReadinessProvider(Protocol):
    async def inspect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> LifecycleReadinessContribution: ...


class SchoolCalendarService:
    @staticmethod
    async def _audit(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        acting_admin_id: uuid.UUID | None,
        previous_state: dict | None = None,
        new_state: dict | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        await SchoolCalendarRepository.add_audit(
            db,
            SchoolCalendarLifecycleAudit(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                previous_state=previous_state,
                new_state=new_state,
                acting_admin_id=acting_admin_id,
                reason=reason,
                metadata_json=metadata,
            ),
        )

    @staticmethod
    async def get_or_create_configuration(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarConfigurationCreate,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarConfigurationResponse:
        existing = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        if existing is not None:
            raise ConflictException("School calendar configuration already exists.")
        config = await SchoolCalendarRepository.create_configuration(
            db,
            SchoolCalendarConfiguration(
                tenant_id=tenant_id,
                **payload.model_dump(),
            ),
        )
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="configuration",
            entity_id=config.id,
            action="created",
            previous_state=None,
            new_state=SchoolCalendarConfigurationResponse.model_validate(config).model_dump(
                mode="json"
            ),
            acting_admin_id=acting_admin_id,
        )
        await db.commit()
        return SchoolCalendarConfigurationResponse.model_validate(config)

    @staticmethod
    async def upsert_configuration(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarConfigurationUpdate,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarConfigurationResponse:
        config = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        if config is None:
            create_payload = SchoolCalendarConfigurationCreate(
                timezone=payload.timezone or "Africa/Lagos",
                instructional_weekdays=payload.instructional_weekdays or [0, 1, 2, 3, 4],
                default_open_time=payload.default_open_time,
                default_close_time=payload.default_close_time,
                default_student_attendance_required=(
                    True
                    if payload.default_student_attendance_required is None
                    else payload.default_student_attendance_required
                ),
                default_workforce_attendance_required=(
                    True
                    if payload.default_workforce_attendance_required is None
                    else payload.default_workforce_attendance_required
                ),
            )
            return await SchoolCalendarService.get_or_create_configuration(
                db,
                tenant_id=tenant_id,
                payload=create_payload,
                acting_admin_id=acting_admin_id,
            )
        previous = SchoolCalendarConfigurationResponse.model_validate(config).model_dump(
            mode="json"
        )
        before_revision_values = _configuration_values(config)
        update_data = payload.model_dump(exclude_unset=True)
        changed = False
        for field, value in update_data.items():
            if getattr(config, field) != value:
                changed = True
            setattr(config, field, value)
        if not changed:
            return SchoolCalendarConfigurationResponse.model_validate(config)
        if any(
            before_revision_values[field] != getattr(config, field)
            for field in CONFIGURATION_REVISION_FIELDS
        ):
            config.revision += 1
        config = await SchoolCalendarRepository.update_configuration(db, config)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="configuration",
            entity_id=config.id,
            action="updated",
            previous_state=previous,
            new_state=SchoolCalendarConfigurationResponse.model_validate(config).model_dump(
                mode="json"
            ),
            acting_admin_id=acting_admin_id,
        )
        await db.commit()
        return SchoolCalendarConfigurationResponse.model_validate(config)

    @staticmethod
    async def get_configuration(
        db: AsyncSession, tenant_id: uuid.UUID
    ) -> SchoolCalendarConfigurationResponse:
        config = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        if config is None:
            raise NotFoundException("School calendar configuration not found.")
        return SchoolCalendarConfigurationResponse.model_validate(config)

    @staticmethod
    async def build_calendar_response(
        db: AsyncSession, calendar: SchoolCalendar
    ) -> SchoolCalendarResponse:
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db, calendar.tenant_id, calendar.id
        )
        base = SchoolCalendarResponse.model_validate(calendar)
        base_payload = base.model_dump(
            exclude={
                "can_activate",
                "can_archive",
                "can_edit",
                "can_regenerate",
                "blocker_messages",
                "blocker_codes",
                "missing_dates",
                "extra_dates",
                "duplicate_dates",
                "invalid_days",
                "configuration_outdated",
                "dependency_counts",
            }
        )
        return SchoolCalendarResponse(
            **base_payload,
            can_activate=preview.can_activate,
            can_archive=preview.can_archive,
            can_edit=preview.can_edit,
            can_regenerate=preview.can_regenerate,
            blocker_messages=preview.blocker_messages,
            blocker_codes=preview.blocker_codes,
            missing_dates=preview.missing_dates,
            extra_dates=preview.extra_dates,
            duplicate_dates=preview.duplicate_dates,
            invalid_days=preview.invalid_days,
            configuration_outdated=preview.configuration_outdated,
            dependency_counts=preview.dependency_counts,
        )

    @staticmethod
    async def tenant_today(db: AsyncSession, tenant_id: uuid.UUID) -> date:
        config = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        return datetime.now(_safe_zoneinfo(config.timezone if config else None)).date()

    @staticmethod
    async def list_calendars(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        status: SchoolCalendarStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> SchoolCalendarListResponse:
        rows, total = await SchoolCalendarRepository.list_calendars(
            db,
            tenant_id,
            academic_session_id=academic_session_id,
            status=status,
            skip=skip,
            limit=limit,
        )
        return SchoolCalendarListResponse(
            items=[await SchoolCalendarService.build_calendar_response(db, row) for row in rows],
            total=total,
        )

    @staticmethod
    async def get_calendar(
        db: AsyncSession, tenant_id: uuid.UUID, calendar_id: uuid.UUID
    ) -> SchoolCalendarResponse:
        calendar = await SchoolCalendarRepository.get_calendar_by_id(db, tenant_id, calendar_id)
        if calendar is None:
            raise NotFoundException("School calendar not found.")
        return await SchoolCalendarService.build_calendar_response(db, calendar)

    @staticmethod
    async def calendar_dependency_preview(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        calendar_id: uuid.UUID,
    ) -> SchoolCalendarDependencyPreview:
        calendar = await SchoolCalendarRepository.get_calendar_by_id(db, tenant_id, calendar_id)
        if calendar is None:
            raise NotFoundException("School calendar not found.")
        session = await StudentAcademicRepository.get_academic_session_by_id(
            db, tenant_id, calendar.academic_session_id
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db, tenant_id, calendar.academic_term_id
        )
        config = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        counts = {
            "days": await SchoolCalendarRepository.count_days(db, tenant_id, calendar.id),
            "unresolved_days": await SchoolCalendarRepository.count_unresolved_days(
                db, tenant_id, calendar.id
            ),
            "missing_dates": 0,
            "extra_dates": 0,
            "duplicate_dates": await SchoolCalendarRepository.count_duplicate_dates(
                db, tenant_id, calendar.id
            ),
            "invalid_days": await SchoolCalendarRepository.count_invalid_days(
                db, tenant_id, calendar.id
            ),
        }
        blockers: list[str] = []
        blocker_codes: list[str] = []

        def block(code: str, message: str) -> None:
            blocker_codes.append(code)
            blockers.append(message)

        if session is None:
            block("SESSION_MISSING", "Academic session is missing.")
        elif session.status != AcademicSessionStatus.OPEN or not session.is_current:
            block(
                "SESSION_NOT_OPEN_CURRENT",
                "Academic session must be open and current before calendar activation.",
            )
        if term is None:
            block("TERM_MISSING", "Academic term is missing.")
        else:
            if session is not None and term.academic_session_id != session.id:
                block(
                    "TERM_SESSION_MISMATCH",
                    "Academic term does not belong to the calendar session.",
                )
            if term.status != AcademicTermStatus.DRAFT:
                block(
                    "TERM_NOT_DRAFT",
                    "Academic term must be draft before calendar activation.",
                )
            if term.start_date is None or term.end_date is None:
                block("TERM_DATES_INCOMPLETE", "Academic term dates are incomplete.")
            else:
                counts["missing_dates"] = await SchoolCalendarRepository.count_missing_dates(
                    db,
                    tenant_id,
                    calendar.id,
                    start_date=term.start_date,
                    end_date=term.end_date,
                )
                counts["extra_dates"] = await SchoolCalendarRepository.count_extra_dates(
                    db,
                    tenant_id,
                    calendar.id,
                    start_date=term.start_date,
                    end_date=term.end_date,
                )
                if counts["missing_dates"]:
                    block(
                        "MISSING_DATES",
                        "Calendar does not cover every date in the term.",
                    )
                if counts["extra_dates"]:
                    block("EXTRA_DATES", "Calendar contains dates outside the term.")
        if config is None:
            block("CONFIGURATION_MISSING", "School calendar configuration is missing.")
        elif calendar.generated_from_configuration_revision != config.revision:
            block(
                "CONFIGURATION_OUTDATED",
                "Calendar was generated from an older configuration revision.",
            )
        if counts["unresolved_days"]:
            block("UNRESOLVED_DAYS", "Calendar has unresolved days.")
        if counts["duplicate_dates"]:
            block("DUPLICATE_DATES", "Calendar contains duplicate dates.")
        if counts["invalid_days"]:
            block("INVALID_DAYS", "Calendar contains invalid operational flags or hours.")
        can_activate = calendar.status == SchoolCalendarStatus.DRAFT and not blockers
        can_archive = calendar.status == SchoolCalendarStatus.ACTIVE and (
            term is not None
            and (
                term.status == AcademicTermStatus.CLOSED
                or (
                    session is not None
                    and session.status
                    in {AcademicSessionStatus.CLOSING, AcademicSessionStatus.CLOSED}
                )
            )
        )
        return SchoolCalendarDependencyPreview(
            calendar_id=calendar.id,
            dependency_counts=counts,
            blocker_messages=blockers,
            blocker_codes=blocker_codes,
            can_activate=can_activate,
            can_archive=can_archive,
            can_edit=calendar.status in {SchoolCalendarStatus.DRAFT, SchoolCalendarStatus.ACTIVE},
            can_regenerate=calendar.status == SchoolCalendarStatus.DRAFT,
            missing_dates=counts["missing_dates"],
            extra_dates=counts["extra_dates"],
            duplicate_dates=counts["duplicate_dates"],
            invalid_days=counts["invalid_days"],
            configuration_outdated="CONFIGURATION_OUTDATED" in blocker_codes,
        )

    @staticmethod
    async def term_calendar_readiness(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> LifecycleReadinessContribution:
        calendar = await SchoolCalendarRepository.get_calendar_by_term(db, tenant_id, term_id)
        blockers: list[str] = []
        counts: dict[str, int] = {
            "calendar_days": 0,
            "missing_calendar_dates": 0,
            "unresolved_calendar_days": 0,
        }
        if calendar is None:
            blockers.append("Generate and activate a calendar for this term.")
            return LifecycleReadinessContribution(
                blockers=blockers, counts=counts, calendar_id=None
            )
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db, tenant_id, calendar.id
        )
        counts["calendar_days"] = preview.dependency_counts.get("days", 0)
        counts["missing_calendar_dates"] = preview.dependency_counts.get("missing_dates", 0)
        counts["unresolved_calendar_days"] = preview.dependency_counts.get("unresolved_days", 0)
        if calendar.status != SchoolCalendarStatus.ACTIVE:
            blockers.append("The term calendar must be active.")
        blockers.extend(preview.blocker_messages)
        return LifecycleReadinessContribution(
            blockers=list(dict.fromkeys(blockers)),
            counts=counts,
            calendar_id=str(calendar.id),
        )

    @staticmethod
    async def inspect_term_closure_readiness(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> LifecycleReadinessContribution:
        calendar = await SchoolCalendarRepository.get_calendar_by_term(db, tenant_id, term_id)
        blockers: list[str] = []
        counts = {"missing_calendar_dates": 0, "unresolved_calendar_days": 0}
        if calendar is None:
            blockers.append("Calendar history is missing for this term.")
            return LifecycleReadinessContribution(
                blockers=blockers, counts=counts, calendar_id=None
            )
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db, tenant_id, calendar.id
        )
        counts["missing_calendar_dates"] = preview.dependency_counts.get("missing_dates", 0)
        counts["unresolved_calendar_days"] = preview.dependency_counts.get("unresolved_days", 0)
        if counts["missing_calendar_dates"]:
            blockers.append("Calendar coverage is incomplete.")
        if counts["unresolved_calendar_days"]:
            blockers.append("Calendar contains unresolved days.")
        return LifecycleReadinessContribution(
            blockers=blockers, counts=counts, calendar_id=str(calendar.id)
        )

    @staticmethod
    async def activate_calendar(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        calendar_id: uuid.UUID,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarResponse:
        calendar = await SchoolCalendarRepository.lock_calendar(db, tenant_id, calendar_id)
        if calendar is None:
            raise NotFoundException("School calendar not found.")
        if calendar.status == SchoolCalendarStatus.ACTIVE:
            return await SchoolCalendarService.build_calendar_response(db, calendar)
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db, tenant_id, calendar.id
        )
        if not preview.can_activate:
            raise ConflictException(
                "School calendar cannot be activated.",
                payload=preview.model_dump(mode="json"),
            )
        previous = {"status": calendar.status.value}
        calendar.status = SchoolCalendarStatus.ACTIVE
        calendar.activated_at = _utc_now()
        calendar.activated_by_admin_id = acting_admin_id
        await SchoolCalendarRepository.save_calendar(db, calendar)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="calendar",
            entity_id=calendar.id,
            action="activated",
            previous_state=previous,
            new_state={"status": calendar.status.value},
            acting_admin_id=acting_admin_id,
        )
        await db.commit()
        await db.refresh(calendar)
        return await SchoolCalendarService.build_calendar_response(db, calendar)

    @staticmethod
    async def archive_calendar(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        calendar_id: uuid.UUID,
        payload: SchoolCalendarArchiveRequest,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarResponse:
        calendar = await SchoolCalendarRepository.lock_calendar(db, tenant_id, calendar_id)
        if calendar is None:
            raise NotFoundException("School calendar not found.")
        if calendar.status == SchoolCalendarStatus.ARCHIVED:
            return await SchoolCalendarService.build_calendar_response(db, calendar)
        # Even forced archival must not leave an operational term without its calendar.
        term = await StudentAcademicRepository.get_term_by_id(
            db, tenant_id, calendar.academic_term_id, lock=True
        )
        if term is not None and term.status in {
            AcademicTermStatus.OPEN,
            AcademicTermStatus.CLOSING,
        }:
            raise ConflictException(
                "An open or closing academic term must retain its active calendar."
            )
        preview = await SchoolCalendarService.calendar_dependency_preview(
            db, tenant_id, calendar.id
        )
        if not preview.can_archive and not payload.force_replacement:
            raise ConflictException(
                "School calendar cannot be archived yet.",
                payload=preview.model_dump(mode="json"),
            )
        if payload.force_replacement and not payload.reason:
            raise BadRequestException("A reason is required for forced archival.")
        previous = {"status": calendar.status.value}
        calendar.status = SchoolCalendarStatus.ARCHIVED
        calendar.archived_at = _utc_now()
        calendar.archived_by_admin_id = acting_admin_id
        await SchoolCalendarRepository.save_calendar(db, calendar)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="calendar",
            entity_id=calendar.id,
            action="archived",
            previous_state=previous,
            new_state={"status": calendar.status.value},
            acting_admin_id=acting_admin_id,
            reason=payload.reason,
            metadata={"force_replacement": payload.force_replacement},
        )
        await db.commit()
        await db.refresh(calendar)
        return await SchoolCalendarService.build_calendar_response(db, calendar)

    @staticmethod
    async def archive_session_calendars(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        acting_admin_id: uuid.UUID,
    ) -> int:
        rows, _ = await SchoolCalendarRepository.list_calendars(
            db,
            tenant_id,
            academic_session_id=academic_session_id,
            status=SchoolCalendarStatus.ACTIVE,
            limit=500,
        )
        count = 0
        for calendar in rows:
            calendar.status = SchoolCalendarStatus.ARCHIVED
            calendar.archived_at = calendar.archived_at or _utc_now()
            calendar.archived_by_admin_id = acting_admin_id
            await SchoolCalendarRepository.save_calendar(db, calendar)
            await SchoolCalendarService._audit(
                db,
                tenant_id=tenant_id,
                entity_type="calendar",
                entity_id=calendar.id,
                action="archived_by_session_closure",
                previous_state={"status": SchoolCalendarStatus.ACTIVE.value},
                new_state={"status": SchoolCalendarStatus.ARCHIVED.value},
                acting_admin_id=acting_admin_id,
            )
            count += 1
        return count

    @staticmethod
    async def archive_term_calendar(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        acting_admin_id: uuid.UUID,
    ) -> int:
        calendar = await SchoolCalendarRepository.get_calendar_by_term(
            db, tenant_id, academic_term_id
        )
        if calendar is None or calendar.status != SchoolCalendarStatus.ACTIVE:
            return 0
        calendar.status = SchoolCalendarStatus.ARCHIVED
        calendar.archived_at = calendar.archived_at or _utc_now()
        calendar.archived_by_admin_id = acting_admin_id
        await SchoolCalendarRepository.save_calendar(db, calendar)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="calendar",
            entity_id=calendar.id,
            action="archived_by_term_closure",
            previous_state={"status": SchoolCalendarStatus.ACTIVE.value},
            new_state={"status": SchoolCalendarStatus.ARCHIVED.value},
            acting_admin_id=acting_admin_id,
        )
        return 1

    @staticmethod
    async def list_days(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        calendar_id: uuid.UUID | None = None,
        start_date: date,
        end_date: date,
        active_only: bool = False,
    ) -> SchoolCalendarRangeResponse:
        days = await SchoolCalendarRepository.list_days_by_range(
            db,
            tenant_id,
            calendar_id=calendar_id,
            start_date=start_date,
            end_date=end_date,
            active_only=active_only,
        )
        return SchoolCalendarRangeResponse(
            items=[SchoolCalendarDayResponse.model_validate(day) for day in days],
            total=len(days),
        )

    @staticmethod
    async def upcoming(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        start_date: date,
        end_date: date,
        audience: set[SchoolCalendarEventAudience],
        limit: int = 10,
    ) -> SchoolCalendarUpcomingResponse:
        days = await SchoolCalendarRepository.list_days_by_range(
            db,
            tenant_id,
            start_date=start_date,
            end_date=end_date,
            active_only=True,
        )
        notable_days = [
            day
            for day in days
            if not day.school_open
            or day.day_type
            in {
                SchoolCalendarDayType.EXAMINATION_DAY,
                SchoolCalendarDayType.PUBLIC_HOLIDAY,
                SchoolCalendarDayType.SCHOOL_HOLIDAY,
                SchoolCalendarDayType.MID_TERM_BREAK,
                SchoolCalendarDayType.EMERGENCY_CLOSURE,
            }
        ][:limit]
        events, _ = await SchoolCalendarRepository.list_events(
            db,
            tenant_id,
            start_date=start_date,
            end_date=end_date,
            status=SchoolCalendarEventStatus.PUBLISHED,
            audience=audience,
            limit=limit,
        )
        return SchoolCalendarUpcomingResponse(
            days=[SchoolCalendarDayResponse.model_validate(day) for day in notable_days],
            events=[SchoolCalendarEventResponse.model_validate(event) for event in events],
            total_days=len(notable_days),
            total_events=len(events),
        )

    @staticmethod
    def _apply_day_update(
        day: SchoolCalendarDay,
        payload: SchoolCalendarDayUpdate | SchoolCalendarDateRangeUpdate,
        admin_id: uuid.UUID,
    ) -> None:
        for field in (
            "day_type",
            "title",
            "description",
            "school_open",
            "student_activity_allowed",
            "student_attendance_required",
            "workforce_attendance_required",
            "opens_at",
            "closes_at",
        ):
            if field in payload.model_fields_set:
                setattr(day, field, getattr(payload, field))
        day.source = SchoolCalendarDaySource.MANUAL
        day.is_manual_override = True
        day.updated_by_admin_id = admin_id

    @staticmethod
    async def update_day(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        calendar_date: date,
        payload: SchoolCalendarDayUpdate,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarDayResponse:
        if payload.calendar_id is not None:
            calendar = await SchoolCalendarRepository.get_calendar_by_id(
                db, tenant_id, payload.calendar_id
            )
        else:
            calendar = await SchoolCalendarRepository.get_active_calendar_for_date(
                db, tenant_id, calendar_date
            )
        if calendar is None:
            raise NotFoundException("No calendar covers this date.")
        if calendar.status not in {
            SchoolCalendarStatus.DRAFT,
            SchoolCalendarStatus.ACTIVE,
        }:
            raise ConflictException("Archived calendar days cannot be edited.")
        day = await SchoolCalendarRepository.get_day_by_date(
            db, tenant_id, calendar.id, calendar_date, lock=True
        )
        if day is None:
            raise NotFoundException("Calendar day not found.")
        today = await SchoolCalendarService.tenant_today(db, tenant_id)
        significant_fields = {
            "day_type",
            "school_open",
            "student_activity_allowed",
            "student_attendance_required",
            "workforce_attendance_required",
        }
        if calendar_date < today and (
            not payload.historical_correction_confirmed or not payload.reason
        ):
            raise ConflictException("Past calendar corrections require confirmation and a reason.")
        if (
            calendar.status == SchoolCalendarStatus.ACTIVE
            and calendar_date >= today
            and significant_fields.intersection(payload.model_fields_set)
            and not payload.reason
        ):
            raise ConflictException("Active calendar operational changes require a reason.")
        previous = SchoolCalendarDayResponse.model_validate(day).model_dump(mode="json")
        SchoolCalendarService._apply_day_update(day, payload, acting_admin_id)
        day = await SchoolCalendarRepository.update_day(db, day)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="day",
            entity_id=day.id,
            action="updated",
            previous_state=previous,
            new_state=SchoolCalendarDayResponse.model_validate(day).model_dump(mode="json"),
            acting_admin_id=acting_admin_id,
            reason=payload.reason,
        )
        await db.commit()
        return SchoolCalendarDayResponse.model_validate(day)

    @staticmethod
    async def update_date_range(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarDateRangeUpdate,
        acting_admin_id: uuid.UUID,
        calendar_id: uuid.UUID | None = None,
    ) -> SchoolCalendarRangeResponse:
        today = await SchoolCalendarService.tenant_today(db, tenant_id)
        if payload.start_date < today and (
            not payload.historical_correction_confirmed or not payload.reason
        ):
            raise ConflictException("Past calendar corrections require confirmation.")
        days = await SchoolCalendarRepository.list_days_by_range(
            db,
            tenant_id,
            calendar_id=calendar_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            lock=True,
        )
        if not days:
            raise NotFoundException("No calendar days were found for this range.")
        expected_days = (payload.end_date - payload.start_date).days + 1
        if len({day.calendar_date for day in days}) != expected_days:
            raise ConflictException("Calendar coverage is incomplete for this date range.")
        if len({day.calendar_id for day in days}) != 1:
            raise ConflictException(
                "Date range spans multiple calendars. Select a range within one active calendar."
            )
        for day in days:
            SchoolCalendarService._apply_day_update(day, payload, acting_admin_id)
        await SchoolCalendarRepository.bulk_update_date_range(db, days)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="day_range",
            entity_id=days[0].calendar_id,
            action="range_updated",
            acting_admin_id=acting_admin_id,
            reason=payload.reason,
            metadata={
                "start_date": payload.start_date.isoformat(),
                "end_date": payload.end_date.isoformat(),
                "day_count": len(days),
            },
        )
        await db.commit()
        return SchoolCalendarRangeResponse(
            items=[SchoolCalendarDayResponse.model_validate(day) for day in days],
            total=len(days),
        )

    @staticmethod
    async def emergency_closure(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarEmergencyClosureRequest,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarRangeResponse:
        selected_calendar = None
        if payload.calendar_id is not None:
            selected_calendar = await SchoolCalendarRepository.get_calendar_by_id(
                db,
                tenant_id,
                payload.calendar_id,
            )
            if selected_calendar is None:
                raise NotFoundException("School calendar not found.")
            if selected_calendar.status != SchoolCalendarStatus.ACTIVE:
                raise ConflictException(
                    "Emergency closure can only be applied to an active calendar."
                )
        today = await SchoolCalendarService.tenant_today(db, tenant_id)
        if payload.start_date < today:
            raise ConflictException(
                "Emergency closure cannot be applied to past dates. Use a historical correction instead."
            )
        start_calendar = await SchoolCalendarRepository.get_active_calendar_for_date(
            db,
            tenant_id,
            payload.start_date,
        )
        end_calendar = await SchoolCalendarRepository.get_active_calendar_for_date(
            db,
            tenant_id,
            payload.end_date,
        )
        if start_calendar is None or end_calendar is None:
            raise NotFoundException("No active school calendar covers this closure range.")
        if start_calendar.id != end_calendar.id:
            raise ConflictException("Emergency closure must stay within one active calendar.")
        if selected_calendar is not None and selected_calendar.id != start_calendar.id:
            raise ConflictException(
                "Emergency closure dates must belong to the selected active calendar."
            )

        update = SchoolCalendarDateRangeUpdate(
            start_date=payload.start_date,
            end_date=payload.end_date,
            day_type=SchoolCalendarDayType.EMERGENCY_CLOSURE,
            title="Emergency closure",
            description=payload.reason,
            school_open=False,
            student_activity_allowed=False,
            student_attendance_required=False,
            workforce_attendance_required=False,
            reason=payload.reason,
            historical_correction_confirmed=True,
        )
        return await SchoolCalendarService.update_date_range(
            db,
            tenant_id=tenant_id,
            payload=update,
            acting_admin_id=acting_admin_id,
            calendar_id=start_calendar.id,
        )

    @staticmethod
    async def create_event(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarEventCreate,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarEventResponse:
        calendar = await SchoolCalendarRepository.get_calendar_by_id(
            db, tenant_id, payload.calendar_id
        )
        if calendar is None:
            raise NotFoundException("School calendar not found.")
        event = await SchoolCalendarRepository.create_event(
            db,
            SchoolCalendarEvent(
                tenant_id=tenant_id,
                calendar_id=calendar.id,
                academic_session_id=calendar.academic_session_id,
                academic_term_id=calendar.academic_term_id,
                created_by_admin_id=acting_admin_id,
                **payload.model_dump(exclude={"calendar_id"}),
            ),
        )
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="event",
            entity_id=event.id,
            action="created",
            acting_admin_id=acting_admin_id,
        )
        await db.commit()
        return SchoolCalendarEventResponse.model_validate(event)

    @staticmethod
    async def list_events(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        calendar_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        status: SchoolCalendarEventStatus | None = None,
        audience: set[SchoolCalendarEventAudience] | None = None,
        actor_facing: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> SchoolCalendarEventListResponse:
        rows, total = await SchoolCalendarRepository.list_events(
            db,
            tenant_id,
            calendar_id=calendar_id,
            start_date=start_date,
            end_date=end_date,
            status=SchoolCalendarEventStatus.PUBLISHED if actor_facing else status,
            audience=audience,
            skip=skip,
            limit=limit,
        )
        return SchoolCalendarEventListResponse(
            items=[SchoolCalendarEventResponse.model_validate(row) for row in rows],
            total=total,
        )

    @staticmethod
    async def update_event(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: SchoolCalendarEventUpdate,
    ) -> SchoolCalendarEventResponse:
        event = await SchoolCalendarRepository.get_event_by_id(db, tenant_id, event_id, lock=True)
        if event is None:
            raise NotFoundException("Calendar event not found.")
        if event.status == SchoolCalendarEventStatus.CANCELLED:
            raise ConflictException("Cancelled events cannot be edited.")
        update_data = payload.model_dump(exclude_unset=True)
        starts_at = update_data.get("starts_at", event.starts_at)
        ends_at = update_data.get("ends_at", event.ends_at)
        if ends_at <= starts_at:
            raise BadRequestException("ends_at must be after starts_at")
        for field, value in update_data.items():
            setattr(event, field, value)
        event = await SchoolCalendarRepository.update_event(db, event)
        await db.commit()
        return SchoolCalendarEventResponse.model_validate(event)

    @staticmethod
    async def publish_event(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: SchoolCalendarEventPublishRequest,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarEventResponse:
        _ = payload.confirmation
        event = await SchoolCalendarRepository.get_event_by_id(db, tenant_id, event_id, lock=True)
        if event is None:
            raise NotFoundException("Calendar event not found.")
        if event.status == SchoolCalendarEventStatus.PUBLISHED:
            return SchoolCalendarEventResponse.model_validate(event)
        if event.status == SchoolCalendarEventStatus.CANCELLED:
            raise ConflictException("Cancelled events cannot be published.")
        event.status = SchoolCalendarEventStatus.PUBLISHED
        event.published_at = _utc_now()
        event = await SchoolCalendarRepository.update_event(db, event)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="event",
            entity_id=event.id,
            action="published",
            acting_admin_id=acting_admin_id,
        )
        await db.commit()
        return SchoolCalendarEventResponse.model_validate(event)

    @staticmethod
    async def cancel_event(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: SchoolCalendarEventCancelRequest,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarEventResponse:
        _ = payload.confirmation
        event = await SchoolCalendarRepository.get_event_by_id(db, tenant_id, event_id, lock=True)
        if event is None:
            raise NotFoundException("Calendar event not found.")
        if event.status == SchoolCalendarEventStatus.CANCELLED:
            return SchoolCalendarEventResponse.model_validate(event)
        event.status = SchoolCalendarEventStatus.CANCELLED
        event.cancelled_at = _utc_now()
        event = await SchoolCalendarRepository.update_event(db, event)
        await SchoolCalendarService._audit(
            db,
            tenant_id=tenant_id,
            entity_type="event",
            entity_id=event.id,
            action="cancelled",
            acting_admin_id=acting_admin_id,
            reason=payload.reason,
        )
        await db.commit()
        return SchoolCalendarEventResponse.model_validate(event)
