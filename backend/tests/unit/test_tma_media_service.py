"""TMA media service tests: authorization, storage isolation and recovery."""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.media.models import MediaVisibility
from app.modules.tma.media_service import TMAMediaService
from app.modules.tma.models import TMAAssignmentStatus, TMAAttemptStatus


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _file() -> UploadFile:
    raw = io.BytesIO()
    Image.new("RGB", (20, 30)).save(raw, "PNG")
    return UploadFile(
        file=io.BytesIO(raw.getvalue()),
        filename="geometry.png",
        headers=Headers({"content-type": "image/png"}),
    )


def _actor() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=_id(), id=_id())


def _storage() -> SimpleNamespace:
    async def upload(**kwargs):
        return SimpleNamespace(object_key=kwargs["object_key"])

    return SimpleNamespace(
        upload_object=AsyncMock(side_effect=upload),
        delete_object=AsyncMock(),
        create_signed_url=AsyncMock(return_value="https://r2.example/signed"),
    )


@pytest.mark.asyncio
async def test_upload_saves_tenant_scoped_private_image(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id = _actor(), _id()
    assignment = SimpleNamespace(id=assignment_id, status=TMAAssignmentStatus.DRAFT)
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=assignment),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    added = AsyncMock()
    monkeypatch.setattr(mod.TMAMediaAssetRepository, "add", added)
    db = AsyncMock()
    asset = await TMAMediaService.upload_image(
        db, actor=actor, assignment_id=assignment_id, file=_file(),
    )
    kwargs = storage.upload_object.await_args.kwargs
    assert kwargs["visibility"] == MediaVisibility.PRIVATE
    assert kwargs["cache_control"].startswith("private")
    assert kwargs["content_type"] == "image/png"
    assert kwargs["object_key"].startswith(
        f"tenants/{actor.tenant_id}/tma/{assignment_id}/images/"
    )
    assert kwargs["metadata"]["tenant-id"] == str(actor.tenant_id)
    assert asset.object_key == kwargs["object_key"]
    assert asset.size_bytes == len(kwargs["data"])
    assert len(asset.checksum_sha256) == 64
    assert asset.assignment_id == assignment_id
    added.assert_awaited_once_with(db, asset)
    db.commit.assert_awaited_once()
    storage.delete_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_assignment_cannot_upload(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor = _actor()
    assignment_id = _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=SimpleNamespace(
            id=assignment_id, status=TMAAssignmentStatus.ACTIVE,
        )),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    with pytest.raises(ConflictException):
        await TMAMediaService.upload_image(
            AsyncMock(), actor=actor, assignment_id=assignment_id, file=_file(),
        )
    storage.upload_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_failure_rolls_back_and_removes_orphan(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id = _actor(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=SimpleNamespace(
            id=assignment_id, status=TMAAssignmentStatus.DRAFT,
        )),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "add",
        AsyncMock(side_effect=RuntimeError("DB failure")),
    )
    db = AsyncMock()
    with pytest.raises(RuntimeError, match="DB failure"):
        await TMAMediaService.upload_image(
            db, actor=actor, assignment_id=assignment_id, file=_file(),
        )
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    storage.delete_object.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_failure_does_not_create_asset(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id = _actor(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=SimpleNamespace(
            id=assignment_id, status=TMAAssignmentStatus.DRAFT,
        )),
    )
    storage = _storage()
    storage.upload_object.side_effect = RuntimeError("R2 unavailable")
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    added = AsyncMock()
    monkeypatch.setattr(mod.TMAMediaAssetRepository, "add", added)
    db = AsyncMock()
    with pytest.raises(RuntimeError, match="R2 unavailable"):
        await TMAMediaService.upload_image(
            db, actor=actor, assignment_id=assignment_id, file=_file(),
        )
    added.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_url_is_scoped_to_assignment_not_just_tenant(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id, asset_id = _actor(), _id(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment", AsyncMock(),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            id=asset_id, assignment_id=_id(), object_key="foreign",
        )),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    with pytest.raises(NotFoundException):
        await TMAMediaService.get_image_url(
            AsyncMock(), actor=actor,
            assignment_id=assignment_id, asset_id=asset_id,
        )
    storage.create_signed_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_author_signed_url_has_short_ttl(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id, asset_id = _actor(), _id(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment", AsyncMock(),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            id=asset_id, assignment_id=assignment_id, object_key="private/key.png",
        )),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    signed = await TMAMediaService.get_image_url(
        AsyncMock(), actor=actor, assignment_id=assignment_id, asset_id=asset_id,
    )
    assert signed.media_asset_id == asset_id
    assert signed.signed_url == "https://r2.example/signed"
    storage.create_signed_url.assert_awaited_once_with(
        object_key="private/key.png", expires_in_seconds=300,
    )


