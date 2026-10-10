"""FastAPI application factory and router registration."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text

import app.models  # noqa: F401
from app.config.database import AsyncSessionLocal, engine
from app.config.database_bootstrap import bootstrap_database
from app.config.logging import get_logger, resolve_log_level
from app.config.sentry import flush_sentry, initialize_sentry
from app.config.settings import settings
from app.core.cache.redis import close_redis, connect_redis, redis_health_check
from app.core.dependencies.route_guards import get_current_superadmin
from app.core.exception_handlers import register_exception_handlers
from app.core.middleware.cookie_request_protection import CookieRequestProtectionMiddleware
from app.core.middleware.platform_lockdown import PlatformLockdownMiddleware
from app.core.middleware.request_timing import RequestTimingMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.core.middleware.trusted_proxy import TrustedProxyHeadersMiddleware
from app.core.runtime_config import router as runtime_config_router
from app.modules.attendance.router import (
    parent_router as parent_attendance_router,
    student_router as student_attendance_router,
    teacher_router as teacher_attendance_router,
    tenant_admin_router as tenant_admin_attendance_router,
)
from app.modules.auth.router import router as auth_router
from app.modules.bulk_imports.router import router as bulk_import_router
from app.modules.cbt.academics.router import router as cbt_academics_router
from app.modules.cbt.ai.router import router as cbt_ai_router
from app.modules.cbt.auth.router import router as cbt_auth_router
from app.modules.cbt.branding.router import router as cbt_branding_router
from app.modules.cbt.pairing.router import router as cbt_pairing_router
from app.modules.cbt.dns.router import router as cbt_dns_router
from app.modules.cbt.results.router import (
    router as cbt_results_router,
    superadmin_router as cbt_result_superadmin_router,
    tenant_admin_router as cbt_result_tenant_admin_router,
)
from app.modules.cbt.sync.listener import cbt_sync_listener
from app.modules.cbt.sync.router import router as cbt_sync_router
from app.modules.cbt.sync.websocket_router import router as cbt_sync_websocket_router
from app.modules.classes.academic_levels_router import router as academic_levels_router
from app.modules.classes.departments_router import router as departments_router
from app.modules.classes.router import router as class_router
from app.modules.communications.router import (
    inbox_router,
    messages_router,
    notices_router,
    notifications_router,
    router as communication_router,
    superadmin_notice_router,
    teacher_notice_router,
    tenant_admin_notice_router,
)
from app.modules.email_outbox.router import router as email_outbox_router
from app.modules.legal_compliance.router import router as legal_compliance_router
from app.modules.media.router import router as media_router
from app.modules.metrics.events import register_metrics_cache_invalidation_events
from app.modules.metrics.router import router as metrics_router
from app.modules.parents.router import router as parent_router
from app.modules.payments.router import router as payments_router
from app.modules.realtime.broker import realtime_broker
from app.modules.realtime.router import router as realtime_router
from app.modules.report_cards.bulk_router import router as bulk_report_card_router
from app.modules.report_cards.comment_router import (
    admin_override_router as admin_teacher_comment_override_router,
    admin_template_router as admin_comment_template_router,
    teacher_comment_router,
    teacher_template_router as teacher_comment_template_router,
)
from app.modules.report_cards.fixed_router import router as fixed_report_card_router
from app.modules.report_cards.router import (
    parent_router as parent_report_card_router,
    student_router as student_report_card_router,
    tenant_admin_router as tenant_admin_report_card_router,
)
from app.modules.school_calendar.admin_router import router as school_calendar_admin_router
from app.modules.school_calendar.shared_router import router as school_calendar_shared_router
from app.modules.search.router import router as tenant_search_router
from app.modules.setup_assistant.router import router as setup_assistant_router
from app.modules.student_academics.assessment_config_router import (
    router as assessment_config_router,
    student_router as assessment_student_router,
    teacher_router as assessment_teacher_router,
)
from app.modules.student_academics.bulk_results_router import (
    admin_router as bulk_results_admin_router,
)
from app.modules.student_academics.curriculum_router import router as curriculum_router
from app.modules.student_academics.elective_router import (
    student_router as elective_student_router,
)
from app.modules.student_academics.grading_readiness_router import (
    router as grading_readiness_router,
)
from app.modules.student_academics.grading_scale_lifecycle_router import (
    router as grading_scale_lifecycle_router,
)
from app.modules.student_academics.open_session_config_router import (
    router as open_session_config_router,
)
from app.modules.student_academics.router import (
    parent_router as parent_academic_router,
    student_router as student_academic_router,
    teacher_router as teacher_academic_router,
    tenant_admin_router as tenant_admin_academic_router,
)
from app.modules.student_academics.session_closure_router import router as session_closure_router
from app.modules.student_academics.subject_card_router import (
    parent_router as current_subject_card_parent_router,
    student_router as current_subject_card_student_router,
)
from app.modules.student_academics.teacher_grading_router import router as teacher_grading_router
from app.modules.student_academics.write_guard import ensure_admin_academic_write_window
from app.modules.students.academic_context_router import router as student_academic_context_router
from app.modules.students.placement_router import router as student_placement_router
from app.modules.students.router import router as student_router
from app.modules.subjects.router import router as subject_router
from app.modules.subscriptions.router import router as subscriptions_router
from app.modules.superadmin.bootstrap import SuperadminBootstrapService
from app.modules.superadmin.models import SuperAdmin
from app.modules.superadmin.router import router as superadmin_router
from app.modules.teachers.router import router as teacher_router
from app.modules.tenant_admins.router import router as tenant_admin_router
from app.modules.tenant_branding.router import (
    router as tenant_branding_router,
    workspace_router as workspace_branding_router,
)
from app.modules.user_guides.router import router as user_guides_router
from app.tenant_management.router import router as tenant_router

logger = get_logger(__name__)
RouteKey = tuple[str, str]
API_V1_PREFIX = settings.API_V1_PREFIX
_TENANT_ADMIN_ACADEMIC_OVERRIDES: set[RouteKey] = {
    ("GET", "/tenant-admin/academics/grading-scales/readiness-preview"),
    ("PATCH", "/tenant-admin/academics/sessions/{session_id}"),
}
_TEACHER_ACADEMIC_OVERRIDES: set[RouteKey] = set()
_STUDENT_ACADEMIC_OVERRIDES: set[RouteKey] = {
    ("GET", "/students/academics/subjects"),
}
_PARENT_ACADEMIC_OVERRIDES: set[RouteKey] = {
    ("GET", "/parents/academics/students/{student_id}/subjects"),
}


def _exclude_overridden_routes(router: APIRouter, overrides: set[RouteKey]) -> None:
    """Remove aggregate handlers superseded by dedicated canonical routers."""

    router.routes[:] = [
        route
        for route in router.routes
        if not (
            isinstance(route, APIRoute)
            and any((method, route.path) in overrides for method in route.methods)
        )
    ]


def _prepare_academic_routers() -> None:
    """Ensure aggregate academic routers do not duplicate canonical handlers."""

    _exclude_overridden_routes(tenant_admin_academic_router, _TENANT_ADMIN_ACADEMIC_OVERRIDES)
    _exclude_overridden_routes(teacher_academic_router, _TEACHER_ACADEMIC_OVERRIDES)
    _exclude_overridden_routes(student_academic_router, _STUDENT_ACADEMIC_OVERRIDES)
    _exclude_overridden_routes(parent_academic_router, _PARENT_ACADEMIC_OVERRIDES)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _ = app
    logger.info("Starting Weave API")
    await bootstrap_database(engine)
    await connect_redis()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await SuperadminBootstrapService.ensure_bootstrap_superadmin(db)
    await realtime_broker.start()
    await cbt_sync_listener.start()
    try:
        yield
    finally:
        logger.info("Closing Redis and database resources")
        try:
            await cbt_sync_listener.stop()
            await realtime_broker.stop()
            try:
                await close_redis()
            finally:
                await engine.dispose()
        finally:
            await flush_sentry()


async def _database_health_check() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database health check failed.")
        return False


def create_app() -> FastAPI:
    initialize_sentry(service="api")
    register_metrics_cache_invalidation_events()
    _prepare_academic_routers()

    app = FastAPI(
        title="Weave Assistant",
        description="School management and academic workflow API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
    )
    middleware_options: dict[str, Any] = {
        "allow_origins": settings.ALLOWED_ORIGINS,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if settings.is_development:
        middleware_options["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    app.add_middleware(PlatformLockdownMiddleware)
    app.add_middleware(CookieRequestProtectionMiddleware)
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        allow_docs_cdn=settings.is_development,
        strict_transport_security=settings.is_production_like,
    )
    app.add_middleware(CORSMiddleware, **middleware_options)
    app.add_middleware(TrustedProxyHeadersMiddleware)
    register_exception_handlers(app)

    app.include_router(auth_router, prefix=f"{API_V1_PREFIX}/auth", tags=["Auth"])
    app.include_router(runtime_config_router, prefix=API_V1_PREFIX)
    app.include_router(superadmin_router, prefix=API_V1_PREFIX)
    app.include_router(
        tenant_admin_router,
        prefix=f"{API_V1_PREFIX}/tenant-admin",
        tags=["Tenant Admin"],
    )
    app.include_router(student_placement_router, prefix=API_V1_PREFIX)
    app.include_router(media_router, prefix=f"{API_V1_PREFIX}/tenant-admin")
    app.include_router(tenant_branding_router, prefix=f"{API_V1_PREFIX}/tenant-admin")
    app.include_router(workspace_branding_router, prefix=API_V1_PREFIX)
    app.include_router(bulk_import_router, prefix=f"{API_V1_PREFIX}/tenant-admin")
    app.include_router(email_outbox_router, prefix=f"{API_V1_PREFIX}/tenant-admin")
    app.include_router(setup_assistant_router, prefix=API_V1_PREFIX)
    app.include_router(legal_compliance_router, prefix=API_V1_PREFIX)
    app.include_router(tenant_router, prefix=f"{API_V1_PREFIX}/tenants", tags=["Tenants"])
    app.include_router(teacher_router, prefix=f"{API_V1_PREFIX}/teachers", tags=["Teachers"])
    app.include_router(student_router, prefix=f"{API_V1_PREFIX}/students", tags=["Students"])
    app.include_router(student_academic_context_router, prefix=API_V1_PREFIX)
    app.include_router(parent_router, prefix=API_V1_PREFIX)
    app.include_router(realtime_router, prefix=API_V1_PREFIX)
    app.include_router(subject_router, prefix=f"{API_V1_PREFIX}/subjects", tags=["Subjects"])
    app.include_router(class_router, prefix=API_V1_PREFIX, tags=["Classes"])
    app.include_router(academic_levels_router, prefix=API_V1_PREFIX)
    app.include_router(departments_router, prefix=API_V1_PREFIX)
    app.include_router(communication_router, prefix=API_V1_PREFIX)
    app.include_router(messages_router, prefix=API_V1_PREFIX)
    app.include_router(inbox_router, prefix=API_V1_PREFIX)
    app.include_router(notifications_router, prefix=API_V1_PREFIX)
    app.include_router(notices_router, prefix=API_V1_PREFIX)
    app.include_router(superadmin_notice_router, prefix=API_V1_PREFIX)
    app.include_router(tenant_admin_notice_router, prefix=API_V1_PREFIX)
    app.include_router(teacher_notice_router, prefix=API_V1_PREFIX)
    app.include_router(metrics_router, prefix=API_V1_PREFIX)
    app.include_router(assessment_teacher_router, prefix=API_V1_PREFIX)
    app.include_router(curriculum_router, prefix=API_V1_PREFIX)
    app.include_router(assessment_student_router, prefix=API_V1_PREFIX)
    app.include_router(elective_student_router, prefix=API_V1_PREFIX)
    app.include_router(current_subject_card_student_router, prefix=API_V1_PREFIX)
    app.include_router(current_subject_card_parent_router, prefix=API_V1_PREFIX)
    app.include_router(grading_readiness_router, prefix=API_V1_PREFIX)
    app.include_router(open_session_config_router, prefix=API_V1_PREFIX)
    app.include_router(session_closure_router, prefix=API_V1_PREFIX)
    app.include_router(school_calendar_admin_router, prefix=API_V1_PREFIX)
    app.include_router(school_calendar_shared_router, prefix=API_V1_PREFIX)
    app.include_router(tenant_admin_attendance_router, prefix=API_V1_PREFIX)
    app.include_router(teacher_attendance_router, prefix=API_V1_PREFIX)
    app.include_router(student_attendance_router, prefix=API_V1_PREFIX)
    app.include_router(parent_attendance_router, prefix=API_V1_PREFIX)
    app.include_router(cbt_pairing_router, prefix=f"{API_V1_PREFIX}/cbt")
app.include_router(cbt_dns_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_auth_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_ai_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_academics_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_branding_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_results_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_sync_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_sync_websocket_router, prefix=f"{API_V1_PREFIX}/cbt")
    app.include_router(cbt_result_tenant_admin_router, prefix=API_V1_PREFIX)
    app.include_router(cbt_result_superadmin_router, prefix=API_V1_PREFIX)

    admin_write_guard = [Depends(ensure_admin_academic_write_window)]
    app.include_router(
        tenant_admin_academic_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(
        bulk_results_admin_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(
        assessment_config_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(
        grading_scale_lifecycle_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(teacher_academic_router, prefix=API_V1_PREFIX)
    app.include_router(teacher_grading_router, prefix=API_V1_PREFIX)
    app.include_router(student_academic_router, prefix=API_V1_PREFIX)
    app.include_router(parent_academic_router, prefix=API_V1_PREFIX)
    app.include_router(teacher_comment_router, prefix=API_V1_PREFIX)
    app.include_router(teacher_comment_template_router, prefix=API_V1_PREFIX)
    app.include_router(
        admin_comment_template_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(
        admin_teacher_comment_override_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(fixed_report_card_router, prefix=API_V1_PREFIX)
    app.include_router(
        bulk_report_card_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(
        tenant_admin_report_card_router,
        prefix=API_V1_PREFIX,
        dependencies=admin_write_guard,
    )
    app.include_router(student_report_card_router, prefix=API_V1_PREFIX)
    app.include_router(parent_report_card_router, prefix=API_V1_PREFIX)
    app.include_router(tenant_search_router, prefix=API_V1_PREFIX)
    app.include_router(payments_router, prefix=API_V1_PREFIX)
    app.include_router(subscriptions_router, prefix=API_V1_PREFIX)
    app.include_router(user_guides_router, prefix=API_V1_PREFIX)

    @app.post(
        "/internal/diagnostics/sentry-error",
        tags=["Diagnostics"],
        include_in_schema=False,
    )
    async def test_sentry_error(
        current_superadmin: SuperAdmin = Depends(get_current_superadmin),
    ) -> None:
        _ = current_superadmin
        raise RuntimeError("WEAVE_SENTRY_DIAGNOSTIC_TEST")

    @app.get("/health/live", tags=["Health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health", tags=["Health"])
    @app.get("/health/ready", tags=["Health"])
    async def readiness() -> JSONResponse:
        database_ok = await _database_health_check()
        redis_ok = await redis_health_check()
        ready = database_ok and redis_ok
        return JSONResponse(
            status_code=(status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE),
            content={
                "status": "ready" if ready else "unavailable",
                "dependencies": {
                    "database": "ok" if database_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                },
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    import logging

    import uvicorn

    uvicorn_log_level = logging.getLevelName(resolve_log_level()).lower()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=uvicorn_log_level,
        access_log=settings.is_development,
    )
