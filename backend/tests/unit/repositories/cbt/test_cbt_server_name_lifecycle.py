from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.modules.cbt.dns.hostname import hostname_prefix

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cbt.models import CBTServer
from app.modules.cbt.repository import CBTServerRepository
from app.tenant_management.models import Tenant


@pytest.mark.asyncio
async def test_revoked_server_name_does_not_block_reuse(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    now = datetime.now(timezone.utc)
    old_server = CBTServer(
        tenant_id=tenant.id,
        name="Main Examination Server",
        paired_at=now,
        dns_school_slug=tenant.slug,
        revoked_at=now,
    )
    old_server.id = uuid4()
    old_server.hostname_prefix = hostname_prefix(old_server.name, old_server.id)
    db_session.add(old_server)
    await db_session.flush()

    match = await CBTServerRepository.get_by_tenant_and_normalized_name(
        db_session,
        tenant_id=tenant.id,
        normalized_name="  main   examination server ",
    )

    assert match is None


@pytest.mark.asyncio
async def test_non_revoked_server_name_still_blocks_duplicate(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    server = CBTServer(
        tenant_id=tenant.id,
        name="Science Lab Server",
        paired_at=datetime.now(timezone.utc),
        dns_school_slug=tenant.slug,
    )
    server.id = uuid4()
    server.hostname_prefix = hostname_prefix(server.name, server.id)
    db_session.add(server)
    await db_session.flush()

    match = await CBTServerRepository.get_by_tenant_and_normalized_name(
        db_session,
        tenant_id=tenant.id,
        normalized_name="science   lab server",
    )

    assert match is not None
    assert match.id == server.id
