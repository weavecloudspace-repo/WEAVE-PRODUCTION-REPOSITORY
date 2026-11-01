from __future__ import annotations

from fastapi.routing import APIRoute

from app.modules.cbt.auth.router import router as auth_router
from app.modules.cbt.branding.router import router as branding_router
from app.modules.cbt.results.router import (
    router as results_router,
    superadmin_router,
    tenant_admin_router,
)


def _route_keys(router) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_machine_cbt_routes_expose_result_ingestion_and_branding_projection() -> None:
    assert ("POST", "/results") in _route_keys(results_router)
    assert ("POST", "/results/rollbacks") in _route_keys(results_router)
    assert ("GET", "/results/rollbacks/{operation_id}") in _route_keys(results_router)
    assert ("GET", "/branding") in _route_keys(branding_router)


def test_staff_refresh_requires_idempotency_header() -> None:
    refresh_route = next(
        route
        for route in auth_router.routes
        if isinstance(route, APIRoute)
        and route.path == "/auth/staff/refresh"
        and "POST" in route.methods
    )

    idempotency_header = next(
        parameter
        for parameter in refresh_route.dependant.header_params
        if parameter.alias == "Idempotency-Key"
    )
    assert idempotency_header.field_info.is_required() is True


def test_tenant_admin_audit_routes_are_read_only() -> None:
    routes = _route_keys(tenant_admin_router)
    assert ("GET", "/tenant-admin/cbt/result-ingestions") in routes
    assert ("GET", "/tenant-admin/cbt/result-ingestions/filter-options") in routes
    assert ("GET", "/tenant-admin/cbt/result-ingestions/{batch_record_id}") in routes
    assert ("GET", "/tenant-admin/cbt/result-ingestions/{batch_record_id}/items") in routes
    assert not any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, _ in routes)


def test_superadmin_audit_routes_are_read_only() -> None:
    routes = _route_keys(superadmin_router)
    assert ("GET", "/superadmin/cbt/result-ingestions") in routes
    assert ("GET", "/superadmin/cbt/result-ingestions/filter-options") in routes
    assert ("GET", "/superadmin/cbt/result-ingestions/{batch_record_id}") in routes
    assert ("GET", "/superadmin/cbt/result-ingestions/{batch_record_id}/items") in routes
    assert not any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, _ in routes)
