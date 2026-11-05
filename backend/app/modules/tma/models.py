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

import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Boolean,
    text,
    BigInteger,
    String,
    Numeric,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import Base, BaseModel, PUBLIC_SCHEMA


class TMAAssignmentStatus(str, PyEnum):
    """Lifecycle states of a Tutor-Marked Assignment."""

    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class TMAActorType(str, PyEnum):
    """Authorized actor types responsible for TMA operations."""

    TEACHER = "teacher"
    TENANT_ADMIN = "tenant_admin"


class TMAAttemptStatus(str, PyEnum):
    """Lifecycle states of a student's TMA attempt."""

    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class TMAAssignment(BaseModel):
    """
    Represents a Tutor-Marked Assignment belonging to a school.

    Assignments are scoped to an academic level, curriculum subject,
    academic session, and term rather than individual classrooms.

    Multiple authorized teachers may collaborate on the same assignment.
    """

    __tablename__ = "tma_assignments"

    # ==========================#
    # Academic Configuration
    # ==========================#

    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    assessment_component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
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

    # Enforced UTC deadline. The worker persists CLOSED; student writes reject
    # overdue assignments immediately, even if the worker has not run yet.
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Completion and reconciliation status for missed-deadline grading.
    zero_grading_last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    zero_grading_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    zero_grading_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    zero_grading_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ==========================#
    # Revision Management
    # ==========================#

    current_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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

    created_by_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Explicit administrator-assigned lead. Legacy teacher-created TMAs with
    # no lead continue to use their creator until an administrator reassigns.
    lead_teacher_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ==========================================
    # Database Constraints and Indexes
    # ==========================================

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_teacher_membership_id"],
            [
                f"{PUBLIC_SCHEMA}.teacher_memberships.tenant_id",
                f"{PUBLIC_SCHEMA}.teacher_memberships.id",
            ],
            name="fk_tma_assignment_tenant_lead_teacher",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "academic_level_id",
            "curriculum_subject_id",
            "academic_session_id",
            "academic_term_id",
            "assessment_component_id",
            name="uq_tma_assignment_component_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "academic_level_id"],
            [
                f"{PUBLIC_SCHEMA}.academic_levels.tenant_id",
                f"{PUBLIC_SCHEMA}.academic_levels.id",
            ],
            name="fk_tma_assignment_tenant_level",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "curriculum_subject_id"],
            [
                f"{PUBLIC_SCHEMA}.curriculum_subjects.tenant_id",
                f"{PUBLIC_SCHEMA}.curriculum_subjects.id",
            ],
            name="fk_tma_assignment_tenant_subject",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "academic_session_id"],
            [
                f"{PUBLIC_SCHEMA}.academic_sessions.tenant_id",
                f"{PUBLIC_SCHEMA}.academic_sessions.id",
            ],
            name="fk_tma_assignment_tenant_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "academic_term_id", "academic_session_id"],
            [
                f"{PUBLIC_SCHEMA}.academic_terms.tenant_id",
                f"{PUBLIC_SCHEMA}.academic_terms.id",
                f"{PUBLIC_SCHEMA}.academic_terms.academic_session_id",
            ],
            name="fk_tma_assignment_term_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assessment_component_id"],
            [
                f"{PUBLIC_SCHEMA}.assessment_components.tenant_id",
                f"{PUBLIC_SCHEMA}.assessment_components.id",
            ],
            name="fk_tma_assignment_tenant_component",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_assignments_tenant_id",
        ),
        CheckConstraint(
            "current_revision_number >= 1",
            name="ck_tma_assignment_revision_positive",
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


class TMAAssignmentRevision(BaseModel):
    """
    Represents a specific revision of a Tutor-Marked Assignment.

    Each revision preserves its associated questions, student attempts
    and historical records.

    Revisions are created when an existing assignment is cancelled and revised.
    Previous revisions remain immutable for auditing.

    The parent TMAAssignment controls the assignment lifecycle.
    """

    __tablename__ = "tma_assignment_revisions"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    eligibility_tracking_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    eligibility_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    zero_grading_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    zero_grading_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    zero_grading_error: Mapped[str | None] = mapped_column(Text)

    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invalidated_by_actor_type: Mapped[TMAActorType | None] = mapped_column(
        SQLEnum(
            TMAActorType,
            name="tma_actor_type",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )

    invalidated_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    invalidation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ==========================================
    # Database Constraints
    # ==========================================

    __table_args__ = (
        # Enforce tenant-safe assignment references.
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignments.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignments.id",
            ],
            name="fk_tma_revisions_tenant_assignment",
            ondelete="RESTRICT",
        ),
        # Prevent duplicate revision numbers.
        UniqueConstraint(
            "tenant_id",
            "assignment_id",
            "revision_number",
            name="uq_tma_revisions_assignment_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "assignment_id",
            name="uq_tma_revisions_tenant_id_assignment",
        ),
        # Support tenant-scoped references from child tables.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_revisions_tenant_id",
        ),
        # Revision numbers must be positive.
        CheckConstraint(
            "revision_number >= 1",
            name="ck_tma_revisions_number_positive",
        ),
        # Invalidation must contain actor information.
        CheckConstraint(
            """
            (
                invalidated_at IS NULL
                AND invalidated_by_actor_type IS NULL
                AND invalidated_by_actor_id IS NULL
            )
            OR
            (
                invalidated_at IS NOT NULL
                AND invalidated_by_actor_type IS NOT NULL
                AND invalidated_by_actor_id IS NOT NULL
            )
            """,
            name="ck_tma_revisions_invalidation_metadata",
        ),
        # A revision cannot be invalidated before publication.
        CheckConstraint(
            """
            invalidated_at IS NULL
            OR (
                published_at IS NOT NULL
                AND invalidated_at >= published_at
            )
            """,
            name="ck_tma_revisions_invalidation_chronology",
        ),
    )


