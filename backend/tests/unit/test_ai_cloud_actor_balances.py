"""Cloud pagination must preserve the shared CBT quota service contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.cbt.ai import cloud_router
from app.modules.cbt.ai.quota.schemas import AIActorQuotaBalance, AIActorQuotaBalanceListResponse
from app.modules.tenant_admins.models import TenantAdmin


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,limit,expected", [(0, 2, [0, 1]), (2, 2, [2]), (5, 2, [])])
async def test_actor_balance_pagination_uses_existing_service_contract(
    monkeypatch, offset, limit, expected
):
    actor = TenantAdmin(id=uuid4(), tenant_id=uuid4())
    converted = SimpleNamespace(tenant_id=actor.tenant_id, actor_type="tenant_admin")
    items = [
        AIActorQuotaBalance(
            quota_account_id=uuid4(),
            actor_type="tenant_admin",
            actor_id=uuid4(),
            display_name=f"Administrator {index}",
            email=f"admin{index}@example.test",
            weekly_available_credits=10,
            weekly_used_credits=0,
            extra_available_credits=0,
            total_available_credits=10,
        )
        for index in range(3)
    ]
    cached = AIActorQuotaBalanceListResponse(items=items, total=3)

    # Deliberately use the real keyword-only signature: an unrestricted mock
    # would hide the unexpected-offset TypeError reported by the dashboard.
    async def list_balances(db, *, actor):
        assert actor is converted
        return cached

    service = AsyncMock(spec=list_balances, side_effect=list_balances)
    monkeypatch.setattr(cloud_router.CBTAIService, "list_actor_quota_balances", service)
    monkeypatch.setattr(cloud_router, "to_existing_ai_actor", lambda value: converted)
    db = AsyncMock()
    result = await cloud_router.admin_cloud_actor_balances(db, actor, offset=offset, limit=limit)
    service.assert_awaited_once_with(db, actor=converted)
    assert result.total == 3
    assert [item.actor_id for item in result.items] == [items[i].actor_id for i in expected]
    assert len(cached.items) == 3
    assert result is not cached


@pytest.mark.asyncio
async def test_actor_search_finds_matches_after_original_first_100(monkeypatch) -> None:
    actor = TenantAdmin(id=uuid4(), tenant_id=uuid4())
    converted = SimpleNamespace(tenant_id=actor.tenant_id, actor_type="tenant_admin")
    items = [
        AIActorQuotaBalance(
            quota_account_id=uuid4(),
            actor_type="tenant_admin",
            actor_id=uuid4(),
            display_name=f"Staff {i:03d}",
            email=f"staff{i:03d}@example.test",
            weekly_available_credits=10,
            weekly_used_credits=2,
            extra_available_credits=0,
            total_available_credits=10,
        )
        for i in range(150)
    ]
    cached = AIActorQuotaBalanceListResponse(items=items, total=150, weekly_used_credits_total=300)

    async def list_balances(db, *, actor):
        assert actor is converted
        return cached

    monkeypatch.setattr(cloud_router.CBTAIService, "list_actor_quota_balances", list_balances)
    monkeypatch.setattr(cloud_router, "to_existing_ai_actor", lambda value: converted)
    response = await cloud_router.admin_cloud_actor_balances(
        AsyncMock(), actor, search="STAFF149", offset=0, limit=20
    )
    assert response.total == 1
    assert response.items[0].actor_id == items[149].actor_id
    assert response.weekly_used_credits_total == 300
    assert cached.total == 150
    assert len(cached.items) == 150
