"""Allow teachers to buy AI credits into their personal quota account.

Revision ID: 20261101_ai_teacher_purchase
Revises: 20261101_tma_closes_at
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_ai_teacher_purchase"
down_revision = "20261101_tma_closes_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cbt_ai_quota_purchases",
        sa.Column(
            "initiated_by_teacher_membership_id",
            postgresql.UUID(as_uuid=True), nullable=True,
        ),
        schema="public",
    )
    op.create_foreign_key(
        "fk_cbt_ai_quota_purchases_teacher",
        "cbt_ai_quota_purchases", "teacher_memberships",
        ["initiated_by_teacher_membership_id"], ["id"],
        source_schema="public", referent_schema="public", ondelete="RESTRICT",
    )
    op.alter_column(
        "cbt_ai_quota_purchases", "initiated_by_admin_id",
        existing_type=postgresql.UUID(as_uuid=True), nullable=True,
        schema="public",
    )
    op.create_check_constraint(
        "ck_cbt_ai_quota_purchase_one_purchaser",
        "cbt_ai_quota_purchases",
        "(initiated_by_admin_id IS NOT NULL) <> "
        "(initiated_by_teacher_membership_id IS NOT NULL)",
        schema="public",
    )
    op.create_index(
        "ix_cbt_ai_quota_purchases_teacher",
        "cbt_ai_quota_purchases",
        ["tenant_id", "initiated_by_teacher_membership_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cbt_ai_quota_purchases_teacher",
        table_name="cbt_ai_quota_purchases", schema="public",
    )
    op.drop_constraint(
        "ck_cbt_ai_quota_purchase_one_purchaser",
        "cbt_ai_quota_purchases", type_="check", schema="public",
    )
    # An admin-only schema cannot represent personal purchases. Refuse
    # data-losing rollback until those purchases have been reconciled.
    bind = op.get_bind()
    count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM public.cbt_ai_quota_purchases "
        "WHERE initiated_by_teacher_membership_id IS NOT NULL"
    )).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade while teacher AI purchases exist; reconcile them first."
        )
    op.alter_column(
        "cbt_ai_quota_purchases", "initiated_by_admin_id",
        existing_type=postgresql.UUID(as_uuid=True), nullable=False,
        schema="public",
    )
    op.drop_constraint(
        "fk_cbt_ai_quota_purchases_teacher",
        "cbt_ai_quota_purchases", type_="foreignkey", schema="public",
    )
    op.drop_column(
        "cbt_ai_quota_purchases", "initiated_by_teacher_membership_id", schema="public",
    )
