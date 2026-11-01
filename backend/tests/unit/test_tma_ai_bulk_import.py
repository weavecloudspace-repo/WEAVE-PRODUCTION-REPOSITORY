"""Atomic, tenant-scoped and retry-safe import of browser-reviewed AI batches."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestException, ConflictException
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma import ai_service as mod
from app.modules.tma.ai_schemas import TMAAIBulkImportRequest


@pytest.fixture
def context(monkeypatch):
    actor = TenantAdmin(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    assignment = SimpleNamespace(id=uuid.uuid4(), current_revision_number=1)
    payload = TMAAIBulkImportRequest(
        draft_id=uuid.uuid4(),
        revision_number=1,
        questions=[
            {
                "question_type": "single_choice",
                "prompt": "Which answer?",
                "options": [{"text": str(i), "is_correct": i == 4} for i in range(1, 5)],
            }
        ]
        * 2,
    )
    context = AsyncMock(return_value=(assignment, SimpleNamespace()))
    lookup = AsyncMock(return_value=None)
    create = AsyncMock()
    save = AsyncMock()
    storage = SimpleNamespace(delete_object=AsyncMock())
    monkeypatch.setattr(mod.TMAQuestionService, "_draft_context", context)
    monkeypatch.setattr(mod.AIIdempotencyRepository, "get_by_scope", lookup)
    monkeypatch.setattr(mod.AIIdempotencyRepository, "create", create)
    monkeypatch.setattr(mod.TMAAIService, "import_question", save)
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    monkeypatch.setattr(mod, "flush_cache_invalidation_events", AsyncMock())
    return SimpleNamespace(
        actor=actor,
        assignment=assignment,
        payload=payload,
        context=context,
        lookup=lookup,
        create=create,
        save=save,
        storage=storage,
        db=AsyncMock(),
    )


async def run(c):
    return await mod.TMAAIService.import_questions(
        c.db, actor=c.actor, assignment_id=c.assignment.id, payload=c.payload
    )


@pytest.mark.asyncio
async def test_batch_commits_once_and_replays_without_duplicate_questions(context):
    c = context
    assert await run(c) == 2
    c.context.assert_awaited_once_with(c.db, actor=c.actor, assignment_id=c.assignment.id)
    assert c.save.await_count == 2
    assert all(call.kwargs["commit"] is False for call in c.save.await_args_list)
    c.db.commit.assert_awaited_once()
    record = c.create.await_args.args[1]
    assert record.tenant_id == c.actor.tenant_id
    assert record.actor_id == c.actor.id
    assert record.operation == "tma_import"
    assert record.status == "succeeded"
    c.lookup.return_value = record
    c.save.reset_mock()
    assert await run(c) == 2
    c.save.assert_not_awaited()
    c.db.commit.assert_awaited_once()
    assert c.lookup.await_args.kwargs["tenant_id"] == c.actor.tenant_id
    assert c.lookup.await_args.kwargs["lock"] is True


@pytest.mark.asyncio
async def test_reusing_draft_with_changed_payload_is_rejected(context):
    c = context
    await run(c)
    c.lookup.return_value = c.create.await_args.args[1]
    c.payload.questions[0].prompt = "Changed"
    c.save.reset_mock()
    with pytest.raises(ConflictException, match="different questions"):
        await run(c)
    c.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_question_rolls_back_all_rows_and_cleans_uploaded_media(context):
    c = context

    async def save(*args, **kwargs):
        kwargs["uploaded_keys"].append("private-object")
        raise RuntimeError("Import failed")

    c.save.side_effect = save
    with pytest.raises(RuntimeError):
        await run(c)
    c.db.rollback.assert_awaited_once()
    c.db.commit.assert_not_awaited()
    c.create.assert_not_awaited()
    c.storage.delete_object.assert_awaited_once_with(object_key="private-object")


@pytest.mark.asyncio
async def test_validation_checks_entire_batch_before_writes(context):
    c = context
    c.payload.questions[-1].options = []
    with pytest.raises(BadRequestException):
        await run(c)
    c.save.assert_not_awaited()
    c.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_revision_cannot_be_imported(context):
    c = context
    c.assignment.current_revision_number = 2
    with pytest.raises(ConflictException, match="older assignment revision"):
        await run(c)
    c.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_commit_does_not_delete_potentially_live_media(context):
    c = context

    async def save(*args, **kwargs):
        kwargs["uploaded_keys"].append("private-object")

    c.save.side_effect = save
    c.db.commit.side_effect = RuntimeError("Connection lost during commit")
    with pytest.raises(RuntimeError):
        await run(c)
    c.storage.delete_object.assert_not_awaited()
