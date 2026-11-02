"""Designate tenant-safe TMA lead teacher membership without changing existing assignments.

Revision ID: 20261101_tma_lead_teacher
Revises: 20261101_merge_cbt_tma
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261101_tma_lead_teacher"
down_revision = "20261101_merge_cbt_tma"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_teacher_memberships_tenant_id",
        "teacher_memberships",
        ["tenant_id", "id"],
        schema="public",
    )
    op.add_column(
        "tma_assignments",
        sa.Column("lead_teacher_membership_id", UUID(as_uuid=True), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "fk_tma_assignment_tenant_lead_teacher",
        "tma_assignments",
        "teacher_memberships",
        ["tenant_id", "lead_teacher_membership_id"],
        ["tenant_id", "id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )
    # Existing teacher-authored assignments keep their original lead.
    op.execute("""
        UPDATE public.tma_assignments AS a
        SET lead_teacher_membership_id = a.created_by_actor_id
        FROM public.teacher_memberships AS t
        WHERE a.created_by_actor_type = 'teacher'
          AND a.lead_teacher_membership_id IS NULL
          AND a.tenant_id = t.tenant_id AND a.created_by_actor_id = t.id
    """)


def downgrade() -> None:
    op.drop_constraint(
        "fk_tma_assignment_tenant_lead_teacher",
        "tma_assignments",
        type_="foreignkey",
        schema="public",
    )
    op.drop_column("tma_assignments", "lead_teacher_membership_id", schema="public")
    op.drop_constraint(
        "uq_teacher_memberships_tenant_id",
        "teacher_memberships",
        type_="unique",
        schema="public",
    )
