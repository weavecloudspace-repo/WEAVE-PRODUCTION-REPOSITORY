"""Machine-authenticated ACME TXT challenge API (no arbitrary DNS operations)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.core.dependencies.db import DbSession
from app.modules.cbt.dependencies import CurrentCBTServer
from app.modules.cbt.dns.schemas import CreateDNSChallengeRequest, DNSChallengeResponse
from app.modules.cbt.dns.service import CBTDNSChallengeService

router = APIRouter(prefix="/certificates/dns-challenges", tags=["CBT DNS Verification"])


@router.post("", response_model=DNSChallengeResponse, status_code=status.HTTP_201_CREATED)
async def create_challenge(
    payload: CreateDNSChallengeRequest, db: DbSession, current_server: CurrentCBTServer
) -> DNSChallengeResponse:
    return await CBTDNSChallengeService.create(db, current_server, payload)


@router.get("/{challenge_id}", response_model=DNSChallengeResponse)
async def get_challenge(
    challenge_id: UUID, db: DbSession, current_server: CurrentCBTServer
) -> DNSChallengeResponse:
    return await CBTDNSChallengeService.get(db, current_server, challenge_id)


@router.delete("/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_challenge(
    challenge_id: UUID, db: DbSession, current_server: CurrentCBTServer
) -> Response:
    await CBTDNSChallengeService.remove(db, current_server, challenge_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
