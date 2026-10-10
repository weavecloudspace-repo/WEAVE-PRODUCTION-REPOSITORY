# ====================================== #
#             cbt/models.py              #
# ====================================== #

"""Database models for Weave CBT server registration and authentication."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    BigInteger,
    UniqueConstraint,
    func,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.cbt.enums import CBTServerStatus
from app.shared.base_model import Base, BaseModel, PUBLIC_SCHEMA
from app.shared.mixins import TimestampMixin, UUIDMixin


class CBTServer(BaseModel):
    """Represent one local Weave CBT server paired to a tenant."""

    __tablename__ = "cbt_servers"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    hostname_prefix: Mapped[str] = mapped_column(String(63), nullable=False)

    @property
    def hostname(self) -> str:
        from app.config.settings import settings
        from app.modules.cbt.dns.hostname import hostname_for_server

        return hostname_for_server(
            prefix=self.hostname_prefix,
            tenant_id=self.tenant_id,
            environment=settings.ENV.value,
        )

    status: Mapped[CBTServerStatus] = mapped_column(
        SQLEnum(
            CBTServerStatus,
            name="cbt_server_status",
            schema=PUBLIC_SCHEMA,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=CBTServerStatus.ACTIVE,
        server_default=CBTServerStatus.ACTIVE.value,
    )
    paired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paired_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.tenant_admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.tenant_admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_cbt_servers_tenant_status", "tenant_id", "status"),
        Index("ix_cbt_servers_tenant_last_seen", "tenant_id", "last_seen_at"),
        Index(
            "uq_cbt_servers_tenant_normalized_name",
            "tenant_id",
            func.lower(
                func.regexp_replace(
                    func.btrim(name),
                    r"\s+",
                    " ",
                    "g",
                )
            ),
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class CBTServerCredential(UUIDMixin, TimestampMixin, Base):
    """Store authentication material issued to one paired CBT server."""

    __tablename__ = "cbt_server_credentials"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.cbt_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_cbt_server_credentials_server_revoked", "server_id", "revoked_at"),
        Index(
            "uq_cbt_server_credentials_active_server",
            "server_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class CBTPairingCode(BaseModel):
    """Store a short-lived, one-time CBT server pairing challenge."""

    __tablename__ = "cbt_pairing_codes"

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.tenant_admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.cbt_servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_cbt_pairing_codes_tenant_expiry", "tenant_id", "expires_at"),
        Index(
            "ix_cbt_pairing_codes_tenant_active",
            "tenant_id",
            "expires_at",
            postgresql_where=text("used_at IS NULL AND invalidated_at IS NULL"),
        ),
    )


class CBTDNSChallenge(BaseModel):
    """Provider-owned TXT record for one authenticated server's ACME DNS-01 challenge."""

    __tablename__ = "cbt_dns_challenges"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.cbt_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fqdn: Mapped[str] = mapped_column(String(253), nullable=False)
    value_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_record_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("server_id", "request_id", name="uq_cbt_dns_challenges_server_request"),
        Index(
            "ix_cbt_dns_challenges_expiry",
            "expires_at",
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_cbt_dns_challenges_tenant_server", "tenant_id", "server_id"),
    )
