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
from app.modules.cbt.enums import CBTServerStatus
from app.modules.cbt.models import CBTServer
from app.core.exceptions import ForbiddenException, NotFoundException


@pytest.fixture
def unrevoke_context(monkeypatch):
    now = datetime.now(timezone.utc)
    admin = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    server = CBTServer(
        id=uuid4(),
        tenant_id=admin.tenant_id,
        name="ICT Lab",
        hostname_prefix="ict-lab",
        dns_school_slug="school",
        status=CBTServerStatus.REVOKED,
        paired_at=now,
        created_at=now,
        updated_at=now,
        revoked_at=now,
        revoked_by_admin_id=admin.id,
        revocation_reason="Retired",
    )
    ctx = SimpleNamespace(db=SimpleNamespace(flush=AsyncMock()), admin=admin, server=server)
    for key, target in [
        ("tenant", "CBTPairingService._get_pairable_tenant"),
        ("feature", "SubscriptionFeatureService.ensure_feature_enabled"),
        ("capacity", "CBTPairingService._ensure_cbt_pairing_allowed"),
        ("name", "CBTPairingService._ensure_server_name_available"),
        ("credentials", "CBTServerCredentialRepository.create"),
    ]:
        mock = AsyncMock()
        setattr(ctx, key, mock)
        monkeypatch.setattr("app.modules.cbt.pairing.service." + target, mock)
    ctx.get_server = AsyncMock(return_value=server)
    monkeypatch.setattr(
        "app.modules.cbt.pairing.service.CBTServerRepository.get_by_tenant_and_id",
        ctx.get_server,
    )
    return ctx


@pytest.mark.asyncio
async def test_unrevoke_restores_only_suspended_registration(unrevoke_context):
    ctx = unrevoke_context
    result = await CBTPairingService.unrevoke_server(
        ctx.db, admin=ctx.admin, server_id=ctx.server.id
    )
    assert result.status == CBTServerStatus.SUSPENDED
    assert result.revoked_at is None
    assert result.suspended_at is not None
    assert result.revocation_reason == "Retired"
    assert result.revoked_by_admin_id == ctx.admin.id
    ctx.get_server.assert_awaited_once_with(
        ctx.db, tenant_id=ctx.admin.tenant_id, server_id=ctx.server.id, lock=True
    )
    ctx.tenant.assert_awaited_once_with(ctx.db, tenant_id=ctx.admin.tenant_id, lock=True)
    ctx.capacity.assert_awaited_once_with(ctx.db, tenant_id=ctx.admin.tenant_id)
    ctx.name.assert_awaited_once_with(
        ctx.db, tenant_id=ctx.admin.tenant_id, normalized_name="ICT Lab"
    )
    ctx.credentials.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["tenant", "feature", "capacity", "name"])
async def test_unrevoke_guard_failure_preserves_revocation(unrevoke_context, guard):
    ctx = unrevoke_context
    error_type = ConflictException if guard == "name" else ForbiddenException
    getattr(ctx, guard).side_effect = error_type(detail="Not permitted")
    with pytest.raises(error_type):
        await CBTPairingService.unrevoke_server(ctx.db, admin=ctx.admin, server_id=ctx.server.id)
    assert ctx.server.status == CBTServerStatus.REVOKED
    assert ctx.server.revoked_at is not None
    ctx.db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrevoke_wrong_tenant_server_is_not_found(unrevoke_context):
    ctx = unrevoke_context
    ctx.get_server.return_value = None
    with pytest.raises(NotFoundException):
        await CBTPairingService.unrevoke_server(ctx.db, admin=ctx.admin, server_id=uuid4())
    ctx.capacity.assert_not_awaited()
    ctx.db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrevoke_admin_without_tenant_rejected(unrevoke_context):
    ctx = unrevoke_context
    ctx.admin.tenant_id = None
    with pytest.raises(ForbiddenException):
        await CBTPairingService.unrevoke_server(ctx.db, admin=ctx.admin, server_id=ctx.server.id)
    ctx.tenant.assert_not_awaited()
    ctx.get_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrevoke_route_invalidates_usage_after_restoring(unrevoke_context, monkeypatch):
    from app.modules.cbt.pairing.router import unrevoke_cbt_server

    ctx = unrevoke_context
    invalidate = AsyncMock()
    monkeypatch.setattr(
        "app.modules.cbt.pairing.router.SubscriptionFeatureService.invalidate_tenant_subscription_state",
        invalidate,
    )
    result = await unrevoke_cbt_server(ctx.server.id, ctx.db, ctx.admin)
    assert result.status == CBTServerStatus.SUSPENDED
    invalidate.assert_awaited_once_with(ctx.admin.tenant_id, db=ctx.db)


@pytest.mark.asyncio
async def test_unrevoke_active_rejected_and_suspended_retry_safe(unrevoke_context):
    ctx = unrevoke_context
    ctx.server.status = CBTServerStatus.ACTIVE
    with pytest.raises(BadRequestException):
        await CBTPairingService.unrevoke_server(ctx.db, admin=ctx.admin, server_id=ctx.server.id)
    ctx.server.status = CBTServerStatus.SUSPENDED
    ctx.server.revoked_at = None
    result = await CBTPairingService.unrevoke_server(
        ctx.db, admin=ctx.admin, server_id=ctx.server.id
    )
    assert result.status == CBTServerStatus.SUSPENDED
    ctx.capacity.assert_not_awaited()
    ctx.db.flush.assert_not_awaited()


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
            return_value=SimpleNamespace(
                id=tenant_id, school_name="Weave School", slug="weave-school"
            )
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
