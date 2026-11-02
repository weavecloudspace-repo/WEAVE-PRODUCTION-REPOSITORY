from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException, ForbiddenException
from app.modules.cbt.ai.authoring.providers.base import ProviderUsage
from app.modules.cbt.ai.authoring.schemas import AISingleChoiceQuestionDraft
from app.modules.cbt.ai.authoring.service import (
    AuthoredQuestion,
    QuestionGenerationResult,
    QuestionRegenerationResult,
)
from app.modules.cbt.ai.quota.models import AIQuotaActorType
from app.modules.cbt.ai.quota.schemas import AICreditSettlementResponse
from app.modules.cbt.ai.quota.service import (
    AIInsufficientCreditsError,
    AIQuotaConflictError,
    AIQuotaService,
)
from app.modules.cbt.ai.schemas import (
    AIGenerateQuestionsRequest,
    AIRegenerateQuestionRequest,
)
from app.modules.cbt.ai.service import CBTAIService
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor


def _teacher_actor() -> AuthenticatedCBTActor:
    return AuthenticatedCBTActor(
        authorization_id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        membership_id=uuid4(),
        role="teacher",
    )


def _admin_actor() -> AuthenticatedCBTActor:
    return AuthenticatedCBTActor(
        authorization_id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        membership_id=None,
        role="admin",
    )


def _question(prompt: str) -> AISingleChoiceQuestionDraft:
    return AISingleChoiceQuestionDraft(
        question_type="single_choice",
        prompt=prompt,
        instruction=None,
        image=None,
        options=[
            {"text": "A", "image": None, "is_correct": True},
            {"text": "B", "image": None, "is_correct": False},
            {"text": "C", "image": None, "is_correct": False},
            {"text": "D", "image": None, "is_correct": False},
        ],
    )


