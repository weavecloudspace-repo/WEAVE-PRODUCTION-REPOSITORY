"""TMA search indexes and their corresponding query expression remain aligned."""

import inspect

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.modules.classes.models import AcademicLevel
from app.modules.students.models import Student
from app.modules.subjects.models import Subject
from app.modules.tma.reporting_repository import TMAReportingRepository


def test_trigram_indexes_compile_for_postgresql():
    tables = (Subject.__table__, AcademicLevel.__table__, Student.__table__)
    indexes = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for table in tables
        for index in table.indexes
        if "_tma_" in index.name and index.name.endswith("_trgm")
    }
    assert set(indexes) == {
        "ix_subjects_tma_name_trgm",
        "ix_subjects_tma_code_trgm",
        "ix_academic_levels_tma_name_trgm",
        "ix_students_tma_admission_trgm",
        "ix_students_tma_full_name_trgm",
    }
    for sql in indexes.values():
        assert "USING gin" in sql
        assert "gin_trgm_ops" in sql

    full_name = next(
        index for index in Student.__table__.indexes
        if index.name == "ix_students_tma_full_name_trgm"
    )
    assert full_name.dialect_options["postgresql"]["ops"] == {
        "tma_full_name": "gin_trgm_ops"
    }
    assert "gin_trgm_ops" not in str(full_name.expressions[0])


def test_student_name_lookup_uses_the_immutable_expression_indexed_by_migration():
    source = inspect.getsource(TMAReportingRepository._query)
    assert "func.btrim(" in source
    assert "func.coalesce(Student.first_name, literal_column(\"''\"))" in source
    assert "func.coalesce(Student.last_name, literal_column(\"''\"))" in source
    assert "name.ilike(pattern" in source
