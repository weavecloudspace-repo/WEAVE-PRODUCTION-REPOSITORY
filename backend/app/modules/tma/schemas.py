"""Pydantic v2 contracts for WEAVE TMA.

Identity, tenant and actor identifiers are server-controlled and never accepted
from student/teacher create payloads. Correct options are excluded from every
student-facing question schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.tma.models import (
    TMAActorType,
    TMAAssignmentStatus,
    TMAAttemptStatus,
)


class TMAInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TMAOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class TMAAuthoringScope(TMAOutput):
    academic_level_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    level_name: str
    subject_name: str


class TMAAuthoringComponent(TMAOutput):
    id: uuid.UUID
    name: str
    maximum_score: Decimal


class TMAAuthoringClass(TMAOutput):
    id: uuid.UUID
    name: str
    academic_level_id: uuid.UUID


class TMALeadTeacherChoice(TMAOutput):
    teacher_membership_id: uuid.UUID
    academic_level_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    display_name: str


class TMAAuthoringConfiguration(TMAOutput):
    academic_session_id: uuid.UUID | None
    academic_term_id: uuid.UUID | None
    term_name: str | None
    term_open: bool
    scopes: list[TMAAuthoringScope]
    components: list[TMAAuthoringComponent]
    classes: list[TMAAuthoringClass] = Field(default_factory=list)
    lead_teachers: list[TMALeadTeacherChoice] = Field(default_factory=list)


# ---------- Assignment and lifecycle ----------


class TMAAssignmentCreate(TMAInput):
    academic_level_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    academic_session_id: uuid.UUID
    academic_term_id: uuid.UUID
    assessment_component_id: uuid.UUID
    closes_at: AwareDatetime | None = None
    lead_teacher_membership_id: uuid.UUID | None = None


class TMAAssignmentUpdate(TMAInput):
    """Academic scope is draft-only; closing estimate is editable while active."""

    academic_level_id: uuid.UUID | None = None
    curriculum_subject_id: uuid.UUID | None = None
    academic_session_id: uuid.UUID | None = None
    academic_term_id: uuid.UUID | None = None
    assessment_component_id: uuid.UUID | None = None
    closes_at: AwareDatetime | None = None
    lead_teacher_membership_id: uuid.UUID | None = None


class TMAAssignmentResponse(TMAOutput):
    id: uuid.UUID
    academic_level_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    academic_session_id: uuid.UUID
    academic_term_id: uuid.UUID
    assessment_component_id: uuid.UUID
    status: TMAAssignmentStatus
    current_revision_number: int
    created_by_actor_type: TMAActorType
    created_by_actor_id: uuid.UUID
    lead_teacher_membership_id: uuid.UUID | None = None
    activated_at: datetime | None
    closes_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TMAAssignmentListResponse(TMAOutput):
    items: list[TMAAssignmentResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class TMAAssignmentStatusResponse(TMAOutput):
    id: uuid.UUID
    status: TMAAssignmentStatus
    current_revision_number: int
    activated_at: datetime | None
    closes_at: datetime | None
    closed_at: datetime | None


# ---------- Revision history ----------


class TMARevisionCreate(TMAInput):
    """Reason for replacing a published revision, not for reopening CLOSED."""

    invalidation_reason: str = Field(min_length=1, max_length=2000)


class TMARevisionResponse(TMAOutput):
    id: uuid.UUID
    assignment_id: uuid.UUID
    revision_number: int = Field(ge=1)
    published_at: datetime | None
    invalidated_at: datetime | None
    invalidated_by_actor_type: TMAActorType | None
    invalidated_by_actor_id: uuid.UUID | None
    invalidation_reason: str | None
    created_at: datetime


class TMARevisionHistoryResponse(TMAOutput):
    assignment_id: uuid.UUID
    revisions: list[TMARevisionResponse] = Field(default_factory=list)


class TMACancellationRequest(TMAInput):
    reason: str = Field(min_length=5, max_length=2000)


class TMACancellationRunResponse(TMAOutput):
    id: uuid.UUID
    assignment_id: uuid.UUID
    revision_id: uuid.UUID
    status: str
    reason: str
    reversed_scores: int = Field(ge=0)
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


# ---------- Question and option authoring ----------


def _validate_option_set(options: list[TMAOptionInput]) -> None:
    """Validate a complete objective question before accepting its options."""
    if len(options) < 4:
        raise ValueError("a question requires at least four options")
    if len({option.position for option in options}) != len(options):
        raise ValueError("option positions must be unique")
    if sum(option.is_correct for option in options) != 1:
        raise ValueError("exactly one option must be correct")


class TMAOptionInput(TMAInput):
    position: int = Field(ge=1)
    option_text: str | None = Field(default=None, min_length=1)
    image_asset_id: uuid.UUID | None = None
    is_correct: bool = False

    @model_validator(mode="after")
    def require_content(self) -> TMAOptionInput:
        if self.option_text is None and self.image_asset_id is None:
            raise ValueError("an option needs text or an image")
        return self


class TMAQuestionCreate(TMAInput):
    position: int = Field(ge=1)
    question_text: str | None = Field(default=None, min_length=1)
    image_asset_id: uuid.UUID | None = None
    options: list[TMAOptionInput] = Field(min_length=4)

    @model_validator(mode="after")
    def require_valid_question(self) -> TMAQuestionCreate:
        if self.question_text is None and self.image_asset_id is None:
            raise ValueError("a question needs text or an image")
        _validate_option_set(self.options)
        return self


class TMAQuestionUpdate(TMAInput):
    """Optimistic concurrency is enforced against the question's version."""

    version: int = Field(ge=1)
    position: int | None = Field(default=None, ge=1)
    question_text: str | None = Field(default=None, min_length=1)
    image_asset_id: uuid.UUID | None = None
    options: list[TMAOptionInput] | None = Field(default=None, min_length=4)

    @model_validator(mode="after")
    def validate_replacement_options(self) -> TMAQuestionUpdate:
        if self.options is not None:
            _validate_option_set(self.options)
        # After merging a partial patch, the service checks text/image presence.
        return self


