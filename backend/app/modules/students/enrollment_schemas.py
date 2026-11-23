"""Canonical request contracts for student placement operations."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StudentClassPlacementRequest(EnrollmentInput):
    """Bulk-place unassigned enrollments into a class in their existing level."""

    academic_session_id: uuid.UUID
    academic_level_id: uuid.UUID
    target_class_id: uuid.UUID
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)

    @field_validator("student_ids")
    @classmethod
    def unique_students(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("student_ids must not contain duplicates")
        # Normalize row-lock acquisition order for every bulk placement caller.
        return sorted(value, key=lambda student_id: student_id.int)


class StudentClassPlacementResponse(BaseModel):
    placed_student_ids: list[uuid.UUID]
    target_class_id: uuid.UUID
    placed_count: int


class StudentClassReassignmentRequest(EnrollmentInput):
    """Move one already-classed student within the same academic level."""

    carry_finalized_results: bool = False

    target_class_id: uuid.UUID
    academic_session_id: uuid.UUID
    effective_date: date
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("reason cannot be empty")
        return cleaned


class StudentAcademicLevelReassignmentRequest(EnrollmentInput):
    """Move one student to a different academic level and a class in that level."""

    target_academic_level_id: uuid.UUID
    target_class_id: uuid.UUID
    academic_session_id: uuid.UUID
    effective_date: date
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("reason cannot be empty")
        return cleaned


class ExistingResultReconciliationRequest(EnrollmentInput):
    """Correct existing academic results after a previous class reassignment."""

    academic_session_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)
    carry_finalized_results: bool = False


class PlacementImpactPreviewRequest(EnrollmentInput):
    target_academic_level_id: uuid.UUID
    target_class_id: uuid.UUID
    academic_session_id: uuid.UUID
    academic_term_id: uuid.UUID
    effective_date: date


class StudentUpcomingEnrollmentUpdateRequest(EnrollmentInput):
    """Edit a placement segment before it becomes effective."""

    target_academic_level_id: uuid.UUID
    target_class_id: uuid.UUID
    academic_session_id: uuid.UUID
    effective_date: date
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("reason cannot be empty")
        return cleaned


class PlacementImpactSubject(BaseModel):
    curriculum_subject_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str


class PlacementResultImpact(BaseModel):
    result_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    status: str
    action: str
    reason: str = ""


class PlacementImpactPreviewResponse(BaseModel):
    current_academic_level_id: uuid.UUID
    current_class_id: uuid.UUID | None
    destination_academic_level_id: uuid.UUID
    destination_class_id: uuid.UUID
    current_department: str | None = None
    destination_department: str | None = None
    department_changed: bool
    subjects_remaining_applicable: list[PlacementImpactSubject] = Field(default_factory=list)
    subjects_becoming_historical_only: list[PlacementImpactSubject] = Field(default_factory=list)
    destination_subjects_without_scores: list[PlacementImpactSubject] = Field(default_factory=list)
    teacher_comment_requires_review: bool
    report_card_affected: bool
    ranking_context_affected: bool = True
    warnings: list[str] = Field(default_factory=list)
    result_impacts: list[PlacementResultImpact] = Field(default_factory=list)
