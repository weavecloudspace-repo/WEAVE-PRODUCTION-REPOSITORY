# ==========================#
#  student model.py#
# ==========================#
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.shared.base_model import BaseModel, PUBLIC_SCHEMA

if TYPE_CHECKING:
    from app.modules.classes.models import AcademicLevel, ClassRoom
    from app.modules.parents.models import ParentInvitation, ParentMembership
    from app.modules.student_academics.models import AcademicSession


def enum_values(enum_cls: type[PyEnum]) -> list[Any]:
    """Persist enum values rather than enum member names."""

    return [item.value for item in enum_cls]


class Gender(str, PyEnum):
    MALE = "male"
    FEMALE = "female"


class AcademicStatus(str, PyEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    SUSPENDED = "suspended"
    GRADUATED = "graduated"
    EXPELLED = "expelled"


class ParentRelationship(str, PyEnum):
    FATHER = "father"
    MOTHER = "mother"
    GUARDIAN = "guardian"
    SPONSOR = "sponsor"
    OTHER = "other"


class StudentParentLinkStatus(str, PyEnum):
    """Access state for one verified parent-child relationship."""

    ACTIVE = "active"
    READ_ONLY = "read_only"
    ALUMNI_READ_ONLY = "alumni_read_only"
    ENDED = "ended"


class ParentLinkVerifiedByType(str, PyEnum):
    """Actor category that verified a parent-child relationship."""

    STUDENT = "student"
    TENANT_ADMIN = "tenant_admin"
    SYSTEM = "system"


class StudentEnrollmentOutcome(str, PyEnum):
    """Reason an immutable enrollment segment started or ended."""

    ENROLLED = "enrolled"
    PROMOTED = "promoted"
    REPEATED = "repeated"
    DEMOTED = "demoted"
    RECLASSIFIED = "reclassified"
    CLASS_PLACED = "class_placed"
    LEVEL_REASSIGNED = "level_reassigned"
    REINSTATED = "reinstated"
    WITHDRAWN = "withdrawn"
    EXPELLED = "expelled"
    GRADUATED = "graduated"


class StudentProfileStatus(str, PyEnum):
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


class StudentAccountStatus(str, PyEnum):
    """Student account lifecycle status."""

    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"


class StudentAccessCodePurpose(str, PyEnum):
    """Reason why a temporary student access code was created."""

    INITIAL_SETUP = "initial_setup"
    PASSWORD_RESET = "password_reset"


class StudentParentLinkRequestStatus(str, PyEnum):
    """Lifecycle states for parent-student link approval requests."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Student(BaseModel):
    """Student actor account and academic profile.

    Class placement is not persisted on this row. The ``class_id`` projection is
    attached after StudentEnrollment is declared and is calculated from the single
    open enrollment.
    """

    __tablename__ = "students"

    admission_number: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_status: Mapped[StudentAccountStatus] = mapped_column(
        SQLEnum(
            StudentAccountStatus,
            name="student_account_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentAccountStatus.ACTIVE,
        server_default=StudentAccountStatus.ACTIVE.value,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    password_reset_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(
        SQLEnum(
            Gender,
            name="studentgender",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    state_of_origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    passport_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admission_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AcademicStatus] = mapped_column(
        SQLEnum(
            AcademicStatus,
            name="academicstatus",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=AcademicStatus.ACTIVE,
        server_default=AcademicStatus.ACTIVE.value,
    )
    promotion_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    archive_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_status: Mapped[StudentProfileStatus] = mapped_column(
        SQLEnum(
            StudentProfileStatus,
            name="studentprofilestatus",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentProfileStatus.INCOMPLETE,
        server_default=StudentProfileStatus.INCOMPLETE.value,
    )

    parent_links: Mapped[list["StudentParentLink"]] = relationship(
        "StudentParentLink",
        back_populates="student",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    parent_link_requests: Mapped[list["StudentParentLinkRequest"]] = relationship(
        "StudentParentLinkRequest",
        back_populates="student",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    access_codes: Mapped[list["StudentAccessCode"]] = relationship(
        "StudentAccessCode",
        back_populates="student",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    enrollments: Mapped[list["StudentEnrollment"]] = relationship(
        "StudentEnrollment",
        back_populates="student",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="StudentEnrollment.started_on",
    )
    parent_invitations: Mapped[list["ParentInvitation"]] = relationship(
        "ParentInvitation",
        primaryjoin="Student.id == foreign(ParentInvitation.student_id)",
        cascade="save-update, merge",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_students_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "admission_number", name="uq_students_tenant_admission_number"
        ),
        CheckConstraint(
            """
            (
                is_archived = false
                AND archived_at IS NULL
                AND archived_by_admin_id IS NULL
                AND archive_reason IS NULL
            )
            OR
            (
                is_archived = true
                AND archived_at IS NOT NULL
                AND archive_reason IS NOT NULL
            )
            """,
            name="ck_students_archive_consistency",
        ),
        CheckConstraint(
            "status <> 'graduated' OR graduation_date IS NOT NULL",
            name="ck_students_graduated_has_date",
        ),
        Index("ix_students_tenant_admission_number", "tenant_id", "admission_number"),
        Index(
            "ix_students_tma_admission_trgm",
            "admission_number",
            postgresql_using="gin",
            postgresql_ops={"admission_number": "gin_trgm_ops"},
        ),
        Index(
            "ix_students_tma_full_name_trgm",
            text("(btrim(coalesce(first_name, '') || ' ' || coalesce(last_name, ''))) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index("ix_students_tenant_status", "tenant_id", "status"),
        Index("ix_students_tenant_account_status", "tenant_id", "account_status"),
        Index("ix_students_tenant_archived", "tenant_id", "is_archived"),
    )


class StudentEnrollment(BaseModel):
    """Immutable historical segment of one student's academic placement."""

    __tablename__ = "student_enrollments"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    academic_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_levels.id", ondelete="RESTRICT"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=True
    )
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_outcome: Mapped[StudentEnrollmentOutcome] = mapped_column(
        SQLEnum(
            StudentEnrollmentOutcome,
            name="student_enrollment_outcome",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentEnrollmentOutcome.ENROLLED,
        server_default=StudentEnrollmentOutcome.ENROLLED.value,
    )
    exit_outcome: Mapped[StudentEnrollmentOutcome | None] = mapped_column(
        SQLEnum(
            StudentEnrollmentOutcome,
            name="student_enrollment_outcome",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    entry_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )
    ended_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    student: Mapped["Student"] = relationship("Student", back_populates="enrollments")
    academic_level: Mapped["AcademicLevel"] = relationship(
        "AcademicLevel", foreign_keys=[academic_level_id]
    )
    classroom: Mapped["ClassRoom | None"] = relationship("ClassRoom", foreign_keys=[class_id])
    academic_session: Mapped["AcademicSession"] = relationship(
        "AcademicSession", foreign_keys=[academic_session_id]
    )

    @hybrid_property
    def is_current(self) -> bool:
        """Return whether this placement segment is effective today."""

        today = date.today()
        return self.started_on <= today and (self.ended_on is None or self.ended_on >= today)

    @is_current.expression
    def is_current(cls):
        today = func.current_date()
        return (cls.started_on <= today) & (cls.ended_on.is_(None) | (cls.ended_on >= today))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            "student_id",
            "class_id",
            name="uq_student_enrollments_tenant_id_student_class",
        ),
        CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on", name="ck_student_enrollment_date_order"
        ),
        CheckConstraint(
            """
            (
                ended_on IS NULL
                AND exit_outcome IS NULL
                AND exit_reason IS NULL
                AND ended_by_admin_id IS NULL
            )
            OR
            (
                ended_on IS NOT NULL
                AND exit_outcome IS NOT NULL
                AND exit_reason IS NOT NULL
            )
            """,
            name="ck_student_enrollment_exit_consistency",
        ),
        Index(
            "uq_student_enrollments_one_current",
            "tenant_id",
            "student_id",
            unique=True,
            postgresql_where=text("ended_on IS NULL"),
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("student_id", "="),
            (func.daterange(started_on, ended_on, "[]"), "&&"),
            name="excl_student_enrollments_effective_overlap",
            using="gist",
        ),
        Index("ix_student_enrollments_tenant_student", "tenant_id", "student_id"),
        Index("ix_student_enrollments_tenant_class", "tenant_id", "class_id"),
        Index("ix_student_enrollments_tenant_level", "tenant_id", "academic_level_id"),
        Index("ix_student_enrollments_tenant_session", "tenant_id", "academic_session_id"),
        Index("ix_student_enrollments_student_session", "student_id", "academic_session_id"),
    )


