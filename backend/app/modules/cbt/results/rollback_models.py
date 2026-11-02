"""Durable, tenant-scoped CBT result-withdrawal history and work ledger."""

from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.base_model import BaseModel, PUBLIC_SCHEMA


class CBTResultRollbackOperation(BaseModel):
    __tablename__ = "cbt_result_rollback_operations"

    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cbt_server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.cbt_servers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "cbt_server_id", "operation_id", name="uq_cbt_rollback_server_operation"
        ),
        Index("ix_cbt_rollback_tenant_status", "tenant_id", "status"),
        Index("ix_cbt_rollback_server_batch", "tenant_id", "cbt_server_id", "source_batch_id"),
    )


class CBTResultRollbackItem(BaseModel):
    __tablename__ = "cbt_result_rollback_items"

    rollback_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PUBLIC_SCHEMA}.cbt_result_rollback_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "rollback_operation_id", "student_id", name="uq_cbt_rollback_item_student"
        ),
        Index("ix_cbt_rollback_item_operation_status", "rollback_operation_id", "status"),
    )