class TMAQuestion(BaseModel):
    """
    Represents an objective question belonging to a TMA revision.

    Each question contributes exactly one raw mark to the assignment.

    Questions may contain text, an image or both. Image binaries are
    stored in Cloudflare R2 and referenced through TMAMediaAsset.

    Questions belong to a specific assignment revision, preserving
    historical question records when an assignment is revised.

    Question ordering is maintained for administrative purposes.
    Student-facing question randomization is handled separately.
    """

    __tablename__ = "tma_questions"

    # =============================#
    # Assignment Revision Reference
    # =============================#

    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Enforce asset ownership within the assignment of this revision.
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    position: Mapped[int] = mapped_column(Integer, nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    author_actor_type: Mapped[TMAActorType] = mapped_column(
        SQLEnum(
            TMAActorType,
            name="tma_actor_type",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    author_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    __table_args__ = (
        # Ensure the revision belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "revision_id", "assignment_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.assignment_id",
            ],
            name="fk_tma_questions_tenant_revision",
            ondelete="RESTRICT",
        ),
        # Ensure the referenced image belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id", "image_asset_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_media_assets.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_media_assets.assignment_id",
                f"{PUBLIC_SCHEMA}.tma_media_assets.id",
            ],
            name="fk_tma_questions_tenant_media",
            ondelete="RESTRICT",
        ),
        # Ensure each question has a unique position
        # within its revision.
        UniqueConstraint(
            "tenant_id",
            "revision_id",
            "position",
            name="uq_tma_questions_revision_position",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "revision_id",
            name="uq_tma_questions_tenant_id_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "assignment_id",
            name="uq_tma_questions_tenant_id_assignment",
        ),
        # Support tenant-safe references from question options.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_questions_tenant_id",
        ),
        # Every question must contain text or an image.
        CheckConstraint(
            """
            (
                question_text IS NOT NULL
                AND LENGTH(BTRIM(question_text)) > 0
            )
            OR image_asset_id IS NOT NULL
            """,
            name="ck_tma_questions_content_required",
        ),
        # Question positions start from 1.
        CheckConstraint(
            "position >= 1",
            name="ck_tma_questions_position_positive",
        ),
        # Question versions must be positive.
        CheckConstraint(
            "version >= 1",
            name="ck_tma_questions_version_positive",
        ),
    )


class TMAQuestionOption(BaseModel):
    """
    Represents an answer option for a TMA question.

    Each question must contain at least four answer options
    and exactly one correct answer before publication.

    Options may contain text, an image, or both.
    Image binaries are stored in Cloudflare R2.

    The position field maintains the original ordering of options.
    Student-facing option randomization is handled separately.

    Question-level versioning manages concurrent modifications
    to questions and their associated options.
    """

    __tablename__ = "tma_question_options"

    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    option_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    is_correct: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        # Ensure the question belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "question_id", "assignment_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_questions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_questions.id",
                f"{PUBLIC_SCHEMA}.tma_questions.assignment_id",
            ],
            name="fk_tma_question_options_tenant_question",
            ondelete="RESTRICT",
        ),
        # Ensure the referenced image belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id", "image_asset_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_media_assets.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_media_assets.assignment_id",
                f"{PUBLIC_SCHEMA}.tma_media_assets.id",
            ],
            name="fk_tma_question_options_tenant_media",
            ondelete="RESTRICT",
        ),
        # Prevent duplicate positions within a question.
        UniqueConstraint(
            "tenant_id",
            "question_id",
            "position",
            name="uq_tma_question_options_position",
        ),
        # Support tenant-safe references from student answers.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_question_options_tenant_id",
        ),
        # Ensure an answer's selected option belongs to its question.
        UniqueConstraint(
            "tenant_id",
            "question_id",
            "id",
            name="uq_tma_question_options_tenant_question_id",
        ),
        # Allow at most one correct answer per question.
        Index(
            "uq_tma_question_options_one_correct",
            "tenant_id",
            "question_id",
            unique=True,
            postgresql_where=text("is_correct = true"),
        ),
        # Every option must contain text or an image.
        CheckConstraint(
            """
            (
                option_text IS NOT NULL
                AND LENGTH(BTRIM(option_text)) > 0
            )
            OR image_asset_id IS NOT NULL
            """,
            name="ck_tma_question_options_content_required",
        ),
        # Positions must start from 1.
        CheckConstraint(
            "position >= 1",
            name="ck_tma_question_options_position_positive",
        ),
    )