class TMAOptionAdminResponse(TMAOutput):
    id: uuid.UUID
    question_id: uuid.UUID
    position: int
    option_text: str | None
    image_asset_id: uuid.UUID | None
    is_correct: bool


class TMAQuestionAdminResponse(TMAOutput):
    id: uuid.UUID
    assignment_id: uuid.UUID
    revision_id: uuid.UUID
    position: int
    version: int
    question_text: str | None
    image_asset_id: uuid.UUID | None
    author_actor_type: TMAActorType
    author_actor_id: uuid.UUID
    options: list[TMAOptionAdminResponse] = Field(default_factory=list)


# Student delivery MUST never extend the admin response models.
class TMAStudentOptionResponse(TMAOutput):
    id: uuid.UUID
    option_text: str | None
    image_asset_id: uuid.UUID | None


class TMAStudentQuestionResponse(TMAOutput):
    id: uuid.UUID
    question_text: str | None
    image_asset_id: uuid.UUID | None
    options: list[TMAStudentOptionResponse] = Field(default_factory=list)


# ---------- Image metadata ----------


class TMAMediaAssetResponse(TMAOutput):
    """Admin/teacher asset metadata; never return permanent keys to students."""

    id: uuid.UUID
    assignment_id: uuid.UUID
    object_key: str
    content_type: str
    size_bytes: int = Field(gt=0)
    checksum_sha256: str | None
    created_at: datetime


class TMAMediaSignedUrlResponse(TMAOutput):
    media_asset_id: uuid.UUID
    signed_url: str
    expires_at: datetime


class TMAMediaDeleteResponse(TMAOutput):
    media_asset_id: uuid.UUID
    deleted: bool
    storage_cleaned: bool


# ---------- Basic staff submissions roster ----------


class TMAParticipationStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class TMASubmissionStudentResponse(TMAOutput):
    student_id: uuid.UUID
    admission_number: str
    student_name: str
    class_id: uuid.UUID | None
    class_name: str | None
    participation_status: TMAParticipationStatus
    score: Decimal | None = None
    submitted_at: datetime | None = None
    is_currently_eligible: bool


class TMASubmissionListResponse(TMAOutput):
    assignment_id: uuid.UUID
    items: list[TMASubmissionStudentResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


# ---------- Roster and participation ----------


class TMAParticipantResponse(TMAOutput):
    id: uuid.UUID
    revision_id: uuid.UUID
    student_id: uuid.UUID
    student_enrollment_id: uuid.UUID
    class_id: uuid.UUID
    created_at: datetime


class TMARosterResponse(TMAOutput):
    revision_id: uuid.UUID
    participants: list[TMAParticipantResponse] = Field(default_factory=list)
    total: int = Field(ge=0)


# ---------- Student attempt and autosave ----------


class TMAAttemptResponse(TMAOutput):
    id: uuid.UUID
    participant_id: uuid.UUID
    revision_id: uuid.UUID
    status: TMAAttemptStatus
    started_at: datetime
    submitted_at: datetime | None
    correct_answers: int | None
    total_questions: int | None


class TMAAnswerResponse(TMAOutput):
    question_id: uuid.UUID
    selected_option_id: uuid.UUID


class TMAStartResponse(TMAOutput):
    """Service must shuffle options and include saved answers on resume."""

    attempt: TMAAttemptResponse
    questions: list[TMAStudentQuestionResponse] = Field(default_factory=list)
    saved_answers: list[TMAAnswerResponse] = Field(default_factory=list)


class TMAAnswerSaveRequest(TMAInput):
    question_id: uuid.UUID
    # Explicit null means remove the saved answer.
    selected_option_id: uuid.UUID | None


class TMAAnswerSaveResponse(TMAOutput):
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    selected_option_id: uuid.UUID | None
    saved_at: datetime


class TMASubmitResponse(TMAOutput):
    attempt_id: uuid.UUID
    status: TMAAttemptStatus
    correct_answers: int = Field(ge=0)
    total_questions: int = Field(gt=0)
    component_score: Decimal = Field(ge=0, max_digits=5, decimal_places=2)
    submitted_at: datetime


class TMAStudentAssignmentResponse(TMAOutput):
    """Student subject-card TMA summary derived from current eligibility."""

    assignment_id: uuid.UUID
    academic_term_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    assessment_component_id: uuid.UUID
    status: TMAAssignmentStatus
    attempt_status: TMAAttemptStatus | None
    attempt_id: uuid.UUID | None = None
    closes_at: datetime | None
    can_start_or_resume: bool
    component_maximum_score: Decimal = Field(gt=0, max_digits=5, decimal_places=2)
