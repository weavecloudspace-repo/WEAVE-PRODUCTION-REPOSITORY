from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import BadRequestException, ConflictException
from app.modules.cbt.dns.hostname import hostname_for_server, hostname_prefix
from app.modules.cbt.pairing.schemas import (
    CBT_SERVER_REVOKE_CONFIRMATION_LITERAL,
    PairingRequest,
)
from app.modules.cbt.pairing.service import CBTPairingService


@pytest.mark.asyncio
async def test_ensure_server_name_available_raises_conflict_for_normalized_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_server = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.get_by_tenant_and_normalized_name",
        AsyncMock(return_value=existing_server),
    )

    with pytest.raises(
        ConflictException,
        match="already exists for this tenant",
    ):
        await CBTPairingService._ensure_server_name_available(
            object(),  # type: ignore[arg-type]
            tenant_id=uuid4(),
            normalized_name="ICT CBT Lab",
        )


def test_validate_revocation_request_requires_reason_and_literal() -> None:
    with pytest.raises(BadRequestException, match="reason is required"):
        CBTPairingService._validate_revocation_request(
            reason="   ",
            confirmation_literal=CBT_SERVER_REVOKE_CONFIRMATION_LITERAL,
        )

    with pytest.raises(BadRequestException, match="Type REVOKE SERVER"):
        CBTPairingService._validate_revocation_request(
            reason="Decommissioned lab machine",
            confirmation_literal="REVOKE",
        )


def test_validate_revocation_request_returns_normalized_reason() -> None:
    assert (
        CBTPairingService._validate_revocation_request(
            reason="  Decommissioned lab machine  ",
            confirmation_literal=CBT_SERVER_REVOKE_CONFIRMATION_LITERAL,
        )
        == "Decommissioned lab machine"
    )


@pytest.mark.asyncio
async def test_revoke_server_rejects_invalid_literal_before_loading_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_server = AsyncMock()
    monkeypatch.setattr(
        CBTPairingService,
        "_get_server_for_admin",
        get_server,
    )

    with pytest.raises(BadRequestException, match="Type REVOKE SERVER"):
        await CBTPairingService.revoke_server(
            object(),  # type: ignore[arg-type]
            admin=SimpleNamespace(),
            server_id=uuid4(),
            reason="Decommissioned lab machine",
            confirmation_literal="REVOKE",
        )

    get_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_pair_server_queues_correlated_event_for_code_creator(monkeypatch) -> None:
    tenant_id = uuid4()
    admin_id = uuid4()
    pairing_id = uuid4()
    server_id = uuid4()
    pairing = SimpleNamespace(
        id=pairing_id,
        tenant_id=tenant_id,
        created_by_admin_id=admin_id,
        used_at=None,
        invalidated_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    server = SimpleNamespace(
        id=server_id,
        name="ICT CBT Lab",
        hostname=hostname_for_server(
            prefix=hostname_prefix("ICT CBT Lab", server_id),
            school_slug="weave-school",
            environment="staging",
        ),
        paired_at=datetime.now(timezone.utc),
    )
    queued = []

    monkeypatch.setattr("app.modules.cbt.pairing.service.hash_pairing_code", lambda _v: "hash")
    monkeypatch.setattr("app.modules.cbt.pairing.service.generate_server_token", lambda: "token")
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.hash_server_token", lambda _v: "token-hash"
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTPairingCodeRepository.get_by_hash",
        AsyncMock(side_effect=[pairing, pairing]),
    )
    monkeypatch.setattr(
        CBTPairingService,
        "_get_pairable_tenant",
        AsyncMock(
            return_value=SimpleNamespace(id=tenant_id, school_name="Weave School", slug="weave-school")
        ),
    )
    monkeypatch.setattr(CBTPairingService, "_ensure_cbt_pairing_allowed", AsyncMock())
    monkeypatch.setattr(CBTPairingService, "_ensure_server_name_available", AsyncMock())
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.get_school_dns_slug",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.dns_school_slug_owned_by_other",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.dns_name_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.create",
        AsyncMock(return_value=server),
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerCredentialRepository.create", AsyncMock()
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTPairingCodeRepository.consume", AsyncMock()
    )
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.RealtimePublisher.defer_to_actor",
        lambda _db, **kwargs: queued.append(kwargs),
    )

    result = await CBTPairingService.pair_server(
        db=SimpleNamespace(info={}),
        payload=PairingRequest(pairing_code="ABCD-EFGH", server_name=" ICT   CBT Lab "),
    )

    assert result.server_id == server_id
    assert result.hostname == server.hostname
    assert queued == [
        {
            "event_type": "cbt.pairing.completed",
            "actor_type": "tenant_admin",
            "actor_id": admin_id,
            "tenant_id": tenant_id,
            "data": {
                "pairing_request_id": str(pairing_id),
                "server_id": str(server_id),
                "server_name": "ICT CBT Lab",
            },
        }
    ]
