"""Require an elective group for every elective curriculum subject.

Revision ID: 20261011_elective_group_required
Revises: 20261010_cbt_friendly_dns

Existing ungrouped electives must be assigned their intended groups before
upgrade. This migration deliberately does not invent school selection policies
or change subject meaning. PostgreSQL validates existing rows atomically and
rejects the upgrade if any elective still has no group.

Downgrade removes only the new constraint; repaired group links remain intact.
"""

from alembic import op

revision: str = "20261011_elective_group_required"
down_revision: str | None = "20261010_cbt_friendly_dns"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_elective_subject_requires_group",
        "curriculum_subjects",
        "NOT is_elective OR elective_group_id IS NOT NULL",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_elective_subject_requires_group",
        "curriculum_subjects",
        type_="check",
        schema="public",
    )
