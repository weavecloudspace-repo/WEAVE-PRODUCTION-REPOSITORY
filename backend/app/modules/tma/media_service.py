"""Private TMA image storage, access control and cleanup.

Uses WEAVE's existing storage backend, never a second R2 client.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache.events import flush_cache_invalidation_events
from app.core.cache.events import queue_cache_key_invalidation
from app.modules.tma.cache import generation_key

from app.core.exceptions import ConflictException, NotFoundException
from app.core.storage.factory import get_media_storage
from app.modules.media.models import MediaVisibility
from app.modules.students.models import Student
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.authorization import TMAAuthor, TMAAuthorizationService
from app.modules.tma.media_validators import validate_tma_image
from app.modules.tma.models import TMAMediaAsset, TMAAssignmentStatus, TMAAttemptStatus
from app.modules.tma.repository import (
    TMAAssignmentRepository,
    TMAQuestionRepository,
    TMAMediaAssetRepository,
)
from app.modules.tma.schemas import TMAMediaDeleteResponse, TMAMediaSignedUrlResponse

logger = logging.getLogger(__name__)
SIGNED_URL_TTL_SECONDS = 300


class TMAMediaService:
    @staticmethod
    async def _author_assignment(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        lock: bool = False,
    ):
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            actor.tenant_id,
            assignment_id,
            lock=lock,
        )
        if assignment is None:
            raise NotFoundException("TMA assignment not found.")
        await TMAAuthorizationService.require_assignment_access(
            db,
            actor=actor,
            assignment=assignment,
        )
        return assignment

    @staticmethod
    async def upload_image(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        file: UploadFile,
    ) -> TMAMediaAsset:
        """Upload a private draft image, then create tenant-scoped metadata.

        If persistence fails, remove the newly uploaded object to avoid an orphan.
        """
        assignment = await TMAMediaService._author_assignment(
            db,
            actor=actor,
            assignment_id=assignment_id,
            lock=True,
        )
        TMAAuthorizationService.require_draft_assignment(assignment)
        validated = await validate_tma_image(file)
        asset_id = uuid.uuid4()
        object_key = (
            f"tenants/{actor.tenant_id}/tma/{assignment.id}/images/{asset_id}.{validated.extension}"
        )
        storage = get_media_storage()
        uploaded = await storage.upload_object(
            object_key=object_key,
            data=validated.data,
            content_type=validated.content_type,
            visibility=MediaVisibility.PRIVATE,
            cache_control="private, max-age=300",
            metadata={"tenant-id": str(actor.tenant_id), "assignment-id": str(assignment.id)},
        )
        asset = TMAMediaAsset(
            id=asset_id,
            tenant_id=actor.tenant_id,
            assignment_id=assignment.id,
            object_key=uploaded.object_key,
            content_type=validated.content_type,
            size_bytes=validated.size_bytes,
            checksum_sha256=validated.checksum_sha256,
        )
        try:
            await TMAMediaAssetRepository.add(db, asset)
            await db.commit()
            await flush_cache_invalidation_events(db)
        except Exception:
            await db.rollback()
            try:
                await storage.delete_object(object_key=uploaded.object_key)
            except Exception:
                logger.exception("Unable to clean up failed TMA upload: %s", uploaded.object_key)
            raise
        return asset

    @staticmethod
    async def list_assignment_images(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
    ) -> list[TMAMediaAsset]:
        await TMAMediaService._author_assignment(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        return await TMAMediaAssetRepository.list_for_assignment(
            db,
            actor.tenant_id,
            assignment_id,
        )

    @staticmethod
    async def get_image_url(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> TMAMediaSignedUrlResponse:
        await TMAMediaService._author_assignment(
            db,
            actor=actor,
            assignment_id=assignment_id,
        )
        asset = await TMAMediaService._get_asset(
            db,
            tenant_id=actor.tenant_id,
            assignment_id=assignment_id,
            asset_id=asset_id,
        )
        return await TMAMediaService._sign(asset)

    @staticmethod
    async def get_student_image_url(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> TMAMediaSignedUrlResponse:
        """Only serve images referenced by the student's published attempt."""
        attempt, _, revision = await TMAAttemptService._load_owned_attempt(
            db,
            student=student,
            attempt_id=attempt_id,
        )
        if attempt.status != TMAAttemptStatus.IN_PROGRESS:
            raise ConflictException("Image access requires an in-progress assignment.")
        assignment, active_revision, _ = await TMAAttemptService._active_assignment(
            db,
            student=student,
            assignment_id=revision.assignment_id,
        )
        if revision.id != active_revision.id:
            raise ConflictException("This attempt is no longer the current revision.")
        asset = await TMAMediaService._get_asset(
            db,
            tenant_id=student.tenant_id,
            assignment_id=assignment.id,
            asset_id=asset_id,
        )
        questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            student.tenant_id,
            revision.id,
        )
        used = any(
            question.image_asset_id == asset_id
            or any(option.image_asset_id == asset_id for option in options)
            for question, options in questions
        )
        if not used:
            raise NotFoundException("Image not found in this assignment.")
        return await TMAMediaService._sign(asset)

    @staticmethod
    async def _get_asset(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> TMAMediaAsset:
        asset = await TMAMediaAssetRepository.get_by_id(db, tenant_id, asset_id)
        if asset is None or asset.assignment_id != assignment_id:
            raise NotFoundException("TMA image not found.")
        return asset

    @staticmethod
    async def _sign(asset: TMAMediaAsset) -> TMAMediaSignedUrlResponse:
        url = await get_media_storage().create_signed_url(
            object_key=asset.object_key,
            expires_in_seconds=SIGNED_URL_TTL_SECONDS,
        )
        return TMAMediaSignedUrlResponse(
            media_asset_id=asset.id,
            signed_url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=SIGNED_URL_TTL_SECONDS),
        )

    @staticmethod
    async def delete_unused_image(
        db: AsyncSession,
        *,
        actor: TMAAuthor,
        assignment_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> TMAMediaDeleteResponse:
        """Remove unused draft metadata, then best-effort delete physical object.

        Deleting database metadata first avoids dangling question references if
        R2 deletion fails. The returned cleanup flag makes orphan cleanup visible.
        """
        assignment = await TMAMediaService._author_assignment(
            db,
            actor=actor,
            assignment_id=assignment_id,
            lock=True,
        )
        TMAAuthorizationService.require_draft_assignment(assignment)
        asset = await TMAMediaService._get_asset(
            db,
            tenant_id=actor.tenant_id,
            assignment_id=assignment_id,
            asset_id=asset_id,
        )
        deleted = await TMAMediaAssetRepository.delete_unreferenced(
            db,
            actor.tenant_id,
            asset.id,
        )
        if not deleted:
            raise ConflictException("The image is still referenced by a question or option.")
        queue_cache_key_invalidation(db, generation_key(actor.tenant_id))
        await db.commit()
        await flush_cache_invalidation_events(db)
        try:
            await get_media_storage().delete_object(object_key=asset.object_key)
        except Exception:
            logger.exception("TMA R2 object cleanup pending for %s", asset.object_key)
            return TMAMediaDeleteResponse(
                media_asset_id=asset.id,
                deleted=True,
                storage_cleaned=False,
            )
        return TMAMediaDeleteResponse(
            media_asset_id=asset.id,
            deleted=True,
            storage_cleaned=True,
        )