Student.class_id = column_property(  # type: ignore[attr-defined]
    select(StudentEnrollment.class_id)
    .where(
        StudentEnrollment.tenant_id == Student.tenant_id,
        StudentEnrollment.student_id == Student.id,
        StudentEnrollment.started_on <= func.current_date(),
        (
            StudentEnrollment.ended_on.is_(None)
            | (StudentEnrollment.ended_on >= func.current_date())
        ),
    )
    .correlate(Student)
    .scalar_subquery()
)


class StudentAccessCode(BaseModel):
    """Temporary code used for student first login or password reset."""

    __tablename__ = "student_access_codes"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    code_digest: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[StudentAccessCodePurpose] = mapped_column(
        SQLEnum(
            StudentAccessCodePurpose,
            name="student_access_code_purpose",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_admins.id", ondelete="SET NULL"), nullable=True
    )

    student: Mapped["Student"] = relationship("Student", back_populates="access_codes")

    __table_args__ = (
        Index("ix_student_access_codes_tenant_student", "tenant_id", "student_id"),
        Index("ix_student_access_codes_tenant_code_digest", "tenant_id", "code_digest"),
        Index("ix_student_access_codes_tenant_student_used", "tenant_id", "student_id", "is_used"),
        Index("ix_student_access_codes_expires_at", "expires_at"),
        Index("ix_student_access_codes_is_used", "is_used"),
    )


class StudentParentLink(BaseModel):
    """Verified tenant-scoped relationship granting access to one student."""

    __tablename__ = "student_parent_links"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    parent_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.parent_memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relationship_type: Mapped[ParentRelationship] = mapped_column(
        SQLEnum(
            ParentRelationship,
            name="parentrelationship",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ParentRelationship.GUARDIAN,
        server_default=ParentRelationship.GUARDIAN.value,
    )
    status: Mapped[StudentParentLinkStatus] = mapped_column(
        SQLEnum(
            StudentParentLinkStatus,
            name="student_parent_link_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentParentLinkStatus.ACTIVE,
        server_default=StudentParentLinkStatus.ACTIVE.value,
    )
    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    receives_academic_updates: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    receives_fee_updates: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    verified_by_type: Mapped[ParentLinkVerifiedByType] = mapped_column(
        SQLEnum(
            ParentLinkVerifiedByType,
            name="parent_link_verified_by_type",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    student: Mapped["Student"] = relationship("Student", back_populates="parent_links")
    parent_membership: Mapped["ParentMembership"] = relationship(
        "ParentMembership", back_populates="student_links"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "student_id",
            "parent_membership_id",
            name="uq_student_parent_link_tenant_student_membership",
        ),
        CheckConstraint(
            """
            (
                status IN ('active', 'read_only', 'alumni_read_only')
                AND ended_at IS NULL
            )
            OR
            (
                status = 'ended'
                AND ended_at IS NOT NULL
            )
            """,
            name="ck_student_parent_link_status_end_consistency",
        ),
        CheckConstraint(
            "(status = 'ended' AND end_reason IS NOT NULL) OR status <> 'ended'",
            name="ck_student_parent_link_ended_reason",
        ),
        Index("ix_student_parent_links_tenant_student", "tenant_id", "student_id"),
        Index("ix_student_parent_links_tenant_membership", "tenant_id", "parent_membership_id"),
        Index("ix_student_parent_links_tenant_status", "tenant_id", "status"),
        Index(
            "uq_student_parent_links_primary_contact",
            "tenant_id",
            "student_id",
            unique=True,
            postgresql_where=text(
                "is_primary_contact = true AND status IN ('active', 'read_only', 'alumni_read_only')"
            ),
        ),
    )


class StudentParentLinkRequest(BaseModel):
    """Approval request produced from a valid ParentInvitation."""

    __tablename__ = "student_parent_link_requests"

    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.parent_invitations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    parent_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.parent_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.parent_memberships.id", ondelete="RESTRICT"),
        nullable=True,
    )
    admission_number_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    relationship_type: Mapped[ParentRelationship] = mapped_column(
        SQLEnum(
            ParentRelationship,
            name="parentrelationship",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ParentRelationship.GUARDIAN,
        server_default=ParentRelationship.GUARDIAN.value,
    )
    status: Mapped[StudentParentLinkRequestStatus] = mapped_column(
        SQLEnum(
            StudentParentLinkRequestStatus,
            name="student_parent_link_request_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StudentParentLinkRequestStatus.PENDING,
        server_default=StudentParentLinkRequestStatus.PENDING.value,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_by_type: Mapped[ParentLinkVerifiedByType | None] = mapped_column(
        SQLEnum(
            ParentLinkVerifiedByType,
            name="parent_link_verified_by_type",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    responded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    student: Mapped["Student"] = relationship("Student", back_populates="parent_link_requests")
    parent_membership: Mapped["ParentMembership | None"] = relationship(
        "ParentMembership", back_populates="student_link_requests"
    )

    __table_args__ = (
        UniqueConstraint("invitation_id", name="uq_student_parent_link_requests_invitation"),
        CheckConstraint(
            """
            (
                status = 'pending'
                AND responded_at IS NULL
                AND responded_by_type IS NULL
                AND responded_by_id IS NULL
            )
            OR
            (
                status <> 'pending'
                AND responded_at IS NOT NULL
            )
            """,
            name="ck_parent_link_request_response_consistency",
        ),
        CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name="ck_parent_link_request_rejection_reason",
        ),
        Index("ix_student_parent_link_requests_tenant_student", "tenant_id", "student_id"),
        Index(
            "ix_student_parent_link_requests_tenant_membership", "tenant_id", "parent_membership_id"
        ),
        Index("ix_student_parent_link_requests_tenant_account", "tenant_id", "parent_account_id"),
        Index("ix_student_parent_link_requests_tenant_status", "tenant_id", "status"),
        Index(
            "uq_student_parent_link_requests_pending_account_student",
            "tenant_id",
            "student_id",
            "parent_account_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
