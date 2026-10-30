"""Idempotent orchestration for credit-consuming CBT AI authoring calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import TypeVar
from uuid import UUID

from fastapi import status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor
from app.modules.cbt.ai.authoring.providers.base import ProviderStructuredOutputError
from app.modules.cbt.ai.idempotency.cache import (
    AI_REPLAY_TTL_SECONDS,
    AIReplayCache,
    AIReplayStoreUnavailableError,
)
from app.modules.cbt.ai.idempotency.models import (
    AI_IDEMPOTENCY_FAILED,
    AI_IDEMPOTENCY_IN_PROGRESS,
    AI_IDEMPOTENCY_SUCCEEDED,
    AIIdempotencyRecord,
)
from app.modules.cbt.ai.idempotency.repository import AIIdempotencyRepository
from app.modules.cbt.ai.quota.models import AICreditReservationStatus
from app.modules.cbt.ai.quota.repository import AICreditReservationRepository
from app.modules.cbt.ai.quota.service import AIQuotaService
from app.modules.cbt.ai.schemas import (
    AICreditChargeResponse,
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIRegenerateQuestionRequest,
    AIRegenerateQuestionResponse,
)
from app.modules.cbt.ai.service import CBTAIService

ResponseT = TypeVar("ResponseT", bound=BaseModel)
STALE_UNRESERVED_OPERATION_AFTER = timedelta(minutes=5)


class CBTAIIdempotentAuthoringService:
    """Execute one logical generation operation at most once per actor/key."""

    @staticmethod
    def _request_hash(request: BaseModel) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _normalize_key(idempotency_key: str) -> str:
        key = idempotency_key.strip()
        if not key:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key is required for AI authoring requests.",
            )
        if len(key) > 128:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key must not exceed 128 characters.",
            )
        return key

    @classmethod
    async def generate_questions(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIGenerateQuestionsRequest,
        idempotency_key: str,
    ) -> AIGenerateQuestionsResponse:
        return await cls._execute(
            db,
            actor=actor,
            request=request,
            idempotency_key=idempotency_key,
            operation="generate",
            response_model=AIGenerateQuestionsResponse,
        )

    @classmethod
    async def regenerate_question(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIRegenerateQuestionRequest,
        idempotency_key: str,
    ) -> AIRegenerateQuestionResponse:
        return await cls._execute(
            db,
            actor=actor,
            request=request,
            idempotency_key=idempotency_key,
            operation="regenerate",
            response_model=AIRegenerateQuestionResponse,
        )

    @classmethod
    async def _execute(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIGenerateQuestionsRequest | AIRegenerateQuestionRequest,
        idempotency_key: str,
        operation: str,
        response_model: type[ResponseT],
    ) -> ResponseT:
        key = cls._normalize_key(idempotency_key)
        request_hash = cls._request_hash(request)
        actor_type, quota_actor_id = CBTAIService._resolve_quota_actor(actor)

        record, created = await cls._claim(
            db,
            actor=actor,
            actor_type=actor_type.value,
            actor_id=quota_actor_id,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
        )
        if not created:
            return await cls._resolve_existing(
                db,
                record=record,
                request_hash=request_hash,
                response_model=response_model,
            )

        requested_credits = (
            request.question_count * CBTAIService.CREDITS_PER_GENERATED_QUESTION
            if isinstance(request, AIGenerateQuestionsRequest)
            else CBTAIService.CREDITS_PER_REGENERATED_QUESTION
        )
        reservation = None
        settled = False
        try:
            reservation = await AIQuotaService.reserve_credits(
                db,
                tenant_id=actor.tenant_id,
                actor_type=actor_type,
                actor_id=quota_actor_id,
                credits=requested_credits,
            )
            await cls._attach_reservation(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                reservation_id=reservation.id,
            )

            authoring_service = CBTAIService._build_authoring_service()
            if isinstance(request, AIGenerateQuestionsRequest):
                authoring_result = await authoring_service.generate_questions(
                    request=request.model_dump(exclude_none=True),
                    expected_count=request.question_count,
                    expected_type_counts=request.question_type_counts,
                )
                actual_credits = (
                    len(authoring_result.questions) * CBTAIService.CREDITS_PER_GENERATED_QUESTION
                )
                provisional = AIGenerateQuestionsResponse(
                    questions=[
                        CBTAIService._build_question_response(question)
                        for question in authoring_result.questions
                    ],
                    repaired=authoring_result.repaired,
                    charge=AICreditChargeResponse(
                        reservation_id=reservation.id,
                        credits_charged=actual_credits,
                        credits_released=reservation.total_reserved_credits - actual_credits,
                    ),
                )
            else:
                (
                    prepared_request,
                    reference_images,
                ) = await CBTAIService._prepare_regeneration_request(request)
                authoring_result = await authoring_service.regenerate_question(
                    request=prepared_request,
                    expected_question_type=request.existing_question.question_type,
                    reference_images=reference_images,
                )
                actual_credits = CBTAIService.CREDITS_PER_REGENERATED_QUESTION
                provisional = AIRegenerateQuestionResponse(
                    question=CBTAIService._build_question_response(authoring_result.question),
                    repaired=authoring_result.repaired,
                    charge=AICreditChargeResponse(
                        reservation_id=reservation.id,
                        credits_charged=actual_credits,
                        credits_released=reservation.total_reserved_credits - actual_credits,
                    ),
                )

            # The output must be replayable before credits are settled. A failed
            # replay write therefore releases the reservation instead of billing.
            await AIReplayCache.store(record.id, provisional.model_dump(mode="json"))

            settlement = await AIQuotaService.settle_reservation(
                db,
                tenant_id=actor.tenant_id,
                reservation_id=reservation.id,
                actual_credits=actual_credits,
            )
            settled = True
            final_response = (
                CBTAIService._build_generation_response(
                    result=authoring_result, settlement=settlement
                )
                if isinstance(request, AIGenerateQuestionsRequest)
                else CBTAIService._build_regeneration_response(
                    result=authoring_result, settlement=settlement
                )
            )
            await cls._mark_succeeded(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                credits_charged=settlement.total_settled_credits,
                credits_released=settlement.released_credits,
            )
            try:
                await AIReplayCache.store(record.id, final_response.model_dump(mode="json"))
            except AIReplayStoreUnavailableError:
                # The pre-settlement replay body already contains the same charge
                # projection, so a transient refresh failure does not invalidate it.
                pass
            return response_model.model_validate(final_response.model_dump(mode="json"))
        except AIReplayStoreUnavailableError as exc:
            if reservation is not None:
                await CBTAIService._release_reservation_safely(
                    db,
                    tenant_id=actor.tenant_id,
                    reservation_id=reservation.id,
                )
            await cls._mark_failed(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                code="AI_REPLAY_UNAVAILABLE",
                detail=str(exc),
            )
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "AI generation could not be safely recorded for recovery. "
                    "No credits were charged."
                ),
                payload={"code": "AI_REPLAY_UNAVAILABLE", "retryable": True},
            ) from exc
        except Exception as exc:
            # Once settlement commits, preserve both the in-progress metadata and
            # replay body. The next call with this key can repair the narrow crash
            # window from the settled reservation without charging again.
            if settled:
                raise
            if reservation is not None:
                await CBTAIService._release_reservation_safely(
                    db,
                    tenant_id=actor.tenant_id,
                    reservation_id=reservation.id,
                )
            await AIReplayCache.delete(record.id)
            await cls._mark_failed(
                db,
                tenant_id=actor.tenant_id,
                record_id=record.id,
                code="AI_AUTHORING_FAILED",
                detail=str(exc),
            )
            if isinstance(exc, ProviderStructuredOutputError):
                raise AppException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="AI returned an invalid question structure after repair. No credits were charged.",
                    payload={"code": "AI_INVALID_QUESTION_OUTPUT", "retryable": False},
                ) from exc
            raise

    @classmethod
    async def _claim(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        actor_type: str,
        actor_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[AIIdempotencyRecord, bool]:
        existing = await AIIdempotencyRepository.get_by_scope(
            db,
            tenant_id=actor.tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            await db.commit()
            return existing, False

        record = AIIdempotencyRecord(
            tenant_id=actor.tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=AI_IDEMPOTENCY_IN_PROGRESS,
        )
        try:
            await AIIdempotencyRepository.create(db, record)
            await db.commit()
            return record, True
        except IntegrityError:
            await db.rollback()
            existing = await AIIdempotencyRepository.get_by_scope(
                db,
                tenant_id=actor.tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            await db.commit()
            if existing is None:
                raise
            return existing, False

    @classmethod
    async def _resolve_existing(
        cls,
        db: AsyncSession,
        *,
        record: AIIdempotencyRecord,
        request_hash: str,
        response_model: type[ResponseT],
    ) -> ResponseT:
        if record.request_hash != request_hash:
            raise ConflictException(
                "Idempotency key was already used with a different AI request.",
                payload={"code": "IDEMPOTENCY_KEY_REUSED"},
            )

        if record.status == AI_IDEMPOTENCY_SUCCEEDED:
            payload = await cls._load_replay(record.id)
            if payload is None:
                raise ConflictException(
                    "This AI request already completed, but its replay result is no longer available.",
                    payload={
                        "code": "AI_RESULT_EXPIRED",
                        "requires_new_generation": True,
                    },
                )
            return response_model.model_validate(payload)

        if record.status == AI_IDEMPOTENCY_FAILED:
            raise ConflictException(
                record.failure_detail or "This AI request previously failed.",
                payload={
                    "code": record.failure_code or "AI_REQUEST_FAILED",
                    "requires_new_generation": True,
                },
            )

        if record.reservation_id is not None:
            reservation = await AICreditReservationRepository.get_by_tenant_and_id(
                db,
                tenant_id=record.tenant_id,
                reservation_id=record.reservation_id,
            )
            await db.commit()

            if reservation is not None and reservation.status == AICreditReservationStatus.PENDING:
                payload = await cls._load_replay(record.id)
                if payload is not None:
                    replay_response = response_model.model_validate(payload)
                    settlement = await AIQuotaService.settle_reservation(
                        db,
                        tenant_id=record.tenant_id,
                        reservation_id=reservation.id,
                        actual_credits=replay_response.charge.credits_charged,
                    )
                    payload["charge"] = {
                        "reservation_id": str(reservation.id),
                        "credits_charged": settlement.total_settled_credits,
                        "credits_released": settlement.released_credits,
                    }
                    await cls._mark_succeeded(
                        db,
                        tenant_id=record.tenant_id,
                        record_id=record.id,
                        credits_charged=settlement.total_settled_credits,
                        credits_released=settlement.released_credits,
                    )
                    try:
                        await AIReplayCache.store(record.id, payload)
                    except AIReplayStoreUnavailableError:
                        pass
                    return response_model.model_validate(payload)

            if reservation is not None and reservation.status == AICreditReservationStatus.SETTLED:
                payload = await cls._load_replay(record.id)
                if payload is None:
                    raise ConflictException(
                        "This AI request was charged successfully, but its replay result is unavailable.",
                        payload={"code": "AI_RESULT_LOST", "requires_support": True},
                    )
                charged = reservation.settled_free_credits + reservation.settled_extra_credits
                reserved = reservation.reserved_free_credits + reservation.reserved_extra_credits
                payload["charge"] = {
                    "reservation_id": str(reservation.id),
                    "credits_charged": charged,
                    "credits_released": reserved - charged,
                }
                await cls._mark_succeeded(
                    db,
                    tenant_id=record.tenant_id,
                    record_id=record.id,
                    credits_charged=charged,
                    credits_released=reserved - charged,
                )
                return response_model.model_validate(payload)
            if reservation is not None and reservation.status in {
                AICreditReservationStatus.RELEASED,
                AICreditReservationStatus.EXPIRED,
            }:
                await cls._mark_failed(
                    db,
                    tenant_id=record.tenant_id,
                    record_id=record.id,
                    code="AI_REQUEST_ABORTED",
                    detail="The prior AI operation ended without charging credits.",
                )
                raise ConflictException(
                    "The prior AI operation ended without charging credits. Start a new generation.",
                    payload={"code": "AI_REQUEST_ABORTED", "requires_new_generation": True},
                )
        elif datetime.now(timezone.utc) - record.created_at > STALE_UNRESERVED_OPERATION_AFTER:
            await cls._mark_failed(
                db,
                tenant_id=record.tenant_id,
                record_id=record.id,
                code="AI_REQUEST_ABORTED",
                detail="The prior AI operation stopped before reserving credits.",
            )
            raise ConflictException(
                "The prior AI operation stopped before reserving credits. Start a new generation.",
                payload={"code": "AI_REQUEST_ABORTED", "requires_new_generation": True},
            )

        raise ConflictException(
            "This AI request is already being processed.",
            payload={"code": "AI_REQUEST_IN_PROGRESS", "retryable": True},
        )

    @staticmethod
    async def _load_replay(record_id: UUID) -> dict | None:
        try:
            return await AIReplayCache.load(record_id)
        except AIReplayStoreUnavailableError as exc:
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI result recovery is temporarily unavailable. Retry the same operation.",
                payload={"code": "AI_REPLAY_UNAVAILABLE", "retryable": True},
            ) from exc

    @staticmethod
    async def _attach_reservation(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        record_id: UUID,
        reservation_id: UUID,
    ) -> None:
        record = await AIIdempotencyRepository.get_by_id(
            db, tenant_id=tenant_id, record_id=record_id, lock=True
        )
        if record is None:
            await db.rollback()
            raise RuntimeError("AI idempotency record disappeared during execution.")
        record.reservation_id = reservation_id
        await AIIdempotencyRepository.save(db, record)
        await db.commit()

    @staticmethod
    async def _mark_succeeded(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        record_id: UUID,
        credits_charged: int,
        credits_released: int,
    ) -> None:
        record = await AIIdempotencyRepository.get_by_id(
            db, tenant_id=tenant_id, record_id=record_id, lock=True
        )
        if record is None:
            await db.rollback()
            raise RuntimeError("AI idempotency record disappeared during settlement.")
        record.status = AI_IDEMPOTENCY_SUCCEEDED
        record.credits_charged = credits_charged
        record.credits_released = credits_released
        record.failure_code = None
        record.failure_detail = None
        record.completed_at = datetime.now(timezone.utc)
        record.replay_expires_at = record.completed_at + timedelta(seconds=AI_REPLAY_TTL_SECONDS)
        await AIIdempotencyRepository.save(db, record)
        await db.commit()

    @staticmethod
    async def _mark_failed(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        record_id: UUID,
        code: str,
        detail: str,
    ) -> None:
        try:
            record = await AIIdempotencyRepository.get_by_id(
                db, tenant_id=tenant_id, record_id=record_id, lock=True
            )
            if record is None or record.status == AI_IDEMPOTENCY_SUCCEEDED:
                await db.rollback()
                return
            record.status = AI_IDEMPOTENCY_FAILED
            record.failure_code = code[:64]
            record.failure_detail = detail[:4_000]
            record.completed_at = datetime.now(timezone.utc)
            await AIIdempotencyRepository.save(db, record)
            await db.commit()
        except Exception:
            await db.rollback()
