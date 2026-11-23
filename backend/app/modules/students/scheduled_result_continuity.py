"""Activate scheduled same-level result ownership changes after the placement date."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicSession,
    AcademicSessionStatus,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.students.models import StudentEnrollment, StudentEnrollmentOutcome
from app.modules.students.placement_service import StudentPlacementService
from app.modules.students.repository import StudentEnrollmentRepository
from app.modules.students.result_continuity import AcademicResultContinuityService


PENDING_ACTION = "result_continuity_scheduled"
ACTIVATED_ACTION = "result_continuity_activated"


class ScheduledResultContinuityService:
    """Retryable marker processing with one committed transaction per enrollment."""

    @staticmethod
    async def due_ids(db: AsyncSession, *, limit: int = 25) -> list[UUID]:
        """Discover due markers; cancelled enrollments cannot be selected."""
        activated = aliased(AcademicLifecycleAudit)
        already_done = (
            select(activated.id)
            .where(
                activated.tenant_id == AcademicLifecycleAudit.tenant_id,
                activated.entity_id == AcademicLifecycleAudit.entity_id,
                activated.entity_type == "student_enrollment",
                activated.action == ACTIVATED_ACTION,
            )
            .correlate(AcademicLifecycleAudit)
            .exists()
        )
        rows = await db.execute(
            select(AcademicLifecycleAudit.id)
            .join(
                StudentEnrollment,
                and_(
                    StudentEnrollment.tenant_id == AcademicLifecycleAudit.tenant_id,
                    StudentEnrollment.id == AcademicLifecycleAudit.entity_id,
                ),
            )
            .where(
                AcademicLifecycleAudit.entity_type == "student_enrollment",
                AcademicLifecycleAudit.action == PENDING_ACTION,
                StudentEnrollment.started_on <= func.current_date(),
                ~already_done,
            )
            .order_by(StudentEnrollment.started_on, AcademicLifecycleAudit.id)
            .limit(limit)
        )
        return list(rows.scalars())

    @staticmethod
    async def activate_one(db: AsyncSession, audit_id: UUID) -> int | None:
        """Correct due results once; return None when already processed or claimed."""
        pending = (
            await db.execute(
                select(AcademicLifecycleAudit)
                .where(
                    AcademicLifecycleAudit.id == audit_id,
                    AcademicLifecycleAudit.entity_type == "student_enrollment",
                    AcademicLifecycleAudit.action == PENDING_ACTION,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if pending is None:
            return None

        completed = (
            await db.execute(
                select(AcademicLifecycleAudit.id)
                .where(
                    AcademicLifecycleAudit.tenant_id == pending.tenant_id,
                    AcademicLifecycleAudit.entity_type == "student_enrollment",
                    AcademicLifecycleAudit.entity_id == pending.entity_id,
                    AcademicLifecycleAudit.action == ACTIVATED_ACTION,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if completed is not None:
            return None

        destination = await StudentEnrollmentRepository.get_by_id(
            db, pending.tenant_id, pending.entity_id, lock=True
        )
        if destination is None:
            # An upcoming enrollment can be cancelled without rewriting scores.
            return None
        if destination.started_on > date.today():
            return None

        metadata = pending.metadata_json or {}
        current = await StudentEnrollmentRepository.get_current(
            db, pending.tenant_id, destination.student_id, lock=True
        )
        session = (
            await db.execute(
                select(AcademicSession).where(
                    AcademicSession.tenant_id == pending.tenant_id,
                    AcademicSession.id == destination.academic_session_id,
                )
            )
        ).scalar_one_or_none()

        changes = 0
        outcome = "skipped"
        if (
            current is not None
            and current.id == destination.id
            and destination.class_id is not None
            and destination.entry_outcome == StudentEnrollmentOutcome.RECLASSIFIED
            and str(destination.academic_level_id) == metadata.get("source_level_id")
            and str(destination.academic_session_id) == metadata.get("academic_session_id")
            and session is not None
            and session.status == AcademicSessionStatus.OPEN
            and session.is_current
        ):
            await ensure_academic_write_window(db, tenant_id=pending.tenant_id)
            decisions = await AcademicResultContinuityService.apply(
                db,
                actor_id=pending.acting_admin_id,
                tenant_id=pending.tenant_id,
                student_id=destination.student_id,
                academic_session_id=destination.academic_session_id,
                source_level_id=destination.academic_level_id,
                destination_enrollment=destination,
                effective_date=destination.started_on,
                reason=pending.reason or "Scheduled same-level placement activated",
                carry_finalized_results=bool(metadata.get("carry_finalized_results", False)),
            )
            changes = sum(decision.applied for decision in decisions)
            outcome = "activated"
            await StudentPlacementService._invalidate_derived_context(
                db,
                tenant_id=pending.tenant_id,
                student_id=destination.student_id,
                academic_session_id=destination.academic_session_id,
            )

        await StudentAcademicRepository.add_academic_lifecycle_audit(
            db,
            AcademicLifecycleAudit(
                tenant_id=pending.tenant_id,
                entity_type="student_enrollment",
                entity_id=destination.id,
                action=ACTIVATED_ACTION,
                acting_admin_id=pending.acting_admin_id,
                reason=pending.reason,
                metadata_json={
                    "student_id": str(destination.student_id),
                    "outcome": outcome,
                    "result_corrections": changes,
                    "scheduled_audit_id": str(pending.id),
                },
            ),
        )
        if outcome == "activated":
            await StudentPlacementService._commit_with_readiness_invalidation(
                db,
                tenant_id=pending.tenant_id,
                student_id=destination.student_id,
                academic_session_id=destination.academic_session_id,
            )
        else:
            await db.commit()
        return changes
