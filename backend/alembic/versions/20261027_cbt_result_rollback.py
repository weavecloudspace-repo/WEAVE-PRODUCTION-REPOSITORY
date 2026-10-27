"""Add durable, draft-only CBT rollback records and score publication identity."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_cbt_result_rollback"
down_revision = "20261020_hybrid_exam_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("student_assessment_scores", sa.Column("cbt_source_batch_id", sa.UUID(), nullable=True), schema="public")
    op.create_index("ix_student_assessment_cbt_batch", "student_assessment_scores", ["tenant_id", "cbt_source_batch_id"], schema="public")

    # Legacy provenance: backfill only when exactly one APPLIED ingestion item
    # matches the still-current CBT contribution. Ambiguous scores are not auto-withdrawable.
    op.execute("""
    WITH verified AS (
      SELECT s.id AS score_id, b.batch_id,
             row_number() OVER (PARTITION BY s.id ORDER BY b.processed_at DESC, b.id DESC) AS rn,
             count(*) OVER (PARTITION BY s.id) AS matches
      FROM public.student_assessment_scores s
      JOIN public.cbt_result_ingestion_items i
        ON i.tenant_id = s.tenant_id
       AND i.student_subject_result_id = s.student_subject_result_id
       AND i.outcome = 'applied'
       AND i.incoming_score = s.cbt_score
      JOIN public.cbt_result_ingestion_batches b
        ON b.id = i.ingestion_batch_id
       AND b.tenant_id = s.tenant_id
       AND b.assessment_component_id = s.assessment_component_id
       AND b.source_exam_id = s.source_exam_id
      WHERE s.cbt_score IS NOT NULL
        AND ((s.theory_score IS NULL AND s.score = s.cbt_score)
          OR (s.theory_score IS NOT NULL AND s.score = s.cbt_score + s.theory_score))
    )
    UPDATE public.student_assessment_scores s
       SET cbt_source_batch_id = v.batch_id
      FROM verified v WHERE v.score_id = s.id AND v.rn = 1 AND v.matches = 1
    """)
    op.create_table(
        "cbt_result_rollback_operations",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("public.tenants.id"), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("cbt_server_id", sa.UUID(), sa.ForeignKey("public.cbt_servers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("source_batch_id", sa.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "cbt_server_id", "operation_id", name="uq_cbt_rollback_server_operation"),
        schema="public",
    )
    op.create_index("ix_cbt_rollback_tenant_status", "cbt_result_rollback_operations", ["tenant_id", "status"], schema="public")
    op.create_index("ix_cbt_rollback_server_batch", "cbt_result_rollback_operations", ["tenant_id", "cbt_server_id", "source_batch_id"], schema="public")
    op.create_table(
        "cbt_result_rollback_items",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("public.tenants.id"), nullable=False),
        sa.Column("rollback_operation_id", sa.UUID(), sa.ForeignKey("public.cbt_result_rollback_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rollback_operation_id", "student_id", name="uq_cbt_rollback_item_student"),
        schema="public",
    )
    op.create_index("ix_cbt_rollback_item_operation_status", "cbt_result_rollback_items", ["rollback_operation_id", "status"], schema="public")


def downgrade() -> None:
    op.drop_index("ix_cbt_rollback_item_operation_status", table_name="cbt_result_rollback_items", schema="public")
    op.drop_table("cbt_result_rollback_items", schema="public")
    op.drop_index("ix_cbt_rollback_server_batch", table_name="cbt_result_rollback_operations", schema="public")
    op.drop_index("ix_cbt_rollback_tenant_status", table_name="cbt_result_rollback_operations", schema="public")
    op.drop_table("cbt_result_rollback_operations", schema="public")
    op.drop_index("ix_student_assessment_cbt_batch", table_name="student_assessment_scores", schema="public")
    op.drop_column("student_assessment_scores", "cbt_source_batch_id", schema="public")
