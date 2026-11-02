"""Durable, idempotent automatic closure for overdue TMA assignments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.events import flush_cache_invalidation_events
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus


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
            assignment.status = TMAAssignmentStatus.CLOSED
            assignment.closed_at = current
            assignment.zero_grading_requested_at = current
        if due:
            await db.commit()
            await flush_cache_invalidation_events(db)
        return {"closed": len(due)}