@pytest.mark.asyncio
async def test_student_can_view_only_referenced_image_in_owned_attempt(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt_id, revision_id, assignment_id, asset_id = (_id() for _ in range(4))
    monkeypatch.setattr(
        mod.TMAAttemptService, "_load_owned_attempt",
        AsyncMock(return_value=(
            SimpleNamespace(status=TMAAttemptStatus.IN_PROGRESS),
            None,
            SimpleNamespace(id=revision_id, assignment_id=assignment_id),
        )),
    )
    monkeypatch.setattr(
        mod.TMAAttemptService, "_active_assignment",
        AsyncMock(return_value=(
            SimpleNamespace(id=assignment_id),
            SimpleNamespace(id=revision_id),
            None,
        )),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            id=asset_id, assignment_id=assignment_id, object_key="private/figure.png",
        )),
    )
    references = AsyncMock(return_value=[
        (SimpleNamespace(image_asset_id=None), [
            SimpleNamespace(image_asset_id=asset_id),
        ]),
    ])
    monkeypatch.setattr(
        mod.TMAQuestionRepository, "list_for_revision_with_options", references,
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    response = await TMAMediaService.get_student_image_url(
        AsyncMock(), student=student, attempt_id=attempt_id, asset_id=asset_id,
    )
    assert response.media_asset_id == asset_id
    references.assert_awaited_once()
    storage.create_signed_url.assert_awaited_once()

    references.return_value = [
        (SimpleNamespace(image_asset_id=_id()), [
            SimpleNamespace(image_asset_id=_id()),
        ]),
    ]
    storage.create_signed_url.reset_mock()
    with pytest.raises(NotFoundException):
        await TMAMediaService.get_student_image_url(
            AsyncMock(), student=student, attempt_id=attempt_id, asset_id=asset_id,
        )
    storage.create_signed_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_student_cannot_view_submitted_or_stale_attempt_images(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    attempt_id, assignment_id, revision_id = (_id() for _ in range(3))
    state = SimpleNamespace(status=TMAAttemptStatus.SUBMITTED)
    monkeypatch.setattr(
        mod.TMAAttemptService, "_load_owned_attempt",
        AsyncMock(return_value=(
            state, None,
            SimpleNamespace(id=revision_id, assignment_id=assignment_id),
        )),
    )
    active = AsyncMock(return_value=(
        SimpleNamespace(id=assignment_id),
        SimpleNamespace(id=_id()),
        None,
    ))
    monkeypatch.setattr(mod.TMAAttemptService, "_active_assignment", active)
    with pytest.raises(ConflictException):
        await TMAMediaService.get_student_image_url(
            AsyncMock(), student=student, attempt_id=attempt_id, asset_id=_id(),
        )
    active.assert_not_awaited()
    state.status = TMAAttemptStatus.IN_PROGRESS
    with pytest.raises(ConflictException):
        await TMAMediaService.get_student_image_url(
            AsyncMock(), student=student, attempt_id=attempt_id, asset_id=_id(),
        )


@pytest.mark.asyncio
async def test_delete_referenced_image_is_blocked_without_commit(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id, asset_id = _actor(), _id(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=SimpleNamespace(
            id=assignment_id, status=TMAAssignmentStatus.DRAFT,
        )),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            id=asset_id, assignment_id=assignment_id, object_key="private/key",
        )),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "delete_unreferenced",
        AsyncMock(return_value=False),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    db = AsyncMock()
    with pytest.raises(ConflictException):
        await TMAMediaService.delete_unused_image(
            db, actor=actor, assignment_id=assignment_id, asset_id=asset_id,
        )
    db.commit.assert_not_awaited()
    storage.delete_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_cleanup_status_after_database_commit(monkeypatch) -> None:
    from app.modules.tma import media_service as mod

    actor, assignment_id, asset_id = _actor(), _id(), _id()
    monkeypatch.setattr(
        mod.TMAMediaService, "_author_assignment",
        AsyncMock(return_value=SimpleNamespace(
            id=assignment_id, status=TMAAssignmentStatus.DRAFT,
        )),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "get_by_id",
        AsyncMock(return_value=SimpleNamespace(
            id=asset_id, assignment_id=assignment_id, object_key="private/key",
        )),
    )
    monkeypatch.setattr(
        mod.TMAMediaAssetRepository, "delete_unreferenced",
        AsyncMock(return_value=True),
    )
    storage = _storage()
    monkeypatch.setattr(mod, "get_media_storage", lambda: storage)
    db = AsyncMock()
    deleted = await TMAMediaService.delete_unused_image(
        db, actor=actor, assignment_id=assignment_id, asset_id=asset_id,
    )
    assert deleted.deleted and deleted.storage_cleaned
    db.commit.assert_awaited_once()
    storage.delete_object.assert_awaited_once_with(object_key="private/key")

    storage.delete_object.side_effect = RuntimeError("R2 unavailable")
    orphan = await TMAMediaService.delete_unused_image(
        AsyncMock(), actor=actor, assignment_id=assignment_id, asset_id=asset_id,
    )
    assert orphan.deleted and not orphan.storage_cleaned
