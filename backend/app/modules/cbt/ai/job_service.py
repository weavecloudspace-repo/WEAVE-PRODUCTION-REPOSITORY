"""Authenticated asynchronous CBT AI generation jobs.

Reuse the existing durable idempotency record, credit reservations, and
compressed result replay. A job has no candidate-facing partial results.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.core.queue.arq import enqueue_cbt_ai_generation_job
from app.modules.cbt.ai.idempotency.cache import AIReplayCache
from app.modules.cbt.ai.idempotency.models import (
    AI_IDEMPOTENCY_FAILED,
    AI_IDEMPOTENCY_IN_PROGRESS,
    AI_IDEMPOTENCY_SUCCEEDED,
    AIIdempotencyRecord,
)
from app.modules.cbt.ai.idempotency.repository import AIIdempotencyRepository
from app.modules.cbt.ai.idempotency.service import CBTAIIdempotentAuthoringService
from app.modules.cbt.ai.job_progress import AIJobProgressCache
from app.modules.cbt.ai.quota.service import AIQuotaService
from app.modules.cbt.ai.schemas import (
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIGenerationJobStatusResponse,
)
from app.modules.cbt.ai.service import CBTAIService
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor


class CBTAIJobService:
    OPERATION = "generate_job"

    @classmethod
    async def submit(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIGenerateQuestionsRequest,
        idempotency_key: str,
    ) -> AIGenerationJobStatusResponse:
        actor_type, actor_id = CBTAIService._resolve_quota_actor(actor)
        service = CBTAIIdempotentAuthoringService
        request_hash = service._request_hash(request)
        record, created = await service._claim(
            db,
            actor=actor,
            actor_type=actor_type.value,
            actor_id=actor_id,
            operation=cls.OPERATION,
            idempotency_key=service._normalize_key(idempotency_key),
            request_hash=request_hash,
        )
        if not created:
            if record.request_hash != request_hash:
                raise ConflictException(
                    "Idempotency key belongs to a different generation request.",
                    payload={"code": "IDEMPOTENCY_KEY_REUSED"},
                )
            return await cls._status_for_record(record)

        reservation = None
        try:
            reservation = await AIQuotaService.reserve_credits(
                db,
                tenant_id=actor.tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                credits=request.question_count * CBTAIService.CREDITS_PER_GENERATED_QUESTION,
            )
            await service._attach_reservation(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                reservation_id=reservation.id,
            )
            # Status and reservation are durable before enqueue. This prevents
            # double-claims when a client retries after a dropped HTTP response.
            await AIJobProgressCache.set(record.id, "queued")
            enqueued = await enqueue_cbt_ai_generation_job(
                job_id=str(record.id),
                tenant_id=str(actor.tenant_id),
                request_payload=request.model_dump(mode="json", exclude_none=True),
            )
            if not enqueued:
                raise RuntimeError("Duplicate or unavailable CBT AI queue job.")
        except Exception:
            if reservation is not None:
                await CBTAIService._release_reservation_safely(
                    db,
                    tenant_id=actor.tenant_id,
                    reservation_id=reservation.id,
                )
            await service._mark_failed(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                code="AI_ENQUEUE_FAILED",
                detail="The AI generation job could not be queued. No credits were charged.",
            )
            raise
        return AIGenerationJobStatusResponse(
            job_id=record.id, status="queued", result_available=False
        )

    @classmethod
    async def _owned_record(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        job_id: UUID,
    ) -> AIIdempotencyRecord:
        actor_type, actor_id = CBTAIService._resolve_quota_actor(actor)
        record = await AIIdempotencyRepository.get_by_id(
            db,
            tenant_id=actor.tenant_id,
            record_id=job_id,
        )
        if (
            record is None
            or record.actor_type != actor_type.value
            or record.actor_id != actor_id
            or record.operation != cls.OPERATION
        ):
            raise NotFoundException("AI generation job not found.")
        return record

    @classmethod
    async def _status_for_record(
        cls, record: AIIdempotencyRecord
    ) -> AIGenerationJobStatusResponse:
        if record.status == AI_IDEMPOTENCY_SUCCEEDED:
            return AIGenerationJobStatusResponse(
                job_id=record.id, status="completed", result_available=True
            )
        if record.status == AI_IDEMPOTENCY_FAILED:
            return AIGenerationJobStatusResponse(
                job_id=record.id,
                status="failed",
                failure_code=record.failure_code,
            )
        stage = await AIJobProgressCache.get(record.id)
        return AIGenerationJobStatusResponse(
            job_id=record.id,
            status=stage or "queued",
            result_available=False,
        )

    @classmethod
    async def status(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        job_id: UUID,
    ) -> AIGenerationJobStatusResponse:
        record = await cls._owned_record(db, actor=actor, job_id=job_id)
        return await cls._status_for_record(record)

    @classmethod
    async def result(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        job_id: UUID,
    ) -> AIGenerateQuestionsResponse:
        record = await cls._owned_record(db, actor=actor, job_id=job_id)
        if record.status == AI_IDEMPOTENCY_IN_PROGRESS:
            # Existing recovery handles the narrow post-settlement crash
            # window without creating another billable generation.
            return await CBTAIIdempotentAuthoringService._resolve_existing(
                db,
                record=record,
                request_hash=record.request_hash,
                response_model=AIGenerateQuestionsResponse,
            )
        if record.status == AI_IDEMPOTENCY_FAILED:
            raise ConflictException(
                "AI generation failed. No successful-batch credits were charged.",
                payload={"code": record.failure_code or "AI_GENERATION_FAILED"},
            )
        body = await AIReplayCache.load(record.id)
        if body is None:
            raise ConflictException(
                "Completed result has expired. Do not retry with this job ID.",
                payload={"code": "AI_RESULT_EXPIRED"},
            )
        return AIGenerateQuestionsResponse.model_validate(body)
