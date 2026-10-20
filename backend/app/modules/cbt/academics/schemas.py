"""Stable Cloud -> local CBT academic bootstrap contract."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.cbt.sync.schemas import SYNC_SCHEMA_VERSION


class SnapshotBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class CBTSyncMetadata(SnapshotBase):
    schema_version: int = SYNC_SCHEMA_VERSION
    snapshot_id: uuid.UUID
    generated_at: datetime
    cursor: int = Field(ge=0)


class CBTSchoolSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str
    institution_type: str | None = None
    timezone: str


class CBTServerSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str


class CBTAcademicSessionSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str
    status: str
    is_current: bool


class CBTAcademicTermSnapshot(SnapshotBase):
    id: uuid.UUID
    academic_session_id: uuid.UUID
    name: str
    status: str
    is_current: bool


class CBTAcademicLevelSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str
    category: str
    position: int
    specialization_required_from_term_position: int | None = None


class CBTArmLabelSnapshot(SnapshotBase):
    id: uuid.UUID
    label: str


class CBTDepartmentSnapshot(SnapshotBase):
    """Level-specific specialization identity consumed by CBT."""

    id: uuid.UUID
    academic_level_id: uuid.UUID
    name: str


class CBTClassSnapshot(SnapshotBase):
    id: uuid.UUID
    academic_level_id: uuid.UUID
    arm_label_id: uuid.UUID
    display_name: str
    is_active: bool


class CBTClassTermDepartmentSnapshot(SnapshotBase):
    id: uuid.UUID
    class_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID


class CBTSubjectSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str
    code: str | None = None
    is_active: bool


class CBTCurriculumSnapshot(SnapshotBase):
    id: uuid.UUID
    academic_level_id: uuid.UUID


class CBTCurriculumSubjectSnapshot(SnapshotBase):
    id: uuid.UUID
    curriculum_id: uuid.UUID
    subject_id: uuid.UUID
    is_elective: bool
    elective_group_id: uuid.UUID | None = None
    is_active: bool


class CBTCurriculumSubjectDepartmentSnapshot(SnapshotBase):
    id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    department_id: uuid.UUID


class CBTAssessmentSchemeSnapshot(SnapshotBase):
    id: uuid.UUID
    name: str
    status: str


class CBTAssessmentComponentSnapshot(SnapshotBase):
    id: uuid.UUID
    assessment_scheme_id: uuid.UUID
    name: str
    code: str | None = None
    maximum_score: Decimal
    position: int
    is_active: bool
    is_hybrid: bool = False


class CBTAdminSnapshot(SnapshotBase):
    id: uuid.UUID
    email: str
    status: str


class CBTTeacherSnapshot(SnapshotBase):
    id: uuid.UUID
    teacher_account_id: uuid.UUID
    first_name: str | None = None
    last_name: str | None = None
    staff_id: str | None = None
    status: str


class CBTTeacherAssignmentSnapshot(SnapshotBase):
    id: uuid.UUID
    teacher_membership_id: uuid.UUID
    class_id: uuid.UUID
    curriculum_subject_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None


class CBTStudentEnrollmentSnapshot(SnapshotBase):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_number: str
    first_name: str | None = None
    last_name: str | None = None
    academic_level_id: uuid.UUID
    class_id: uuid.UUID | None = None
    academic_session_id: uuid.UUID
    is_current: bool
    student_status: str


class CBTStudentElectiveSelectionSnapshot(SnapshotBase):
    id: uuid.UUID
    student_id: uuid.UUID
    elective_group_id: uuid.UUID
    curriculum_subject_id: uuid.UUID


class CBTAcademicBootstrapResponse(SnapshotBase):
    metadata: CBTSyncMetadata
    school: CBTSchoolSnapshot
    server: CBTServerSnapshot
    sessions: list[CBTAcademicSessionSnapshot]
    terms: list[CBTAcademicTermSnapshot]
    levels: list[CBTAcademicLevelSnapshot]
    arm_labels: list[CBTArmLabelSnapshot]
    departments: list[CBTDepartmentSnapshot]
    classes: list[CBTClassSnapshot]
    class_term_departments: list[CBTClassTermDepartmentSnapshot]
    subjects: list[CBTSubjectSnapshot]
    curricula: list[CBTCurriculumSnapshot]
    curriculum_subjects: list[CBTCurriculumSubjectSnapshot]
    curriculum_subject_departments: list[CBTCurriculumSubjectDepartmentSnapshot]
    assessment_schemes: list[CBTAssessmentSchemeSnapshot]
    assessment_components: list[CBTAssessmentComponentSnapshot]
    admins: list[CBTAdminSnapshot]
    teachers: list[CBTTeacherSnapshot]
    teacher_assignments: list[CBTTeacherAssignmentSnapshot]
    student_enrollments: list[CBTStudentEnrollmentSnapshot]
    student_elective_selections: list[CBTStudentElectiveSelectionSnapshot]
