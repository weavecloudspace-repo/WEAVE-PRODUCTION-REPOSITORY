"""Add informational target closing time to TMA assignments.

Revision ID: 20261101_tma_closes_at
Revises: 20261101_tma

This field does not trigger automatic closure or enforce deadlines.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261101_tma_closes_at"
down_revision = "20261101_tma"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tma_assignments",
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("tma_assignments", "closes_at", schema="public")
