"""Immediate and idempotent TMA grading dispatch, retry and stale-job coverage."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.queue import arq, heavy_worker
from app.modules.tma import deadline_zero_service, router


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_zero_job_deduplicates_one_closure(monkeypatch):
    redis = SimpleNamespace(enqueue_job=AsyncMock(return_value=object()), close=AsyncMock())
    monkeypatch.setattr(arq, "create_pool", AsyncMock(return_value=redis))
    assignment_id, tenant_id = _uid(), _uid()
    closed_at = "2026-11-05T20:00:00+00:00"
    assert await arq.enqueue_tma_zero_grading_job(
        assignment_id=assignment_id, tenant_id=tenant_id, closed_at=closed_at
    )
    assert redis.enqueue_job.call_args.kwargs["_queue_name"] == arq.HEAVY_QUEUE_NAME
    assert redis.enqueue_job.call_args.kwargs["_job_id"] == (
        f"tma-zero:{assignment_id}:{closed_at}"
    )
    redis.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_enqueues_after_service_commit_even_if_redis_fails(monkeypatch):
    assignment = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), closed_at=datetime.now(timezone.utc)
    )
    close = AsyncMock(return_value=assignment)
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(router.TMACancellationService, "close", close)
    monkeypatch.setattr(arq, "enqueue_tma_zero_grading_job", enqueue)
    monkeypatch.setattr(
        router,
        "TMAAssignmentStatusResponse",
        SimpleNamespace(model_validate=lambda value: value),
    )
    db, actor = AsyncMock(), SimpleNamespace()
    assert await router.close_assignment(assignment.id, db, actor) is assignment
    close.assert_awaited_once()
    enqueue.assert_awaited_once_with(
        assignment_id=str(assignment.id),
        tenant_id=str(assignment.tenant_id),
        closed_at=assignment.closed_at.isoformat(),
    )
    enqueue.side_effect = ConnectionError("Redis down")
    assert await router.close_assignment(assignment.id, db, actor) is assignment


@pytest.mark.asyncio
async def test_prompt_worker_drains_batches_and_stops_on_failure(monkeypatch):
    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(heavy_worker, "AsyncSessionLocal", session)
    process = AsyncMock(
        side_effect=[
            {"zeroed": 200, "blocked": 0, "pending": 1},
            {"zeroed": 2, "blocked": 1, "pending": 1},
        ]
    )
    monkeypatch.setattr(heavy_worker.TMADeadlineZeroService, "process_pending", process)
    assignment_id, tenant_id = _uid(), _uid()
    closed_at = "2026-11-05T20:00:00+00:00"
    assert await heavy_worker.process_tma_zero_grading_job(
        {}, assignment_id, tenant_id, closed_at
    ) == {"zeroed": 202, "blocked": 1, "pending": 2}
    assert process.await_count == 2
    for call in process.await_args_list:
        assert call.kwargs["assignment_id"] == uuid.UUID(assignment_id)
        assert call.kwargs["tenant_ids"] == {uuid.UUID(tenant_id)}
        assert call.kwargs["closed_at"] == datetime.fromisoformat(closed_at)


@pytest.mark.asyncio
async def test_poll_avoids_same_failed_assignment_in_one_run(monkeypatch):
    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(heavy_worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(
        heavy_worker.TMAExpirationService,
        "close_due_assignments",
        AsyncMock(return_value={"closed": 0}),
    )
    assignment = uuid.uuid4()
    seen = []

    async def process(_db, *, skip_assignment_ids, retry_cooldown_seconds):
        assert retry_cooldown_seconds >= 0
        seen.append(set(skip_assignment_ids))
        if assignment in skip_assignment_ids:
            return {"zeroed": 0, "blocked": 0, "pending": 0}
        skip_assignment_ids.add(assignment)
        return {"zeroed": 0, "blocked": 1, "pending": 1}

    monkeypatch.setattr(heavy_worker.TMADeadlineZeroService, "process_pending", process)
    assert (await heavy_worker.poll_tma_deadlines({}))["blocked"] == 1
    assert seen == [set(), {assignment}]


@pytest.mark.asyncio
async def test_stale_closure_is_filtered_and_failed_retry_is_cooled_down():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    closed_at = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
    assert await deadline_zero_service.TMADeadlineZeroService.process_pending(
        db,
        assignment_id=uuid.uuid4(),
        closed_at=closed_at,
        skip_assignment_ids={uuid.uuid4()},
        retry_cooldown_seconds=120,
    ) == {"zeroed": 0, "blocked": 0, "pending": 0}
    compiled = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "tma_assignments.id = " in compiled
    assert "tma_assignments.closed_at = " in compiled
    assert "zero_grading_last_processed_at" in compiled
    assert "zero_grading_error IS NULL" in compiled


@pytest.mark.asyncio
async def test_healthy_large_batch_remains_eligible_in_same_poll(monkeypatch):
    from app.modules.tma import deadline_zero_service as zero

    now = datetime.now(timezone.utc)
    assignment = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        current_revision_number=1,
        zero_grading_completed_at=None,
        zero_grading_error=None,
    )
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: assignment),
        SimpleNamespace(scalar_one=lambda: 0),
    ]
    monkeypatch.setattr(zero.TMADeadlineZeroService, "MAX_WRITES", 1)
    monkeypatch.setattr(
        zero.TMARevisionRepository,
        "get_by_number",
        AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4(), published_at=now, invalidated_at=None)
        ),
    )
    monkeypatch.setattr(
        zero.TMAQuestionRepository,
        "list_for_revision_with_options",
        AsyncMock(return_value=[(SimpleNamespace(), [])]),
    )
    monkeypatch.setattr(zero.TMAAuthorizationService, "require_open_term", AsyncMock())
    monkeypatch.setattr(
        zero.TMADeadlineEligibilityRepository,
        "_closure",
        AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
    )
    monkeypatch.setattr(
        zero.TMADeadlineEligibilityRepository,
        "pending",
        AsyncMock(return_value=[(uuid.uuid4(), None), (uuid.uuid4(), None)]),
    )

    @asynccontextmanager
    async def nested():
        yield

    db.begin_nested = nested
    monkeypatch.setattr(zero.TMADeadlineZeroService, "_write_zero", AsyncMock(return_value=True))
    monkeypatch.setattr(zero, "flush_cache_invalidation_events", AsyncMock())
    seen = set()
    result = await zero.TMADeadlineZeroService.process_pending(db, skip_assignment_ids=seen)
    assert result == {"zeroed": 1, "blocked": 0, "pending": 1}
    assert seen == set()
