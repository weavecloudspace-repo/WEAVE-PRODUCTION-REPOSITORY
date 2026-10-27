"""HTTP routes for CBT result ingestion and forensic audit access."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    get_current_superadmin,
    get_current_tenant_admin,
)
from app.modules.cbt.dependencies import CurrentCBTServer, CurrentCBTActor
from app.modules.cbt.enums import (
    CBTResultIngestionOutcome,
    CBTResultIngestionStatus,
)
from app.modules.cbt.results.audit_service import CBTResultIngestionAuditService
from app.modules.cbt.results.schemas import (
    CBTResultAuditFilterOptionsResponse,
    CBTResultBulkRequest,
    CBTResultBulkResponse,
    CBTResultIngestionBatchListResponse,
    CBTResultIngestionBatchResponse,
    CBTResultIngestionItemListResponse,
)
from app.modules.cbt.results.service import CBTResultIngestionService
from app.modules.cbt.results.rollback_service import CBTResultRollbackService
from app.modules.cbt.results.rollback_schemas import (
    CBTResultRollbackRequest,
    CBTResultRollbackResponse,
)
from app.core.queue.arq import get_arq_redis_settings, HEAVY_QUEUE_NAME
from arq import create_pool
from app.modules.superadmin.models import SuperAdmin
from app.modules.tenant_admins.models import TenantAdmin


CurrentTenantAdmin = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]
CurrentSuperadmin = Annotated[SuperAdmin, Depends(get_current_superadmin)]


router = APIRouter(prefix="/results", tags=["CBT Results"])
tenant_admin_router = APIRouter(
    prefix="/tenant-admin/cbt/result-ingestions",
    tags=["Tenant Admin CBT Result Audit"],
)
superadmin_router = APIRouter(
    prefix="/superadmin/cbt/result-ingestions",
    tags=["Superadmin CBT Result Audit"],
)


def _batch_filters(
    *,
    batch_id: UUID | None,
    ingestion_reference: str | None,
    source_exam_id: UUID | None,
    cbt_server_id: UUID | None,
    academic_session_id: UUID | None,
    academic_term_id: UUID | None,
    academic_level_id: UUID | None,
    curriculum_subject_id: UUID | None,
    assessment_component_id: UUID | None,
    exam_date: date | None,
    ingestion_status: CBTResultIngestionStatus | None,
) -> dict[str, object]:
    normalized_reference = ingestion_reference.strip().upper() if ingestion_reference else None
    return {
        "batch_id": batch_id,
        "ingestion_reference": normalized_reference,
        "source_exam_id": source_exam_id,
        "cbt_server_id": cbt_server_id,
        "academic_session_id": academic_session_id,
        "academic_term_id": academic_term_id,
        "academic_level_id": academic_level_id,
        "curriculum_subject_id": curriculum_subject_id,
        "assessment_component_id": assessment_component_id,
        "exam_date": exam_date,
        "status": ingestion_status,
    }


def _item_filters(
    *,
    submitted_student_id: UUID | None,
    outcome: CBTResultIngestionOutcome | None,
    error_code: str | None,
    student_subject_result_id: UUID | None,
    resolved_teacher_assignment_id: UUID | None,
) -> dict[str, object]:
    return {
        "submitted_student_id": submitted_student_id,
        "outcome": outcome,
        "error_code": error_code,
        "student_subject_result_id": student_subject_result_id,
        "resolved_teacher_assignment_id": resolved_teacher_assignment_id,
    }


@router.post(
    "",
    response_model=CBTResultBulkResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest CBT result scores",
)
async def ingest_results(
    db: DbSession,
    current_server: CurrentCBTServer,
    payload: CBTResultBulkRequest,
    response: Response,
) -> CBTResultBulkResponse:
    response.headers["Cache-Control"] = "no-store"
    return await CBTResultIngestionService.ingest(
        db,
        server=current_server,
        payload=payload,
    )


@router.post(
    "/rollbacks", response_model=CBTResultRollbackResponse, status_code=status.HTTP_202_ACCEPTED
)
async def request_result_rollback(
    db: DbSession,
    current_server: CurrentCBTServer,
    current_actor: CurrentCBTActor,
    payload: CBTResultRollbackRequest,
    response: Response,
) -> CBTResultRollbackResponse:
    """Persist the authorized request before queuing; Redis loss is recoverable."""
    response.headers["Cache-Control"] = "no-store"
    operation = await CBTResultRollbackService.register(
        db, server=current_server, actor=current_actor, payload=payload
    )
    if operation.status in ("pending", "processing"):
        try:
            redis = await create_pool(get_arq_redis_settings(), default_queue_name=HEAVY_QUEUE_NAME)
            try:
                await redis.enqueue_job(
                    "process_cbt_result_rollback_job",
                    str(operation.operation_id),
                    _queue_name=HEAVY_QUEUE_NAME,
                )
            finally:
                await redis.close()
        except Exception:
            # Periodic heavy-worker sweeps recover operations committed to PostgreSQL.
            pass
    return operation


@router.get("/rollbacks/{operation_id}", response_model=CBTResultRollbackResponse)
async def get_result_rollback(
    operation_id: UUID,
    db: DbSession,
    current_server: CurrentCBTServer,
    response: Response,
) -> CBTResultRollbackResponse:
    response.headers["Cache-Control"] = "no-store"
    operation = await CBTResultRollbackService.get_operation(
        db, server=current_server, operation_id=operation_id
    )
    return await CBTResultRollbackService.response(db, operation)


@tenant_admin_router.get(
    "/filter-options",
    response_model=CBTResultAuditFilterOptionsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_tenant_ingestion_filter_options(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
) -> CBTResultAuditFilterOptionsResponse:
    response.headers["Cache-Control"] = "no-store"
    return await CBTResultIngestionAuditService.get_filter_options_for_admin(
        db,
        tenant_id=current_admin.tenant_id,
    )


@tenant_admin_router.get(
    "",
    response_model=CBTResultIngestionBatchListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_tenant_ingestion_batches(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
    batch_id: UUID | None = None,
    ingestion_reference: str | None = Query(default=None, max_length=32),
    source_exam_id: UUID | None = None,
    cbt_server_id: UUID | None = None,
    academic_session_id: UUID | None = None,
    academic_term_id: UUID | None = None,
    academic_level_id: UUID | None = None,
    curriculum_subject_id: UUID | None = None,
    assessment_component_id: UUID | None = None,
    exam_date: date | None = None,
    ingestion_status: CBTResultIngestionStatus | None = Query(
        default=None,
        alias="status",
    ),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CBTResultIngestionBatchListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await CBTResultIngestionAuditService.list_batches_for_admin(
        db,
        tenant_id=current_admin.tenant_id,
        filters=_batch_filters(
            batch_id=batch_id,
            ingestion_reference=ingestion_reference,
            source_exam_id=source_exam_id,
            cbt_server_id=cbt_server_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            academic_level_id=academic_level_id,
            curriculum_subject_id=curriculum_subject_id,
            assessment_component_id=assessment_component_id,
            exam_date=exam_date,
            ingestion_status=ingestion_status,
        ),
        created_from=created_from,
        created_to=created_to,
        skip=skip,
        limit=limit,
    )
    return CBTResultIngestionBatchListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@tenant_admin_router.get(
    "/{batch_record_id}",
    response_model=CBTResultIngestionBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def get_tenant_ingestion_batch(
    batch_record_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
) -> CBTResultIngestionBatchResponse:
    response.headers["Cache-Control"] = "no-store"
    return await CBTResultIngestionAuditService.get_batch_for_admin(
        db,
        tenant_id=current_admin.tenant_id,
        batch_record_id=batch_record_id,
    )


@tenant_admin_router.get(
    "/{batch_record_id}/items",
    response_model=CBTResultIngestionItemListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_tenant_ingestion_items(
    batch_record_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
    submitted_student_id: UUID | None = None,
    outcome: CBTResultIngestionOutcome | None = None,
    error_code: str | None = Query(default=None, max_length=100),
    student_subject_result_id: UUID | None = None,
    resolved_teacher_assignment_id: UUID | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> CBTResultIngestionItemListResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await CBTResultIngestionAuditService.list_batch_items_for_admin(
        db,
        tenant_id=current_admin.tenant_id,
        batch_record_id=batch_record_id,
        filters=_item_filters(
            submitted_student_id=submitted_student_id,
            outcome=outcome,
            error_code=error_code,
            student_subject_result_id=student_subject_result_id,
            resolved_teacher_assignment_id=resolved_teacher_assignment_id,
        ),
        skip=skip,
        limit=limit,
    )
    return CBTResultIngestionItemListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@superadmin_router.get(
    "/filter-options",
    response_model=CBTResultAuditFilterOptionsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_superadmin_ingestion_filter_options(
    db: DbSession,
    current_superadmin: CurrentSuperadmin,
    response: Response,
    tenant_id: UUID,
) -> CBTResultAuditFilterOptionsResponse:
    _ = current_superadmin
    response.headers["Cache-Control"] = "no-store"
    return await CBTResultIngestionAuditService.get_filter_options_for_superadmin(
        db,
        tenant_id=tenant_id,
    )


@superadmin_router.get(
    "",
    response_model=CBTResultIngestionBatchListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_superadmin_ingestion_batches(
    db: DbSession,
    current_superadmin: CurrentSuperadmin,
    response: Response,
    tenant_id: UUID | None = None,
    batch_id: UUID | None = None,
    ingestion_reference: str | None = Query(default=None, max_length=32),
    source_exam_id: UUID | None = None,
    cbt_server_id: UUID | None = None,
    academic_session_id: UUID | None = None,
    academic_term_id: UUID | None = None,
    academic_level_id: UUID | None = None,
    curriculum_subject_id: UUID | None = None,
    assessment_component_id: UUID | None = None,
    exam_date: date | None = None,
    ingestion_status: CBTResultIngestionStatus | None = Query(
        default=None,
        alias="status",
    ),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CBTResultIngestionBatchListResponse:
    _ = current_superadmin
    response.headers["Cache-Control"] = "no-store"
    items, total = await CBTResultIngestionAuditService.list_batches_for_superadmin(
        db,
        tenant_id=tenant_id,
        filters=_batch_filters(
            batch_id=batch_id,
            ingestion_reference=ingestion_reference,
            source_exam_id=source_exam_id,
            cbt_server_id=cbt_server_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            academic_level_id=academic_level_id,
            curriculum_subject_id=curriculum_subject_id,
            assessment_component_id=assessment_component_id,
            exam_date=exam_date,
            ingestion_status=ingestion_status,
        ),
        created_from=created_from,
        created_to=created_to,
        skip=skip,
        limit=limit,
    )
    return CBTResultIngestionBatchListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@superadmin_router.get(
    "/{batch_record_id}",
    response_model=CBTResultIngestionBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def get_superadmin_ingestion_batch(
    batch_record_id: UUID,
    db: DbSession,
    current_superadmin: CurrentSuperadmin,
    response: Response,
) -> CBTResultIngestionBatchResponse:
    _ = current_superadmin
    response.headers["Cache-Control"] = "no-store"
    return await CBTResultIngestionAuditService.get_batch_for_superadmin(
        db,
        batch_record_id=batch_record_id,
    )


@superadmin_router.get(
    "/{batch_record_id}/items",
    response_model=CBTResultIngestionItemListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_superadmin_ingestion_items(
    batch_record_id: UUID,
    db: DbSession,
    current_superadmin: CurrentSuperadmin,
    response: Response,
    submitted_student_id: UUID | None = None,
    outcome: CBTResultIngestionOutcome | None = None,
    error_code: str | None = Query(default=None, max_length=100),
    student_subject_result_id: UUID | None = None,
    resolved_teacher_assignment_id: UUID | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> CBTResultIngestionItemListResponse:
    _ = current_superadmin
    response.headers["Cache-Control"] = "no-store"
    items, total = await CBTResultIngestionAuditService.list_batch_items_for_superadmin(
        db,
        batch_record_id=batch_record_id,
        filters=_item_filters(
            submitted_student_id=submitted_student_id,
            outcome=outcome,
            error_code=error_code,
            student_subject_result_id=student_subject_result_id,
            resolved_teacher_assignment_id=resolved_teacher_assignment_id,
        ),
        skip=skip,
        limit=limit,
    )
    return CBTResultIngestionItemListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )
