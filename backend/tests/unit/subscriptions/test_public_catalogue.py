import pytest

from app.config.settings import settings
from app.modules.subscriptions.catalogue import PublicSubscriptionCatalogueService


@pytest.mark.asyncio
async def test_public_catalogue_is_term_priced_and_includes_permanent_free(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_PLUS_TERM_AMOUNT_KOBO", 1_700_000)
    catalogue = PublicSubscriptionCatalogueService.build_catalogue()
    by_code = {item.plan_code: item for item in catalogue.plans}
    assert catalogue.billing_intervals == ["term"]
    assert by_code["free"].amount_kobo == 0
    assert by_code["plus"].amount_kobo == 1_700_000
    assert "free_trial" not in by_code
    assert by_code["free"].features["advanced_analytics"] is True


def test_cbt_v1_server_registration_limit_is_two_for_eligible_plans():
    from app.modules.subscriptions.plans import get_plan_entitlements
    from app.modules.subscriptions.subscription_enums import ResourceLimitCode

    for plan in ("professional", "enterprise"):
        entitlements = get_plan_entitlements(plan)
        assert entitlements.limits[ResourceLimitCode.CBT_SERVERS] == 2
        assert entitlements.features["cbt_pairing"] is True

    for plan in ("free", "plus"):
        assert get_plan_entitlements(plan).limits[ResourceLimitCode.CBT_SERVERS] == 0
