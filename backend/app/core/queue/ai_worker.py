"""Dedicated, rate-limited AI authoring worker.

Run with: arq app.core.queue.ai_worker.WorkerSettings
Only this worker consumes the CBT AI queue, so image workloads cannot starve
attendance, email, progression or other school background tasks.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import app.models  # noqa: F401

from app.config.database import AsyncSessionLocal, engine  # noqa: E402
from app.config.logging import get_logger  # noqa: E402
from app.config.sentry import flush_sentry, initialize_sentry  # noqa: E402
from app.core.queue.arq import AI_QUEUE_NAME, get_arq_redis_settings  # noqa: E402
from app.core.queue.sentry import capture_worker_exceptions  # noqa: E402
from app.modules.cbt.ai.idempotency.cache import AIReplayCache  # noqa: E402
from app.modules.cbt.ai.idempotency.models import (  # noqa: E402
    AI_IDEMPOTENCY_IN_PROGRESS,
    AI_IDEMPOTENCY_SUCCEEDED,
)
from app.modules.cbt.ai.idempotency.repository import AIIdempotencyRepository  # noqa: E402
from app.modules.cbt.ai.idempotency.service import (  # noqa: E402
    CBTAIIdempotentAuthoringService,
)
from app.modules.cbt.ai.job_progress import AIJobProgressCache  # noqa: E402
from app.modules.cbt.ai.quota.service import AIQuotaService  # noqa: E402
from app.modules.cbt.ai.schemas import (  # noqa: E402
    AICreditChargeResponse,
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
)
from app.modules.cbt.ai.service import CBTAIService  # noqa: E402

logger = get_logger(__name__)


@capture_worker_exceptions(queue_name=AI_QUEUE_NAME)
async def process_cbt_ai_generation_job(
    ctx: dict[str, Any], job_id: str, tenant_id: str, request_payload: dict
) -> dict[str, str]:
    del ctx
    record_id = UUID(job_id)
    tenant = UUID(tenant_id)
    idem = CBTAIIdempotentAuthoringService
    reserved_id: UUID | None = None
    settled = False

    async with AsyncSessionLocal() as db:
        try:
            record = await AIIdempotencyRepository.get_by_id(
                db, tenant_id=tenant, record_id=record_id
            )
            if record is None or record.operation != "generate_job":
                raise RuntimeError("Unknown CBT AI job")
            if record.status == AI_IDEMPOTENCY_SUCCEEDED:
                return {"status": "completed", "job_id": job_id}
            if record.status != AI_IDEMPOTENCY_IN_PROGRESS:
                return {"status": "ignored", "job_id": job_id}
            if record.reservation_id is None:
                raise RuntimeError("AI job is missing reserved credits.")
            reserved_id = record.reservation_id
            request = AIGenerateQuestionsRequest.model_validate(request_payload)
            if record.request_hash != idem._request_hash(request):
                raise RuntimeError("AI job request hash mismatch.")

            logger.info("cbt.ai.job.started", extra={"ai_job_id": job_id})
            service = CBTAIService._build_authoring_service()

            async def progress(stage: str) -> None:
                await AIJobProgressCache.set(record_id, stage)

            output = await service.generate_questions(
                request=request.model_dump(mode="json", exclude_none=True),
                expected_count=request.question_count,
                expected_type_counts=request.question_type_counts,
                progress_callback=progress,
            )
            charged = len(output.questions) * CBTAIService.CREDITS_PER_GENERATED_QUESTION
            provisional = AIGenerateQuestionsResponse(
                questions=[
                    CBTAIService._build_question_response(question)
                    for question in output.questions
                ],
                repaired=output.repaired,
                charge=AICreditChargeResponse(
                    reservation_id=reserved_id,
                    credits_charged=charged,
                    credits_released=0,
                ),
            )
            # Replay must be stored BEFORE settlement. All images are present
            # or the entire generation fails without settling any credits.
            await AIReplayCache.store(
                record_id, provisional.model_dump(mode="json")
            )
            settlement = await AIQuotaService.settle_reservation(
                db,
                tenant_id=tenant,
                reservation_id=reserved_id,
                actual_credits=charged,
            )
            settled = True
            await idem._mark_succeeded(
                db,
                tenant_id=tenant,
                record_id=record_id,
                credits_charged=settlement.total_settled_credits,
                credits_released=settlement.released_credits,
            )
            final = CBTAIService._build_generation_response(
                result=output,
                settlement=settlement,
            )
            try:
                await AIReplayCache.store(record_id, final.model_dump(mode="json"))
            except Exception:
                # A recoverable pre-settlement replay body already exists.
                logger.warning(
                    "cbt.ai.job.final_replay_refresh_failed",
                    extra={"ai_job_id": job_id},
                )
            logger.info("cbt.ai.job.completed", extra={"ai_job_id": job_id})
            return {"status": "completed", "job_id": job_id}
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "cbt.ai.job.failed",
                extra={"ai_job_id": job_id, "ai_error_type": type(exc).__name__},
            )
            if not settled:
                if reserved_id is not None:
                    await CBTAIService._release_reservation_safely(
                        db, tenant_id=tenant, reservation_id=reserved_id
                    )
                await AIReplayCache.delete(record_id)
                await idem._mark_failed(
                    db,
                    tenant_id=tenant,
                    record_id=record_id,
                    code="AI_GENERATION_FAILED",
                    detail=(
                        "Question or Qwen image generation failed. "
                        "No successful-batch credits were charged."
                    ),
                )
            raise


async def startup(ctx: dict[str, Any]) -> None:
    del ctx
    initialize_sentry(service="worker-cbt-ai")


async def shutdown(ctx: dict[str, Any]) -> None:
    del ctx
    try:
        await engine.dispose()
    finally:
        await flush_sentry()


class WorkerSettings:
    redis_settings = get_arq_redis_settings()
    queue_name = AI_QUEUE_NAME
    functions = [process_cbt_ai_generation_job]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    max_tries = 1
    job_timeout = 1200
    keep_result = 3600
    health_check_key = f"{AI_QUEUE_NAME}:health"
