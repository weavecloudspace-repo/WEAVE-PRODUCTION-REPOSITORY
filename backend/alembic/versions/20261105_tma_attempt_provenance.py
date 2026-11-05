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
    # The old revision-wide capture trigger is incompatible with dynamic
    # eligibility and repeated closure. Retain all historical snapshot rows.
    for table in (
        "students",
        "student_enrollments",
        "student_elective_selections",
        "classes",
        "academic_levels",
        "curricula",
        "curriculum_subjects",
        "subjects",
        "curriculum_subject_departments",
        "class_term_department_assignments",
        "academic_level_departments",
        "departments",
        "academic_terms",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS tma_preserve_deadline ON public.{table}"
        )

    op.create_table(
        "tma_closure_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_closure_tenant_assignment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            ["public.tma_assignment_revisions.tenant_id", "public.tma_assignment_revisions.id"],
            name="fk_tma_closure_tenant_revision", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "assignment_id", "closed_at",
            name="uq_tma_closure_assignment_closed_at",
        ),
        schema="public",
    )
    op.create_index(
        "ix_tma_closure_assignment", "tma_closure_runs",
        ["tenant_id", "assignment_id", "closed_at"], schema="public",
    )
    # Preserve already closed assignments as legacy closure events. This
    # does not change any existing attempt, mark, report card, or revision.
    op.execute("""
        INSERT INTO public.tma_closure_runs (
            id, tenant_id, assignment_id, revision_id, closed_at,
            cutoff_at, original_deadline_at, kind, completed_at
        )
        SELECT gen_random_uuid(), a.tenant_id, a.id, r.id, a.closed_at,
            LEAST(a.closes_at, a.closed_at), a.closes_at, 'legacy',
            a.zero_grading_completed_at
        FROM public.tma_assignments a
        JOIN public.tma_assignment_revisions r
          ON r.tenant_id = a.tenant_id
         AND r.assignment_id = a.id
         AND r.revision_number = a.current_revision_number
        WHERE a.status::text = 'closed' AND a.closed_at IS NOT NULL
          AND a.closes_at IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

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
    raise RuntimeError("TMA attempt provenance contains academic history; use a forward repair.")
