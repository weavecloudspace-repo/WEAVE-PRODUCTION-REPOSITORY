"""Introduce opt-in hybrid CBT/theory scores without changing existing results."""

from alembic import op
import sqlalchemy as sa

revision = "20261020_hybrid_exam_scores"
down_revision = "20261011_elective_group_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_components",
        sa.Column("is_hybrid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="public",
    )
    op.create_check_constraint(
        "ck_assessment_component_hybrid_examinable",
        "assessment_components",
        "NOT is_hybrid OR is_examinable",
        schema="public",
    )
    for name, column_type in (
        ("cbt_score", sa.Numeric(5, 2)),
        ("cbt_maximum_score", sa.Numeric(5, 2)),
        ("theory_score", sa.Numeric(5, 2)),
        ("source_exam_id", sa.UUID()),
    ):
        op.add_column(
            "student_assessment_scores",
            sa.Column(name, column_type, nullable=True),
            schema="public",
        )
    op.create_check_constraint(
        "ck_student_assessment_cbt_nonnegative",
        "student_assessment_scores",
        "cbt_score IS NULL OR cbt_score >= 0",
        schema="public",
    )
    op.create_check_constraint(
        "ck_student_assessment_theory_nonnegative",
        "student_assessment_scores",
        "theory_score IS NULL OR theory_score >= 0",
        schema="public",
    )
    op.create_check_constraint(
        "ck_student_assessment_cbt_max_positive",
        "student_assessment_scores",
        "cbt_maximum_score IS NULL OR cbt_maximum_score > 0",
        schema="public",
    )
    op.add_column(
        "cbt_result_ingestion_batches",
        sa.Column("cbt_maximum_score", sa.Numeric(5, 2), nullable=True),
        schema="public",
    )
    op.create_table(
        "cbt_exam_score_allocations",
        sa.Column("cbt_server_id", sa.UUID(), nullable=False),
        sa.Column("source_exam_id", sa.UUID(), nullable=False),
        sa.Column("academic_session_id", sa.UUID(), nullable=False),
        sa.Column("academic_term_id", sa.UUID(), nullable=False),
        sa.Column("academic_level_id", sa.UUID(), nullable=False),
        sa.Column("curriculum_subject_id", sa.UUID(), nullable=False),
        sa.Column("assessment_component_id", sa.UUID(), nullable=False),
        sa.Column("component_maximum_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("cbt_maximum_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "cbt_maximum_score > 0 AND cbt_maximum_score <= component_maximum_score",
            name="ck_cbt_exam_allocation_valid_maximum",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "cbt_server_id",
            "source_exam_id",
            name="uq_cbt_exam_allocation_tenant_server_exam",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"]),
        sa.ForeignKeyConstraint(["cbt_server_id"], ["public.cbt_servers.id"], ondelete="RESTRICT"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("cbt_exam_score_allocations", schema="public")
    op.drop_column("cbt_result_ingestion_batches", "cbt_maximum_score", schema="public")
    for constraint in (
        "ck_student_assessment_cbt_nonnegative",
        "ck_student_assessment_theory_nonnegative",
        "ck_student_assessment_cbt_max_positive",
    ):
        op.drop_constraint(constraint, "student_assessment_scores", type_="check", schema="public")
    for column in ("source_exam_id", "theory_score", "cbt_maximum_score", "cbt_score"):
        op.drop_column("student_assessment_scores", column, schema="public")
    op.drop_constraint(
        "ck_assessment_component_hybrid_examinable",
        "assessment_components",
        type_="check",
        schema="public",
    )
    op.drop_column("assessment_components", "is_hybrid", schema="public")
