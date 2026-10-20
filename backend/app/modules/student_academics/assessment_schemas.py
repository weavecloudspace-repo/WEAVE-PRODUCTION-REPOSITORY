import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.student_academics.models import AssessmentSchemeStatus

# Ensure direct imports of this schema module see the same mapped column as the
# application model registry and Alembic metadata.
import app.modules.student_academics.assessment_examinability  # noqa: E402,F401


_PATCH_NULL_ERROR = "cannot be null; omit the field to leave the current value unchanged"


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AssessmentComponentCreate(AssessmentInput):
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    maximum_score: Decimal = Field(gt=0, le=100, max_digits=5, decimal_places=2)
    position: int = Field(ge=0)
    is_examinable: bool = True
    is_hybrid: bool = False

    @model_validator(mode="after")
    def validate_hybrid(self):
        if self.is_hybrid and not self.is_examinable:
            raise ValueError("Hybrid components must be examinable.")
        return self


class AssessmentComponentUpdate(AssessmentInput):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    maximum_score: Decimal | None = Field(
        default=None, gt=0, le=100, max_digits=5, decimal_places=2
    )
    is_examinable: bool | None = None
    is_hybrid: bool | None = None

    @field_validator("name", "maximum_score", "is_examinable", "is_hybrid", mode="before")
    @classmethod
    def reject_null_non_clearable_fields(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} {_PATCH_NULL_ERROR}")
        return value

    @model_validator(mode="after")
    def require_patch_field(self) -> "AssessmentComponentUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one assessment component field must be provided")
        if self.is_hybrid is True and self.is_examinable is False:
            raise ValueError("Hybrid components must be examinable.")
        return self


class AssessmentComponentResponse(AssessmentOutput):
    id: uuid.UUID
    assessment_scheme_id: uuid.UUID
    name: str
    code: str | None = None
    maximum_score: Decimal
    position: int
    is_active: bool
    is_examinable: bool = True
    is_hybrid: bool = False


class AssessmentSchemeCreate(AssessmentInput):
    name: str = Field(min_length=1, max_length=100)
    components: list[AssessmentComponentCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_components(self):
        names = [item.name.casefold() for item in self.components]
        positions = [item.position for item in self.components]
        if len(names) != len(set(names)) or len(positions) != len(set(positions)):
            raise ValueError("Component names and positions must be unique.")
        return self


class AssessmentSchemeUpdate(AssessmentInput):
    name: str = Field(min_length=1, max_length=100)


class AssessmentComponentOrder(AssessmentInput):
    component_ids: list[uuid.UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_components(self):
        if len(self.component_ids) != len(set(self.component_ids)):
            raise ValueError("Component ordering must not contain duplicates.")
        return self


class AssessmentSchemeResponse(AssessmentOutput):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    status: AssessmentSchemeStatus
    activated_at: datetime | None = None
    archived_at: datetime | None = None
    components: list[AssessmentComponentResponse] = Field(default_factory=list)
    total_maximum_score: Decimal = Decimal("0")
    is_configured: bool = False
    created_at: datetime
    updated_at: datetime


class AssessmentSchemeListResponse(AssessmentOutput):
    items: list[AssessmentSchemeResponse]
    total: int
