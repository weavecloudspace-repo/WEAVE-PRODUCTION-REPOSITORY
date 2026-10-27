import uuid
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_tenant_admin
from app.modules.student_academics.curriculum_v2_schemas import (
    AcademicLevelSpecializationResponse,
    AcademicLevelSpecializationUpdate,
    ClassTermDepartmentCopyRequest,
    ClassTermDepartmentCopyResponse,
    ClassTermDepartmentResponse,
    ClassTermDepartmentSet,
    CurriculumResponse,
    CurriculumCopyRequest,
    CurriculumCopyResponse,
    CurriculumSubjectCreate,
    CurriculumSubjectsBulkCreate,
    CurriculumSubjectsBulkResponse,
    SetupReadinessResponse,
    SpecializationWorkspaceResponse,
    CurriculumSubjectResponse,
    CurriculumSubjectUpdate,
    EligibleTeacherAssignmentClassResponse,
    ResolvedClassSubjectResponse,
    TeacherAssignmentBulkCreate,
    TeacherAssignmentBulkResponse,
    TeacherAssignmentSubjectAvailabilityResponse,
)
from app.modules.student_academics.curriculum_v2_service import AcademicCurriculumService
from app.modules.student_academics.curriculum_bulk_service import add_curriculum_subjects
from app.modules.student_academics.curriculum_copy_service import copy_curriculum
from app.modules.student_academics.elective_schemas import (
    ElectiveGroupCreate,
    ElectiveGroupResponse,
    ElectiveGroupUpdate,
)
from app.modules.student_academics.elective_service import (
    ElectiveAwareCurriculumService,
    ElectivePolicyService,
)
from app.modules.student_academics.specialization_workspace import specialization_workspace
from app.modules.student_academics.setup_readiness import get_setup_readiness
from app.modules.student_academics.service import StudentAcademicService
from app.modules.tenant_admins.models import TenantAdmin

router = APIRouter(prefix="/tenant-admin/academics", tags=["Curriculum"])
CurrentTenantAdmin: TypeAlias = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]


@router.get("/setup-readiness", response_model=SetupReadinessResponse)
async def setup_readiness(db: DbSession, current_admin: CurrentTenantAdmin):
    return await get_setup_readiness(db, current_admin.tenant_id)


