from pydantic import BaseModel, ConfigDict, field_validator

from app.core.utils.normalization import normalize_class_name


class OutputBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("class_name", mode="before", check_fields=False)
    @classmethod
    def normalize_response_class_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_class_name(value) or value


class TenantSearchResult(OutputBase):
    label: str
    role: str
    passport_photo_url: str | None = None
    metadata: str | None = None
    admission_number: str | None = None
    staff_id: str | None = None
    class_name: str | None = None
    subject_name: str | None = None
    email: str | None = None
    href: str


class TenantSearchResponse(OutputBase):
    items: list[TenantSearchResult]
    total: int
