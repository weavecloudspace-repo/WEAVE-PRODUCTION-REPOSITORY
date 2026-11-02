"""Track idempotent, reversible TMA missed-deadline scores.

Revision ID: 20261102_tma_missed_zero
Revises: 20261101_tma_lead_teacher
"""

from alembic import op
import sqlalchemy as sa

revision = "20261102_tma_missed_zero"
down_revision = "20261101_tma_lead_teacher"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tma_assignments",
        sa.Column("zero_grading_requested_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_assignments",
        sa.Column("zero_grading_completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_assignments",
        sa.Column("zero_grading_error", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_attempts",
        sa.Column("auto_zeroed_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("tma_attempts", "auto_zeroed_at", schema="public")
    op.drop_column("tma_assignments", "zero_grading_error", schema="public")
    op.drop_column("tma_assignments", "zero_grading_completed_at", schema="public")
    op.drop_column("tma_assignments", "zero_grading_requested_at", schema="public")
