"""Support TMA subject, level and student substring search with pg_trgm.

Use transactional DDL for Weave's externally managed Alembic migration runner.
The extension is retained on downgrade because other indexes may rely on it.
"""

from alembic import op

revision = "20261104_tma_search_trigram"
down_revision = "20261102_tma_revision_safety"
branch_labels = None
depends_on = None


_TRIGRAM_INDEXES = (
    ("ix_subjects_tma_name_trgm", "subjects", "name"),
    ("ix_subjects_tma_code_trgm", "subjects", "code"),
    ("ix_academic_levels_tma_name_trgm", "academic_levels", "name"),
    ("ix_students_tma_admission_trgm", "students", "admission_number"),
)


def upgrade() -> None:
    # Avoid an extended wait behind active writers during deploy. Index creation
    # remains transactional because the migration runner owns the transaction.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index, table, column in _TRIGRAM_INDEXES:
        op.create_index(
            index,
            table,
            [column],
            schema="public",
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    # concat_ws is not IMMUTABLE; use the same expression as the query.
    op.execute(
        """
        CREATE INDEX ix_students_tma_full_name_trgm
        ON public.students USING gin (
            (btrim(coalesce(first_name, '') || ' ' || coalesce(last_name, '')))
            gin_trgm_ops
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_students_tma_full_name_trgm", schema="public")
    for index, _table, _column in reversed(_TRIGRAM_INDEXES):
        op.drop_index(index, schema="public")
