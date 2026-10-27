"""ARQ worker for database-heavy bulk import and progression jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import app.models  # noqa: F401

from app.config.database import AsyncSessionLocal, engine  # noqa: E402
from app.config.logging import get_logger  # noqa: E402
from app.config.sentry import flush_sentry, initialize_sentry  # noqa: E402
from app.core.queue.sentry import capture_worker_exceptions  # noqa: E402
from app.core.queue.arq import HEAVY_QUEUE_NAME, get_arq_redis_settings  # noqa: E402
from app.modules.cbt.results.rollback_worker import (
    process_cbt_result_rollback_job,
    recover_cbt_result_rollbacks,
)  # noqa: E402
from arq import cron  # noqa: E402
from app.core.queue.context import (  # noqa: E402
    reset_current_bulk_import_job_id,
    set_current_bulk_import_job_id,
)
from app.modules.bulk_imports.live_service import BulkImportLiveService  # noqa: E402
from app.modules.bulk_imports.models import ImportJobStatus  # noqa: E402
from app.modules.bulk_imports.repository import ImportJobRepository  # noqa: E402
from app.modules.student_academics.lifecycle_repository import (  # noqa: E402
    StudentProgressionRepository,
)
from app.modules.student_academics.models import (  # noqa: E402
    StudentProgressionRunStatus,
)
from app.modules.student_academics.session_closure_service import (  # noqa: E402
    SessionClosureService,
)
from app.modules.realtime.publisher import RealtimePublisher  # noqa: E402

logger = get_logger(__name__)


@capture_worker_exceptions(queue_name=HEAVY_QUEUE_NAME)
async def process_bulk_import_job(
    ctx: dict[str, Any],
    job_id: str,
    tenant_id: str,
    actor_id: str,
    notify_on_completion: bool = True,
) -> dict[str, int | str]:
    """Process one confirmed bulk-import job."""

    _ = ctx
    parsed_job_id = UUID(job_id)
    parsed_tenant_id = UUID(tenant_id)
    parsed_actor_id = UUID(actor_id)
    context_token = set_current_bulk_import_job_id(job_id)
    logger.info(
        "bulk_import.started",
        extra={"job_id": job_id, "tenant_id": tenant_id, "actor_id": actor_id},
    )
    try:
        async with AsyncSessionLocal() as db:
            try:
                result = await BulkImportLiveService.process_confirmed_import_job(
                    db=db,
                    tenant_id=parsed_tenant_id,
                    actor_id=parsed_actor_id,
                    job_id=parsed_job_id,
                    notify_on_completion=notify_on_completion,
                )
            except Exception:
                await db.rollback()
                raise
    except Exception as exc:
        logger.exception(
            "bulk_import.failed",
            extra={"job_id": job_id, "tenant_id": tenant_id, "actor_id": actor_id},
        )
        async with AsyncSessionLocal() as failure_db:
            failed_job = await ImportJobRepository.get_job_by_id(
                db=failure_db,
                tenant_id=parsed_tenant_id,
                job_id=parsed_job_id,
                lock=True,
            )
            if failed_job is not None and failed_job.status in {
                ImportJobStatus.PENDING,
                ImportJobStatus.PROCESSING,
            }:
                await BulkImportLiveService._mark_job_failed(
                    db=failure_db,
                    import_job=failed_job,
                    actor_id=parsed_actor_id,
                    error_message=str(exc),
                )
        raise
    finally:
        reset_current_bulk_import_job_id(context_token)

    logger.info(
        "bulk_import.completed",
        extra={"job_id": job_id, "tenant_id": tenant_id, "bulk_import_result": result},
    )
    return result


@capture_worker_exceptions(queue_name=HEAVY_QUEUE_NAME)
async def process_session_progression_job(
    ctx: dict[str, Any],
    run_id: str,
    tenant_id: str,
) -> dict[str, int | str]:
    """Progress eligible students while preserving the existing lifecycle rules."""

    _ = ctx
    parsed_run_id = uuid.UUID(run_id)
    parsed_tenant_id = uuid.UUID(tenant_id)
    failure_exception: Exception | None = None

    logger.info(
        "session_progression.started",
        extra={"run_id": run_id, "tenant_id": tenant_id},
    )

    async with AsyncSessionLocal() as db:
        try:
            result = await SessionClosureService.process_progression_run(
                db,
                tenant_id=parsed_tenant_id,
                run_id=parsed_run_id,
            )
        except Exception as exc:
            failure_exception = exc
            await db.rollback()
        else:
            logger.info(
                "session_progression.completed",
                extra={"run_id": run_id, "tenant_id": tenant_id, **result},
            )
            return result

    if failure_exception is None:
        raise RuntimeError("Session progression failed without an exception.")

    logger.exception(
        "session_progression.failed",
        exc_info=(
            type(failure_exception),
            failure_exception,
            failure_exception.__traceback__,
        ),
        extra={"run_id": run_id, "tenant_id": tenant_id},
    )

    async with AsyncSessionLocal() as failure_db:
        run = await StudentProgressionRepository.get_run_by_id(
            failure_db,
            parsed_tenant_id,
            parsed_run_id,
            lock=True,
        )
        if run is not None and run.status != StudentProgressionRunStatus.COMPLETED:
            run.status = StudentProgressionRunStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.failed_students = max(run.failed_students, 1)
            run.failure_reason = str(failure_exception)[:1000]
            await StudentProgressionRepository.save_run(failure_db, run)
            if run.initiated_by_admin_id is not None:
                await SessionClosureService._broadcast(
                    failure_db,
                    tenant_id=parsed_tenant_id,
                    actor_id=run.initiated_by_admin_id,
                    title="Academic session progression failed",
                    body=(
                        "The session remains in closing and academic writes remain paused. "
                        f"Review the progression status before retrying. Reason: {str(failure_exception)[:500]}"
                    ),
                    priority="urgent",
                )
            await failure_db.commit()
            await RealtimePublisher.publish_deferred_after_commit(failure_db)
            await SessionClosureService._publish_progression_event(
                run=run,
                event_type="academic_session.progression.failed",
            )
        raise failure_exception


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize optional monitoring for this worker process."""

    _ = ctx

    initialize_sentry(
        service="worker-heavy",
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Dispose the worker's database and monitoring resources."""

    _ = ctx

    try:
        await engine.dispose()
    finally:
        await flush_sentry()


class WorkerSettings:
    """Settings for serialized database-heavy jobs."""

    redis_settings = get_arq_redis_settings()
    queue_name = HEAVY_QUEUE_NAME
    functions = [
        process_bulk_import_job,
        process_session_progression_job,
        process_cbt_result_rollback_job,
    ]

    cron_jobs = [cron(recover_cbt_result_rollbacks, minute=set(range(0, 60, 2)), unique=True)]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1
    job_timeout = 3600
    keep_result = 3600
    max_tries = 3
    health_check_key = f"{HEAVY_QUEUE_NAME}:health"
