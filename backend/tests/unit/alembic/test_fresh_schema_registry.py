"""Regression checks for the fresh Alembic schema baseline."""

from io import StringIO
from pathlib import Path
import re

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.config.schema_baseline import BASELINE_REVISION, BASELINE_TABLES
from app.modules.student_academics.models import StudentProgressionRun
from app.shared.base_model import Base

CRITICAL_TABLES = {
    "tenants",
    "tenant_admins",
    "teacher_accounts",
    "teacher_memberships",
    "parent_accounts",
    "parent_memberships",
    "students",
    "student_enrollments",
    "auth_identities",
    "auth_sessions",
    "auth_refresh_tokens",
    "media_assets",
    "platform_controls",
    "security_ip_blocks",
    "email_outbox",
    "import_jobs",
    "academic_levels",
    "departments",
    "arm_labels",
    "classes",
    "curricula",
    "curriculum_elective_groups",
    "curriculum_subjects",
    "student_elective_selections",
    "curriculum_subject_departments",
    "class_term_department_assignments",
    "teacher_assignments",
    "academic_sessions",
    "academic_terms",
    "assessment_schemes",
    "assessment_components",
    "student_subject_results",
    "report_cards",
    "report_card_subject_lines",
    "report_card_subject_components",
    "comment_templates",
    "student_term_teacher_comments",
    "teacher_comment_overrides",
    "cbt_servers",
    "cbt_server_credentials",
    "cbt_pairing_codes",
    "cbt_sync_tenant_states",
    "cbt_sync_changes",
    "tenant_subscriptions",
    "payment_transactions",
    "term_plan_entitlements",
    "payment_webhook_events",
}

OBSOLETE_ACADEMIC_TABLES = {
    "curriculum_offerings",
    "level_subjects",
    "student_department_assignments",
}


def test_alembic_has_one_current_schema_head_and_one_root_baseline() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    config = Config(str(backend_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    # Later migrations must not force changes to the immutable initial revision.
    assert len(script.get_heads()) == 1
    head = script.get_revision(BASELINE_REVISION)
    assert head is not None
    assert head.down_revision is None
    assert any(rev.revision == BASELINE_REVISION for rev in script.walk_revisions())

    roots = [
        revision
        for revision in script.walk_revisions(base="base", head="heads")
        if revision.down_revision is None
    ]
    assert len(roots) == 1
    assert roots[0].revision == "20260911_initial_schema"


def test_model_registry_contains_critical_fresh_schema_tables() -> None:
    """Ensure the current schema imports every critical SQLAlchemy model module."""

    configure_mappers()
    registered_table_names = {table.name for table in Base.metadata.tables.values()}
    missing_tables = CRITICAL_TABLES - registered_table_names
    assert not missing_tables, (
        f"The fresh schema is missing registered model tables: {sorted(missing_tables)}"
    )


def test_model_registry_excludes_obsolete_academic_tables() -> None:
    """The pre-launch v2 cutover must not keep legacy academic tables registered."""

    configure_mappers()
    registered_table_names = {table.name for table in Base.metadata.tables.values()}
    stale_tables = OBSOLETE_ACADEMIC_TABLES & registered_table_names
    assert not stale_tables, f"Obsolete academic tables remain registered: {sorted(stale_tables)}"


def test_model_registry_has_unique_table_keys() -> None:
    """Guard against duplicate table registrations before migration execution."""

    configure_mappers()
    table_keys = list(Base.metadata.tables)
    assert len(table_keys) == len(set(table_keys))


def test_curriculum_department_scope_foreign_keys_are_tenant_aware() -> None:
    table = next(
        table
        for table in Base.metadata.tables.values()
        if table.name == "curriculum_subject_departments"
    )
    foreign_key_columns = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }

    assert ("tenant_id", "curriculum_subject_id") in foreign_key_columns
    assert ("tenant_id", "academic_level_department_id") in foreign_key_columns


def test_progression_run_count_constraints_match_v2_contract() -> None:
    """Progression accounting must use the persisted v2 counter columns only."""

    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in StudentProgressionRun.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_progression_run_nonnegative_counts" in constraints
    assert "ck_progression_run_count_total" in constraints
    assert "processed_students" not in " ".join(constraints.values())

    count_total = constraints["ck_progression_run_count_total"]
    for column_name in (
        "total_students",
        "promoted_students",
        "graduated_students",
        "skipped_students",
        "pending_students",
        "failed_students",
    ):
        assert column_name in count_total


def test_frozen_baseline_emits_all_registered_tables_without_database_access() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    script = ScriptDirectory.from_config(Config(str(backend_root / "alembic.ini")))
    baseline = script.get_revision(BASELINE_REVISION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output, "literal_binds": True},
    )
    with Operations.context(context):
        baseline.module.upgrade()
    sql = output.getvalue()
    created_tables = set(re.findall(r"CREATE TABLE (?:public\.)?(\w+)", sql))
    assert created_tables == BASELINE_TABLES
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in sql
    assert "CREATE TRIGGER trg_comment_templates_no_distinct_range_overlap" in sql
    assert "'student_elective_selection'" in sql
    assert "is_examinable BOOLEAN DEFAULT true NOT NULL" in sql
    assert "uq_cbt_ai_idempotency" in sql

    output.seek(0)
    output.truncate()
    with Operations.context(context):
        baseline.module.downgrade()
    dropped_tables = set(re.findall(r"DROP TABLE (?:public\.)?(\w+)", output.getvalue()))
    assert dropped_tables == created_tables
