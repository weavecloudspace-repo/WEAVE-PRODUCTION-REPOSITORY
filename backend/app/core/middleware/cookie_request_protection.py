"""Protect cookie-authenticated mutation endpoints from cross-site requests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config.settings import settings

_PROTECTED_ROUTES = frozenset(
    {
        f"{settings.API_V1_PREFIX}/auth/refresh",
        f"{settings.API_V1_PREFIX}/auth/logout",
    }
)
_CSRF_HEADER_NAME = "x-weave-csrf"
_CSRF_HEADER_VALUE = "1"


def _normalized_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _allowed_origins() -> set[str]:
    origins = {
        normalized
        for origin in settings.ALLOWED_ORIGINS
        if (normalized := _normalized_origin(origin)) is not None
    }
    if (
        settings.ALLOW_CROSS_SITE_REFRESH_COOKIE
        and settings.ENV.value == "prod"
        and datetime.now(timezone.utc) < datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc)
    ):
        origins.add(settings.TEMPORARY_FRONTEND_ORIGIN)
    return origins


def _development_local_origin(origin: str) -> bool:
    if not settings.is_development:
        return False
    parsed = urlsplit(origin)
    return parsed.hostname in {"localhost", "127.0.0.1"}


class CookieRequestProtectionMiddleware:
    """Require a trusted browser origin and an explicit CSRF request header."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if request.method != "POST" or request.url.path not in _PROTECTED_ROUTES:
            await self.app(scope, receive, send)
            return

        if request.headers.get(_CSRF_HEADER_NAME) != _CSRF_HEADER_VALUE:
            response = JSONResponse(
                status_code=403,
                content={"detail": "Missing CSRF protection header."},
            )
            await response(scope, receive, send)
            return

        origin = _normalized_origin(request.headers.get("origin"))
        if origin is None:
            origin = _normalized_origin(request.headers.get("referer"))

        allowed = _allowed_origins()
        if origin is None or (origin not in allowed and not _development_local_origin(origin)):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Untrusted request origin."},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
