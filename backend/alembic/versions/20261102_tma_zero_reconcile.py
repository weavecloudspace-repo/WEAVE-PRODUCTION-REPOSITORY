"""Persist per-student TMA missed-zero reconciliation without modifying existing scores.

Revision ID: 20261102_tma_zero_reconcile
Revises: 20261102_tma_draft_delete
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261102_tma_zero_reconcile"
down_revision = "20261102_tma_draft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tma_zero_grading_failures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_zero_failure_tenant_assignment",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "assignment_id", "student_id",
            name="uq_tma_zero_failure_tenant_assignment_student",
        ),
        schema="public",
    )
    op.create_index(
        "ix_tma_zero_failure_pending", "tma_zero_grading_failures",
        ["tenant_id", "assignment_id", "resolved_at"], schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tma_zero_failure_pending",
        table_name="tma_zero_grading_failures",
        schema="public",
    )
    op.drop_table("tma_zero_grading_failures", schema="public")
