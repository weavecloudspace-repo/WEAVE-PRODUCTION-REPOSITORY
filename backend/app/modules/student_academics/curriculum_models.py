"""Level-owned curriculum and term-specific class specialization models.

Curriculum membership is persistent. Department applicability is also persistent
and is expressed through CurriculumSubjectDepartment. Academic terms do not own
subject applicability; they only determine when specialization filtering is active
and which specialization a class uses for that exact term.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class ElectiveGroupLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Curriculum(BaseModel):
    __tablename__ = "curricula"

    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_levels.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "academic_level_id",
            name="uq_curricula_tenant_level",
        ),
    )


class CurriculumElectiveGroup(BaseModel):
    """Persistent choice policy for elective subjects in one level curriculum."""

    __tablename__ = "curriculum_elective_groups"

    curriculum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curricula.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    minimum_choices: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    maximum_choices: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ElectiveGroupLifecycle.ACTIVE.value,
        server_default=ElectiveGroupLifecycle.ACTIVE.value,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_curriculum_elective_groups_tenant_id"),
        UniqueConstraint(
            "tenant_id", "curriculum_id", "name", name="uq_curriculum_elective_group_name"
        ),
        CheckConstraint("minimum_choices >= 0", name="ck_elective_group_min_nonnegative"),
        CheckConstraint("maximum_choices >= 1", name="ck_elective_group_max_positive"),
        CheckConstraint("minimum_choices <= maximum_choices", name="ck_elective_group_min_lte_max"),
        CheckConstraint("lifecycle IN ('ACTIVE', 'ARCHIVED')", name="ck_elective_group_lifecycle"),
        Index("ix_curriculum_elective_groups_tenant_curriculum", "tenant_id", "curriculum_id"),
    )


class CurriculumSubject(BaseModel):
    __tablename__ = "curriculum_subjects"

    curriculum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curricula.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_elective: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    elective_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curriculum_elective_groups.id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "curriculum_id",
            "subject_id",
            name="uq_curriculum_subject_tenant_curriculum_subject",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_curriculum_subjects_tenant_id"),
        CheckConstraint(
            "is_elective OR elective_group_id IS NULL",
            name="ck_compulsory_subject_has_no_elective_group",
        ),
        CheckConstraint(
            "NOT is_elective OR elective_group_id IS NOT NULL",
            name="ck_elective_subject_requires_group",
        ),
        Index(
            "ix_curriculum_subjects_tenant_curriculum",
            "tenant_id",
            "curriculum_id",
        ),
        Index("ix_curriculum_subjects_elective_group", "tenant_id", "elective_group_id"),
    )


class StudentElectiveSelection(BaseModel):
    """The student's current authoritative elective subject selection.

    Selections intentionally do not carry a term id: they persist across terms until
    the student changes them. Result rows preserve historical academic evidence.
    """

    __tablename__ = "student_elective_selections"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    elective_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curriculum_elective_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "student_id",
            "curriculum_subject_id",
            name="uq_student_elective_selection_subject",
        ),
        Index(
            "ix_student_elective_selections_student_group",
            "tenant_id",
            "student_id",
            "elective_group_id",
        ),
        Index(
            "ix_student_elective_selections_curriculum_subject",
            "tenant_id",
            "curriculum_subject_id",
        ),
    )


class CurriculumSubjectDepartment(BaseModel):
    """Persistent department applicability for one level curriculum subject.

    A curriculum subject with no rows in this table is GENERAL and therefore
    applies to every specialization. One or more rows make it department-scoped.
    The referenced AcademicLevelDepartment preserves exact level identity.
    """

    __tablename__ = "curriculum_subject_departments"

    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    academic_level_department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "curriculum_subject_id"],
            ["curriculum_subjects.tenant_id", "curriculum_subjects.id"],
            name="fk_curriculum_subject_department_tenant_subject",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "academic_level_department_id"],
            ["academic_level_departments.tenant_id", "academic_level_departments.id"],
            name="fk_curriculum_subject_department_tenant_level_department",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "curriculum_subject_id",
            "academic_level_department_id",
            name="uq_curriculum_subject_department_scope",
        ),
        Index(
            "ix_curriculum_subject_departments_tenant_subject",
            "tenant_id",
            "curriculum_subject_id",
        ),
        Index(
            "ix_curriculum_subject_departments_tenant_level_department",
            "tenant_id",
            "academic_level_department_id",
        ),
    )


class ClassTermDepartmentAssignment(BaseModel):
    """The exact specialization of one class in one academic term."""

    __tablename__ = "class_term_department_assignments"

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_terms.id", ondelete="CASCADE"),
        nullable=False,
    )
    academic_level_department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_level_departments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_admins.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "class_id",
            "academic_term_id",
            name="uq_class_term_department_assignment",
        ),
        Index(
            "ix_class_term_department_tenant_term",
            "tenant_id",
            "academic_term_id",
        ),
        Index(
            "ix_class_term_department_tenant_level_department",
            "tenant_id",
            "academic_level_department_id",
        ),
    )
