"""Static plan entitlement definitions for the subscription module."""

from dataclasses import dataclass
from typing import Any

from app.modules.subscriptions.constants import PLAN_ALIASES
from app.modules.subscriptions.subscription_enums import FeatureCode, ResourceLimitCode
from app.tenant_management.models import SubscriptionPlan


@dataclass(frozen=True)
class PlanEntitlements:
    """Defines what one subscription plan can access."""

    features: dict[FeatureCode, bool]
    limits: dict[ResourceLimitCode, int | None]


def _features(
    *,
    student_management: bool = True,
    teacher_management: bool = True,
    parent_portal: bool = True,
    academic_setup: bool = True,
    report_cards: bool = True,
    notices: bool = True,
    attendance: bool = True,
    geofencing: bool = True,
    advanced_analytics: bool = True,
    ai_assistant: bool = False,
    bulk_import: bool = False,
    bulk_academic_operations: bool = False,
    tenant_branding: bool = False,
    cbt_pairing: bool = False,
) -> dict[FeatureCode, bool]:
    return {
        FeatureCode.STUDENT_MANAGEMENT: student_management,
        FeatureCode.TEACHER_MANAGEMENT: teacher_management,
        FeatureCode.PARENT_PORTAL: parent_portal,
        FeatureCode.ACADEMIC_SETUP: academic_setup,
        FeatureCode.REPORT_CARDS: report_cards,
        FeatureCode.NOTICES: notices,
        FeatureCode.ATTENDANCE: attendance,
        FeatureCode.GEOFENCING: geofencing,
        FeatureCode.ADVANCED_ANALYTICS: advanced_analytics,
        FeatureCode.AI_ASSISTANT: ai_assistant,
        FeatureCode.BULK_IMPORT: bulk_import,
        FeatureCode.BULK_ACADEMIC_OPERATIONS: bulk_academic_operations,
        FeatureCode.TENANT_BRANDING: tenant_branding,
        FeatureCode.CBT_PAIRING: cbt_pairing,
    }


def _paid_features(
    *,
    tenant_branding: bool = False,
    cbt_pairing: bool = False,
) -> dict[FeatureCode, bool]:
    """All paying customers get full product features; quotas scale by plan."""

    return _features(
        advanced_analytics=True,
        ai_assistant=True,
        bulk_import=True,
        bulk_academic_operations=True,
        tenant_branding=tenant_branding,
        cbt_pairing=cbt_pairing,
    )


def _limits(
    *,
    students: int | None,
    teachers: int | None,
    parents: int | None,
    cbt_servers: int | None,
) -> dict[ResourceLimitCode, int | None]:
    return {
        ResourceLimitCode.STUDENTS: students,
        ResourceLimitCode.TEACHERS: teachers,
        ResourceLimitCode.PARENTS: parents,
        ResourceLimitCode.CBT_SERVERS: cbt_servers,
    }


_FREE_ENTITLEMENTS = PlanEntitlements(
    features=_features(
        ai_assistant=False,
        bulk_import=False,
        bulk_academic_operations=False,
    ),
    limits=_limits(students=50, teachers=10, parents=50, cbt_servers=0),
)

PLAN_ENTITLEMENTS: dict[str, PlanEntitlements] = {
    SubscriptionPlan.FREE.value: _FREE_ENTITLEMENTS,
    SubscriptionPlan.FREE_TRIAL.value: _FREE_ENTITLEMENTS,
    SubscriptionPlan.PLUS.value: PlanEntitlements(
        features=_paid_features(),
        limits=_limits(students=500, teachers=50, parents=300, cbt_servers=0),
    ),
    SubscriptionPlan.PROFESSIONAL.value: PlanEntitlements(
        features=_paid_features(tenant_branding=True, cbt_pairing=True),
        limits=_limits(students=1200, teachers=100, parents=1000, cbt_servers=2),
    ),
    SubscriptionPlan.ENTERPRISE.value: PlanEntitlements(
        features=_paid_features(tenant_branding=True, cbt_pairing=True),
        limits=_limits(students=None, teachers=None, parents=None, cbt_servers=2),
    ),
}


def coerce_subscription_plan(plan: Any) -> SubscriptionPlan:
    if isinstance(plan, SubscriptionPlan):
        return SubscriptionPlan.FREE if plan == SubscriptionPlan.FREE_TRIAL else plan
    raw_value = getattr(plan, "value", plan)
    normalized = str(raw_value or "").strip().lower()
    if not normalized or normalized == SubscriptionPlan.FREE_TRIAL.value:
        return SubscriptionPlan.FREE
    resolved = PLAN_ALIASES.get(normalized, SubscriptionPlan.FREE)
    return SubscriptionPlan.FREE if resolved == SubscriptionPlan.FREE_TRIAL else resolved


def normalize_plan_code(plan: Any) -> str:
    return coerce_subscription_plan(plan).value


def get_plan_entitlements(plan: Any) -> PlanEntitlements:
    plan_code = normalize_plan_code(plan)
    return PLAN_ENTITLEMENTS.get(plan_code, PLAN_ENTITLEMENTS[SubscriptionPlan.FREE.value])
