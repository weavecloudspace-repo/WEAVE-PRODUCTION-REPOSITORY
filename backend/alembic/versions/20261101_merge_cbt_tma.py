"""Join existing CBT rollback and TMA migration histories.

This is a graph-only merge: each parent migration owns its own schema changes.
Preserve both histories so databases already on either branch can upgrade safely.
"""

revision = "20261101_merge_cbt_tma"
down_revision = ("20261027_cbt_result_rollback", "20261101_tma_cancellation")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
