"""Academic sessions, curriculum assignments, results, and progression audit models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    UUID,
    and_,
    func,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, PUBLIC_SCHEMA


def enum_values(enum_cls):
    return [item.value for item in enum_cls]


class AcademicTermName(str, PyEnum):
    FIRST_TERM = "first_term"
    SECOND_TERM = "second_term"
    THIRD_TERM = "third_term"


class AcademicTermStatus(str, PyEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class AcademicResultStatus(str, PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    LOCKED = "locked"


class AssessmentSchemeStatus(str, PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class AcademicSessionStatus(str, PyEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    CLOSING = "closing"


class TeacherAssignmentState(str, PyEnum):
    SCHEDULED = "scheduled"
    CURRENT = "current"
    ENDED = "ended"


class StudentProgressionRunStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StudentProgressionItemStatus(str, PyEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class StudentProgressionItemAction(str, PyEnum):
    PROGRESS = "progress"
    COMPLETE = "complete"
    SKIP = "skip"


class AcademicLifecycleAudit(BaseModel):
    __tablename__ = "academic_lifecycle_audits"

    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    acting_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "ix_academic_lifecycle_audits_tenant_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
        ),
        Index("ix_academic_lifecycle_audits_tenant_action", "tenant_id", "action"),
    )


class AcademicSession(BaseModel):
    __tablename__ = "academic_sessions"

    name: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AcademicSessionStatus] = mapped_column(
        SQLEnum(
            AcademicSessionStatus,
            name="academic_session_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AcademicSessionStatus.DRAFT,
        server_default=AcademicSessionStatus.DRAFT.value,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    closing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    next_academic_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_academic_session_tenant_name"),
        Index(
            "uq_academic_sessions_current_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_current = true AND status IN ('open', 'closing')"),
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            (func.daterange(start_date, end_date, "[]"), "&&"),
            name="excl_academic_sessions_date_overlap",
            using="gist",
            where=text("start_date IS NOT NULL AND end_date IS NOT NULL"),
        ),
        Index("ix_academic_sessions_tenant_status", "tenant_id", "status"),
        Index("ix_academic_sessions_tenant_next", "tenant_id", "next_academic_session_id"),
        CheckConstraint(
            "next_academic_session_id IS NULL OR next_academic_session_id <> id",
            name="ck_academic_session_next_not_self",
        ),
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date > start_date",
            name="ck_academic_session_date_range",
        ),
        CheckConstraint(
            "status = 'draft' OR (start_date IS NOT NULL AND end_date IS NOT NULL)",
            name="ck_academic_session_operational_dates",
        ),
        CheckConstraint(
            """
            (status IN ('draft', 'open') AND closing_started_at IS NULL AND closed_at IS NULL)
            OR (status = 'closing' AND closing_started_at IS NOT NULL AND closed_at IS NULL)
            OR (status = 'closed' AND closing_started_at IS NOT NULL AND closed_at IS NOT NULL)
            """,
            name="ck_academic_session_status_timestamps",
        ),
        CheckConstraint(
            "((status IN ('open', 'closing')) AND is_current = true) OR "
            "((status IN ('draft', 'closed')) AND is_current = false)",
            name="ck_academic_session_current_matches_status",
        ),
    )


class AcademicTerm(BaseModel):
    __tablename__ = "academic_terms"

    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[AcademicTermName] = mapped_column(
        SQLEnum(
            AcademicTermName,
            name="academic_term_name",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AcademicTermStatus] = mapped_column(
        SQLEnum(
            AcademicTermStatus,
            name="academic_term_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AcademicTermStatus.DRAFT,
        server_default=AcademicTermStatus.DRAFT.value,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    closed_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "academic_session_id",
            "name",
            name="uq_academic_term_tenant_session_name",
        ),
        Index(
            "uq_academic_terms_current_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_current = true AND status IN ('open', 'closing')"),
        ),
        CheckConstraint(
            """
            (status = 'draft'
                AND opened_at IS NULL
                AND closing_started_at IS NULL
                AND closed_at IS NULL)
            OR
            (status = 'open'
                AND opened_at IS NOT NULL
                AND closing_started_at IS NULL
                AND closed_at IS NULL)
            OR
            (status = 'closing'
                AND opened_at IS NOT NULL
                AND closing_started_at IS NOT NULL
                AND closed_at IS NULL)
            OR
            (status = 'closed'
                AND opened_at IS NOT NULL
                AND closing_started_at IS NOT NULL
                AND closed_at IS NOT NULL)
            """,
            name="ck_academic_term_status_timestamps",
        ),
        CheckConstraint(
            "is_current = false OR status IN ('open', 'closing')",
            name="ck_academic_term_current_requires_open",
        ),
    )


class GradingScale(BaseModel):
    __tablename__ = "grading_scales"

    min_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "grade", name="uq_grading_scale_tenant_grade"),)


class AssessmentScheme(BaseModel):
    __tablename__ = "assessment_schemes"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AssessmentSchemeStatus] = mapped_column(
        SQLEnum(
            AssessmentSchemeStatus,
            name="assessment_scheme_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AssessmentSchemeStatus.DRAFT,
        server_default=AssessmentSchemeStatus.DRAFT.value,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_assessment_scheme_tenant_name"),
        Index(
            "uq_assessment_scheme_active_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "(status = 'draft' AND activated_at IS NULL AND archived_at IS NULL) OR "
            "(status = 'active' AND activated_at IS NOT NULL AND archived_at IS NULL) OR "
            "(status = 'archived' AND archived_at IS NOT NULL)",
            name="ck_assessment_scheme_status_timestamps",
        ),
    )


class AssessmentComponent(BaseModel):
    __tablename__ = "assessment_components"

    assessment_scheme_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("assessment_schemes.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    is_hybrid: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "NOT is_hybrid OR is_examinable", name="ck_assessment_component_hybrid_examinable"
        ),
        UniqueConstraint(
            "assessment_scheme_id", "name", name="uq_assessment_component_scheme_name"
        ),
        UniqueConstraint(
            "assessment_scheme_id", "position", name="uq_assessment_component_scheme_position"
        ),
        CheckConstraint(
            "maximum_score > 0 AND maximum_score <= 100",
            name="ck_assessment_component_maximum",
        ),
        CheckConstraint("position >= 0", name="ck_assessment_component_position"),
        Index(
            "ix_assessment_components_tenant_scheme_position",
            "tenant_id",
            "assessment_scheme_id",
            "position",
        ),
    )


class TeacherAssignment(BaseModel):
    __tablename__ = "teacher_assignments"

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("teacher_memberships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def state(self) -> TeacherAssignmentState:
        today = date.today()
        if self.effective_from > today:
            return TeacherAssignmentState.SCHEDULED
        if self.effective_to is not None and self.effective_to < today:
            return TeacherAssignmentState.ENDED
        return TeacherAssignmentState.CURRENT

    @hybrid_property
    def is_active(self) -> bool:
        """Derived operational convenience; effective dates remain authoritative."""

        return self.state == TeacherAssignmentState.CURRENT

    @is_active.inplace.expression
    @classmethod
    def _is_active_expression(cls):
        today = func.current_date()
        return and_(
            cls.effective_from <= today,
            or_(cls.effective_to.is_(None), cls.effective_to >= today),
        )

    __table_args__ = (
        ExcludeConstraint(
            ("tenant_id", "="),
            ("class_id", "="),
            ("curriculum_subject_id", "="),
            (func.daterange(effective_from, effective_to, "[]"), "&&"),
            name="excl_teacher_assignments_effective_overlap",
            using="gist",
        ),
        Index(
            "ix_teacher_assignments_tenant_membership",
            "tenant_id",
            "teacher_membership_id",
        ),
        Index(
            "ix_teacher_assignments_scope_effective_from",
            "tenant_id",
            "class_id",
            "curriculum_subject_id",
            "effective_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_teacher_assignments_effective_range",
        ),
    )


class TeacherAssignmentLifecycleAudit(BaseModel):
    __tablename__ = "teacher_assignment_lifecycle_audits"

    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID,
        ForeignKey("teacher_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    previous_teacher_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("teacher_memberships.id", ondelete="SET NULL"), nullable=True
    )
    new_teacher_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("teacher_memberships.id", ondelete="SET NULL"), nullable=True
    )
    previous_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    acting_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index(
            "ix_teacher_assignment_lifecycle_audits_tenant_assignment",
            "tenant_id",
            "assignment_id",
        ),
        Index(
            "ix_teacher_assignment_audits_tenant_class_curriculum_subject",
            "tenant_id",
            "class_id",
            "curriculum_subject_id",
        ),
    )


class StudentProgressionRun(BaseModel):
    __tablename__ = "student_progression_runs"

    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    next_academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(150), nullable=False)
    terminal_completion_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[StudentProgressionRunStatus] = mapped_column(
        SQLEnum(
            StudentProgressionRunStatus,
            name="student_progression_run_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentProgressionRunStatus.PENDING,
        server_default=StudentProgressionRunStatus.PENDING.value,
    )
    total_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    promoted_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    graduated_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    skipped_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pending_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_students: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initiated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_student_progression_run_tenant_idempotency"
        ),
        UniqueConstraint(
            "tenant_id", "academic_session_id", name="uq_student_progression_run_tenant_session"
        ),
        Index("ix_student_progression_runs_tenant_status", "tenant_id", "status"),
        Index("ix_student_progression_runs_tenant_session", "tenant_id", "academic_session_id"),
        CheckConstraint(
            "total_students >= 0 AND promoted_students >= 0 AND graduated_students >= 0 AND skipped_students >= 0 AND pending_students >= 0 AND failed_students >= 0",
            name="ck_progression_run_nonnegative_counts",
        ),
        CheckConstraint(
            "promoted_students + graduated_students + skipped_students + pending_students + failed_students <= total_students",
            name="ck_progression_run_count_total",
        ),
        CheckConstraint(
            "(status IN ('pending', 'processing') AND completed_at IS NULL) OR (status IN ('completed', 'failed') AND completed_at IS NOT NULL)",
            name="ck_progression_run_completion_consistency",
        ),
    )


class StudentProgressionItem(BaseModel):
    __tablename__ = "student_progression_items"

    progression_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("student_progression_runs.id", ondelete="RESTRICT"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    from_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("student_enrollments.id", ondelete="RESTRICT"), nullable=True
    )
    to_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("student_enrollments.id", ondelete="RESTRICT"), nullable=True
    )
    from_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=False
    )
    to_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=True
    )
    from_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=True
    )
    to_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[StudentProgressionItemAction] = mapped_column(
        SQLEnum(
            StudentProgressionItemAction,
            name="student_progression_item_action",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[StudentProgressionItemStatus] = mapped_column(
        SQLEnum(
            StudentProgressionItemStatus,
            name="student_progression_item_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "progression_run_id", "student_id", name="uq_progression_item_run_student"
        ),
        Index("ix_progression_items_tenant_run", "tenant_id", "progression_run_id"),
        Index("ix_progression_items_tenant_student", "tenant_id", "student_id"),
        Index("ix_progression_items_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "status <> 'completed' OR action IN ('progress', 'complete')",
            name="ck_progression_item_completed_action",
        ),
    )


class StudentSubjectResult(BaseModel):
    __tablename__ = "student_subject_results"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    teacher_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("teacher_memberships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    curriculum_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("teacher_assignments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID,
        ForeignKey("student_enrollments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("academic_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("academic_terms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    grading_scale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("grading_scales.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    assessment_scheme_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("assessment_schemes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(10), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[AcademicResultStatus] = mapped_column(
        SQLEnum(
            AcademicResultStatus,
            name="academic_result_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AcademicResultStatus.DRAFT,
        server_default=AcademicResultStatus.DRAFT.value,
    )
    recorded_by_actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    recorded_by_actor_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_actor_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    submitted_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "student_id",
            "curriculum_subject_id",
            "academic_session_id",
            "academic_term_id",
            name="uq_student_subject_result_scope_v2",
        ),
        Index("ix_student_subject_results_tenant_student", "tenant_id", "student_id"),
        Index("ix_student_subject_results_tenant_class", "tenant_id", "class_id"),
        Index(
            "ix_student_subject_results_tenant_teacher_membership",
            "tenant_id",
            "teacher_membership_id",
        ),
        Index("ix_student_subject_results_tenant_status", "tenant_id", "status"),
        Index(
            "ix_student_subject_results_student_period",
            "tenant_id",
            "student_id",
            "academic_session_id",
            "academic_term_id",
        ),
        Index(
            "ix_student_subject_results_class_period_status",
            "tenant_id",
            "class_id",
            "academic_session_id",
            "academic_term_id",
            "status",
        ),
        Index(
            "ix_student_subject_results_teacher_period",
            "tenant_id",
            "teacher_membership_id",
            "academic_session_id",
            "academic_term_id",
        ),
        CheckConstraint(
            """
            status = 'draft'
            OR (submitted_at IS NOT NULL
                AND submitted_by_actor_type IS NOT NULL
                AND submitted_by_actor_id IS NOT NULL)
            """,
            name="ck_student_subject_results_submitted_metadata",
        ),
        CheckConstraint(
            """
            status = 'draft'
            OR (total_score IS NOT NULL
                AND grade IS NOT NULL
                AND grading_scale_id IS NOT NULL)
            """,
            name="ck_student_subject_results_completeness",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'locked') OR (approved_at IS NOT NULL AND approved_by_admin_id IS NOT NULL)",
            name="ck_student_subject_results_approved_metadata",
        ),
        CheckConstraint(
            "status <> 'locked' OR (locked_at IS NOT NULL AND locked_by_admin_id IS NOT NULL)",
            name="ck_student_subject_results_locked_metadata",
        ),
    )


class StudentAssessmentScore(BaseModel):
    __tablename__ = "student_assessment_scores"

    student_subject_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("student_subject_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    assessment_component_id: Mapped[uuid.UUID] = mapped_column(
        UUID,
        ForeignKey("assessment_components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    cbt_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    cbt_maximum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    theory_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    source_exam_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "cbt_score IS NULL OR cbt_score >= 0", name="ck_student_assessment_cbt_nonnegative"
        ),
        CheckConstraint(
            "theory_score IS NULL OR theory_score >= 0",
            name="ck_student_assessment_theory_nonnegative",
        ),
        CheckConstraint(
            "cbt_maximum_score IS NULL OR cbt_maximum_score > 0",
            name="ck_student_assessment_cbt_max_positive",
        ),
        UniqueConstraint(
            "student_subject_result_id",
            "assessment_component_id",
            name="uq_student_assessment_score_result_component",
        ),
        CheckConstraint("score >= 0", name="ck_student_assessment_score_nonnegative"),
        Index(
            "ix_student_assessment_scores_tenant_result",
            "tenant_id",
            "student_subject_result_id",
        ),
        Index(
            "ix_student_assessment_scores_tenant_component",
            "tenant_id",
            "assessment_component_id",
        ),
    )
