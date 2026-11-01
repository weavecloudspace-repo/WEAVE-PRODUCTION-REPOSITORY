"""Teacher account, tenant membership, invitation, and capability models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import Base, BaseModel, PUBLIC_SCHEMA
from app.shared.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.subjects.models import Subject


def enum_values(enum_cls: type[PyEnum]) -> list[Any]:
    return [item.value for item in enum_cls]


class TeacherAccountStatus(str, PyEnum):
    PENDING = "pending"
    ACTIVE = "active"
    LOCKED = "locked"
    INACTIVE = "inactive"


class TeacherStatus(str, PyEnum):
    """Compatibility enum for tenant-facing status comparisons."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class TeacherMembershipStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class TeacherInvitationStatus(str, PyEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TeacherAccount(UUIDMixin, TimestampMixin, Base):
    """Global teacher login identity shared across tenants."""

    __tablename__ = "teacher_accounts"

    email: Mapped[str] = mapped_column(String(300), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    qualification: Mapped[str | None] = mapped_column(String(100), nullable=True)
    specialization: Mapped[str | None] = mapped_column(String(150), nullable=True)
    passport_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    account_status: Mapped[TeacherAccountStatus] = mapped_column(
        SQLEnum(
            TeacherAccountStatus,
            name="teacher_account_status_v2",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=TeacherAccountStatus.PENDING,
        server_default=TeacherAccountStatus.PENDING.value,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    memberships: Mapped[list["TeacherMembership"]] = relationship(
        "TeacherMembership",
        back_populates="teacher_account",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_teacher_accounts_email"),
        Index("ix_teacher_accounts_email", "email"),
        Index(
            "ix_teacher_accounts_status_active",
            "account_status",
            "is_active",
        ),
    )

    @property
    def profile_completed(self) -> bool:
        return bool(
            self.first_name
            and self.first_name.strip()
            and self.last_name
            and self.last_name.strip()
        )


class TeacherMembership(BaseModel):
    """Tenant-scoped employment and authorization context."""

    __tablename__ = "teacher_memberships"

    teacher_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{PUBLIC_SCHEMA}.teacher_accounts.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    staff_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[TeacherMembershipStatus] = mapped_column(
        SQLEnum(
            TeacherMembershipStatus,
            name="teacher_membership_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=TeacherMembershipStatus.ACTIVE,
        server_default=TeacherMembershipStatus.ACTIVE.value,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    end_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receive_email_notifications: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    receive_push_notifications: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    teacher_account: Mapped[TeacherAccount] = relationship(
        "TeacherAccount",
        back_populates="memberships",
    )
    subject_links: Mapped[list["TeacherMembershipSubject"]] = relationship(
        "TeacherMembershipSubject",
        back_populates="teacher_membership",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_teacher_memberships_tenant_id"),
        UniqueConstraint(
            "teacher_account_id",
            "tenant_id",
            name="uq_teacher_memberships_account_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "staff_id",
            name="uq_teacher_memberships_tenant_staff_id",
        ),
        CheckConstraint(
            """
            (status IN ('active', 'suspended') AND ended_at IS NULL)
            OR (status = 'inactive' AND ended_at IS NOT NULL)
            """,
            name="ck_teacher_membership_status_end_consistency",
        ),
        Index(
            "ix_teacher_memberships_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_teacher_memberships_account_status",
            "teacher_account_id",
            "status",
        ),
    )

    @property
    def email(self) -> str:
        return self.teacher_account.email

    @property
    def password_hash(self) -> str:
        return self.teacher_account.password_hash

    @property
    def first_name(self) -> str | None:
        return self.teacher_account.first_name

    @property
    def last_name(self) -> str | None:
        return self.teacher_account.last_name

    @property
    def phone_number(self) -> str | None:
        return self.teacher_account.phone_number

    @property
    def qualification(self) -> str | None:
        return self.teacher_account.qualification

    @property
    def specialization(self) -> str | None:
        return self.teacher_account.specialization

    @property
    def passport_photo_url(self) -> str | None:
        return self.teacher_account.passport_photo_url

    @property
    def account_status(self) -> TeacherAccountStatus:
        return self.teacher_account.account_status

    @property
    def is_verified(self) -> bool:
        return self.teacher_account.is_verified

    @property
    def is_active(self) -> bool:
        return self.teacher_account.is_active and self.status != TeacherMembershipStatus.INACTIVE

    @property
    def profile_completed(self) -> bool:
        return self.teacher_account.profile_completed

    @property
    def last_login_at(self) -> datetime | None:
        return self.teacher_account.last_login_at


class TeacherInvitation(BaseModel):
    """Single-use invitation for a teacher to join one tenant."""

    __tablename__ = "teacher_invitations"

    invited_email: Mapped[str] = mapped_column(String(300), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(255), nullable=False)
    staff_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[TeacherInvitationStatus] = mapped_column(
        SQLEnum(
            TeacherInvitationStatus,
            name="teacher_invitation_status",
            schema=PUBLIC_SCHEMA,
            values_callable=enum_values,
        ),
        nullable=False,
        default=TeacherInvitationStatus.PENDING,
        server_default=TeacherInvitationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{PUBLIC_SCHEMA}.tenant_admins.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    accepted_by_teacher_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{PUBLIC_SCHEMA}.teacher_accounts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_teacher_invitations_token_digest",
        ),
        CheckConstraint(
            """
            (
                status = 'accepted'
                AND accepted_at IS NOT NULL
                AND accepted_by_teacher_account_id IS NOT NULL
            )
            OR status <> 'accepted'
            """,
            name="ck_teacher_invitation_acceptance_consistency",
        ),
        CheckConstraint(
            """
            (status = 'revoked' AND revoked_at IS NOT NULL)
            OR status <> 'revoked'
            """,
            name="ck_teacher_invitation_revocation_consistency",
        ),
        Index(
            "ix_teacher_invitations_tenant_email_status",
            "tenant_id",
            "invited_email",
            "status",
        ),
        Index(
            "uq_teacher_invitations_pending_email",
            "tenant_id",
            "invited_email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )


class TeacherMembershipSubject(BaseModel):
    """Tenant-approved subject capability for one teacher membership."""

    __tablename__ = "teacher_membership_subjects"

    teacher_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{PUBLIC_SCHEMA}.teacher_memberships.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{PUBLIC_SCHEMA}.subjects.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    teacher_membership: Mapped[TeacherMembership] = relationship(
        "TeacherMembership",
        back_populates="subject_links",
    )
    subject: Mapped["Subject"] = relationship(
        "Subject",
        back_populates="teacher_links",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "teacher_membership_id",
            "subject_id",
            name=("uq_teacher_membership_subjects_tenant_membership_subject"),
        ),
        Index(
            "ix_teacher_membership_subjects_membership",
            "tenant_id",
            "teacher_membership_id",
        ),
        Index(
            "ix_teacher_membership_subjects_subject",
            "tenant_id",
            "subject_id",
        ),
    )


# Tenant-facing code uses Teacher as the membership actor. Global login code uses
# TeacherAccount explicitly.
Teacher = TeacherMembership
TeacherSubject = TeacherMembershipSubject
