"""Freeze human-friendly CBT school/server labels.

Revision ID: 20261010_cbt_friendly_dns
Revises: 20261010_cbt_bunny_dns
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261010_cbt_friendly_dns"
down_revision: str | Sequence[str] | None = "20261010_cbt_bunny_dns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slug(text: str, limit: int = 63) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    label = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return label[:limit].strip("-") or "server"


def upgrade() -> None:
    op.add_column(
        "cbt_servers", sa.Column("dns_school_slug", sa.String(63), nullable=True), schema="public"
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT s.id, s.name, s.tenant_id, t.slug "
            "FROM public.cbt_servers s JOIN public.tenants t ON t.id = s.tenant_id "
            "ORDER BY s.paired_at, s.id"
        )
    ).all()
    schools: dict[object, str] = {}
    reserved_schools: dict[str, object] = {}
    taken: set[tuple[str, str]] = set()
    for server_id, server_name, tenant_id, tenant_slug in rows:
        if tenant_id not in schools:
            school = _slug(tenant_slug)
            if school in reserved_schools and reserved_schools[school] != tenant_id:
                school = f"{_slug(tenant_slug, 54)}-{tenant_id.hex[:8]}"
            if school in reserved_schools and reserved_schools[school] != tenant_id:
                raise ValueError("Conflicting school DNS label during migration")
            schools[tenant_id] = school
            reserved_schools[school] = tenant_id
        school = schools[tenant_id]
        label = _slug(server_name)
        if (school, label) in taken:
            label = f"{_slug(server_name, 54)}-{server_id.hex[:8]}"
        if (school, label) in taken:
            raise ValueError("Conflicting server DNS label during migration")
        taken.add((school, label))
        connection.execute(
            sa.text(
                "UPDATE public.cbt_servers SET dns_school_slug=:school, "
                "hostname_prefix=:label WHERE id=:id"
            ),
            {"school": school, "label": label, "id": server_id},
        )
    op.alter_column("cbt_servers", "dns_school_slug", nullable=False, schema="public")
    op.create_unique_constraint(
        "uq_cbt_servers_dns_hostname",
        "cbt_servers",
        ["dns_school_slug", "hostname_prefix"],
        schema="public",
    )


def downgrade() -> None:
    # Reverting would silently change an already issued hostname/certificate.
    raise RuntimeError("CBT DNS hostname migration cannot be automatically reversed")