class TMAMediaAsset(BaseModel):
    """
    Represents an image asset associated with a TMA assignment.

    Image binaries are stored in Cloudflare R2, while this model
    maintains their permanent storage references and metadata.

    Media assets belong to an assignment rather than an individual
    revision, allowing images to remain accessible across revisions.

    Questions and answer options reference these assets through
    their respective image_asset_id fields.

    Temporary signed URLs are generated by the storage service
    and are never persisted in this table.
    """

    __tablename__ = "tma_media_assets"

    # ==========================================
    # Assignment Reference
    # ==========================================

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # ==========================================
    # Cloudflare R2 Storage
    # ==========================================

    object_key: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )

    # ==========================================
    # Image Metadata
    # ==========================================

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    checksum_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # ==========================================
    # Database Constraints and Indexes
    # ==========================================

    __table_args__ = (
        # Ensure the asset and assignment belong to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignments.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignments.id",
            ],
            name="fk_tma_media_assets_tenant_assignment",
            ondelete="RESTRICT",
        ),
        # Prevent duplicate object keys within a tenant.
        UniqueConstraint(
            "tenant_id",
            "object_key",
            name="uq_tma_media_assets_tenant_object_key",
        ),
        # Enforce assignment ownership of question and option images.
        UniqueConstraint(
            "tenant_id",
            "assignment_id",
            "id",
            name="uq_tma_media_tenant_assignment_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_media_assets_tenant_id",
        ),
        CheckConstraint(
            "LENGTH(BTRIM(content_type)) > 0",
            name="ck_tma_media_assets_content_type_required",
        ),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_tma_media_assets_checksum_sha256",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_tma_media_assets_size_positive",
        ),
        CheckConstraint(
            "LENGTH(BTRIM(object_key)) > 0",
            name="ck_tma_media_assets_object_key_required",
        ),
        Index(
            "ix_tma_media_assets_tenant_assignment",
            "tenant_id",
            "assignment_id",
        ),
    )


class TMAParticipant(BaseModel):
    """
    Records a student's participation in a TMA assignment revision.

    Participants are registered when an assignment is activated.

    Each student can have only one participant record per
    assignment revision, regardless of subsequent changes
    to their academic enrollment or classroom.

    The original enrollment and classroom references are
    preserved for historical academic context. Current roster
    eligibility is derived from live enrollment and curriculum.

    Assessment scores are managed by WEAVE's existing
    academic assessment infrastructure, not this model.
    """

    __tablename__ = "tma_participants"

    # ==========================================
    # Assignment Revision Reference
    # ==========================================

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # ==========================================
    # Student Reference
    # ==========================================

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # ==========================================
    # Original Enrollment Context
    # ==========================================

    student_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # ==========================================
    # Database Constraints and Indexes
    # ==========================================

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            [
                f"{PUBLIC_SCHEMA}.students.tenant_id",
                f"{PUBLIC_SCHEMA}.students.id",
            ],
            name="fk_tma_participants_tenant_student",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "student_enrollment_id", "student_id", "class_id"],
            [
                f"{PUBLIC_SCHEMA}.student_enrollments.tenant_id",
                f"{PUBLIC_SCHEMA}.student_enrollments.id",
                f"{PUBLIC_SCHEMA}.student_enrollments.student_id",
                f"{PUBLIC_SCHEMA}.student_enrollments.class_id",
            ],
            name="fk_tma_participants_student_enrollment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "class_id"],
            [
                f"{PUBLIC_SCHEMA}.classes.tenant_id",
                f"{PUBLIC_SCHEMA}.classes.id",
            ],
            name="fk_tma_participants_tenant_class",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "revision_id",
            name="uq_tma_participants_tenant_id_revision",
        ),
        # Ensure the revision belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.id",
            ],
            name="fk_tma_participants_tenant_revision",
            ondelete="RESTRICT",
        ),
        # Prevent duplicate participation for the same
        # student within an assignment revision.
        UniqueConstraint(
            "tenant_id",
            "revision_id",
            "student_id",
            name="uq_tma_participants_revision_student",
        ),
        # Support tenant-safe references from attempts.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_participants_tenant_id",
        ),
        # Optimize student participation history.
        Index(
            "ix_tma_participants_tenant_student",
            "tenant_id",
            "student_id",
        ),
    )


