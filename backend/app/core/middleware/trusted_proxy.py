"""Normalize proxy forwarding headers before security middleware uses client IPs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any

from app.config.logging import get_logger
from app.config.settings import settings


logger = get_logger(__name__)

# TEMPORARY, STAGING-ONLY. Remove after confirming Railway IP forwarding.
_STAGING_IP_DIAGNOSTIC_FILE = "/tmp/weave-ip-resolution-staging.jsonl"
_STAGING_IP_DIAGNOSTIC_PATHS = frozenset({"/api/v1/auth/login", "/health/live"})


def _write_staging_ip_diagnostic(scope: dict[str, Any], resolved_ip: str | None) -> None:
    """Write relevant proxy identity details to a private container file, not deploy logs."""
    if settings.ENV.value != "stg" or scope.get("path") not in _STAGING_IP_DIAGNOSTIC_PATHS:
        return

    headers = scope.get("headers") or []

    def first_header(name: bytes) -> str | None:
        return next(
            (value.decode("latin-1") for key, value in headers if key.lower() == name),
            None,
        )

    forwarded_for = first_header(b"x-forwarded-for")
    real_ip = first_header(b"x-real-ip")
    test_id = first_header(b"x-weave-ip-test-id")
    asgi_client = scope.get("client")
    asgi_client_ip = asgi_client[0] if asgi_client else None

    # The auth router reads the normalized XFF if this middleware resolved a client.
    auth_ip = (
        resolved_ip
        or (forwarded_for.split(",", 1)[0].strip() if forwarded_for else None)
        or asgi_client_ip
    )
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "method": scope.get("method"),
        "path": scope.get("path"),
        "test_id": test_id[:80] if test_id else None,
        "asgi_client_before_weave": asgi_client_ip,
        "x_forwarded_for": forwarded_for[:512] if forwarded_for else None,
        "x_real_ip": real_ip[:80] if real_ip else None,
        "trust_proxy_headers": settings.TRUST_PROXY_HEADERS,
        "trusted_proxy_hops": settings.TRUSTED_PROXY_HOPS,
        "middleware_resolved_ip": resolved_ip,
        "auth_rate_limit_ip": auth_ip,
    }

    try:
        # Append a single JSONL record; 0600 prevents access by other local users.
        data = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(
            _STAGING_IP_DIAGNOSTIC_FILE,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError:
        # Diagnostics must never prevent a real login.
        logger.warning("staging_ip_diagnostic_file_write_failed")


class TrustedProxyHeadersMiddleware:
    """Replace untrusted forwarding chains with one validated client address."""

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _resolved_ip(scope: dict[str, Any]) -> str | None:
        headers = scope.get("headers") or []
        forwarded_for = None
        for raw_name, raw_value in headers:
            if raw_name.lower() == b"x-forwarded-for":
                forwarded_for = raw_value.decode("latin-1")
                break

        if settings.TRUST_PROXY_HEADERS and forwarded_for:
            chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            if chain:
                # X-Forwarded-For is ordered from the original sender to the
                # nearest forwarding address. TRUSTED_PROXY_HOPS includes the
                # immediate socket peer, which is not normally present in the
                # header, so select the rightmost untrusted header entry.
                index = max(len(chain) - settings.TRUSTED_PROXY_HOPS, 0)
                candidate = chain[index]
                try:
                    return str(ip_address(candidate))
                except ValueError:
                    pass

        client = scope.get("client")
        if client and client[0]:
            try:
                return str(ip_address(client[0]))
            except ValueError:
                return None
        return None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        resolved_ip = self._resolved_ip(scope)
        _write_staging_ip_diagnostic(scope, resolved_ip)
        if resolved_ip:
            original_client = scope.get("client")
            port = original_client[1] if original_client else 0
            scope = dict(scope)
            scope["client"] = (resolved_ip, port)

            sanitized_headers = [
                (name, value)
                for name, value in scope.get("headers") or []
                if name.lower() not in {b"x-forwarded-for", b"x-real-ip"}
            ]
            sanitized_headers.append((b"x-forwarded-for", resolved_ip.encode("ascii")))
            sanitized_headers.append((b"x-real-ip", resolved_ip.encode("ascii")))
            scope["headers"] = sanitized_headers

        await self.app(scope, receive, send)
