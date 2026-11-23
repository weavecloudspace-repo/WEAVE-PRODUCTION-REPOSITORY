"""Canonical tenant-admin routes for student placement."""

from __future__ import annotations

from typing import Annotated, TypeAlias
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_tenant_admin
from app.modules.students.enrollment_schemas import (
    PlacementImpactPreviewRequest,
    PlacementImpactPreviewResponse,
    ExistingResultReconciliationRequest,
    StudentAcademicLevelReassignmentRequest,
    StudentClassPlacementRequest,
    StudentClassPlacementResponse,
    StudentClassReassignmentRequest,
    StudentUpcomingEnrollmentUpdateRequest,
)
from app.modules.students.placement_service import StudentPlacementService
from app.modules.students.schemas import (
    StudentDetailResponse,
    StudentEnrollmentListResponse,
    StudentLifecycleReasonRequest,
)
from app.modules.tenant_admins.models import TenantAdmin

router = APIRouter(prefix="/tenant-admin/students", tags=["Tenant Admin Student Placement"])
CurrentTenantAdmin: TypeAlias = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]


@router.post("/class-placement", response_model=StudentClassPlacementResponse)
async def place_students_in_class(
    payload: StudentClassPlacementRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentClassPlacementResponse:
    return await StudentPlacementService.place_class(db, actor=current_admin, payload=payload)


@router.get("/{student_id}/placement-history", response_model=StudentEnrollmentListResponse)
async def placement_history(
    student_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentEnrollmentListResponse:
    items = await StudentPlacementService.list_history(
        db,
        tenant_id=current_admin.tenant_id,
        student_id=student_id,
    )
    return StudentEnrollmentListResponse(items=items, total=len(items))


@router.post("/{student_id}/reassign-class", response_model=StudentDetailResponse)
async def reassign_class(
    student_id: UUID,
    payload: StudentClassReassignmentRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentDetailResponse:
    return await StudentPlacementService.reassign_class(
        db,
        actor=current_admin,
        student_id=student_id,
        payload=payload,
    )


@router.post("/{student_id}/reconcile-existing-results", response_model=StudentDetailResponse)
async def reconcile_existing_results(
    student_id: UUID,
    payload: ExistingResultReconciliationRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentDetailResponse:
    return await StudentPlacementService.reconcile_existing_results(
        db,
        actor=current_admin,
        student_id=student_id,
        academic_session_id=payload.academic_session_id,
        reason=payload.reason,
        carry_finalized_results=payload.carry_finalized_results,
    )


@router.post("/{student_id}/reassign-academic-level", response_model=StudentDetailResponse)
async def reassign_academic_level(
    student_id: UUID,
    payload: StudentAcademicLevelReassignmentRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentDetailResponse:
    return await StudentPlacementService.reassign_academic_level(
        db,
        actor=current_admin,
        student_id=student_id,
        payload=payload,
    )


@router.patch(
    "/{student_id}/upcoming-enrollments/{enrollment_id}",
    response_model=StudentDetailResponse,
)
async def update_upcoming_enrollment(
    student_id: UUID,
    enrollment_id: UUID,
    payload: StudentUpcomingEnrollmentUpdateRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentDetailResponse:
    return await StudentPlacementService.update_upcoming_enrollment(
        db,
        actor=current_admin,
        student_id=student_id,
        enrollment_id=enrollment_id,
        payload=payload,
    )


@router.post(
    "/{student_id}/upcoming-enrollments/{enrollment_id}/cancel",
    response_model=StudentDetailResponse,
)
async def cancel_upcoming_enrollment(
    student_id: UUID,
    enrollment_id: UUID,
    payload: StudentLifecycleReasonRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> StudentDetailResponse:
    return await StudentPlacementService.cancel_upcoming_enrollment(
        db,
        actor=current_admin,
        student_id=student_id,
        enrollment_id=enrollment_id,
        payload=payload,
    )


@router.post(
    "/{student_id}/placement-impact-preview", response_model=PlacementImpactPreviewResponse
)
async def placement_impact_preview(
    student_id: UUID,
    payload: PlacementImpactPreviewRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> PlacementImpactPreviewResponse:
    return await StudentPlacementService.impact_preview(
        db,
        actor=current_admin,
        student_id=student_id,
        payload=payload,
    )
