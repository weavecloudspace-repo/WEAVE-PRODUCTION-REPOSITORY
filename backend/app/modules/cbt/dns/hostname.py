"""Human-readable, persisted CBT hostname labels with explicit environment mapping."""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

ROOT_DOMAIN = "weavecloudspace.com"
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def slug_label(value: str, *, max_length: int = 63) -> str:
    if not 1 <= max_length <= 63:
        raise ValueError("Invalid maximum DNS label length")
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    label = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return label[:max_length].strip("-") or "server"


def school_label(school_slug: str) -> str:
    return slug_label(school_slug)


def hostname_prefix(server_name: str, server_id: UUID | None = None) -> str:
    """Readable primary label, with no exposed machine UUID."""
    return slug_label(server_name)


def collision_label(server_name: str, server_id: UUID) -> str:
    """Stable fallback when another server owns the readable name."""
    return f"{slug_label(server_name, max_length=54)}-{server_id.hex[:8]}"


def hostname_for_server(*, prefix: str, school_slug: str, environment: str) -> str:
    if not DNS_LABEL.fullmatch(prefix) or not DNS_LABEL.fullmatch(school_slug):
        raise ValueError("Invalid persisted CBT DNS label")
    if environment in ("prod", "production"):
        suffix = "cbt"
    elif environment in ("stg", "staging", "dev", "development"):
        suffix = "cbt-staging"
    else:
        raise ValueError("Unsupported WEAVE environment for CBT DNS")
    return f"{prefix}.{school_slug}.{suffix}.{ROOT_DOMAIN}"


def challenge_record_name(hostname: str) -> str:
    if not hostname.endswith("." + ROOT_DOMAIN):
        raise ValueError("CBT hostname is outside the expected DNS zone")
    return "_acme-challenge." + hostname[: -(len(ROOT_DOMAIN) + 1)]
