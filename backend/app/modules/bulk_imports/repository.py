# ============================== #
#   bulk_imports_repository.py   #
# ============================== #

"""Database operations for tenant bulk import workflows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.bulk_imports.models import (
    ImportJob,
    ImportJobStatus,
    ImportResourceType,
    ImportRowError,
    ImportStagedRow,
)
from app.modules.bulk_imports.schemas import (
    ImportJobCreate,
    ImportJobUpdate,
    ImportRowErrorCreate,
)
from app.modules.bulk_imports.validators import ImportRowValidationResult


class ImportJobRepository:
    """Database operations for import jobs."""

    @staticmethod
    async def create_job(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        job_data: ImportJobCreate,
    ) -> ImportJob:
        """Create a new import job."""

        import_job = ImportJob(
            tenant_id=tenant_id,
            resource_type=job_data.resource_type,
            file_type=job_data.file_type,
            original_filename=job_data.original_filename,
            stored_filename=job_data.stored_filename,
            source_file_path=job_data.source_file_path,
            file_size_bytes=job_data.file_size_bytes,
            source_fingerprint=job_data.source_fingerprint,
            confirmed_fingerprint=job_data.confirmed_fingerprint,
            created_by_admin_id=job_data.created_by_admin_id,
            metadata_json=job_data.metadata_json or {},
        )

        db.add(import_job)
        await db.flush()
        await db.refresh(import_job)
        return import_job

    @staticmethod
    async def get_job_by_id(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        job_id: UUID,
        include_children: bool = False,
        lock: bool = False,
    ) -> ImportJob | None:
        """Get an import job by ID within a tenant."""

        query = select(ImportJob).where(
            ImportJob.tenant_id == tenant_id,
            ImportJob.id == job_id,
        )

        if include_children:
            query = query.options(selectinload(ImportJob.row_errors))

        if lock:
            query = query.with_for_update()

        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_confirmed_job_by_fingerprint(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        resource_type: ImportResourceType,
        source_fingerprint: str,
        exclude_job_id: UUID | None = None,
        lock: bool = False,
    ) -> ImportJob | None:
        """Return the job that already claimed a canonical import fingerprint."""

        query = select(ImportJob).where(
            ImportJob.tenant_id == tenant_id,
            ImportJob.resource_type == resource_type,
            ImportJob.confirmed_fingerprint == source_fingerprint,
        )
        if exclude_job_id is not None:
            query = query.where(ImportJob.id != exclude_job_id)
        if lock:
            query = query.with_for_update()
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_jobs(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        resource_type: ImportResourceType | None = None,
        status: ImportJobStatus | None = None,
        search: str | None = None,
    ) -> tuple[list[ImportJob], int]:
        """List import jobs for a tenant with optional filters."""

        conditions = [ImportJob.tenant_id == tenant_id]

        if resource_type is not None:
            conditions.append(ImportJob.resource_type == resource_type)

        if status is not None:
            conditions.append(ImportJob.status == status)

        if search and search.strip():
            conditions.append(ImportJob.original_filename.ilike(f"%{search.strip()}%"))

        result = await db.execute(
            select(ImportJob)
            .where(*conditions)
            .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
            .offset(skip)
            .limit(limit)
        )
        jobs = list(result.scalars().all())

        total_result = await db.execute(
            select(func.count()).select_from(ImportJob).where(*conditions)
        )
        total = total_result.scalar_one()

        return jobs, total

    @staticmethod
    async def update_job(
        db: AsyncSession,
        *,
        import_job: ImportJob,
        job_update: ImportJobUpdate,
    ) -> ImportJob:
        """Update an import job from an update schema."""

        update_data = job_update.model_dump(exclude_unset=True)

        for field_name, value in update_data.items():
            setattr(import_job, field_name, value)

        db.add(import_job)
        await db.flush()
        await db.refresh(import_job)
        return import_job

    @staticmethod
    async def save(
        db: AsyncSession,
        *,
        import_job: ImportJob,
    ) -> ImportJob:
        """Persist import job changes."""

        db.add(import_job)
        await db.flush()
        await db.refresh(import_job)
        return import_job

    @staticmethod
    async def delete_job(
        db: AsyncSession,
        *,
        import_job: ImportJob,
    ) -> None:
        """Delete an import job.

        Row errors and staged rows are deleted by cascade.
        """

        await db.delete(import_job)
        await db.flush()


class ImportRowErrorRepository:
    """Database operations for row-level import errors."""

    @staticmethod
    async def create_error(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        row_error_data: ImportRowErrorCreate,
    ) -> ImportRowError:
        """Create one row-level import error."""

        row_error = ImportRowError(
            tenant_id=tenant_id,
            import_job_id=row_error_data.import_job_id,
            row_number=row_error_data.row_number,
            field_name=row_error_data.field_name,
            error_code=row_error_data.error_code,
            error_message=row_error_data.error_message,
            raw_row=row_error_data.raw_row,
            normalized_row=row_error_data.normalized_row,
        )

        db.add(row_error)
        await db.flush()
        await db.refresh(row_error)
        return row_error

    @staticmethod
    async def create_many(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        row_error_items: list[ImportRowErrorCreate],
    ) -> list[ImportRowError]:
        """Create multiple row-level import errors."""

        row_errors = [
            ImportRowError(
                tenant_id=tenant_id,
                import_job_id=row_error_data.import_job_id,
                row_number=row_error_data.row_number,
                field_name=row_error_data.field_name,
                error_code=row_error_data.error_code,
                error_message=row_error_data.error_message,
                raw_row=row_error_data.raw_row,
                normalized_row=row_error_data.normalized_row,
            )
            for row_error_data in row_error_items
        ]

        if not row_errors:
            return []

        db.add_all(row_errors)
        await db.flush()

        for row_error in row_errors:
            await db.refresh(row_error)

        return row_errors

    @staticmethod
    async def get_error_by_id(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        error_id: UUID,
    ) -> ImportRowError | None:
        """Get a row error by ID within a tenant."""

        result = await db.execute(
            select(ImportRowError).where(
                ImportRowError.tenant_id == tenant_id,
                ImportRowError.id == error_id,
            )
        )

        return result.scalar_one_or_none()

    @staticmethod
    async def list_errors_by_job(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        import_job_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ImportRowError], int]:
        """List row-level errors for one import job."""

        conditions = [
            ImportRowError.tenant_id == tenant_id,
            ImportRowError.import_job_id == import_job_id,
        ]

        result = await db.execute(
            select(ImportRowError)
            .where(*conditions)
            .order_by(ImportRowError.row_number.asc(), ImportRowError.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        row_errors = list(result.scalars().all())

        total_result = await db.execute(
            select(func.count()).select_from(ImportRowError).where(*conditions)
        )
        total = total_result.scalar_one()

        return row_errors, total


class ImportStagedRowRepository:
    """Database operations for dry-run staged rows."""

    @staticmethod
    async def create_many(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        import_job_id: UUID,
        validation_results: list[ImportRowValidationResult],
    ) -> list[ImportStagedRow]:
        """Create staged rows for all valid dry-run rows."""

        staged_rows = [
            ImportStagedRow(
                tenant_id=tenant_id,
                import_job_id=import_job_id,
                row_number=validation_result.row_number,
                raw_row=validation_result.raw_row,
                normalized_row=validation_result.normalized_row,
            )
            for validation_result in validation_results
            if validation_result.is_valid
        ]

        if not staged_rows:
            return []

        db.add_all(staged_rows)
        await db.flush()

        for staged_row in staged_rows:
            await db.refresh(staged_row)

        return staged_rows

    @staticmethod
    async def list_by_job(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        import_job_id: UUID,
    ) -> list[ImportStagedRow]:
        """List staged rows for one import job."""

        result = await db.execute(
            select(ImportStagedRow)
            .where(
                ImportStagedRow.tenant_id == tenant_id,
                ImportStagedRow.import_job_id == import_job_id,
            )
            .order_by(ImportStagedRow.row_number.asc())
        )

        return list(result.scalars().all())

    @staticmethod
    async def delete_by_job(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        import_job_id: UUID,
    ) -> None:
        """Delete staged rows for one import job."""

        await db.execute(
            delete(ImportStagedRow).where(
                ImportStagedRow.tenant_id == tenant_id,
                ImportStagedRow.import_job_id == import_job_id,
            )
        )
        await db.flush()
