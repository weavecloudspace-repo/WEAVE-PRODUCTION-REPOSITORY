"""Authenticated CBT DNS-01 challenge lifecycle with provider-owned record IDs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import AppException, ConflictException, ForbiddenException, NotFoundException
from app.modules.cbt.auth.schemas import AuthenticatedCBTServer
from app.modules.cbt.dns.bunny import BunnyDNSClient, BunnyDNSUnavailable
from app.modules.cbt.dns.hostname import challenge_record_name
from app.modules.cbt.dns.schemas import CreateDNSChallengeRequest, DNSChallengeResponse
from app.modules.cbt.enums import CBTServerStatus
from app.modules.cbt.models import CBTDNSChallenge
from app.modules.cbt.repository import CBTServerRepository

MAX_ACTIVE_CHALLENGES = 3
MAX_HOURLY_CHALLENGES = 15
CHALLENGE_LIFETIME = timedelta(minutes=20)


def _provider() -> BunnyDNSClient:
    key = settings.BUNNY_DNS_API_KEY
    zone_id = settings.BUNNY_DNS_ZONE_ID
    if key is None or not key.get_secret_value() or zone_id is None:
        raise AppException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CBT DNS verification is not configured.",
        )
    return BunnyDNSClient(api_key=key.get_secret_value(), zone_id=zone_id)


def _provider_error() -> AppException:
    return AppException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="CBT DNS provider temporarily unavailable.",
    )


def _response(challenge: CBTDNSChallenge, hostname: str) -> DNSChallengeResponse:
    now = datetime.now(timezone.utc)
    state = (
        "removed" if challenge.removed_at is not None
        else "expired" if challenge.expires_at <= now
        else "created"
    )
    return DNSChallengeResponse(
        id=challenge.id,
        hostname=hostname,
        fqdn=challenge.fqdn,
        status=state,
        expires_at=challenge.expires_at,
    )


class CBTDNSChallengeService:
    @staticmethod
    async def _owned(
        db: AsyncSession, actor: AuthenticatedCBTServer, challenge_id: UUID, *, lock: bool = False
    ) -> CBTDNSChallenge:
        query = select(CBTDNSChallenge).where(
            CBTDNSChallenge.id == challenge_id,
            CBTDNSChallenge.tenant_id == actor.tenant_id,
            CBTDNSChallenge.server_id == actor.server_id,
        )
        if lock:
            query = query.with_for_update()
        result = await db.execute(query)
        challenge = result.scalar_one_or_none()
        if challenge is None:
            raise NotFoundException(detail="CBT DNS challenge not found")
        return challenge

    @staticmethod
    async def _server(db: AsyncSession, actor: AuthenticatedCBTServer, *, lock: bool = False):
        server = await CBTServerRepository.get_by_tenant_and_id(
            db, tenant_id=actor.tenant_id, server_id=actor.server_id, lock=lock,
        )
        if server is None or server.status != CBTServerStatus.ACTIVE or server.revoked_at is not None:
            raise ForbiddenException(detail="CBT server is not active")
        return server

    @staticmethod
    async def create(
        db: AsyncSession, actor: AuthenticatedCBTServer, payload: CreateDNSChallengeRequest
    ) -> DNSChallengeResponse:
        # Serialize all creation requests for this machine using its existing row lock.
        server = await CBTDNSChallengeService._server(db, actor, lock=True)
        digest = hashlib.sha256(payload.value.encode("ascii")).hexdigest()
        existing = await db.scalar(
            select(CBTDNSChallenge).where(
                CBTDNSChallenge.server_id == actor.server_id,
                CBTDNSChallenge.request_id == payload.request_id,
            )
        )
        if existing is not None:
            if existing.value_sha256 != digest:
                raise ConflictException(detail="Challenge request ID already used")
            return _response(existing, server.hostname)

        now = datetime.now(timezone.utc)
        active = await db.scalar(
            select(func.count(CBTDNSChallenge.id)).where(
                CBTDNSChallenge.server_id == actor.server_id,
                CBTDNSChallenge.removed_at.is_(None),
                CBTDNSChallenge.expires_at > now,
            )
        )
        recent = await db.scalar(
            select(func.count(CBTDNSChallenge.id)).where(
                CBTDNSChallenge.server_id == actor.server_id,
                CBTDNSChallenge.created_at >= now - timedelta(hours=1),
            )
        )
        if (active or 0) >= MAX_ACTIVE_CHALLENGES or (recent or 0) >= MAX_HOURLY_CHALLENGES:
            raise AppException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="CBT DNS challenge quota exceeded. Retry later.",
            )

        hostname = server.hostname
        name = challenge_record_name(hostname)
        fqdn = f"{name}.weavecloudspace.com"
        client = _provider()
        try:
            record_id = await client.create_txt(
                name=name, value=payload.value, request_id=str(payload.request_id),
            )
        except BunnyDNSUnavailable:
            raise _provider_error() from None

        challenge = CBTDNSChallenge(
            tenant_id=actor.tenant_id,
            server_id=actor.server_id,
            request_id=payload.request_id,
            fqdn=fqdn,
            value_sha256=digest,
            provider_record_id=record_id,
            expires_at=now + CHALLENGE_LIFETIME,
        )
        db.add(challenge)
        try:
            await db.flush()
        except Exception:
            # Best-effort compensation; no unowned TXT records should survive DB failure.
            try:
                await client.delete_txt(record_id=record_id)
            except BunnyDNSUnavailable:
                pass
            raise
        return _response(challenge, hostname)

    @staticmethod
    async def get(
        db: AsyncSession, actor: AuthenticatedCBTServer, challenge_id: UUID
    ) -> DNSChallengeResponse:
        server = await CBTDNSChallengeService._server(db, actor)
        challenge = await CBTDNSChallengeService._owned(db, actor, challenge_id)
        return _response(challenge, server.hostname)

    @staticmethod
    async def remove(
        db: AsyncSession, actor: AuthenticatedCBTServer, challenge_id: UUID
    ) -> None:
        await CBTDNSChallengeService._server(db, actor)
        challenge = await CBTDNSChallengeService._owned(db, actor, challenge_id, lock=True)
        if challenge.removed_at is not None:
            return
        try:
            await _provider().delete_txt(record_id=challenge.provider_record_id)
        except BunnyDNSUnavailable:
            raise _provider_error() from None
        challenge.removed_at = datetime.now(timezone.utc)
        await db.flush()

    @staticmethod
    async def cleanup_expired(db: AsyncSession, *, limit: int = 50) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        rows = (
            await db.execute(
                select(CBTDNSChallenge)
                .where(CBTDNSChallenge.removed_at.is_(None), CBTDNSChallenge.expires_at <= now)
                .order_by(CBTDNSChallenge.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not rows:
            return {"removed": 0, "failed": 0}
        client = _provider()
        removed = failed = 0
        for item in rows:
            try:
                await client.delete_txt(record_id=item.provider_record_id)
            except BunnyDNSUnavailable:
                failed += 1
                continue
            item.removed_at = now
            removed += 1
        await db.flush()
        return {"removed": removed, "failed": failed}