@router.get(
    "/terms/{academic_term_id}/specialization-workspace",
    response_model=SpecializationWorkspaceResponse,
)
async def get_specialization_workspace(
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await specialization_workspace(db, current_admin.tenant_id, academic_term_id)


@router.get(
    "/levels/{academic_level_id}/elective-groups",
    response_model=list[ElectiveGroupResponse],
)
async def list_elective_groups(
    academic_level_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectivePolicyService.list_groups(
        db,
        tenant_id=current_admin.tenant_id,
        academic_level_id=academic_level_id,
    )


@router.post(
    "/levels/{academic_level_id}/elective-groups",
    response_model=ElectiveGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_elective_group(
    academic_level_id: uuid.UUID,
    payload: ElectiveGroupCreate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectivePolicyService.create_group(
        db,
        tenant_id=current_admin.tenant_id,
        academic_level_id=academic_level_id,
        payload=payload,
    )


@router.patch(
    "/elective-groups/{elective_group_id}",
    response_model=ElectiveGroupResponse,
)
async def update_elective_group(
    elective_group_id: uuid.UUID,
    payload: ElectiveGroupUpdate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectivePolicyService.update_group(
        db,
        tenant_id=current_admin.tenant_id,
        elective_group_id=elective_group_id,
        payload=payload,
    )


@router.post(
    "/elective-groups/{elective_group_id}/archive",
    response_model=ElectiveGroupResponse,
)
async def archive_elective_group(
    elective_group_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectivePolicyService.archive_group(
        db,
        tenant_id=current_admin.tenant_id,
        elective_group_id=elective_group_id,
    )


@router.post(
    "/elective-groups/{elective_group_id}/restore",
    response_model=ElectiveGroupResponse,
)
async def restore_elective_group(
    elective_group_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectivePolicyService.restore_group(
        db,
        tenant_id=current_admin.tenant_id,
        elective_group_id=elective_group_id,
    )


@router.get("/levels/{academic_level_id}/curriculum", response_model=CurriculumResponse)
async def get_curriculum(
    academic_level_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.get_curriculum(
        db, current_admin.tenant_id, academic_level_id
    )


@router.post(
    "/levels/{academic_level_id}/curriculum/subjects",
    response_model=CurriculumSubjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_curriculum_subject(
    academic_level_id: uuid.UUID,
    payload: CurriculumSubjectCreate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.add_subject(
        db, current_admin.tenant_id, academic_level_id, payload
    )


@router.post(
    "/levels/{academic_level_id}/curriculum/subjects/bulk",
    status_code=201,
    response_model=CurriculumSubjectsBulkResponse,
)
async def bulk_add_curriculum_subjects(
    academic_level_id: uuid.UUID,
    payload: CurriculumSubjectsBulkCreate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await add_curriculum_subjects(db, current_admin.tenant_id, academic_level_id, payload)


@router.post(
    "/levels/{academic_level_id}/curriculum/copy",
    response_model=CurriculumCopyResponse,
)
async def copy_level_curriculum(
    academic_level_id: uuid.UUID,
    payload: CurriculumCopyRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await copy_curriculum(
        db, current_admin.tenant_id, academic_level_id, payload.source_academic_level_id
    )


@router.patch(
    "/curriculum-subjects/{curriculum_subject_id}",
    response_model=CurriculumSubjectResponse,
)
async def update_curriculum_subject(
    curriculum_subject_id: uuid.UUID,
    payload: CurriculumSubjectUpdate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.update_subject(
        db, current_admin.tenant_id, curriculum_subject_id, payload
    )


@router.post(
    "/curriculum-subjects/{curriculum_subject_id}/activate",
    response_model=CurriculumSubjectResponse,
)
async def activate_curriculum_subject(
    curriculum_subject_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.activate_subject(
        db, current_admin.tenant_id, curriculum_subject_id
    )


@router.post(
    "/curriculum-subjects/{curriculum_subject_id}/deactivate",
    response_model=CurriculumSubjectResponse,
)
async def deactivate_curriculum_subject(
    curriculum_subject_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.deactivate_subject(
        db, current_admin.tenant_id, curriculum_subject_id
    )


@router.delete(
    "/curriculum-subjects/{curriculum_subject_id}",
    response_model=CurriculumSubjectResponse,
)
async def delete_curriculum_subject(
    curriculum_subject_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await ElectiveAwareCurriculumService.hard_delete_subject(
        db, current_admin.tenant_id, curriculum_subject_id
    )


@router.get(
    "/curriculum-subjects/{curriculum_subject_id}/eligible-classes/{academic_term_id}",
    response_model=list[EligibleTeacherAssignmentClassResponse],
)
async def eligible_classes_for_curriculum_subject(
    curriculum_subject_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.eligible_classes_for_subject(
        db,
        tenant_id=current_admin.tenant_id,
        curriculum_subject_id=curriculum_subject_id,
        academic_term_id=academic_term_id,
    )


@router.get(
    "/levels/{academic_level_id}/teacher-assignment-availability/{academic_term_id}",
    response_model=list[TeacherAssignmentSubjectAvailabilityResponse],
)
async def teacher_assignment_subject_availability(
    academic_level_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.teacher_assignment_subject_availability(
        db,
        tenant_id=current_admin.tenant_id,
        academic_level_id=academic_level_id,
        academic_term_id=academic_term_id,
    )


@router.get(
    "/students/{student_id}/terms/{academic_term_id}/subjects",
    response_model=list[ResolvedClassSubjectResponse],
)
async def resolved_student_subjects_for_admin(
    student_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.resolved_student_subject_responses(
        db,
        tenant_id=current_admin.tenant_id,
        student_id=student_id,
        academic_term_id=academic_term_id,
    )


@router.get(
    "/classes/{class_id}/terms/{academic_term_id}/subjects",
    response_model=list[ResolvedClassSubjectResponse],
)
async def resolved_class_subjects(
    class_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.resolved_class_subject_responses(
        db,
        tenant_id=current_admin.tenant_id,
        class_id=class_id,
        academic_term_id=academic_term_id,
    )


@router.post(
    "/teacher-assignments/bulk",
    response_model=TeacherAssignmentBulkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_teacher_assignments_bulk(
    payload: TeacherAssignmentBulkCreate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await StudentAcademicService.create_teacher_assignments_bulk(
        db,
        current_admin.tenant_id,
        payload,
        acting_admin_id=current_admin.id,
    )


@router.patch(
    "/levels/{academic_level_id}/specialization-policy",
    response_model=AcademicLevelSpecializationResponse,
)
async def update_specialization_policy(
    academic_level_id: uuid.UUID,
    payload: AcademicLevelSpecializationUpdate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.update_specialization_policy(
        db,
        tenant_id=current_admin.tenant_id,
        admin_id=current_admin.id,
        academic_level_id=academic_level_id,
        payload=payload,
    )


@router.get(
    "/terms/{academic_term_id}/class-departments",
    response_model=list[ClassTermDepartmentResponse],
)
async def list_class_term_departments(
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.list_class_departments(
        db, current_admin.tenant_id, academic_term_id
    )


@router.post(
    "/terms/{academic_term_id}/class-departments/copy",
    response_model=ClassTermDepartmentCopyResponse,
)
async def copy_class_term_departments(
    academic_term_id: uuid.UUID,
    payload: ClassTermDepartmentCopyRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.copy_class_departments(
        db,
        tenant_id=current_admin.tenant_id,
        admin_id=current_admin.id,
        target_term_id=academic_term_id,
        source_term_id=payload.source_academic_term_id,
    )


@router.get(
    "/classes/{class_id}/terms/{academic_term_id}/department",
    response_model=ClassTermDepartmentResponse | None,
)
async def get_class_term_department(
    class_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.get_class_department(
        db, current_admin.tenant_id, class_id, academic_term_id
    )


@router.put(
    "/classes/{class_id}/terms/{academic_term_id}/department",
    response_model=ClassTermDepartmentResponse,
)
async def set_class_term_department(
    class_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    payload: ClassTermDepartmentSet,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    return await AcademicCurriculumService.set_class_department(
        db,
        current_admin.tenant_id,
        current_admin.id,
        class_id,
        academic_term_id,
        payload.academic_level_department_id,
    )


@router.delete(
    "/classes/{class_id}/terms/{academic_term_id}/department",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_class_term_department(
    class_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
):
    await AcademicCurriculumService.clear_class_department(
        db,
        current_admin.tenant_id,
        class_id,
        academic_term_id,
        current_admin.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
