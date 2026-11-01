"""Regression tests for TMA's additive access to CBT AI services."""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.core.exceptions import BadRequestException
from app.modules.cbt.ai.schemas import AIQuestionOptionResponse, AIQuestionResponse
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.teachers.models import TeacherMembership
from app.modules.tma.ai_actor import to_existing_ai_actor
from app.modules.tma.ai_schemas import TMAAIGenerateRequest
from app.modules.tma.ai_service import TMAAIService


def _id():
    return uuid.uuid4()


def _admin():
    return TenantAdmin(id=_id(), tenant_id=_id())


def _preview(*, question_type="single_choice", image=None):
    return AIQuestionResponse(
        question_type=question_type,
        prompt="Which answer is correct?",
        image=image,
        options=[
            AIQuestionOptionResponse(text=str(i), is_correct=i == 2)
            for i in range(1, 5)
        ],
    )


def test_cloud_staff_maps_to_existing_quota_actor_without_server_credentials() -> None:
    admin = _admin()
    adapted = to_existing_ai_actor(admin)
    assert adapted.role == "admin"
    assert adapted.tenant_id == admin.tenant_id
    assert adapted.actor_id == admin.id
    assert adapted.membership_id is None

    teacher = TeacherMembership(
        id=_id(), tenant_id=_id(), teacher_account_id=_id(),
    )
    adapted = to_existing_ai_actor(teacher)
    assert adapted.role == "teacher"
    assert adapted.tenant_id == teacher.tenant_id
    assert adapted.membership_id == teacher.id


@pytest.mark.asyncio
async def test_tma_generation_reuses_cbt_idempotent_authoring(monkeypatch) -> None:
    from app.modules.tma import ai_service as mod

    actor = _admin()
    assignment_id = _id()
    monkeypatch.setattr(
        mod.TMAAIService, "_context",
        AsyncMock(return_value=(
            SimpleNamespace(id=assignment_id),
            SimpleNamespace(id=_id()), "Mathematics", "JSS3",
        )),
    )
    run = AsyncMock(return_value=object())
    monkeypatch.setattr(
        mod.CBTAIIdempotentAuthoringService, "generate_questions", run,
    )
    payload = TMAAIGenerateRequest(
        generation_prompt="Algebra", question_count=10,
        visual_mode="text_only",
    )
    response = await TMAAIService.generate(
        AsyncMock(), actor=actor, assignment_id=assignment_id,
        payload=payload, idempotency_key="request-123",
    )
    assert response is run.return_value
    args = run.await_args.kwargs
    assert args["request"].question_count == 10
    assert args["request"].question_type_counts == {"single_choice": 10}
    assert args["request"].subject == "Mathematics"
    assert args["actor"].tenant_id == actor.tenant_id
    assert len(args["idempotency_key"]) == 64

    await TMAAIService.generate(
        AsyncMock(), actor=actor, assignment_id=_id(),
        payload=payload, idempotency_key="request-123",
    )
    assert run.await_args.kwargs["idempotency_key"] != args["idempotency_key"]


@pytest.mark.asyncio
async def test_question_import_saves_into_existing_tma_question_service(monkeypatch) -> None:
    from app.modules.tma import ai_service as mod

    actor = _admin()
    assignment, revision = SimpleNamespace(id=_id()), SimpleNamespace(id=_id())
    monkeypatch.setattr(
        mod.TMAAIService, "_context",
        AsyncMock(return_value=(assignment, revision, "Biology", "JSS2")),
    )
    monkeypatch.setattr(
        mod.TMAQuestionRepository, "list_for_revision_with_options",
        AsyncMock(return_value=[(SimpleNamespace(position=3), [])]),
    )
    save = AsyncMock(return_value=SimpleNamespace(id=_id()))
    monkeypatch.setattr(mod.TMAQuestionService, "add_question", save)
    await TMAAIService.import_question(
        AsyncMock(), actor=actor, assignment_id=assignment.id, question=_preview(),
    )
    payload = save.await_args.kwargs["payload"]
    assert payload.position == 4
    assert len(payload.options) == 4
    assert sum(option.is_correct for option in payload.options) == 1
    assert payload.question_text == "Which answer is correct?"


def test_tma_rejects_incompatible_question_types_before_storage() -> None:
    with pytest.raises(BadRequestException, match="single"):
        TMAAIService._validate_preview(_preview(question_type="multiple_choice"))
    incomplete = _preview()
    incomplete.options = incomplete.options[:3]
    with pytest.raises(BadRequestException, match="four"):
        TMAAIService._validate_preview(incomplete)


@pytest.mark.asyncio
async def test_import_persists_generated_image_via_existing_tma_r2_service(monkeypatch) -> None:
    from app.modules.tma import ai_service as mod
    from app.modules.cbt.ai.schemas import AIResolvedImageResponse

    raw_buffer = io.BytesIO()
    Image.new("RGB", (24, 24)).save(raw_buffer, "PNG")
    data = raw_buffer.getvalue()
    image = AIResolvedImageResponse(
        source="generated", content_type="image/png",
        data_base64=base64.b64encode(data).decode(),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    actor = _admin()
    assignment, revision = SimpleNamespace(id=_id()), SimpleNamespace(id=_id())
    monkeypatch.setattr(
        mod.TMAAIService, "_context",
        AsyncMock(return_value=(assignment, revision, "Math", "JSS3")),
    )
    upload = AsyncMock(return_value=SimpleNamespace(id=_id()))
    monkeypatch.setattr(mod.TMAMediaService, "upload_image", upload)
    monkeypatch.setattr(
        mod.TMAQuestionRepository, "list_for_revision_with_options",
        AsyncMock(return_value=[]),
    )
    save = AsyncMock(return_value=SimpleNamespace(id=_id()))
    monkeypatch.setattr(mod.TMAQuestionService, "add_question", save)
    await TMAAIService.import_question(
        AsyncMock(), actor=actor, assignment_id=assignment.id,
        question=_preview(image=image),
    )
    assert upload.await_count == 1
    assert save.await_args.kwargs["payload"].image_asset_id == upload.return_value.id


def test_additive_ai_routes_do_not_change_cbt_server_authentication() -> None:
    from app.modules.cbt.ai.router import router as cbt_router
    from app.modules.cbt.ai.cloud_router import router as cloud_router
    from app.modules.tma.ai_router import router as tma_router

    cbt = {route.path for route in cbt_router.routes}
    cloud = {route.path for route in cloud_router.routes}
    tma = {route.path for route in tma_router.routes}
    assert "/ai/questions/generate" in cbt
    assert "/ai/teacher/purchases/checkout" in cbt
    assert "/ai/teacher/purchases" in cbt
    assert "/ai/quota" in cloud
    assert "/ai/teacher/purchases/checkout" in cloud
    assert "/tma/assignments/{assignment_id}/ai/questions/generate" in tma
