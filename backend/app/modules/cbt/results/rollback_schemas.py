"""Wire contract for draft-only result withdrawal."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CBTResultRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_id: UUID
    source_batch_id: UUID
    student_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)
    reason: str = Field(min_length=5, max_length=1024)

    @model_validator(mode="after")
    def ensure_unique_students(self):
        if self.student_ids is not None and len(set(self.student_ids)) != len(self.student_ids):
            raise ValueError("Duplicate student IDs in rollback request")
        return self


class CBTResultRollbackItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    student_id: UUID
    status: Literal["pending", "completed", "rejected"]
    error_code: str | None = None
    error_detail: str | None = None


class CBTResultRollbackResponse(BaseModel):
    operation_id: UUID
    source_batch_id: UUID
    status: Literal["pending", "processing", "completed", "partially_completed", "rejected"]
    target_count: int
    completed_count: int
    rejected_count: int
    completed_at: datetime | None = None
    items: list[CBTResultRollbackItemResponse] = Field(default_factory=list)
