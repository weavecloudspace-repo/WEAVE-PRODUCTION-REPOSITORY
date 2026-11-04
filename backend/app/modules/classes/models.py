"""Academic level, department, arm-label, and class structure models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils.normalization import normalize_class_name, normalized_class_name_key
from app.shared.base_model import BaseModel, PUBLIC_SCHEMA

if TYPE_CHECKING:
    from app.modules.teachers.models import TeacherMembership


def enum_values(enum_cls):
    return [item.value for item in enum_cls]


class AcademicCategory(str, PyEnum):
    KINDERGARTEN = "KINDERGARTEN"
    NURSERY = "NURSERY"
    PRIMARY = "PRIMARY"
    JUNIOR_SECONDARY = "JUNIOR_SECONDARY"
    SENIOR_SECONDARY = "SENIOR_SECONDARY"


class AcademicLevelStatus(str, PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class AcademicLevel(BaseModel):
    """Tenant-scoped curriculum level. Class arms organize students inside the level."""

    __tablename__ = "academic_levels"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[AcademicCategory] = mapped_column(
        SQLEnum(
            AcademicCategory,
            name="academic_category",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(nullable=False)
    specialization_required_from_term_position: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    status: Mapped[AcademicLevelStatus] = mapped_column(
        SQLEnum(
            AcademicLevelStatus,
            name="academic_level_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        default=AcademicLevelStatus.DRAFT,
        server_default=AcademicLevelStatus.DRAFT.value,
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    classrooms: Mapped[list["ClassRoom"]] = relationship(
        "ClassRoom", back_populates="academic_level"
    )
    department_links: Mapped[list["AcademicLevelDepartment"]] = relationship(
        "AcademicLevelDepartment", back_populates="academic_level"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_academic_levels_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "normalized_name", name="uq_academic_levels_tenant_normalized_name"
        ),
        UniqueConstraint(
            "tenant_id", "category", "position", name="uq_academic_levels_tenant_category_position"
        ),
        CheckConstraint(
            """
            specialization_required_from_term_position IS NULL
            OR specialization_required_from_term_position BETWEEN 1 AND 3
            """,
            name="ck_academic_levels_specialization_term_position",
        ),
        CheckConstraint(
            """
            (category <> 'SENIOR_SECONDARY'
                AND specialization_required_from_term_position IS NULL)
            OR
            (category = 'SENIOR_SECONDARY' AND (
                (position = 1
                    AND specialization_required_from_term_position BETWEEN 1 AND 3)
                OR
                (position > 1
                    AND specialization_required_from_term_position = 1)
            ))
            """,
            name="ck_academic_levels_specialization_policy",
        ),
        CheckConstraint("position > 0", name="ck_academic_levels_position_positive"),
        CheckConstraint(
            """
            (status = 'archived' AND archived_at IS NOT NULL)
            OR (status <> 'archived' AND archived_at IS NULL AND archived_by_admin_id IS NULL)
            """,
            name="ck_academic_levels_archive_metadata_matches_status",
        ),
        Index("ix_academic_levels_tenant_status", "tenant_id", "status"),
        Index("ix_academic_levels_tenant_category_position", "tenant_id", "category", "position"),
        Index("ix_academic_levels_tenant_archived", "tenant_id", "archived_at"),
        Index(
            "ix_academic_levels_tma_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class Department(BaseModel):
    """Tenant-wide canonical specialization definition, e.g. Science or Arts."""

    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    level_links: Mapped[list["AcademicLevelDepartment"]] = relationship(
        "AcademicLevelDepartment", back_populates="department"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name="uq_departments_tenant_name",
        ),
        CheckConstraint(
            """
            (archived_at IS NULL AND archived_by_admin_id IS NULL)
            OR (archived_at IS NOT NULL AND is_active = false)
            """,
            name="ck_departments_archive_metadata_consistency",
        ),
        Index("ix_departments_tenant_active", "tenant_id", "is_active"),
        Index("ix_departments_tenant_archived", "tenant_id", "archived_at"),
    )


class AcademicLevelDepartment(BaseModel):
    """Enable one canonical Department for one AcademicLevel.

    Per-level lifecycle belongs here. Operational specialization references use this
    identity so the database preserves the exact level/department scope.
    """

    __tablename__ = "academic_level_departments"

    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    academic_level: Mapped[AcademicLevel] = relationship(
        "AcademicLevel", back_populates="department_links"
    )
    department: Mapped[Department] = relationship("Department", back_populates="level_links")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "academic_level_id",
            "department_id",
            name="uq_academic_level_departments_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_academic_level_departments_tenant_id"),
        CheckConstraint(
            """
            (archived_at IS NULL AND archived_by_admin_id IS NULL)
            OR (archived_at IS NOT NULL AND is_active = false)
            """,
            name="ck_academic_level_departments_archive_metadata",
        ),
        Index(
            "ix_academic_level_departments_tenant_level",
            "tenant_id",
            "academic_level_id",
        ),
        Index(
            "ix_academic_level_departments_tenant_department",
            "tenant_id",
            "department_id",
        ),
        Index(
            "ix_academic_level_departments_tenant_level_active",
            "tenant_id",
            "academic_level_id",
            "is_active",
        ),
    )


class ArmLabel(BaseModel):
    """Tenant-wide reusable class arm label such as A, B, or C."""

    __tablename__ = "arm_labels"

    label: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(40), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_label", name="uq_arm_labels_tenant_label"),
        CheckConstraint(
            """
            (archived_at IS NULL AND archived_by_admin_id IS NULL)
            OR (archived_at IS NOT NULL AND is_active = false)
            """,
            name="ck_arm_labels_archive_metadata_consistency",
        ),
        Index("ix_arm_labels_tenant_active", "tenant_id", "is_active"),
    )


def _populate_academic_level_normalized_fields(
    _: object, __: object, target: AcademicLevel
) -> None:
    normalized_name = normalized_class_name_key(target.name)
    if normalized_name is None:
        return
    target.name = normalize_class_name(target.name) or target.name
    target.normalized_name = normalized_name

    # Specialization is a senior-secondary curriculum policy, not an arbitrary
    # per-level flag. The first senior position is configurable and defaults to
    # Second Term; every later senior position specializes from First Term.
    if target.category != AcademicCategory.SENIOR_SECONDARY:
        target.specialization_required_from_term_position = None
    elif target.position == 1:
        if target.specialization_required_from_term_position is None:
            target.specialization_required_from_term_position = 2
    else:
        target.specialization_required_from_term_position = 1


event.listen(AcademicLevel, "before_insert", _populate_academic_level_normalized_fields)
event.listen(AcademicLevel, "before_update", _populate_academic_level_normalized_fields)


class ClassRoom(BaseModel):
    """Concrete class arm. Specialization is term-specific and intentionally not stored here."""

    __tablename__ = "classes"

    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=False
    )
    arm_label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("arm_labels.id", ondelete="RESTRICT"), nullable=False
    )
    teacher_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_memberships.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    academic_level: Mapped[AcademicLevel] = relationship(
        "AcademicLevel", back_populates="classrooms"
    )
    arm_label_ref: Mapped[ArmLabel] = relationship("ArmLabel", foreign_keys=[arm_label_id])
    teacher_membership: Mapped["TeacherMembership | None"] = relationship(
        "TeacherMembership", foreign_keys=[teacher_membership_id]
    )

    @property
    def academic_level_name(self) -> str:
        return self.academic_level.name

    @property
    def arm_label(self) -> str:
        return self.arm_label_ref.label

    @property
    def arm(self) -> str:
        return self.arm_label

    @property
    def display_name(self) -> str:
        return f"{self.academic_level_name} {self.arm_label}".strip()

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_classes_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "academic_level_id",
            "arm_label_id",
            name="uq_classes_tenant_level_arm_label",
        ),
        CheckConstraint(
            """
            (archived_at IS NULL AND archived_by_admin_id IS NULL)
            OR (archived_at IS NOT NULL AND is_active = false)
            """,
            name="ck_classes_archive_metadata_consistency",
        ),
        Index("ix_classes_tenant_teacher_membership", "tenant_id", "teacher_membership_id"),
        Index("ix_classes_tenant_active", "tenant_id", "is_active"),
        Index("ix_classes_tenant_level", "tenant_id", "academic_level_id"),
        Index("ix_classes_tenant_arm_label", "tenant_id", "arm_label_id"),
        Index("ix_classes_tenant_archived", "tenant_id", "archived_at"),
    )
