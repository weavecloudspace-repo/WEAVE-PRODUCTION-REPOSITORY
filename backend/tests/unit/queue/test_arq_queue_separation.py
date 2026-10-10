from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.queue import arq as arq_queue
from app.core.queue.context import (
    reset_current_bulk_import_job_id,
    set_current_bulk_import_job_id,
)
from app.core.queue.general_worker import WorkerSettings as GeneralWorkerSettings
from app.core.queue.heavy_worker import WorkerSettings as HeavyWorkerSettings
from app.modules.email_outbox.service import resolve_outbox_metadata


def test_workers_listen_to_different_queues() -> None:
    assert GeneralWorkerSettings.queue_name == arq_queue.GENERAL_QUEUE_NAME
    assert HeavyWorkerSettings.queue_name == arq_queue.HEAVY_QUEUE_NAME
    assert GeneralWorkerSettings.queue_name != HeavyWorkerSettings.queue_name


def test_general_worker_registers_lightweight_jobs() -> None:
    function_names = {function.__name__ for function in GeneralWorkerSettings.functions}

    assert function_names == {
        "process_email_outbox_batch",
        "process_attendance_retention_job",
        "process_subscription_lifecycle_job",
    }
    assert len(GeneralWorkerSettings.cron_jobs) == 4
    assert GeneralWorkerSettings.max_jobs == 3


def test_heavy_worker_serializes_heavy_jobs() -> None:
    function_names = {function.__name__ for function in HeavyWorkerSettings.functions}

    assert function_names == {
        "process_bulk_import_job",
        "process_session_progression_job",
    }
    assert HeavyWorkerSettings.max_jobs == 1
    assert HeavyWorkerSettings.job_timeout == 3600


def test_bulk_import_metadata_contains_active_import_job_id() -> None:
    import_job_id = str(uuid4())
    token = set_current_bulk_import_job_id(import_job_id)

    try:
        metadata = resolve_outbox_metadata(
            {
                "source": "bulk_import",
                "actor_type": "parent",
                "actor_id": str(uuid4()),
            }
        )
    finally:
        reset_current_bulk_import_job_id(token)

    assert metadata["import_job_id"] == import_job_id


def test_non_import_email_metadata_is_not_modified() -> None:
    import_job_id = str(uuid4())
    token = set_current_bulk_import_job_id(import_job_id)

    try:
        metadata = resolve_outbox_metadata({"source": "password_reset"})
    finally:
        reset_current_bulk_import_job_id(token)

    assert "import_job_id" not in metadata


@pytest.mark.asyncio
async def test_email_jobs_use_general_queue(monkeypatch) -> None:
    redis = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=object()),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        arq_queue,
        "create_pool",
        AsyncMock(return_value=redis),
    )

    queued = await arq_queue.enqueue_email_outbox_batch(batch_size=20)

    assert queued is True
    redis.enqueue_job.assert_awaited_once_with(
        "process_email_outbox_batch",
        20,
        _queue_name=arq_queue.GENERAL_QUEUE_NAME,
    )


@pytest.mark.asyncio
async def test_attendance_jobs_use_general_queue(monkeypatch) -> None:
    redis = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=object()),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        arq_queue,
        "create_pool",
        AsyncMock(return_value=redis),
    )

    queued = await arq_queue.enqueue_attendance_retention_job(tenant_id=None)

    assert queued is True
    redis.enqueue_job.assert_awaited_once_with(
        "process_attendance_retention_job",
        None,
        _queue_name=arq_queue.GENERAL_QUEUE_NAME,
    )


@pytest.mark.asyncio
async def test_import_jobs_use_heavy_queue(monkeypatch) -> None:
    redis = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=object()),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        arq_queue,
        "create_pool",
        AsyncMock(return_value=redis),
    )

    import_job_id = str(uuid4())
    tenant_id = str(uuid4())
    actor_id = str(uuid4())

    queued = await arq_queue.enqueue_bulk_import_job(
        job_id=import_job_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
    )

    assert queued is True
    redis.enqueue_job.assert_awaited_once_with(
        "process_bulk_import_job",
        import_job_id,
        tenant_id,
        actor_id,
        True,
        _queue_name=arq_queue.HEAVY_QUEUE_NAME,
        _job_id=f"bulk-import:{import_job_id}",
    )


@pytest.mark.asyncio
async def test_progression_jobs_use_heavy_queue(monkeypatch) -> None:
    redis = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=object()),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        arq_queue,
        "create_pool",
        AsyncMock(return_value=redis),
    )

    run_id = str(uuid4())
    tenant_id = str(uuid4())

    queued = await arq_queue.enqueue_session_progression_job(
        run_id=run_id,
        tenant_id=tenant_id,
    )

    assert queued is True
    redis.enqueue_job.assert_awaited_once_with(
        "process_session_progression_job",
        run_id,
        tenant_id,
        _queue_name=arq_queue.HEAVY_QUEUE_NAME,
        _job_id=f"session-progression:{run_id}",
    )