class TMAClosureRun(BaseModel):
    """One manual or automatic closure event; does not freeze students."""

    __tablename__ = "tma_closure_runs"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [f"{PUBLIC_SCHEMA}.tma_assignments.tenant_id", f"{PUBLIC_SCHEMA}.tma_assignments.id"],
            name="fk_tma_closure_tenant_assignment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [f"{PUBLIC_SCHEMA}.tma_assignment_revisions.tenant_id", f"{PUBLIC_SCHEMA}.tma_assignment_revisions.id"],
            name="fk_tma_closure_tenant_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "assignment_id", "closed_at", name="uq_tma_closure_assignment_closed_at"),
        Index("ix_tma_closure_assignment", "tenant_id", "assignment_id", "closed_at"),
    )


class TMAAttempt(BaseModel):
    """
    Represents a student's attempt at a TMA assignment revision.

    Each participant can have only one attempt per revision.

    Attempts remain IN_PROGRESS until explicitly submitted, except that
    the missed-deadline worker finalizes unfinished/missing attempts with
    a provably linked zero when the published deadline passes.

    When an assignment is reopened, unfinished attempts can
    resume using their previously saved answers.

    Submitted attempts are final and cannot be retaken.

    Each question contributes exactly one raw mark.
    Official assessment-component scores are calculated and
    persisted through WEAVE's existing academic results system.
    """

    __tablename__ = "tma_attempts"

    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # Redundant revision key makes attempt/question consistency enforceable.
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    status: Mapped[TMAAttemptStatus] = mapped_column(
        SQLEnum(
            TMAAttemptStatus,
            name="tma_attempt_status",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=TMAAttemptStatus.IN_PROGRESS,
        server_default=TMAAttemptStatus.IN_PROGRESS.value,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # NULL for old records whose genuine start cannot be proven.
    # The worker never sets this field for system-generated zero attempts.
    student_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # None = historical origin unknown; False = worker-generated only;
    # True = student actually opened the attempt.
    started_by_student: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    correct_answers: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    total_questions: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Immutable source evidence for safe component-score rollback. Historical
    # attempts without this provenance must not be automatically rolled back.
    score_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    score_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    score_reversed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_zeroed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Preserve the original missed-deadline event when a later genuine
    # submission replaces the automatic zero.
    auto_zero_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Ensure the participant belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "participant_id", "revision_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_participants.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_participants.id",
                f"{PUBLIC_SCHEMA}.tma_participants.revision_id",
            ],
            name="fk_tma_attempts_tenant_participant",
            ondelete="RESTRICT",
        ),
        # Enforce exactly one attempt per participant.
        UniqueConstraint(
            "tenant_id",
            "participant_id",
            name="uq_tma_attempts_tenant_participant",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "revision_id",
            name="uq_tma_attempts_tenant_id_revision",
        ),
        # Support tenant-safe references from student answers.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_attempts_tenant_id",
        ),
        # Validate attempt lifecycle and grading fields.
        CheckConstraint(
            """
            (
                status = 'in_progress'
                AND submitted_at IS NULL
                AND correct_answers IS NULL
                AND total_questions IS NULL
            )
            OR
            (
                status = 'submitted'
                AND submitted_at IS NOT NULL
                AND correct_answers IS NOT NULL
                AND total_questions IS NOT NULL
                AND total_questions > 0
                AND correct_answers >= 0
                AND correct_answers <= total_questions
            )
            """,
            name="ck_tma_attempts_submission_consistency",
        ),
        # Prevent submission timestamps preceding attempt start.
        CheckConstraint(
            """
            submitted_at IS NULL
            OR submitted_at >= started_at
            """,
            name="ck_tma_attempts_submission_chronology",
        ),
        # Optimize attempt lookups by status.
        Index(
            "ix_tma_attempts_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TMAAnswer(BaseModel):
    """
    Stores one selected option per question for a student's TMA attempt.

    An unanswered question has no TMAAnswer row. While an attempt is
    IN_PROGRESS, the student may update the selected option or remove
    the answer. Submitted attempts and answers must remain immutable.

    The submission service validates that the question belongs to
    the attempt participant's assignment revision, checks that the
    assignment is ACTIVE, and grades the submitted answers.

    Official assessment-component scores belong to WEAVE's existing
    academic results infrastructure rather than this model.
    """

    __tablename__ = "tma_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # Matches both the attempt's and question's assignment revision.
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    selected_option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    __table_args__ = (
        # An answer must belong to an attempt in the same school.
        ForeignKeyConstraint(
            ["tenant_id", "attempt_id", "revision_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_attempts.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_attempts.id",
                f"{PUBLIC_SCHEMA}.tma_attempts.revision_id",
            ],
            name="fk_tma_answers_tenant_attempt",
            ondelete="RESTRICT",
        ),
        # Ensure the question belongs to the same school.
        ForeignKeyConstraint(
            ["tenant_id", "question_id", "revision_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_questions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_questions.id",
                f"{PUBLIC_SCHEMA}.tma_questions.revision_id",
            ],
            name="fk_tma_answers_tenant_question",
            ondelete="RESTRICT",
        ),
        # Prevent selecting an option that belongs to another question.
        ForeignKeyConstraint(
            ["tenant_id", "question_id", "selected_option_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_question_options.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_question_options.question_id",
                f"{PUBLIC_SCHEMA}.tma_question_options.id",
            ],
            name="fk_tma_answers_tenant_question_option",
            ondelete="RESTRICT",
        ),
        # An attempt can have only one saved selection per question.
        UniqueConstraint(
            "tenant_id",
            "attempt_id",
            "question_id",
            name="uq_tma_answers_attempt_question",
        ),
        # Support tenant-safe references to individual answer records.
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tma_answers_tenant_id",
        ),
    )


