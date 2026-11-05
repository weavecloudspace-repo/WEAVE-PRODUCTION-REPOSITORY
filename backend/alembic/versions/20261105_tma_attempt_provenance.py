"""Retain real-start and replacement provenance for reopened TMA attempts.

This migration is additive and intentionally leaves historical unknown starts
NULL. It does not update academic scores, attempt statuses, or saved answers.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261105_tma_attempt_provenance"
down_revision = "20261104_tma_search_trigram"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tma_attempts",
        sa.Column("student_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_attempts",
        sa.Column("started_by_student", sa.Boolean(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tma_attempts",
        sa.Column("auto_zero_resolved_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    # Do not discard provenance collected by a later live release.
    raise RuntimeError(
        "TMA attempt provenance contains academic history; use a forward repair."
    )