def _settlement(reservation_id, *, charged: int) -> AICreditSettlementResponse:
    return AICreditSettlementResponse(
        reservation_id=reservation_id,
        settled_free_credits=charged,
        settled_extra_credits=0,
        total_settled_credits=charged,
        released_credits=0,
        settled_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_generation_reserves_by_question_count_authors_then_settles(monkeypatch) -> None:
    actor = _teacher_actor()
    reservation_id = uuid4()
    db = AsyncMock()
    reserve = AsyncMock(return_value=SimpleNamespace(id=reservation_id))
    settle = AsyncMock(return_value=_settlement(reservation_id, charged=2))
    release = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "reserve_credits", reserve)
    monkeypatch.setattr(AIQuotaService, "settle_reservation", settle)
    monkeypatch.setattr(AIQuotaService, "release_reservation", release)

    authoring = SimpleNamespace(
        generate_questions=AsyncMock(
            return_value=QuestionGenerationResult(
                questions=[
                    AuthoredQuestion(question=_question("Question one")),
                    AuthoredQuestion(question=_question("Question two")),
                ],
                usage=ProviderUsage(input_tokens=10, output_tokens=20),
                repaired=False,
            )
        )
    )
    monkeypatch.setattr(
        CBTAIService,
        "_build_authoring_service",
        staticmethod(lambda: authoring),
    )

    request = AIGenerateQuestionsRequest(
        subject="Mathematics",
        academic_level="SS2",
        generation_prompt="Generate questions about algebra.",
        question_count=2,
        question_type_counts={"single_choice": 2},
        visual_mode="text_only",
    )

    response = await CBTAIService.generate_questions(db, actor=actor, request=request)

    assert len(response.questions) == 2
    assert response.charge.credits_charged == 2
    reserve.assert_awaited_once()
    assert reserve.await_args.kwargs["tenant_id"] == actor.tenant_id
    assert reserve.await_args.kwargs["actor_type"] == AIQuotaActorType.TEACHER
    assert reserve.await_args.kwargs["actor_id"] == actor.membership_id
    assert reserve.await_args.kwargs["credits"] == 2
    authoring.generate_questions.assert_awaited_once()
    assert authoring.generate_questions.await_args.kwargs["expected_count"] == 2
    assert authoring.generate_questions.await_args.kwargs["expected_type_counts"] == {
        "single_choice": 2
    }
    assert authoring.generate_questions.await_args.kwargs["request"]["generation_prompt"] == (
        "Generate questions about algebra."
    )
    settle.assert_awaited_once()
    assert settle.await_args.kwargs["actual_credits"] == 2
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_provider_failure_releases_reservation(monkeypatch) -> None:
    actor = _teacher_actor()
    reservation_id = uuid4()
    reserve = AsyncMock(return_value=SimpleNamespace(id=reservation_id))
    release = AsyncMock()
    settle = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "reserve_credits", reserve)
    monkeypatch.setattr(AIQuotaService, "release_reservation", release)
    monkeypatch.setattr(AIQuotaService, "settle_reservation", settle)

    authoring = SimpleNamespace(
        generate_questions=AsyncMock(side_effect=RuntimeError("provider down"))
    )
    monkeypatch.setattr(
        CBTAIService,
        "_build_authoring_service",
        staticmethod(lambda: authoring),
    )

    request = AIGenerateQuestionsRequest(
        subject="Mathematics",
        academic_level="SS2",
        generation_prompt="Generate questions about algebra.",
        question_count=1,
        visual_mode="text_only",
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await CBTAIService.generate_questions(AsyncMock(), actor=actor, request=request)

    release.assert_awaited_once()
    assert release.await_args.kwargs["reservation_id"] == reservation_id
    settle.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_authoring_does_not_release_when_settlement_fails(monkeypatch) -> None:
    actor = _teacher_actor()
    reservation_id = uuid4()
    monkeypatch.setattr(
        AIQuotaService,
        "reserve_credits",
        AsyncMock(return_value=SimpleNamespace(id=reservation_id)),
    )
    monkeypatch.setattr(
        AIQuotaService,
        "settle_reservation",
        AsyncMock(side_effect=AIQuotaConflictError("settlement failed")),
    )
    release = AsyncMock()
    monkeypatch.setattr(AIQuotaService, "release_reservation", release)

    authoring = SimpleNamespace(
        generate_questions=AsyncMock(
            return_value=QuestionGenerationResult(
                questions=[AuthoredQuestion(question=_question("Completed question"))],
                usage=ProviderUsage(),
                repaired=False,
            )
        )
    )
    monkeypatch.setattr(
        CBTAIService,
        "_build_authoring_service",
        staticmethod(lambda: authoring),
    )

    request = AIGenerateQuestionsRequest(
        subject="Mathematics",
        academic_level="SS2",
        generation_prompt="Generate questions about algebra.",
        question_count=1,
        visual_mode="text_only",
    )

    with pytest.raises(ConflictException, match="settlement failed"):
        await CBTAIService.generate_questions(AsyncMock(), actor=actor, request=request)

    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_insufficient_generation_credits_are_translated(monkeypatch) -> None:
    actor = _teacher_actor()
    monkeypatch.setattr(
        AIQuotaService,
        "reserve_credits",
        AsyncMock(
            side_effect=AIInsufficientCreditsError(
                requested_credits=5,
                available_credits=2,
            )
        ),
    )
    request = AIGenerateQuestionsRequest(
        subject="Biology",
        academic_level="SS2",
        generation_prompt="Generate questions about cells.",
        question_count=5,
        visual_mode="text_only",
    )

    with pytest.raises(ConflictException) as exc_info:
        await CBTAIService.generate_questions(AsyncMock(), actor=actor, request=request)

    assert exc_info.value.payload["code"] == "AI_INSUFFICIENT_CREDITS"
    assert exc_info.value.payload["requested_credits"] == 5
    assert exc_info.value.payload["available_credits"] == 2


@pytest.mark.asyncio
async def test_regeneration_uses_one_admin_credit(monkeypatch) -> None:
    actor = _admin_actor()
    reservation_id = uuid4()
    reserve = AsyncMock(return_value=SimpleNamespace(id=reservation_id))
    settle = AsyncMock(return_value=_settlement(reservation_id, charged=1))
    monkeypatch.setattr(AIQuotaService, "reserve_credits", reserve)
    monkeypatch.setattr(AIQuotaService, "settle_reservation", settle)

    authoring = SimpleNamespace(
        regenerate_question=AsyncMock(
            return_value=QuestionRegenerationResult(
                question=AuthoredQuestion(question=_question("Regenerated")),
                usage=ProviderUsage(),
                repaired=True,
            )
        )
    )
    monkeypatch.setattr(
        CBTAIService,
        "_build_authoring_service",
        staticmethod(lambda: authoring),
    )

    request = AIRegenerateQuestionRequest(
        subject="Mathematics",
        academic_level="SS2",
        generation_prompt="Keep the question focused on algebra.",
        existing_question={
            "question_type": "single_choice",
            "prompt": "Old question",
            "instruction": None,
            "options": [
                {"text": "A", "is_correct": True},
                {"text": "B", "is_correct": False},
            ],
        },
        instruction="Make it clearer",
        visual_mode="text_only",
    )

    response = await CBTAIService.regenerate_question(AsyncMock(), actor=actor, request=request)

    assert response.repaired is True
    assert response.charge.credits_charged == 1
    assert reserve.await_args.kwargs["actor_type"] == AIQuotaActorType.TENANT_ADMIN
    assert reserve.await_args.kwargs["actor_id"] == actor.actor_id
    assert reserve.await_args.kwargs["credits"] == 1
    assert settle.await_args.kwargs["actual_credits"] == 1
    assert authoring.regenerate_question.await_args.kwargs["request"]["generation_prompt"] == (
        "Keep the question focused on algebra."
    )


@pytest.mark.asyncio
async def test_teacher_and_admin_quota_operations_enforce_role_boundary() -> None:
    with pytest.raises(ForbiddenException, match="only to teachers"):
        await CBTAIService.request_credits(
            AsyncMock(),
            actor=_admin_actor(),
            credits=10,
        )

    with pytest.raises(ForbiddenException, match="tenant administrators"):
        await CBTAIService.get_tenant_quota_summary(
            AsyncMock(),
            actor=_teacher_actor(),
        )
