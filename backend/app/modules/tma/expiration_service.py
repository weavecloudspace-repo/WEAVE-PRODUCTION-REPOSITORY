"""Durable, idempotent automatic closure for overdue TMA assignments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.events import flush_cache_invalidation_events
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus, TMAClosureRun
from app.modules.tma.repository import TMARevisionRepository
from app.modules.tma.deadline_eligibility_repository import TMADeadlineEligibilityRepository
from app.core.exceptions import ConflictException


class TMAExpirationService:
    @staticmethod
    async def close_due_assignments(
        db: AsyncSession, *, now: datetime | None = None, batch_size: int = 100
    ) -> dict[str, int]:
        """Close due assignments in small locked batches without touching scores.

        Student writes enforce the timestamp immediately; this worker makes the
        lifecycle state persistent, including during periods of low traffic.
        """
        if not 1 <= batch_size <= 500:
            raise ValueError("batch_size must be between 1 and 500")
        current = now or datetime.now(timezone.utc)
        due = list(
            (
                await db.execute(
                    select(TMAAssignment)
                    .where(
                        TMAAssignment.status == TMAAssignmentStatus.ACTIVE,
                        TMAAssignment.closes_at.is_not(None),
                        TMAAssignment.closes_at <= current,
                    )
                    .order_by(TMAAssignment.closes_at, TMAAssignment.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for assignment in due:
            revision = await TMARevisionRepository.get_by_number(
                db, assignment.tenant_id, assignment.id, assignment.current_revision_number
            )
            if revision is None:
                # Preserve the active assignment for investigation rather than
                # closing it without a durable grading cycle.
                continue
            assignment.status = TMAAssignmentStatus.CLOSED
            assignment.closed_at = current
            assignment.zero_grading_requested_at = current
            assignment.zero_grading_completed_at = None
            db.add(
                TMAClosureRun(
                    tenant_id=assignment.tenant_id,
                    assignment_id=assignment.id,
                    revision_id=revision.id,
                    closed_at=current,
                    cutoff_at=assignment.closes_at,
                    original_deadline_at=assignment.closes_at,
                    kind="automatic",
                )
            )
        if due:
            await db.flush()
            for assignment in due:
                if assignment.status != TMAAssignmentStatus.CLOSED:
                    continue
                try:
                    await TMADeadlineEligibilityRepository.capture(
                        db, tenant_id=assignment.tenant_id, assignment_id=assignment.id
                    )
                except ConflictException as exc:
                    # Preserve the closure, but never zero-grade unverified history.
                    assignment.zero_grading_error = str(exc)
            await db.commit()
            await flush_cache_invalidation_events(db)
        return {"closed": sum(a.status == TMAAssignmentStatus.CLOSED for a in due)}
