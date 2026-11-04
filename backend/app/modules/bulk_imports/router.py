# ========================= #
#   bulk_imports_router.py  #
# ========================= #

"""Tenant admin bulk import routes."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_tenant_admin
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.bulk_imports.live_service import BulkImportLiveService
from app.modules.bulk_imports.models import ImportJobStatus, ImportResourceType
from app.modules.bulk_imports.optimized_service import OptimizedBulkImportService
from app.modules.bulk_imports.repository import ImportJobRepository
from app.modules.bulk_imports.result_writer import (
    create_error_report,
    create_result_report,
    create_student_access_slip_report,
)
from app.modules.bulk_imports.schemas import (
    ImportJobDetailResponse,
    ImportJobListResponse,
    ImportRowErrorListResponse,
    ImportTemplateResponse,
)
from app.modules.bulk_imports.sensitive_results import (
    redact_result_row,
    reveal_result_row,
)
from app.modules.bulk_imports.service import BulkImportService
from app.modules.bulk_imports.slip_schemas import (
    StudentSlipDetailResponse,
    StudentSlipListResponse,
    StudentSlipPrintRequest,
    StudentSlipPrintResponse,
    StudentSlipSummaryResponse,
)
from app.modules.bulk_imports.slip_service import StudentSlipService
from app.modules.subscriptions.quota_lock import acquire_resource_quota_lock
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository

router = APIRouter(prefix="/imports", tags=["Bulk Imports"])
CurrentTenantAdmin: TypeAlias = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]
ResultDownloadFormat: TypeAlias = Literal["spreadsheet", "slip"]


@router.get("/templates", response_model=list[ImportTemplateResponse])
async def list_import_templates(
    current_user: CurrentTenantAdmin,
) -> list[ImportTemplateResponse]:
    _ = current_user
    return BulkImportService.list_templates()


@router.get("/templates/{resource_type}", response_model=ImportTemplateResponse)
async def get_import_template(
    resource_type: ImportResourceType,
    current_user: CurrentTenantAdmin,
) -> ImportTemplateResponse:
    _ = current_user
    return BulkImportService.get_template(resource_type=resource_type)


@router.get("/templates/{resource_type}/download")
async def download_import_template(
    resource_type: ImportResourceType,
    current_user: CurrentTenantAdmin,
) -> Response:
    template = BulkImportService.generate_template_file(
        tenant_id=current_user.tenant_id,
        resource_type=resource_type,
    )
    return Response(
        content=template.content_bytes,
        media_type=template.content_type,
        headers={"Content-Disposition": f'attachment; filename="{template.filename}"'},
    )


@router.post(
    "/{resource_type}/dry-run",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dry_run_bulk_import(
    resource_type: ImportResourceType,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    file: UploadFile = File(...),
    notify_on_completion: bool = Form(default=True),
) -> ImportJobDetailResponse:
    return await OptimizedBulkImportService.create_dry_run_from_upload(
        db=db,
        actor=current_user,
        resource_type=resource_type,
        upload_file=file,
        notify_on_completion=notify_on_completion,
    )


@router.post("/{job_id}/confirm", response_model=ImportJobDetailResponse)
async def confirm_bulk_import(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    notify_on_completion: bool = Query(default=True),
) -> ImportJobDetailResponse:
    import_job = await ImportJobRepository.get_job_by_id(
        db=db,
        tenant_id=current_user.tenant_id,
        job_id=job_id,
    )
    if import_job is None:
        raise NotFoundException(detail="Import job not found")

    await acquire_resource_quota_lock(
        db,
        tenant_id=current_user.tenant_id,
        resource=BulkImportService.resource_limit_code(import_job.resource_type),
    )
    return await BulkImportLiveService.queue_confirmed_import(
        db=db,
        actor=current_user,
        job_id=job_id,
        notify_on_completion=notify_on_completion,
    )


@router.post("/{job_id}/retry", response_model=ImportJobDetailResponse)
async def retry_stale_bulk_import(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> ImportJobDetailResponse:
    """Requeue a stale import and resume from its last committed chunk."""

    return await BulkImportLiveService.retry_stale_import(
        db=db,
        actor=current_user,
        job_id=job_id,
    )


@router.post(
    "/{resource_type}",
    response_model=ImportJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_bulk_import(
    resource_type: ImportResourceType,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    notify_on_completion: bool = Form(default=True),
) -> ImportJobDetailResponse:
    return await OptimizedBulkImportService.create_import_from_upload(
        db=db,
        actor=current_user,
        resource_type=resource_type,
        upload_file=file,
        dry_run=dry_run,
        notify_on_completion=notify_on_completion,
    )


@router.get("", response_model=ImportJobListResponse)
async def list_bulk_import_jobs(
    db: DbSession,
    current_user: CurrentTenantAdmin,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    resource_type: ImportResourceType | None = Query(default=None),
    status_filter: ImportJobStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=160),
) -> ImportJobListResponse:
    return await BulkImportService.list_jobs(
        db=db,
        actor=current_user,
        skip=skip,
        limit=limit,
        resource_type=resource_type,
        status=status_filter,
        search=search,
    )


@router.get("/{job_id}/slips/summary", response_model=StudentSlipSummaryResponse)
async def get_student_slip_summary(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> StudentSlipSummaryResponse:
    return await StudentSlipService.summary(
        db,
        actor=current_user,
        job_id=job_id,
    )


@router.get("/{job_id}/slips", response_model=StudentSlipListResponse)
async def list_student_slips(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    search: str | None = Query(default=None, max_length=160),
    class_key: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> StudentSlipListResponse:
    return await StudentSlipService.list_slips(
        db,
        actor=current_user,
        job_id=job_id,
        search=search,
        class_key=class_key,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}/slips/{row_number}", response_model=StudentSlipDetailResponse)
async def get_student_slip(
    job_id: UUID,
    row_number: int,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> StudentSlipDetailResponse:
    return await StudentSlipService.get_slip(
        db,
        actor=current_user,
        job_id=job_id,
        row_number=row_number,
    )


@router.post("/{job_id}/slips/print", response_model=StudentSlipPrintResponse)
async def get_student_slip_print_data(
    job_id: UUID,
    payload: StudentSlipPrintRequest,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> StudentSlipPrintResponse:
    return await StudentSlipService.print_data(
        db,
        actor=current_user,
        job_id=job_id,
        payload=payload,
    )


@router.get("/{job_id}", response_model=ImportJobDetailResponse)
async def get_bulk_import_job(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> ImportJobDetailResponse:
    return await BulkImportService.get_job(db=db, actor=current_user, job_id=job_id)


@router.get("/{job_id}/errors", response_model=ImportRowErrorListResponse)
async def list_bulk_import_errors(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> ImportRowErrorListResponse:
    return await BulkImportService.list_job_errors(
        db=db,
        actor=current_user,
        job_id=job_id,
        skip=skip,
        limit=limit,
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bulk_import_job(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> Response:
    await BulkImportService.delete_job_history(db=db, actor=current_user, job_id=job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{job_id}/result")
async def download_bulk_import_result(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
    result_format: ResultDownloadFormat = Query(default="spreadsheet", alias="format"),
) -> Response:
    resource_type, stored_rows = await BulkImportService.get_result_rows(
        db=db,
        actor=current_user,
        job_id=job_id,
    )

    if result_format == "slip":
        if resource_type != ImportResourceType.STUDENTS:
            raise BadRequestException(
                detail="Printable slips are only available for student imports."
            )
        result_rows = [reveal_result_row(row) for row in stored_rows]
        tenant = await TenantRepository.get_by_id(db=db, tenant_id=current_user.tenant_id)
        result_file = create_student_access_slip_report(
            result_rows=result_rows,
            school_name=tenant.school_name if tenant is not None else None,
        )
    else:
        result_rows = [redact_result_row(row) for row in stored_rows]
        result_file = create_result_report(
            resource_type=resource_type,
            result_rows=result_rows,
        )

    return Response(
        content=result_file.content_bytes,
        media_type=result_file.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result_file.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        },
    )


@router.get("/{job_id}/errors/download")
async def download_bulk_import_errors(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentTenantAdmin,
) -> Response:
    resource_type, row_errors = await BulkImportService.get_error_report_rows(
        db=db,
        actor=current_user,
        job_id=job_id,
    )
    result_file = create_error_report(resource_type=resource_type, row_errors=row_errors)
    return Response(
        content=result_file.content_bytes,
        media_type=result_file.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result_file.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        },
    )
