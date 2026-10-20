"""Academic session, curriculum-assignment, result, card, and progression schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.utils.normalization import normalize_class_name, normalize_grade
from app.core.utils.validators import validate_academic_session_name
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSessionStatus,
    AcademicTermName,
    AcademicTermStatus,
    StudentProgressionItemAction,
    StudentProgressionItemStatus,
    StudentProgressionRunStatus,
    TeacherAssignmentState,
)

_PATCH_NULL_ERROR = "cannot be null; omit the field to leave the current value unchanged"


class InputBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class OutputBase(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
        populate_by_name=True,
    )

    @field_validator("class_name", mode="before", check_fields=False)
    @classmethod
    def normalize_response_class_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_class_name(value) or value


class AcademicSessionCreate(InputBase):
    name: str = Field(min_length=9, max_length=9)
    start_date: date | None = None
    end_date: date | None = None
    next_academic_session_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_academic_session_name(value)

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class AcademicSessionUpdate(InputBase):
    name: str | None = Field(default=None, min_length=9, max_length=9)
    start_date: date | None = None
    end_date: date | None = None
    next_academic_session_id: uuid.UUID | None = None

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError(f"name {_PATCH_NULL_ERROR}")
        return validate_academic_session_name(value)

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("at least one session field must be provided")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class AcademicSessionOpenRequest(InputBase):
    confirmation: Literal["OPEN_ACADEMIC_SESSION"]


class AcademicSessionDeleteRequest(InputBase):
    confirmation: Literal["DELETE_ACADEMIC_SESSION"]


class AcademicSessionResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    start_date: date | None = None
    end_date: date | None = None
    status: AcademicSessionStatus
    is_current: bool
    closing_started_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by_admin_id: uuid.UUID | None = None
    next_academic_session_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class AcademicTermCreate(InputBase):
    academic_session_id: uuid.UUID
    name: AcademicTermName
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class AcademicTermUpdate(InputBase):
    name: AcademicTermName | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def reject_null_name(cls, value):
        if value is None:
            raise ValueError(f"name {_PATCH_NULL_ERROR}")
        return value

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("at least one term field must be provided")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class AcademicTermOpenRequest(InputBase):
    confirmation: Literal["OPEN_ACADEMIC_TERM"]


class AcademicTermCloseRequest(InputBase):
    confirmation: Literal["CLOSE_ACADEMIC_TERM"]


class AcademicTermStartClosingRequest(InputBase):
    confirmation: Literal["START_TERM_CLOSING"]


class AcademicTermFinalizeCloseRequest(InputBase):
    confirmation: Literal["FINALIZE_TERM_CLOSE"]


class AcademicTermCancelClosureRequest(InputBase):
    confirmation: Literal["CANCEL_TERM_CLOSURE"]
    reason: str = Field(min_length=3, max_length=500)


class AcademicTermDeleteRequest(InputBase):
    confirmation: Literal["DELETE_ACADEMIC_TERM"]


class AcademicTermResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    academic_session_id: uuid.UUID
    name: AcademicTermName
    start_date: date | None = None
    end_date: date | None = None
    status: AcademicTermStatus
    is_current: bool
    opened_at: datetime | None = None
    closing_started_at: datetime | None = None
    closed_at: datetime | None = None
    opened_by_admin_id: uuid.UUID | None = None
    closed_by_admin_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class GradingScaleCreate(InputBase):
    min_score: Decimal = Field(ge=0, le=100)
    max_score: Decimal = Field(ge=0, le=100)
    grade: str = Field(min_length=1, max_length=10)
    remark: str | None = Field(default=None, max_length=100)
    is_active: bool = True

    @field_validator("grade", mode="before")
    @classmethod
    def normalize_grade_value(cls, value: str) -> str:
        normalized = normalize_grade(value)
        if normalized is None:
            raise ValueError("grade cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_score > self.max_score:
            raise ValueError("minimum score cannot exceed maximum score")
        return self


class GradingScaleUpdate(InputBase):
    """Partial grading-scale update; activation uses dedicated lifecycle routes."""

    min_score: Decimal | None = Field(default=None, ge=0, le=100)
    max_score: Decimal | None = Field(default=None, ge=0, le=100)
    grade: str | None = Field(default=None, min_length=1, max_length=10)
    remark: str | None = Field(default=None, max_length=100)

    @field_validator("min_score", "max_score", mode="before")
    @classmethod
    def reject_null_scores(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} {_PATCH_NULL_ERROR}")
        return value

    @field_validator("grade", mode="before")
    @classmethod
    def normalize_grade_value(cls, value: str | None) -> str:
        if value is None:
            raise ValueError(f"grade {_PATCH_NULL_ERROR}")
        normalized = normalize_grade(value)
        if normalized is None:
            raise ValueError("grade cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_range(self):
        if (
            self.min_score is not None
            and self.max_score is not None
            and self.min_score > self.max_score
        ):
            raise ValueError("minimum score cannot exceed maximum score")
        if not self.model_fields_set:
            raise ValueError("at least one grading scale field must be provided")
        return self

    def model_dump(self, *args, **kwargs):
        """Preserve explicit nulls for clearable fields in legacy service callers."""

        if kwargs.get("exclude_unset"):
            kwargs["exclude_none"] = False
        return super().model_dump(*args, **kwargs)


class GradingScaleResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    min_score: Decimal
    max_score: Decimal
    grade: str
    remark: str | None = None
    is_active: bool


class GradingScaleDependencyPreview(OutputBase):
    scale_id: uuid.UUID
    dependency_counts: dict[str, int]
    can_deactivate: bool
    can_delete: bool
    blocker_messages: list[str] = []


class GradingScaleReadiness(OutputBase):
    is_ready: bool
    missing_coverage: list[str] = []
    overlaps: list[str] = []
    messages: list[str] = []


class TeacherAssignmentCreate(InputBase):
    teacher_membership_id: uuid.UUID
    class_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    academic_term_id: uuid.UUID
    effective_from: date | None = None


class TeacherAssignmentReassign(InputBase):
    teacher_membership_id: uuid.UUID
    academic_term_id: uuid.UUID
    effective_from: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class TeacherAssignmentScheduleUpdate(InputBase):
    teacher_membership_id: uuid.UUID
    academic_term_id: uuid.UUID
    effective_from: date
    reason: str = Field(min_length=3, max_length=500)


class TeacherAssignmentScheduleCancel(InputBase):
    reason: str = Field(min_length=3, max_length=500)


class TeacherAssignmentEnd(InputBase):
    academic_term_id: uuid.UUID
    effective_to: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class TeacherAssignmentDependencyPreview(OutputBase):
    assignment_id: uuid.UUID
    dependency_counts: dict[str, int]
    can_end: bool
    can_reassign: bool
    can_delete: bool
    can_edit_schedule: bool = False
    can_cancel_schedule: bool = False
    blocker_messages: list[str] = []


class AcademicSessionDependencyPreview(OutputBase):
    session_id: uuid.UUID
    dependency_counts: dict[str, int]
    blocker_messages: list[str] = []
    can_open: bool
    can_close: bool
    can_start_closing: bool
    can_progress: bool
    can_delete: bool


class AcademicTermDependencyPreview(OutputBase):
    term_id: uuid.UUID
    dependency_counts: dict[str, int]
    blocker_messages: list[str] = []
    can_open: bool
    can_close: bool
    can_start_closing: bool = False
    can_finalize_close: bool = False
    can_cancel_closure: bool = False
    can_delete: bool


class TeacherAssignmentResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    teacher_membership_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str | None = None
    class_arm: str | None = None
    subject_id: uuid.UUID | None = None
    subject_name: str | None = None
    subject_code: str | None = None
    teacher_name: str | None = None
    teacher_staff_id: str | None = None
    has_scheduled_takeover: bool = False
    scheduled_takeover_id: uuid.UUID | None = None
    scheduled_takeover_teacher_membership_id: uuid.UUID | None = None
    scheduled_takeover_teacher_name: str | None = None
    scheduled_takeover_effective_from: date | None = None
    status: TeacherAssignmentState
    effective_from: date
    effective_to: date | None = None
    created_at: datetime
    updated_at: datetime


class StudentAssessmentScoreUpsert(InputBase):
    assessment_component_id: uuid.UUID
    score: Decimal | None = Field(default=None, ge=0)
    theory_score: Decimal | None = Field(default=None, ge=0)
    cbt_score: Decimal | None = Field(default=None, ge=0)
    correction_reason: str | None = Field(default=None, min_length=3, max_length=1000)


class StudentSubjectResultUpsert(InputBase):
    student_id: uuid.UUID
    teacher_assignment_id: uuid.UUID
    academic_session_id: uuid.UUID
    academic_term_id: uuid.UUID
    component_scores: list[StudentAssessmentScoreUpsert] = Field(default_factory=list)
    status: AcademicResultStatus = AcademicResultStatus.DRAFT

    @model_validator(mode="after")
    def validate_result(self):
        component_ids = [item.assessment_component_id for item in self.component_scores]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("assessment components must be unique")
        return self


class AssessmentComponentScoreResponse(OutputBase):
    assessment_component_id: uuid.UUID
    name: str
    code: str | None = None
    position: int
    maximum_score: Decimal
    score: Decimal | None = None
    is_hybrid: bool = False
    cbt_score: Decimal | None = None
    cbt_maximum_score: Decimal | None = None
    theory_score: Decimal | None = None
    theory_maximum_score: Decimal | None = None
    source_exam_id: uuid.UUID | None = None
    is_complete: bool = False


class StudentSubjectResultStatusUpdate(InputBase):
    status: AcademicResultStatus


class StudentSubjectResultFilter(InputBase):
    subject_id: uuid.UUID | None = None
    status: AcademicResultStatus | None = None
    search: str | None = None
    is_complete: bool | None = None
    has_grade: bool | None = None
    teacher_assignment_id: uuid.UUID | None = None


class StudentSubjectResultReopenRequest(InputBase):
    reason: str = Field(min_length=3, max_length=1000)


class StudentSubjectResultResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    admission_number: str | None = None
    class_id: uuid.UUID
    class_name: str | None = None
    class_arm: str | None = None
    subject_id: uuid.UUID
    subject_name: str | None = None
    subject_code: str | None = None
    teacher_membership_id: uuid.UUID
    teacher_name: str | None = None
    curriculum_subject_id: uuid.UUID
    teacher_assignment_id: uuid.UUID | None = None
    academic_session_id: uuid.UUID
    academic_session_name: str | None = None
    academic_term_id: uuid.UUID
    academic_term_name: str | None = None
    assessment_scheme_id: uuid.UUID
    assessment_scheme_name: str
    components: list[AssessmentComponentScoreResponse] = Field(default_factory=list)
    maximum_score: Decimal = Decimal("100")
    total_score: Decimal
    grade: str | None = None
    remark: str | None = None
    status: AcademicResultStatus
    recorded_by_actor_type: str
    recorded_by_actor_id: uuid.UUID
    submitted_at: datetime | None = None
    submitted_by_actor_type: str | None = None
    submitted_by_actor_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    approved_by_admin_id: uuid.UUID | None = None
    locked_at: datetime | None = None
    locked_by_admin_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class StudentSubjectCardResponse(OutputBase):
    id: uuid.UUID
    result_id: uuid.UUID | None = None
    curriculum_subject_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    class_name: str | None = None
    class_arm: str | None = None
    subject_id: uuid.UUID
    subject_name: str | None = None
    subject_code: str | None = None
    teacher_membership_id: uuid.UUID | None = None
    teacher_name: str | None = None
    academic_session_id: uuid.UUID | None = None
    academic_session_name: str | None = None
    academic_term_id: uuid.UUID | None = None
    academic_term_name: str | None = None
    assessment_scheme_id: uuid.UUID | None = None
    assessment_scheme_name: str | None = None
    components: list[AssessmentComponentScoreResponse] = Field(default_factory=list)
    maximum_score: Decimal = Decimal("100")
    total_score: Decimal | None = None
    grade: str | None = None
    remark: str | None = None
    status: str = "pending"
    is_complete: bool = False


class StudentSubjectCardContextResponse(OutputBase):
    class_id: uuid.UUID | None = None
    class_name: str | None = None
    class_arm: str | None = None
    academic_session_id: uuid.UUID | None = None
    academic_session_name: str | None = None
    academic_term_id: uuid.UUID | None = None
    academic_term_name: str | None = None


class StudentSubjectCardListResponse(OutputBase):
    items: list[StudentSubjectCardResponse]
    total: int
    context: StudentSubjectCardContextResponse


class StudentProgressionItemResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    progression_run_id: uuid.UUID
    student_id: uuid.UUID
    from_enrollment_id: uuid.UUID | None = None
    to_enrollment_id: uuid.UUID | None = None
    from_level_id: uuid.UUID
    to_level_id: uuid.UUID | None = None
    from_class_id: uuid.UUID | None = None
    to_class_id: uuid.UUID | None = None
    action: StudentProgressionItemAction
    status: StudentProgressionItemStatus
    reason: str | None = None
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StudentProgressionRunResponse(OutputBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    academic_session_id: uuid.UUID
    next_academic_session_id: uuid.UUID
    idempotency_key: str
    status: StudentProgressionRunStatus
    total_students: int = Field(ge=0)
    promoted_students: int = Field(ge=0)
    graduated_students: int = Field(ge=0)
    skipped_students: int = Field(ge=0)
    pending_students: int = Field(ge=0)
    failed_students: int = Field(ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    initiated_by_admin_id: uuid.UUID | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class StudentProgressionRunDetailResponse(StudentProgressionRunResponse):
    items: list[StudentProgressionItemResponse]


class AcademicSessionListResponse(OutputBase):
    items: list[AcademicSessionResponse]
    total: int


class AcademicTermListResponse(OutputBase):
    items: list[AcademicTermResponse]
    total: int


class GradingScaleListResponse(OutputBase):
    items: list[GradingScaleResponse]
    total: int


class TeacherAssignmentListResponse(OutputBase):
    items: list[TeacherAssignmentResponse]
    total: int


class StudentSubjectResultListResponse(OutputBase):
    items: list[StudentSubjectResultResponse]
    total: int


class StudentProgressionRunListResponse(OutputBase):
    items: list[StudentProgressionRunResponse]
    total: int = Field(ge=0)
