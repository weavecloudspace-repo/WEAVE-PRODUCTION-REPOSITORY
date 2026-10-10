"""Stable, collision-resistant DNS names for paired CBT servers.

A school's immutable tenant UUID is its DNS identifier. The registered
server name remains visible, but a server UUID suffix ensures different
names that slugify identically cannot collide. FQDN is environment-specific.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

ROOT_DOMAIN = "weavecloudspace.com"


def hostname_prefix(server_name: str, server_id: UUID) -> str:
    ascii_name = unicodedata.normalize("NFKD", server_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48].strip("-")
    return f"{slug or 'server'}-{server_id.hex[:12]}"


def hostname_for_server(*, prefix: str, tenant_id: UUID, environment: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", prefix):
        raise ValueError("Invalid persisted CBT server DNS label")
    suffix = "cbt" if environment == "production" else "cbt-staging"
    return f"{prefix}.school-{tenant_id.hex}.{suffix}.{ROOT_DOMAIN}"


def challenge_record_name(hostname: str) -> str:
    if not hostname.endswith("." + ROOT_DOMAIN):
        raise ValueError("CBT hostname is outside the expected DNS zone")
    return "_acme-challenge." + hostname[: -(len(ROOT_DOMAIN) + 1)]
