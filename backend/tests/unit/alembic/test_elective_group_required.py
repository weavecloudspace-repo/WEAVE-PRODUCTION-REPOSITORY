import importlib.util
from io import StringIO
from pathlib import Path
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import CheckConstraint

from app.modules.student_academics.curriculum_models import CurriculumSubject


def _migration():
    path = (
        Path(__file__).resolve().parents[3] / "alembic/versions/20261011_elective_group_required.py"
    )
    spec = importlib.util.spec_from_file_location("elective_group_required", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(operation):
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        operation()
    return output.getvalue()


def test_migration_matches_model_and_validates_existing_rows():
    migration = _migration()
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in CurriculumSubject.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert migration.down_revision == "20261010_cbt_friendly_dns"
    assert len(migration.revision) <= 32
    sql = _sql(migration.upgrade)
    assert (
        "ALTER TABLE public.curriculum_subjects ADD CONSTRAINT "
        "ck_elective_subject_requires_group CHECK "
        f"({checks['ck_elective_subject_requires_group']})"
    ) in sql
    assert "NOT VALID" not in sql
    assert "UPDATE" not in sql


@pytest.mark.parametrize(
    "elective,group,valid",
    [(0, None, True), (0, "group", False), (1, None, False), (1, "group", True)],
)
def test_database_checks_enforce_both_sides_for_insert_and_update(elective, group, valid):
    checks = [
        str(constraint.sqltext)
        for constraint in CurriculumSubject.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    with sqlite3.connect(":memory:") as db:
        db.execute(
            "CREATE TABLE subjects (is_elective BOOLEAN NOT NULL, elective_group_id TEXT, "
            + ", ".join(f"CHECK ({check})" for check in checks)
            + ")"
        )
        if valid:
            db.execute("INSERT INTO subjects VALUES (?, ?)", (elective, group))
        else:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("INSERT INTO subjects VALUES (?, ?)", (elective, group))
        db.execute("DELETE FROM subjects")
        db.execute("INSERT INTO subjects VALUES (0, NULL)")
        if valid:
            db.execute("UPDATE subjects SET is_elective=?, elective_group_id=?", (elective, group))
        else:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE subjects SET is_elective=?, elective_group_id=?", (elective, group)
                )


def test_downgrade_only_removes_new_constraint():
    sql = _sql(_migration().downgrade)
    assert sql.strip() == (
        "ALTER TABLE public.curriculum_subjects DROP CONSTRAINT ck_elective_subject_requires_group;"
    )
