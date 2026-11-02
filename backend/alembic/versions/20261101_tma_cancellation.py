"""Durable TMA cancellation jobs and attempt-owned CA score evidence.

Revision ID: 20261101_tma_cancellation
Revises: 20261101_ai_teacher_purchase
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_tma_cancellation"
down_revision = "20261101_ai_teacher_purchase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL enum additions are forward compatible with existing assignments.
    op.execute("ALTER TYPE public.tma_assignment_status ADD VALUE IF NOT EXISTS 'cancelling'")
    op.execute("ALTER TYPE public.tma_assignment_status ADD VALUE IF NOT EXISTS 'cancelled'")
    op.add_column(
        "tma_attempts",
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_attempts",
        sa.Column("score_snapshot", sa.Numeric(5, 2), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_attempts",
        sa.Column("score_reversed_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_table(
        "tma_cancellation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_by_actor_type",
            postgresql.ENUM(
                "teacher", "tenant_admin", name="tma_actor_type", schema="public", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("requested_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reversed_scores", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_cancellation_assignment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id", "assignment_id"],
            [
                "public.tma_assignment_revisions.tenant_id",
                "public.tma_assignment_revisions.id",
                "public.tma_assignment_revisions.assignment_id",
            ],
            name="fk_tma_cancellation_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "revision_id", name="uq_tma_cancellation_revision"),
        sa.CheckConstraint(
            "status IN ('pending','failed','completed')",
            name="ck_tma_cancellation_status",
        ),
        schema="public",
    )
    op.create_index(
        "ix_tma_cancellation_pending",
        "tma_cancellation_runs",
        ["status", "created_at"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tma_cancellation_pending", table_name="tma_cancellation_runs", schema="public"
    )
    op.drop_table("tma_cancellation_runs", schema="public")
    op.drop_column("tma_attempts", "score_reversed_at", schema="public")
    op.drop_column("tma_attempts", "score_snapshot", schema="public")
    op.drop_column("tma_attempts", "score_id", schema="public")
    # PostgreSQL enum labels are intentionally retained: removing them
    # would require recreating the type and may corrupt existing statuses.
