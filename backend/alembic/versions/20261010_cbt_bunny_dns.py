"""Persist CBT server hostname labels and owned DNS-01 challenge records.

Revision ID: 20261010_cbt_bunny_dns
Revises: 20260911_initial_schema
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261010_cbt_bunny_dns"
down_revision: str | Sequence[str] | None = "20260911_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _server_label(name: str, server_id: object) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48].strip("-")
    return f"{slug or 'server'}-{str(server_id).replace('-', '')[:12]}"


def upgrade() -> None:
    op.add_column("cbt_servers", sa.Column("hostname_prefix", sa.String(63), nullable=True), schema="public")
    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT id, name FROM public.cbt_servers")).all()
    for server_id, name in existing:
        conn.execute(
            sa.text("UPDATE public.cbt_servers SET hostname_prefix = :label WHERE id = :server_id"),
            {"label": _server_label(name, server_id), "server_id": server_id},
        )
    op.alter_column("cbt_servers", "hostname_prefix", nullable=False, schema="public")

    op.create_table(
        "cbt_dns_challenges",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("fqdn", sa.String(253), nullable=False),
        sa.Column("value_sha256", sa.String(64), nullable=False),
        sa.Column("provider_record_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["public.cbt_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id"),
        sa.UniqueConstraint("server_id", "request_id", name="uq_cbt_dns_challenges_server_request"),
        schema="public",
    )
    op.create_index(
        "ix_cbt_dns_challenges_expiry",
        "cbt_dns_challenges",
        ["expires_at"],
        unique=False,
        schema="public",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_cbt_dns_challenges_tenant_server",
        "cbt_dns_challenges",
        ["tenant_id", "server_id"],
        unique=False,
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_cbt_dns_challenges_tenant_server", table_name="cbt_dns_challenges", schema="public")
    op.drop_index("ix_cbt_dns_challenges_expiry", table_name="cbt_dns_challenges", schema="public")
    op.drop_table("cbt_dns_challenges", schema="public")
    op.drop_column("cbt_servers", "hostname_prefix", schema="public")
