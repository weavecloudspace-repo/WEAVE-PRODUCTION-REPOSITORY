"""
WEAVE Cloud — Tutor-Marked Assignment (TMA) Database Models
============================================================

Module: app.modules.tma.models
Layer: Persistence / SQLAlchemy ORM

Overview
--------
Defines the database models supporting WEAVE's Tutor-Marked Assignment
(TMA) system within its multi-tenant academic management architecture.

The TMA module enables authorized teachers and administrators to create,
configure, and manage objective-based assignments for specific academic
levels, subjects, sessions, and terms.

Core Responsibilities
---------------------
- Assignment configuration and lifecycle management.
- Revision tracking and historical attempt preservation.
- Objective questions and answer-option persistence.
- Cloudflare R2 image metadata for questions and options.
- Student eligibility and assignment participation.
- Student attempts, answer persistence, and submission tracking.
- Automatic grading and score storage.
- Assignment lifecycle auditing.

Architectural Principles
------------------------
1. Tenant Isolation:
   All TMA records are scoped to their respective school using tenant_id.

2. Academic Integration:
   Assignments reference existing academic levels, curriculum subjects,
   sessions, terms, and student enrollment records.

3. Revision Integrity:
   Published assignment revisions preserve their question structures
   and historical student attempts.

4. Data Integrity:
   Database constraints enforce referential integrity, uniqueness,
   and valid persistence states.

5. Media Separation:
   Image binaries are stored in Cloudflare R2, while PostgreSQL
   maintains their metadata and object references.

6. Collaboration:
   Teacher permissions are derived from existing academic teaching
   assignments rather than duplicated collaboration records.

7. Separation of Concerns:
   This module defines persistence structures only. Authorization,
   lifecycle transitions, grading, and other business rules belong
   to their respective service layers.

Scope
-----
This module does not implement AI question generation, credit management,
payment processing, or academic result-component synchronization.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import (
    CheckConstraint,
    Index,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Enum as SQLEnum,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.base_model import BaseModel, PUBLIC_SCHEMA


class TMAAssignmentStatus(str, PyEnum):
    """Lifecycle states of a Tutor-Marked Assignment"""

    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class TMAActorType(str, PyEnum):
    """Authorized actor types responsible for TMA operations"""

    TEACHER = "teacher"
    TENANT_ADMIN = "tenant_admin"


class TMAAssignment(BaseModel):
    """
    Represents a Tutor-Marked Assignment belonging to a school.

    Assignments are scoped to an academic level, curriculum subject,
    academic session , and term rather than individual classrooms

    Multiple authorized teachers may collaborate on the same assignment
    """

    __tablename__ = "tma_assignments"

    # ==========================#
    # Academic Configuration
    # ==========================#

    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=False
    )

    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_terms.id", ondelete="RESTRICT"),
        nullable=False,
    )

    assessment_component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_components.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ==========================#
    # Assignment Lifecycle
    # ==========================#

    status: Mapped[TMAAssignmentStatus] = mapped_column(
        SQLEnum(
            TMAAssignmentStatus,
            name="tma_assignment_status",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=TMAAssignmentStatus.DRAFT,
        server_default=TMAAssignmentStatus.DRAFT.value,
    )

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ==========================#
    # Revision Management
    # ==========================#

    current_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # ==========================#
    # Assignment Scoring
    # ==========================#

    total_marks: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )

    created_by_actor_type: Mapped[TMAActorType] = mapped_column(
        SQLEnum(
            TMAActorType,
            name="tma_actor_type",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    created_by_actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # ==========================================
    # Database Constraints and Indexes
    # ==========================================

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_assignments_tenant_id",
        ),
        CheckConstraint(
            "current_revision_number >= 1",
            name="ck_tma_assignment_revision_positive",
        ),
        CheckConstraint(
            "total_marks >= 0",
            name="ck_tma_assignment_marks_nonnegative",
        ),
        Index(
            "ix_tma_assignments_tenant_term_status",
            "tenant_id",
            "academic_term_id",
            "status",
        ),
        Index(
            "ix_tma_assignments_tenant_level_subject",
            "tenant_id",
            "academic_level_id",
            "curriculum_subject_id",
        ),
    )