class TMACancellationRun(BaseModel):
    """Durable, replayable cancellation job for exactly one assignment revision."""

    __tablename__ = "tma_cancellation_runs"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_actor_type: Mapped[TMAActorType] = mapped_column(
        SQLEnum(
            TMAActorType,
            name="tma_actor_type",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    requested_by_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversed_scores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            ["public.tma_assignments.tenant_id", "public.tma_assignments.id"],
            name="fk_tma_cancellation_assignment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "revision_id", "assignment_id"],
            [
                "public.tma_assignment_revisions.tenant_id",
                "public.tma_assignment_revisions.id",
                "public.tma_assignment_revisions.assignment_id",
            ],
            name="fk_tma_cancellation_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "revision_id",
            name="uq_tma_cancellation_revision",
        ),
        Index("ix_tma_cancellation_pending", "status", "created_at"),
        CheckConstraint(
            "status IN ('pending','failed','completed')", name="ck_tma_cancellation_status"
        ),
    )


class TMADraftMediaCleanup(BaseModel):
    """Durable object-storage cleanup for permanently deleted unpublished TMAs.

    The assignment is intentionally not referenced by an FK: database deletion
    must not discard the object key before remote storage cleanup succeeds.
    """

    __tablename__ = "tma_draft_media_cleanup"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "object_key", name="uq_tma_draft_media_cleanup_object"),
        Index("ix_tma_draft_media_cleanup_created", "created_at"),
    )


class TMAZeroGradingFailure(BaseModel):
    """Durable per-student reconciliation record for blocked deadline zeros."""

    __tablename__ = "tma_zero_grading_failures"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignments.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignments.id",
            ],
            name="fk_tma_zero_failure_tenant_assignment",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id", "revision_number"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.assignment_id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.revision_number",
            ],
            name="fk_tma_zero_failure_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "assignment_id",
            "revision_number",
            "student_id",
            name="uq_tma_zero_failure_revision_student",
        ),
        Index(
            "ix_tma_zero_failure_pending",
            "tenant_id",
            "assignment_id",
            "resolved_at",
        ),
    )


class TMADeadlineEligibility(Base):
    """Frozen deadline roster, captured before the first subsequent eligibility change."""

    __tablename__ = "tma_deadline_eligibility"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    student_enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.tenant_id",
                f"{PUBLIC_SCHEMA}.tma_assignment_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "student_enrollment_id", "student_id", "class_id"],
            [
                f"{PUBLIC_SCHEMA}.student_enrollments.tenant_id",
                f"{PUBLIC_SCHEMA}.student_enrollments.id",
                f"{PUBLIC_SCHEMA}.student_enrollments.student_id",
                f"{PUBLIC_SCHEMA}.student_enrollments.class_id",
            ],
        ),
    )
