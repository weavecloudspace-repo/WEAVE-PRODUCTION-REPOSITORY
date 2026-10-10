from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.modules.cbt.dns.hostname import hostname_prefix

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.modules.cbt.models import CBTServer, CBTServerCredential
from app.modules.cbt.pairing.service import CBTPairingService
from app.modules.cbt.repository import CBTServerCredentialRepository, CBTServerRepository
from app.tenant_management.models import (
    SubscriptionPlan,
    Tenant,
    TenantStatus,
    TenantVerificationStatus,
)


class _EmptyResult:
    rowcount = 0

    def scalar_one_or_none(self) -> None:
        return None


class _CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyResult()


def _tenant(*, suffix: str) -> Tenant:
    return Tenant(
        school_name=f"CBT Tenant {suffix}",
        slug=f"cbt-tenant-{suffix}",
        email=f"cbt-{suffix}@example.com",
        status=TenantStatus.ACTIVE,
        plan=SubscriptionPlan.FREE,
        verification_status=TenantVerificationStatus.ACTIVE,
        onboarding_completed=True,
        country="Nigeria",
        timezone="Africa/Lagos",
        language="en",
    )


@pytest.mark.asyncio
async def test_get_active_for_server_query_is_tenant_scoped() -> None:
    db = _CapturingSession()

    await CBTServerCredentialRepository.get_active_for_server(
        db,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        server_id=uuid4(),
        lock=True,
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))

    assert "JOIN public.cbt_servers" in sql
    assert "cbt_servers.tenant_id" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_get_by_tenant_and_normalized_name_query_is_tenant_scoped() -> None:
    db = _CapturingSession()

    await CBTServerRepository.get_by_tenant_and_normalized_name(
        db,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        normalized_name="main cbt lab",
        lock=True,
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))

    assert "public.cbt_servers.tenant_id" in sql
    assert "regexp_replace" in sql
    assert "lower" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_revoke_active_for_server_query_is_tenant_scoped() -> None:
    db = _CapturingSession()

    await CBTServerCredentialRepository.revoke_active_for_server(
        db,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        server_id=uuid4(),
        revoked_at=datetime.now(timezone.utc),
        reason="rotation",
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))

    assert "UPDATE public.cbt_server_credentials" in sql
    assert "SELECT public.cbt_servers.id" in sql
    assert "public.cbt_servers.tenant_id" in sql


@pytest.mark.asyncio
async def test_revoke_active_for_server_does_not_cross_tenant_boundaries(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    other_tenant = _tenant(suffix=uuid4().hex[:8])
    db_session.add(other_tenant)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    server = CBTServer(
        tenant_id=tenant.id,
        name="Main Lab CBT",
        paired_at=now,
    )
    server.id = uuid4()
    server.hostname_prefix = hostname_prefix(server.name, server.id)
    db_session.add(server)
    await db_session.flush()

    credential = CBTServerCredential(
        server_id=server.id,
        credential_hash="a" * 64,
    )
    db_session.add(credential)
    await db_session.flush()

    revoked_count = await CBTServerCredentialRepository.revoke_active_for_server(
        db_session,
        tenant_id=other_tenant.id,
        server_id=server.id,
        revoked_at=now,
        reason="cross-tenant attempt",
    )

    assert revoked_count == 0

    active_credential = await CBTServerCredentialRepository.get_active_for_server(
        db_session,
        tenant_id=tenant.id,
        server_id=server.id,
    )

    assert active_credential is not None
    assert active_credential.revoked_at is None


@pytest.mark.asyncio
async def test_get_by_tenant_and_id_returns_none_for_other_tenant(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    other_tenant = _tenant(suffix=uuid4().hex[:8])
    db_session.add(other_tenant)
    await db_session.flush()

    server = CBTServer(
        tenant_id=tenant.id,
        name="Science Hall CBT",
        paired_at=datetime.now(timezone.utc),
    )
    server.id = uuid4()
    server.hostname_prefix = hostname_prefix(server.name, server.id)
    await CBTServerRepository.create(db_session, server)

    result = await CBTServerRepository.get_by_tenant_and_id(
        db_session,
        tenant_id=other_tenant.id,
        server_id=server.id,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_by_tenant_and_normalized_name_matches_case_and_whitespace_variants(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    server = CBTServer(
        tenant_id=tenant.id,
        name="Main   CBT   Lab",
        paired_at=datetime.now(timezone.utc),
    )
    server.id = uuid4()
    server.hostname_prefix = hostname_prefix(server.name, server.id)
    await CBTServerRepository.create(db_session, server)

    result = await CBTServerRepository.get_by_tenant_and_normalized_name(
        db_session,
        tenant_id=tenant.id,
        normalized_name="  main cbt lab  ",
    )

    assert result is not None
    assert result.id == server.id


def test_normalize_server_name_trims_and_collapses_whitespace() -> None:
    normalized = CBTPairingService.normalize_server_name("  ICT   CBT   Lab  ")

    assert normalized == "ICT CBT Lab"
