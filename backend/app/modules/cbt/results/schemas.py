"""Schemas for CBT -> Weave academic result ingestion."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.cbt.enums import (
    CBTResultIngestionOutcome,
    CBTResultIngestionStatus,
)


class CBTResultInputBase(BaseModel):
    """Base schema for payloads received from a paired CBT server."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class CBTResultOutputBase(BaseModel):
    """Base schema for payloads sent to a paired CBT server."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


class CBTResultBulkScoreItem(CBTResultInputBase):
    """One student's score for the assessment component owned by the batch."""

    student_id: UUID
    score: Decimal = Field(
        ge=0,
        max_digits=5,
        decimal_places=2,
    )


class CBTResultBulkRequest(CBTResultInputBase):
    """Bulk component-score patch produced from one local CBT exam context."""

    batch_id: UUID
    source_exam_id: UUID
    academic_session_id: UUID
    academic_term_id: UUID
    academic_level_id: UUID
    curriculum_subject_id: UUID
    assessment_component_id: UUID
    exam_date: date
    # Older CBT clients omit this, meaning the full component maximum.
    cbt_maximum_score: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
    scores: list[CBTResultBulkScoreItem] = Field(
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_unique_students(self) -> CBTResultBulkRequest:
        student_ids = [item.student_id for item in self.scores]
        if len(student_ids) != len(set(student_ids)):
            raise ValueError("Each student may appear only once in a CBT result batch.")
        return self


class CBTResultBulkError(CBTResultOutputBase):
    """One student score rejected during bulk ingestion."""

    student_id: UUID
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=1000)


class CBTResultBulkResponse(CBTResultOutputBase):
    """Summary returned after processing one CBT result batch."""

    batch_id: UUID
    source_exam_id: UUID
    processed_at: datetime
    received: int = Field(ge=0)
    applied: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    rejected: int = Field(ge=0)
    errors: list[CBTResultBulkError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_processing_counts(self) -> CBTResultBulkResponse:
        processed = self.applied + self.unchanged + self.rejected
        if processed != self.received:
            raise ValueError("Applied, unchanged and rejected counts must equal received count.")
        if len(self.errors) != self.rejected:
            raise ValueError("Each rejected score must have a corresponding error.")
        return self


class CBTResultAuditFilterOption(CBTResultOutputBase):
    """One backend-owned human-readable filter choice."""

    id: UUID
    label: str = Field(min_length=1, max_length=255)


class CBTResultAuditFilterOptionsResponse(CBTResultOutputBase):
    """Tenant-scoped filter metadata for the CBT ingestion audit UI."""

    exams: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    sessions: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    terms: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    levels: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    subjects: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    assessment_components: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    servers: list[CBTResultAuditFilterOption] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class CBTResultIngestionBatchResponse(CBTResultOutputBase):
    """Read-only forensic view of one CBT ingestion batch."""

    id: UUID
    tenant_id: UUID
    cbt_server_id: UUID
    credential_id: UUID
    batch_id: UUID
    ingestion_reference: str
    source_exam_id: UUID
    source_exam_title: str | None = None
    request_hash: str
    academic_session_id: UUID
    academic_term_id: UUID
    academic_level_id: UUID
    curriculum_subject_id: UUID
    assessment_component_id: UUID
    exam_date: date
    status: CBTResultIngestionStatus
    received_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    processed_at: datetime | None = None
    batch_error_code: str | None = None
    batch_error_detail: str | None = None
    created_at: datetime
    updated_at: datetime

    server_name: str | None = None
    tenant_name: str | None = None
    academic_session_name: str | None = None
    academic_term_name: str | None = None
    academic_level_name: str | None = None
    subject_name: str | None = None
    assessment_component_name: str | None = None


class CBTResultIngestionItemResponse(CBTResultOutputBase):
    """Read-only forensic view of one student score ingestion decision."""

    id: UUID
    tenant_id: UUID
    ingestion_batch_id: UUID
    submitted_student_id: UUID
    resolved_teacher_assignment_id: UUID | None = None
    incoming_score: Decimal
    previous_score: Decimal | None = None
    resulting_score: Decimal | None = None
    student_subject_result_id: UUID | None = None
    outcome: CBTResultIngestionOutcome
    error_code: str | None = None
    error_detail: str | None = None
    processed_at: datetime
    created_at: datetime
    updated_at: datetime
    student_name: str | None = None
    student_admission_number: str | None = None


class CBTResultIngestionBatchListResponse(CBTResultOutputBase):
    items: list[CBTResultIngestionBatchResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    skip: int = Field(ge=0)
    limit: int = Field(ge=1)


class CBTResultIngestionItemListResponse(CBTResultOutputBase):
    items: list[CBTResultIngestionItemResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    skip: int = Field(ge=0)
    limit: int = Field(ge=1)
