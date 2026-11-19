"""Regression tests for CBT AI idempotency cleanup after quota rollback."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.core.exceptions import ConflictException
from app.modules.cbt.ai.authoring.schemas import AISingleChoiceQuestionDraft
from app.modules.cbt.ai.idempotency.cache import AIReplayCache
from app.modules.cbt.ai.idempotency.service import CBTAIIdempotentAuthoringService
from app.modules.cbt.ai.quota.service import AIInsufficientCreditsError, AIQuotaService
from app.modules.cbt.ai.schemas import AIGenerateQuestionsRequest, AIRegenerateQuestionRequest
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["generate", "regenerate"])
async def test_quota_rollback_does_not_load_expired_idempotency_record(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """A quota rollback must not turn an insufficient-credit response into HTTP 500."""

    class RollbackSensitiveRecord:
        def __init__(self) -> None:
            self.raw_id = uuid4()
            self.status = "in_progress"
            self.expired = False

        @property
        def id(self):
            if self.expired:
                raise MissingGreenlet("Accessing an expired ORM attribute")
            return self.raw_id

    record = RollbackSensitiveRecord()
    actor = AuthenticatedCBTActor(
        authorization_id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        membership_id=uuid4(),
        role="teacher",
    )
    common = {
        "subject": "Mathematics",
        "academic_level": "SS2",
        "generation_prompt": "Arithmetic",
    }
    if operation == "generate":
        request = AIGenerateQuestionsRequest(
            **common,
            question_count=2,
            question_type_counts={"single_choice": 2},
        )
    else:
        existing = AISingleChoiceQuestionDraft(
            question_type="single_choice",
            prompt="What is 2 + 2?",
            options=[
                {"text": "4", "is_correct": True},
                {"text": "5", "is_correct": False},
                {"text": "6", "is_correct": False},
                {"text": "7", "is_correct": False},
            ],
        )
        request = AIRegenerateQuestionRequest(
            **common,
            existing_question=existing.model_dump(),
            instruction="Clarify the wording",
        )

    service = CBTAIIdempotentAuthoringService
    monkeypatch.setattr(service, "_claim", AsyncMock(return_value=(record, True)))

    async def insufficient_credits(*args, **kwargs):
        # The actual quota service rolls back before propagating this exception.
        record.expired = True
        raise AIInsufficientCreditsError(requested_credits=2, available_credits=0)

    monkeypatch.setattr(AIQuotaService, "reserve_credits", insufficient_credits)
    delete_replay = AsyncMock()
    mark_failed = AsyncMock()
    monkeypatch.setattr(AIReplayCache, "delete", delete_replay)
    monkeypatch.setattr(service, "_mark_failed", mark_failed)

    method = service.generate_questions if operation == "generate" else service.regenerate_question
    with pytest.raises(ConflictException) as caught:
        await method(AsyncMock(), actor=actor, request=request, idempotency_key="low-credits")

    assert caught.value.status_code == 409
    assert caught.value.payload["code"] == "AI_INSUFFICIENT_CREDITS"
    delete_replay.assert_awaited_once_with(record.raw_id)
    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.kwargs["record_id"] == record.raw_id
    assert mark_failed.await_args.kwargs["code"] == "AI_INSUFFICIENT_CREDITS"
