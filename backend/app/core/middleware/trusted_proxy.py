"""Normalize proxy forwarding headers before security middleware uses client IPs."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from app.config.settings import settings


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
