"""Calendar generation for academic terms."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.school_calendar.calendar_enums import (
    SchoolCalendarDaySource,
    SchoolCalendarDayType,
    SchoolCalendarStatus,
)
from app.modules.school_calendar.models import (
    SchoolCalendar,
    SchoolCalendarDay,
    SchoolCalendarLifecycleAudit,
)
from app.modules.school_calendar.repository import SchoolCalendarRepository
from app.modules.school_calendar.schemas import (
    SchoolCalendarGenerateRequest,
    SchoolCalendarGenerateResponse,
)
from app.modules.student_academics.models import AcademicSessionStatus, AcademicTermStatus
from app.modules.student_academics.repository import StudentAcademicRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class GenerationCounts:
    total_days: int = 0
    instructional_days: int = 0
    weekend_days: int = 0
    manual_days_preserved: int = 0
    generated_days_created: int = 0
    generated_days_updated: int = 0


class SchoolCalendarGenerationService:
    @staticmethod
    def _iter_dates(start_date: date, end_date: date):
        cursor = start_date
        while cursor <= end_date:
            yield cursor
            cursor += timedelta(days=1)

    @staticmethod
    async def generate(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payload: SchoolCalendarGenerateRequest,
        acting_admin_id: uuid.UUID,
    ) -> SchoolCalendarGenerateResponse:
        session = await StudentAcademicRepository.get_academic_session_by_id(
            db, tenant_id, payload.academic_session_id, lock=True
        )
        if session is None:
            raise NotFoundException("Academic session not found.")
        term = await StudentAcademicRepository.get_term_by_id(
            db, tenant_id, payload.academic_term_id, lock=True
        )
        if term is None:
            raise NotFoundException("Academic term not found.")
        if term.status != AcademicTermStatus.DRAFT:
            raise ConflictException("Only draft academic terms can generate a calendar.")
        if term.academic_session_id != session.id:
            raise BadRequestException("Academic term does not belong to the selected session.")
        if term.start_date is None or term.end_date is None:
            raise BadRequestException("Complete term dates before generating a calendar.")
        if session.start_date and term.start_date < session.start_date:
            raise BadRequestException("Term starts before the academic session.")
        if session.end_date and term.end_date > session.end_date:
            raise BadRequestException("Term ends after the academic session.")

        config = await SchoolCalendarRepository.get_configuration(db, tenant_id)
        if config is None:
            raise ConflictException("Configure the school calendar before generation.")

        calendar = await SchoolCalendarRepository.get_calendar_by_term(db, tenant_id, term.id)
        now = _utc_now()
        configuration_revision = getattr(config, "revision", 1)
        if calendar is None:
            calendar = await SchoolCalendarRepository.save_calendar(
                db,
                SchoolCalendar(
                    tenant_id=tenant_id,
                    academic_session_id=session.id,
                    academic_term_id=term.id,
                    status=SchoolCalendarStatus.DRAFT,
                    generated_at=now,
                    generated_from_configuration_revision=configuration_revision,
                ),
            )
        elif calendar.status != SchoolCalendarStatus.DRAFT:
            raise ConflictException("Only draft calendars can be regenerated.")
        else:
            calendar.generated_at = now
            await SchoolCalendarRepository.save_calendar(db, calendar)

        existing_days = {
            row.calendar_date: row
            for row in await SchoolCalendarRepository.list_days_by_range(
                db,
                tenant_id,
                calendar_id=calendar.id,
                start_date=term.start_date,
                end_date=term.end_date,
                lock=True,
            )
        }
        counts = GenerationCounts()
        new_days: list[SchoolCalendarDay] = []
        warnings: list[str] = []
        generated_days_skipped = 0

        for target_date in SchoolCalendarGenerationService._iter_dates(
            term.start_date, term.end_date
        ):
            is_instructional = target_date.weekday() in set(config.instructional_weekdays)
            day_type = (
                SchoolCalendarDayType.INSTRUCTIONAL_DAY
                if is_instructional
                else SchoolCalendarDayType.WEEKEND
            )
            school_open = is_instructional
            counts.total_days += 1
            if is_instructional:
                counts.instructional_days += 1
            else:
                counts.weekend_days += 1

            existing = existing_days.get(target_date)
            if existing is not None and existing.is_manual_override:
                counts.manual_days_preserved += 1
                continue
            if existing is not None and not payload.overwrite_generated_days:
                generated_days_skipped += 1
                continue
            if existing is not None:
                existing.day_type = day_type
                existing.school_open = school_open
                existing.student_activity_allowed = school_open
                existing.student_attendance_required = bool(
                    school_open and config.default_student_attendance_required
                )
                existing.workforce_attendance_required = bool(
                    school_open and config.default_workforce_attendance_required
                )
                existing.opens_at = config.default_open_time if school_open else None
                existing.closes_at = config.default_close_time if school_open else None
                existing.source = SchoolCalendarDaySource.GENERATED
                existing.updated_by_admin_id = acting_admin_id
                counts.generated_days_updated += 1
                continue
            new_days.append(
                SchoolCalendarDay(
                    tenant_id=tenant_id,
                    calendar_id=calendar.id,
                    academic_session_id=session.id,
                    academic_term_id=term.id,
                    calendar_date=target_date,
                    day_type=day_type,
                    school_open=school_open,
                    student_activity_allowed=school_open,
                    student_attendance_required=bool(
                        school_open and config.default_student_attendance_required
                    ),
                    workforce_attendance_required=bool(
                        school_open and config.default_workforce_attendance_required
                    ),
                    opens_at=config.default_open_time if school_open else None,
                    closes_at=config.default_close_time if school_open else None,
                    source=SchoolCalendarDaySource.GENERATED,
                    created_by_admin_id=acting_admin_id,
                    updated_by_admin_id=acting_admin_id,
                )
            )
            counts.generated_days_created += 1

        if new_days:
            await SchoolCalendarRepository.bulk_insert_days(db, new_days)
        if generated_days_skipped:
            warnings.append(
                "Generated days were skipped because overwrite_generated_days is false; regenerate with overwrite to make the calendar current."
            )
        else:
            calendar.generated_from_configuration_revision = configuration_revision
            await SchoolCalendarRepository.save_calendar(db, calendar)
        count_payload = asdict(counts)

        await SchoolCalendarRepository.add_audit(
            db,
            SchoolCalendarLifecycleAudit(
                tenant_id=tenant_id,
                entity_type="calendar",
                entity_id=calendar.id,
                action="generated",
                previous_state=None,
                new_state={
                    "status": calendar.status.value,
                    "generated_at": now.isoformat(),
                },
                acting_admin_id=acting_admin_id,
                metadata_json={
                    "academic_session_id": str(session.id),
                    "academic_term_id": str(term.id),
                    "overwrite_generated_days": payload.overwrite_generated_days,
                    "counts": count_payload,
                },
            ),
        )
        await db.commit()
        await db.refresh(calendar)

        from app.modules.school_calendar.service import SchoolCalendarService

        return SchoolCalendarGenerateResponse(
            calendar=await SchoolCalendarService.build_calendar_response(db, calendar),
            warnings=warnings,
            **count_payload,
        )
