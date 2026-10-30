"""Asynchronous CBT AI job admission and ownership tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.cbt.ai.idempotency.models import AI_IDEMPOTENCY_IN_PROGRESS
from app.modules.cbt.ai.idempotency.service import CBTAIIdempotentAuthoringService
from app.modules.cbt.ai.job_service import CBTAIJobService
from app.modules.cbt.ai.schemas import AIGenerateQuestionsRequest
from app.modules.cbt.ai.service import CBTAIService


def _request():
    return AIGenerateQuestionsRequest(
        subject="Biology",
        academic_level="SS2",
        generation_prompt="Set questions about human digestion.",
        question_count=15,
        visual_mode="auto",
    )


@pytest.mark.asyncio
async def test_submitted_ai_job_reserves_once_and_enqueues_once(monkeypatch):
    from app.modules.cbt.ai import job_service

    tenant_id, actor_id, record_id, reservation_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    actor = SimpleNamespace(tenant_id=tenant_id)
    record = SimpleNamespace(
        id=record_id,
        status=AI_IDEMPOTENCY_IN_PROGRESS,
        request_hash=CBTAIIdempotentAuthoringService._request_hash(_request()),
    )
    monkeypatch.setattr(
        CBTAIService, "_resolve_quota_actor",
        lambda actor: (SimpleNamespace(value="teacher"), actor_id),
    )
    claim = AsyncMock(return_value=(record, True))
    monkeypatch.setattr(CBTAIIdempotentAuthoringService, "_claim", claim)
    monkeypatch.setattr(
        CBTAIIdempotentAuthoringService, "_attach_reservation", AsyncMock()
    )
    from app.modules.cbt.ai.quota.service import AIQuotaService
    reserve = AsyncMock(return_value=SimpleNamespace(id=reservation_id))
    monkeypatch.setattr(AIQuotaService, "reserve_credits", reserve)
    queue = AsyncMock(return_value=True)
    monkeypatch.setattr(job_service, "enqueue_cbt_ai_generation_job", queue)
    monkeypatch.setattr(job_service.AIJobProgressCache, "set", AsyncMock())

    submitted = await CBTAIJobService.submit(
        object(), actor=actor, request=_request(), idempotency_key="once"
    )
    assert submitted.job_id == record_id
    assert submitted.status == "queued"
    assert reserve.await_args.kwargs["credits"] == 15
    assert queue.await_count == 1

    claim.return_value = (record, False)
    monkeypatch.setattr(job_service.AIJobProgressCache, "get", AsyncMock(return_value="queued"))
    repeated = await CBTAIJobService.submit(
        object(), actor=actor, request=_request(), idempotency_key="once"
    )
    assert repeated.job_id == record_id
    assert queue.await_count == 1
    assert reserve.await_count == 1


@pytest.mark.asyncio
async def test_job_lookup_rejects_other_actor(monkeypatch):
    from app.modules.cbt.ai.idempotency.repository import AIIdempotencyRepository

    tenant_id, actor_id = uuid4(), uuid4()
    monkeypatch.setattr(
        CBTAIService, "_resolve_quota_actor",
        lambda actor: (SimpleNamespace(value="teacher"), actor_id),
    )
    monkeypatch.setattr(
        AIIdempotencyRepository,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            tenant_id=tenant_id,
            actor_type="teacher",
            actor_id=uuid4(),
            operation="generate_job",
        )),
    )
    with pytest.raises(NotFoundException):
        await CBTAIJobService.status(
            object(), actor=SimpleNamespace(tenant_id=tenant_id), job_id=uuid4()
        )


@pytest.mark.asyncio
async def test_pending_job_result_does_not_settle_credits(monkeypatch):
    from app.modules.cbt.ai import job_service

    record = SimpleNamespace(
        status=AI_IDEMPOTENCY_IN_PROGRESS,
        reservation_id=uuid4(),
        id=uuid4(),
    )
    monkeypatch.setattr(
        CBTAIJobService, "_owned_record", AsyncMock(return_value=record)
    )
    monkeypatch.setattr(
        job_service.AICreditReservationRepository,
        "get_by_tenant_and_id",
        AsyncMock(return_value=SimpleNamespace(status="pending")),
    )
    reconcile = AsyncMock()
    monkeypatch.setattr(
        job_service.CBTAIIdempotentAuthoringService,
        "_resolve_existing",
        reconcile,
    )
    with pytest.raises(ConflictException):
        await CBTAIJobService.result(
            object(),
            actor=SimpleNamespace(tenant_id=uuid4()),
            job_id=record.id,
        )
    reconcile.assert_not_awaited()
