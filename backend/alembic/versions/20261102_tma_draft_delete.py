"""Durable storage cleanup after unpublished TMA draft deletion.

Revision ID: 20261102_tma_draft_delete
Revises: 20261102_tma_missed_zero
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261102_tma_draft_delete"
down_revision = "20261102_tma_missed_zero"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tma_draft_media_cleanup",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_tma_draft_media_cleanup_object"),
        schema="public",
    )
    op.create_index(
        "ix_tma_draft_media_cleanup_created",
        "tma_draft_media_cleanup",
        ["created_at"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tma_draft_media_cleanup_created",
        table_name="tma_draft_media_cleanup",
        schema="public",
    )
    op.drop_table("tma_draft_media_cleanup", schema="public")
