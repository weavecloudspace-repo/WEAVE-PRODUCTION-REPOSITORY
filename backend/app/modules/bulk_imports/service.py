# =========================== #
#   bulk_imports_service.py   #
# =========================== #

"""Main service layer for tenant bulk imports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.core.utils.normalization import normalized_class_arm_key
from app.modules.auth.account_email_guard import AccountEmailGuard
from app.modules.auth_identity.models import ActorType
from app.modules.auth_identity.service import AuthIdentityService
from app.modules.bulk_imports.chunking import chunk_import_items
from app.modules.bulk_imports.models import (
    ImportFileType,
    ImportJob,
    ImportJobStatus,
    ImportResourceType,
)
from app.modules.bulk_imports.normalizers import (
    BulkImportNormalizer,
    SUPPORTED_IMPORT_RESOURCE_TYPES,
)
from app.modules.bulk_imports.notification_service import BulkImportCommunicationService
from app.modules.bulk_imports.parsers import BulkImportParser, ParsedImportFile
from app.modules.bulk_imports.repository import (
    ImportJobRepository,
    ImportRowErrorRepository,
    ImportStagedRowRepository,
)
from app.modules.bulk_imports.schemas import (
    ImportJobCreate,
    ImportJobDetailResponse,
    ImportJobListResponse,
    ImportJobSummaryResponse,
    ImportJobUpdate,
    ImportRowErrorCreate,
    ImportRowErrorListResponse,
)
from app.modules.bulk_imports.template_security import (
    build_headers_hash,
    verify_template_signature,
)
from app.modules.bulk_imports.template_writer import (
    GeneratedImportTemplate,
    create_import_template,
)
from app.modules.bulk_imports.templates import (
    CONTROL_COLUMNS,
    DATA_HEADERS_BY_RESOURCE,
    TEMPLATE_VERSION_BY_RESOURCE,
    get_template_response,
    list_template_responses,
)
from app.modules.bulk_imports.validators import (
    BulkImportValidator,
    ImportRowValidationResult,
    ImportValidationErrorItem,
)
from app.modules.classes.repository import (
    AcademicLevelRepository,
    ArmLabelRepository,
    ClassRoomRepository,
)
from app.modules.classes.department_repository import AcademicLevelDepartmentRepository
from app.modules.classes.models import AcademicLevelStatus
from app.modules.parents.repository import ParentAccountRepository
from app.modules.student_academics.curriculum_models import ClassTermDepartmentAssignment
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.students.models import (
    ParentRelationship,
    Student,
)
from app.modules.students.schemas import StudentCreate, StudentParentInvitationInput
from app.modules.students.service import StudentCreationWorkflowResult, StudentService
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import FeatureCode, ResourceLimitCode
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository

IMPORT_PROCESSING_CHUNK_SIZE = 100


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""

    return datetime.now(timezone.utc)


def compact_validation_error(exc: ValidationError) -> str:
    """Return a compact pydantic validation error message."""

    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = str(first_error.get("msg", "Invalid row data."))
    return f"{location}: {message}" if location else message


def build_failed_result_row(
    *,
    row_number: int,
    normalized_row: dict[str, Any],
    error_message: str,
) -> dict[str, Any]:
    """Build a failed row result."""

    return {
        "row_number": row_number,
        "status": "failed",
        **normalized_row,
        "error_message": error_message,
    }


def build_validation_error_items(
    *,
    import_job_id: UUID,
    validation_result: ImportRowValidationResult,
) -> list[ImportRowErrorCreate]:
    """Build row error schemas from validation errors."""

    return [
        ImportRowErrorCreate(
            import_job_id=import_job_id,
            row_number=error.row_number,
            field_name=error.field_name,
            error_code=error.error_code,
            error_message=error.error_message,
            raw_row=validation_result.raw_row,
            normalized_row=validation_result.normalized_row,
        )
        for error in validation_result.errors
    ]


def strip_control_columns(raw_row: dict[str, Any]) -> dict[str, Any]:
    """Remove signed-template control columns before row normalization."""

    return {
        key: value
        for key, value in raw_row.items()
        if BulkImportNormalizer.normalize_key(key) not in CONTROL_COLUMNS
    }


def _is_blank(value: Any) -> bool:
    """Return True when a value is blank."""

    return value is None or str(value).strip() == ""


def append_validation_error(
    *,
    validation_result: ImportRowValidationResult,
    field_name: str | None,
    error_code: str,
    error_message: str,
) -> None:
    """Append one service-level validation error to a row result."""

    validation_result.errors.append(
        ImportValidationErrorItem(
            row_number=validation_result.row_number,
            field_name=field_name,
            error_code=error_code,
            error_message=error_message,
        )
    )


def _format_class_reference(*parts: Any) -> str:
    """Build a concise class label for validation messages."""

    clean_parts = [str(part).strip() for part in parts if not _is_blank(part)]
    return " ".join(clean_parts) or "the supplied class"


def build_import_source_fingerprint(
    *,
    resource_type: ImportResourceType,
    template_version: str | None,
    rows: list[tuple[int, dict[str, Any]]],
) -> str:
    """Hash canonical normalized rows so the same workbook cannot be confirmed twice."""

    canonical_rows = sorted(
        json.dumps(
            normalized_row,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        for _, normalized_row in rows
    )
    canonical_payload = {
        "resource_type": resource_type.value,
        "template_version": str(template_version or ""),
        "rows": canonical_rows,
    }
    encoded = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def duplicate_import_message(import_job: ImportJob) -> str:
    completed = import_job.completed_at or import_job.created_at
    completed_text = completed.isoformat() if completed else "an earlier date"
    return (
        "This student workbook has already been confirmed and processed "
        f"by import job {import_job.id} on {completed_text}. "
        "Use a new workbook containing only records that have not been imported."
    )


def build_parent_invitations_from_row(
    normalized_row: dict[str, Any],
) -> list[StudentParentInvitationInput]:
    """Build student parent invitations from the two supported spreadsheet slots."""

    invitations: list[StudentParentInvitationInput] = []
    for index in (1, 2):
        email = normalized_row.get(f"parent_email_{index}")
        relationship = normalized_row.get(f"parent_relationship_{index}")
        if _is_blank(email) and _is_blank(relationship):
            continue

        invitations.append(
            StudentParentInvitationInput(
                email=str(email),
                relationship_type=ParentRelationship(str(relationship)),
            )
        )

    return invitations


class BulkImportService:
    """Coordinate parsing, validation, creation, results, and notifications."""

    @staticmethod
    def ensure_supported_resource_type(resource_type: ImportResourceType) -> None:
        """Reject resource types outside this implementation phase."""

        if resource_type not in SUPPORTED_IMPORT_RESOURCE_TYPES:
            raise BadRequestException(
                detail=f"{resource_type.value} bulk import is not supported yet."
            )

    @staticmethod
    def resource_limit_code(resource_type: ImportResourceType) -> ResourceLimitCode:
        """Map import resource type to subscription resource limit code."""

        return {
            ImportResourceType.STUDENTS: ResourceLimitCode.STUDENTS,
        }[resource_type]

    @staticmethod
    def resolve_final_status(*, successful_rows: int, failed_rows: int) -> ImportJobStatus:
        """Resolve final import job status from row counters."""

        if failed_rows == 0:
            return ImportJobStatus.COMPLETED
        if successful_rows > 0:
            return ImportJobStatus.PARTIALLY_COMPLETED
        return ImportJobStatus.FAILED

    @staticmethod
    def validate_dry_run_confirmation_contract(
        *,
        import_job: ImportJob,
        staged_row_count: int,
    ) -> None:
        """Enforce the backend dry-run to confirmed-import contract."""

        metadata_json = dict(import_job.metadata_json or {})
        if import_job.status in {ImportJobStatus.PENDING, ImportJobStatus.PROCESSING}:
            raise ConflictException(detail="This import job is already pending or processing.")
        if not metadata_json.get("dry_run"):
            raise BadRequestException(detail="Only dry-run import jobs can be confirmed.")
        if not metadata_json.get("confirmation_required"):
            raise BadRequestException(detail="This dry-run job does not require confirmation.")
        if metadata_json.get("confirmed_at"):
            raise ConflictException(detail="This import job has already been confirmed.")
        if import_job.status != ImportJobStatus.COMPLETED or import_job.completed_at is None:
            raise BadRequestException(
                detail="The dry run must complete successfully before confirmation."
            )
        if int(import_job.failed_rows or 0) != 0:
            raise BadRequestException(detail="All rows must pass validation before confirmation.")
        if int(import_job.successful_rows or 0) <= 0:
            raise BadRequestException(detail="This dry-run job has no valid rows to confirm.")
        if staged_row_count <= 0:
            raise BadRequestException(
                detail="This dry-run job has no valid staged rows to confirm."
            )
        if staged_row_count != int(import_job.total_rows or 0):
            raise ConflictException(
                detail="The number of staged valid rows does not match the dry-run total rows."
            )

    @staticmethod
    def validate_exact_headers(
        *,
        actual_headers: list[str],
        expected_headers: list[str],
    ) -> None:
        """Ensure uploaded data headers exactly match the current template contract."""

        normalized_actual = [
            BulkImportNormalizer.normalize_key(header) for header in actual_headers
        ]
        normalized_expected = [
            BulkImportNormalizer.normalize_key(header) for header in expected_headers
        ]

        if normalized_actual != normalized_expected:
            raise BadRequestException(
                detail=(
                    "Import file headers do not match the selected template. "
                    f"Expected: {', '.join(expected_headers)}. "
                    f"Received: {', '.join(actual_headers)}."
                )
            )

    @staticmethod
    def validate_import_template_contract(
        *,
        tenant_id: UUID,
        endpoint_resource_type: ImportResourceType,
        parsed_file: ParsedImportFile,
    ) -> None:
        """Validate signed template metadata before processing rows."""

        metadata = parsed_file.metadata or {}
        resource_type_value = metadata.get("_import_resource_type")
        template_version = metadata.get("_import_template_version")
        headers_hash = metadata.get("_import_headers_hash")
        signature = metadata.get("_import_template_signature")

        if not all([resource_type_value, template_version, headers_hash, signature]):
            raise BadRequestException(
                detail="Import file must be generated from a valid backend template."
            )

        resource_type_value = str(resource_type_value).strip()
        template_version = str(template_version).strip()
        headers_hash = str(headers_hash).strip()
        signature = str(signature).strip()

        if resource_type_value != endpoint_resource_type.value:
            raise BadRequestException(
                detail=(
                    f"This file is for {resource_type_value}, but it was uploaded "
                    f"to {endpoint_resource_type.value} import."
                )
            )

        expected_version = TEMPLATE_VERSION_BY_RESOURCE[endpoint_resource_type]
        if template_version != expected_version:
            raise BadRequestException(
                detail="This import template version is no longer supported. Download a new template."
            )

        expected_headers = DATA_HEADERS_BY_RESOURCE[endpoint_resource_type]
        BulkImportService.validate_exact_headers(
            actual_headers=parsed_file.headers,
            expected_headers=expected_headers,
        )

        actual_headers_hash = build_headers_hash(parsed_file.headers)
        expected_headers_hash = build_headers_hash(expected_headers)

        if actual_headers_hash != headers_hash:
            raise BadRequestException(
                detail="Import file headers were changed. Download a new template and try again."
            )

        if headers_hash != expected_headers_hash:
            raise BadRequestException(
                detail="Import template headers do not match the current backend template."
            )

        if not verify_template_signature(
            tenant_id=tenant_id,
            resource_type=endpoint_resource_type,
            template_version=template_version,
            headers_hash=headers_hash,
            signature=signature,
        ):
            raise BadRequestException(
                detail="Invalid import template signature. Download a new template."
            )

    @staticmethod
    def build_validation_result_rows(
        *,
        validation_results: list[ImportRowValidationResult],
    ) -> list[dict[str, Any]]:
        """Build dry-run result rows."""

        result_rows: list[dict[str, Any]] = []

        for validation_result in validation_results:
            if validation_result.is_valid:
                result_rows.append(
                    {
                        "row_number": validation_result.row_number,
                        "status": "valid",
                        **validation_result.normalized_row,
                        "error_message": "",
                    }
                )
                continue

            result_rows.append(
                build_failed_result_row(
                    row_number=validation_result.row_number,
                    normalized_row=validation_result.normalized_row,
                    error_message="; ".join(
                        error.error_message for error in validation_result.errors
                    ),
                )
            )

        return result_rows

    @staticmethod
    def build_row_items(
        *,
        resource_type: ImportResourceType,
        parsed_file: ParsedImportFile,
    ) -> list[tuple[int, dict[str, Any], dict[str, Any], list[str]]]:
        """Strip control columns, normalize parsed rows, and build validator input."""

        row_items: list[tuple[int, dict[str, Any], dict[str, Any], list[str]]] = []

        for parsed_row in parsed_file.rows:
            raw_data = strip_control_columns(parsed_row.raw_data)
            normalized_row, ignored_fields = BulkImportNormalizer.normalize_row(
                resource_type=resource_type,
                raw_row=raw_data,
            )
            row_items.append((parsed_row.row_number, raw_data, normalized_row, ignored_fields))

        return row_items

    @staticmethod
    async def _get_class_term_department_assignment(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        class_id: UUID,
        academic_term_id: UUID,
    ) -> ClassTermDepartmentAssignment | None:
        """Return the class specialization for one exact academic term."""

        return (
            await db.execute(
                select(ClassTermDepartmentAssignment).where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.class_id == class_id,
                    ClassTermDepartmentAssignment.academic_term_id == academic_term_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def resolve_student_class_references(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        validation_results: list[ImportRowValidationResult],
    ) -> None:
        """Resolve level + arm to class and derive current-term specialization."""

        current_term = await StudentAcademicRepository.get_current_term(db, tenant_id)

        for validation_result in validation_results:
            normalized_row = validation_result.normalized_row
            level_name = normalized_row.get("level")
            arm_name = normalized_row.get("arm")

            if _is_blank(level_name) or _is_blank(arm_name):
                continue

            level = await AcademicLevelRepository.get_by_normalized_name(
                db, tenant_id, str(level_name)
            )
            if level is None:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="level",
                    error_code="level_not_found",
                    error_message=f"Academic level {level_name} does not exist.",
                )
                continue
            if level.status != AcademicLevelStatus.ACTIVE:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="level",
                    error_code="level_inactive",
                    error_message=f"Academic level {level.name} is inactive or archived.",
                )
                continue

            normalized_row["academic_level_id"] = str(level.id)
            normalized_row["level"] = level.name

            arm_label = await ArmLabelRepository.get_by_normalized_label(
                db,
                tenant_id,
                normalized_class_arm_key(arm_name),
            )
            if arm_label is None:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="arm",
                    error_code="arm_label_not_found",
                    error_message=(
                        f"Arm label {arm_name} does not exist. "
                        "Create the arm label before importing students."
                    ),
                )
                continue
            if not arm_label.is_active or arm_label.archived_at is not None:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="arm",
                    error_code="arm_label_inactive",
                    error_message=f"Arm label {arm_label.label} is inactive or archived.",
                )
                continue

            normalized_row["arm"] = arm_label.label
            classroom = await ClassRoomRepository.get_by_level_arm_label(
                db=db,
                tenant_id=tenant_id,
                academic_level_id=level.id,
                arm_label_id=arm_label.id,
            )
            class_reference = _format_class_reference(level.name, arm_label.label)

            if classroom is None:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="arm",
                    error_code="class_not_found",
                    error_message=(
                        f"Class {class_reference} does not exist. "
                        "Create the class first before importing students."
                    ),
                )
                continue
            if not classroom.is_active or classroom.archived_at is not None:
                append_validation_error(
                    validation_result=validation_result,
                    field_name="arm",
                    error_code="class_inactive",
                    error_message=(
                        f"Class {class_reference} is inactive or archived. "
                        "Use an active class before importing students."
                    ),
                )
                continue

            normalized_row["class_id"] = str(classroom.id)

            if current_term is None:
                normalized_row["department"] = None
                continue

            assignment = await BulkImportService._get_class_term_department_assignment(
                db,
                tenant_id=tenant_id,
                class_id=classroom.id,
                academic_term_id=current_term.id,
            )

            if assignment is None:
                normalized_row["department"] = None
                continue

            assigned_link = await AcademicLevelDepartmentRepository.get_by_id(
                db,
                tenant_id,
                assignment.academic_level_department_id,
            )
            if (
                assigned_link is None
                or assigned_link.academic_level_id != level.id
                or not assigned_link.is_active
                or assigned_link.archived_at is not None
                or not assigned_link.department.is_active
                or assigned_link.department.archived_at is not None
            ):
                append_validation_error(
                    validation_result=validation_result,
                    field_name="arm",
                    error_code="class_department_assignment_invalid",
                    error_message=(
                        f"Class {class_reference} has an invalid current-term department assignment. "
                        "Fix the academic setup before importing students."
                    ),
                )
                continue

            normalized_row["department"] = assigned_link.department.name

    @staticmethod
    async def preflight_student_parent_invitations(
        db: AsyncSession,
        *,
        validation_results: list[ImportRowValidationResult],
    ) -> dict[str, int]:
        """Validate invitation-safe parent email state without creating records."""

        summary = {
            "parent_emails_supplied": 0,
            "existing_parent_accounts": 0,
            "new_parent_invitations_expected": 0,
            "parent_links_expected_after_acceptance": 0,
        }

        email_slots: list[tuple[ImportRowValidationResult, str, str]] = []
        unique_parent_emails: dict[str, str] = {}

        for validation_result in validation_results:
            if validation_result.errors:
                continue

            for index in (1, 2):
                email_field = f"parent_email_{index}"
                email = validation_result.normalized_row.get(email_field)
                if _is_blank(email):
                    continue

                summary["parent_emails_supplied"] += 1
                normalized_email = AccountEmailGuard._normalize_email(str(email))
                email_slots.append((validation_result, email_field, normalized_email))
                unique_parent_emails.setdefault(normalized_email, normalized_email)

        preflight_by_email: dict[str, dict[str, object]] = {}
        for normalized_email in unique_parent_emails:
            try:
                checked_email = await AccountEmailGuard.ensure_available_for_invitation_role(
                    db=db,
                    email=normalized_email,
                    invited_actor_type=ActorType.PARENT_ACCOUNT,
                )
                existing_parent = await ParentAccountRepository.get_by_email(
                    db,
                    checked_email,
                )
                preflight_by_email[normalized_email] = {
                    "normalized_email": checked_email,
                    "existing_parent": existing_parent,
                    "error": None,
                }
            except ConflictException as exc:
                preflight_by_email[normalized_email] = {
                    "normalized_email": normalized_email,
                    "existing_parent": None,
                    "error": str(exc.detail if hasattr(exc, "detail") else exc),
                }

        summary["existing_parent_accounts"] = sum(
            1
            for preflight in preflight_by_email.values()
            if preflight["existing_parent"] is not None
        )

        for validation_result, email_field, normalized_email in email_slots:
            preflight = preflight_by_email[normalized_email]
            if preflight["error"]:
                append_validation_error(
                    validation_result=validation_result,
                    field_name=email_field,
                    error_code="parent_email_role_conflict",
                    error_message=str(preflight["error"]),
                )
                continue

            validation_result.normalized_row[email_field] = str(preflight["normalized_email"])
            summary["new_parent_invitations_expected"] += 1
            summary["parent_links_expected_after_acceptance"] += 1

        return summary

    @staticmethod
    async def create_student_from_row(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        normalized_row: dict[str, Any],
    ) -> StudentCreationWorkflowResult:
        """Create one student using manual creation semantics without committing."""

        first_name = normalized_row.get("first_name")
        last_name = normalized_row.get("last_name")
        date_of_birth = BulkImportValidator.parse_date(normalized_row.get("date_of_birth"))
        academic_level_id = BulkImportValidator.parse_uuid(normalized_row.get("academic_level_id"))
        class_id = BulkImportValidator.parse_uuid(normalized_row.get("class_id"))
        if (
            _is_blank(first_name)
            or _is_blank(last_name)
            or date_of_birth is None
            or academic_level_id is None
        ):
            raise BadRequestException(detail="Validated student row is missing required fields.")

        student_data = StudentCreate(
            first_name=str(first_name),
            last_name=str(last_name),
            date_of_birth=date_of_birth,
            gender=normalized_row.get("gender"),
            academic_level_id=academic_level_id,
            class_id=class_id,
            state_of_origin=normalized_row.get("state_of_origin"),
            parents=build_parent_invitations_from_row(normalized_row),
        )

        return await StudentService._create_student_with_lifecycle(
            db,
            actor=actor,
            payload=student_data,
            invitation_source="bulk_import",
        )

    @staticmethod
    async def process_valid_row(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        resource_type: ImportResourceType,
        validation_result: ImportRowValidationResult,
        school_name: str,
    ) -> dict[str, Any]:
        """Process one validated row."""

        if resource_type == ImportResourceType.STUDENTS:
            # Re-resolve at the actual creation boundary so the background worker
            # never trusts a department value staged during dry-run. Class and
            # current-term specialization remain the source of truth.
            validation_result.errors.clear()
            await BulkImportService.resolve_student_class_references(
                db=db,
                tenant_id=actor.tenant_id,
                validation_results=[validation_result],
            )
            if validation_result.errors:
                raise ConflictException(
                    detail="; ".join(error.error_message for error in validation_result.errors)
                )

            created = await BulkImportService.create_student_from_row(
                db=db,
                actor=actor,
                normalized_row=validation_result.normalized_row,
            )
            student: Student = created.student
            return {
                "row_number": validation_result.row_number,
                "status": "created",
                "first_name": student.first_name,
                "last_name": student.last_name,
                "admission_number": student.admission_number,
                "level": validation_result.normalized_row.get("level"),
                "arm": validation_result.normalized_row.get("arm"),
                "department": validation_result.normalized_row.get("department"),
                "setup_code": created.setup_code,
                "access_code_expires_at": created.access_code_expires_at.isoformat(),
                "parent_invitations_queued": created.parent_invitation_count,
                "error_message": "",
            }

        raise BadRequestException(detail=f"{resource_type.value} bulk import is not supported yet.")

    @staticmethod
    async def process_valid_rows(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        resource_type: ImportResourceType,
        validation_results: list[ImportRowValidationResult],
        import_job_id: UUID,
        school_name: str,
    ) -> tuple[int, int, list[ImportRowErrorCreate], list[dict[str, Any]]]:
        """Process valid rows in chunks."""

        successful_rows = 0
        failed_rows = 0
        row_error_items: list[ImportRowErrorCreate] = []
        result_rows: list[dict[str, Any]] = []

        for chunk in chunk_import_items(
            items=validation_results, chunk_size=IMPORT_PROCESSING_CHUNK_SIZE
        ):
            for validation_result in chunk.items:
                try:
                    async with db.begin_nested():
                        result_row = await BulkImportService.process_valid_row(
                            db=db,
                            actor=actor,
                            resource_type=resource_type,
                            validation_result=validation_result,
                            school_name=school_name,
                        )
                    successful_rows += 1
                    result_rows.append(result_row)

                except (
                    BadRequestException,
                    ConflictException,
                    NotFoundException,
                    ValidationError,
                ) as exc:
                    failed_rows += 1
                    error_message = (
                        compact_validation_error(exc)
                        if isinstance(exc, ValidationError)
                        else str(exc.detail if hasattr(exc, "detail") else exc)
                    )
                    row_error_items.append(
                        ImportRowErrorCreate(
                            import_job_id=import_job_id,
                            row_number=validation_result.row_number,
                            field_name=None,
                            error_code="processing_error",
                            error_message=error_message,
                            raw_row=validation_result.raw_row,
                            normalized_row=validation_result.normalized_row,
                        )
                    )
                    result_rows.append(
                        build_failed_result_row(
                            row_number=validation_result.row_number,
                            normalized_row=validation_result.normalized_row,
                            error_message=error_message,
                        )
                    )

                except IntegrityError:
                    failed_rows += 1
                    error_message = "Row failed because of a duplicate or invalid database value."
                    row_error_items.append(
                        ImportRowErrorCreate(
                            import_job_id=import_job_id,
                            row_number=validation_result.row_number,
                            field_name=None,
                            error_code="integrity_error",
                            error_message=error_message,
                            raw_row=validation_result.raw_row,
                            normalized_row=validation_result.normalized_row,
                        )
                    )
                    result_rows.append(
                        build_failed_result_row(
                            row_number=validation_result.row_number,
                            normalized_row=validation_result.normalized_row,
                            error_message=error_message,
                        )
                    )

        return successful_rows, failed_rows, row_error_items, result_rows

    @staticmethod
    def generate_template_file(
        *,
        tenant_id: UUID,
        resource_type: ImportResourceType,
        file_type: ImportFileType = ImportFileType.XLSX,
    ) -> GeneratedImportTemplate:
        """Generate a signed backend-owned import template file."""

        BulkImportService.ensure_supported_resource_type(resource_type)
        try:
            return create_import_template(
                tenant_id=tenant_id,
                resource_type=resource_type,
                file_type=file_type,
            )
        except ValueError as exc:
            raise BadRequestException(detail=str(exc)) from exc

    @staticmethod
    async def create_dry_run_from_upload(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        resource_type: ImportResourceType,
        upload_file: UploadFile,
        notify_on_completion: bool = True,
    ) -> ImportJobDetailResponse:
        """Parse, validate, and stage an import file without creating records."""

        BulkImportService.ensure_supported_resource_type(resource_type)

        await SubscriptionFeatureService.ensure_feature_enabled(
            db=db,
            tenant_id=actor.tenant_id,
            feature=FeatureCode.BULK_IMPORT,
        )

        parsed_file = await BulkImportParser.parse_upload(upload_file)
        if not parsed_file.rows:
            raise BadRequestException(detail="Import file does not contain any data rows.")

        BulkImportService.validate_import_template_contract(
            tenant_id=actor.tenant_id,
            endpoint_resource_type=resource_type,
            parsed_file=parsed_file,
        )

        row_items = BulkImportService.build_row_items(
            resource_type=resource_type,
            parsed_file=parsed_file,
        )
        source_fingerprint = build_import_source_fingerprint(
            resource_type=resource_type,
            template_version=parsed_file.metadata.get("_import_template_version"),
            rows=[(row_number, normalized_row) for row_number, _, normalized_row, _ in row_items],
        )
        existing_import = await ImportJobRepository.get_confirmed_job_by_fingerprint(
            db=db,
            tenant_id=actor.tenant_id,
            resource_type=resource_type,
            source_fingerprint=source_fingerprint,
        )
        if existing_import is not None:
            raise ConflictException(detail=duplicate_import_message(existing_import))

        import_job = await ImportJobRepository.create_job(
            db=db,
            tenant_id=actor.tenant_id,
            job_data=ImportJobCreate(
                resource_type=resource_type,
                file_type=parsed_file.file_type,
                original_filename=upload_file.filename
                or f"{resource_type.value}_import.{parsed_file.file_type.value}",
                file_size_bytes=parsed_file.file_size_bytes,
                source_fingerprint=source_fingerprint,
                created_by_admin_id=actor.id,
                metadata_json={
                    "dry_run": True,
                    "confirmation_required": True,
                    "notify_on_completion": notify_on_completion,
                    "template_version": parsed_file.metadata.get("_import_template_version"),
                    "template_headers_hash": parsed_file.metadata.get("_import_headers_hash"),
                    "source_fingerprint": source_fingerprint,
                    "result_rows": [],
                },
            ),
        )

        import_job = await ImportJobRepository.update_job(
            db=db,
            import_job=import_job,
            job_update=ImportJobUpdate(
                status=ImportJobStatus.PROCESSING,
                started_at=utc_now(),
                total_rows=len(parsed_file.rows),
            ),
        )

        validation_results = BulkImportValidator.validate_rows(
            resource_type=resource_type,
            row_items=row_items,
        )

        if resource_type == ImportResourceType.STUDENTS:
            await BulkImportService.resolve_student_class_references(
                db=db,
                tenant_id=actor.tenant_id,
                validation_results=validation_results,
            )
            parent_preflight_summary = await BulkImportService.preflight_student_parent_invitations(
                db=db,
                validation_results=validation_results,
            )
        else:
            parent_preflight_summary = {}

        invalid_results = [result for result in validation_results if not result.is_valid]
        valid_results = [result for result in validation_results if result.is_valid]

        validation_error_items: list[ImportRowErrorCreate] = []
        for validation_result in invalid_results:
            validation_error_items.extend(
                build_validation_error_items(
                    import_job_id=import_job.id,
                    validation_result=validation_result,
                )
            )

        if validation_error_items:
            await ImportRowErrorRepository.create_many(
                db=db,
                tenant_id=actor.tenant_id,
                row_error_items=validation_error_items,
            )

        if valid_results:
            await ImportStagedRowRepository.create_many(
                db=db,
                tenant_id=actor.tenant_id,
                import_job_id=import_job.id,
                validation_results=valid_results,
            )

        successful_rows = len(valid_results)
        failed_rows = len(invalid_results)
        result_rows = BulkImportService.build_validation_result_rows(
            validation_results=validation_results,
        )
        final_status = BulkImportService.resolve_final_status(
            successful_rows=successful_rows,
            failed_rows=failed_rows,
        )

        metadata_json = dict(import_job.metadata_json or {})
        metadata_json["result_rows"] = sorted(
            result_rows,
            key=lambda row: int(row.get("row_number") or 0),
        )
        metadata_json["valid_rows"] = len(valid_results)
        metadata_json["invalid_rows"] = len(invalid_results)
        metadata_json["staged_valid_rows"] = len(valid_results)
        metadata_json["dry_run_completed_at"] = utc_now().isoformat()
        metadata_json.update(parent_preflight_summary)

        import_job = await ImportJobRepository.update_job(
            db=db,
            import_job=import_job,
            job_update=ImportJobUpdate(
                status=final_status,
                total_rows=len(parsed_file.rows),
                processed_rows=len(parsed_file.rows),
                successful_rows=successful_rows,
                failed_rows=failed_rows,
                skipped_rows=0,
                completed_at=utc_now(),
                metadata_json=metadata_json,
            ),
        )

        await db.commit()

        refreshed_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=import_job.id,
            include_children=True,
        )
        if refreshed_job is None:
            raise NotFoundException(detail="Import job not found after dry run.")

        return ImportJobDetailResponse.model_validate(refreshed_job)

    @staticmethod
    async def create_import_from_upload(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        resource_type: ImportResourceType,
        upload_file: UploadFile,
        dry_run: bool = False,
        notify_on_completion: bool = True,
    ) -> ImportJobDetailResponse:
        """Backward-compatible upload entry point.

        Real imports now require a dry-run job and the confirm endpoint.
        """

        if not dry_run:
            raise BadRequestException(
                detail="Direct bulk imports are disabled. Run dry_run=true first, then confirm the import job."
            )

        return await BulkImportService.create_dry_run_from_upload(
            db=db,
            actor=actor,
            resource_type=resource_type,
            upload_file=upload_file,
            notify_on_completion=notify_on_completion,
        )

    @staticmethod
    async def confirm_import_from_dry_run(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
        notify_on_completion: bool = True,
    ) -> ImportJobDetailResponse:
        """Confirm a staged dry-run import and create records from staged rows."""

        await SubscriptionFeatureService.ensure_feature_enabled(
            db=db,
            tenant_id=actor.tenant_id,
            feature=FeatureCode.BULK_IMPORT,
        )

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
            lock=True,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        metadata_json = dict(import_job.metadata_json or {})
        staged_rows = await ImportStagedRowRepository.list_by_job(
            db=db,
            tenant_id=actor.tenant_id,
            import_job_id=import_job.id,
        )
        BulkImportService.validate_dry_run_confirmation_contract(
            import_job=import_job,
            staged_row_count=len(staged_rows),
        )

        source_fingerprint = import_job.source_fingerprint or build_import_source_fingerprint(
            resource_type=import_job.resource_type,
            template_version=metadata_json.get("template_version"),
            rows=[(row.row_number, row.normalized_row) for row in staged_rows],
        )
        existing_import = await ImportJobRepository.get_confirmed_job_by_fingerprint(
            db=db,
            tenant_id=actor.tenant_id,
            resource_type=import_job.resource_type,
            source_fingerprint=source_fingerprint,
            exclude_job_id=import_job.id,
        )
        if existing_import is not None:
            raise ConflictException(detail=duplicate_import_message(existing_import))

        tenant = await TenantRepository.get_by_id(db=db, tenant_id=actor.tenant_id)
        if tenant is None:
            raise NotFoundException(detail="Tenant not found")

        await SubscriptionFeatureService.ensure_resource_limit_available(
            db=db,
            tenant_id=actor.tenant_id,
            resource=BulkImportService.resource_limit_code(import_job.resource_type),
            increment=len(staged_rows),
        )

        import_job = await ImportJobRepository.update_job(
            db=db,
            import_job=import_job,
            job_update=ImportJobUpdate(
                status=ImportJobStatus.PROCESSING,
                started_at=utc_now(),
                completed_at=None,
                successful_rows=0,
                failed_rows=0,
                processed_rows=0,
                source_fingerprint=source_fingerprint,
                confirmed_fingerprint=source_fingerprint,
            ),
        )

        validation_results = [
            ImportRowValidationResult(
                row_number=staged_row.row_number,
                raw_row=staged_row.raw_row,
                normalized_row=staged_row.normalized_row,
            )
            for staged_row in staged_rows
        ]

        (
            created_count,
            processing_failed_count,
            processing_errors,
            processing_result_rows,
        ) = await BulkImportService.process_valid_rows(
            db=db,
            actor=actor,
            resource_type=import_job.resource_type,
            validation_results=validation_results,
            import_job_id=import_job.id,
            school_name=tenant.school_name,
        )

        if processing_errors:
            await ImportRowErrorRepository.create_many(
                db=db,
                tenant_id=actor.tenant_id,
                row_error_items=processing_errors,
            )

        existing_result_rows = list(metadata_json.get("result_rows") or [])
        invalid_result_rows = [row for row in existing_result_rows if row.get("status") == "failed"]

        invalid_rows = int(metadata_json.get("invalid_rows") or 0)
        successful_rows = created_count
        failed_rows = invalid_rows + processing_failed_count
        result_rows = [*invalid_result_rows, *processing_result_rows]
        final_status = BulkImportService.resolve_final_status(
            successful_rows=successful_rows,
            failed_rows=failed_rows,
        )

        metadata_json["dry_run"] = False
        metadata_json["confirmed_from_dry_run"] = True
        metadata_json["confirmation_required"] = False
        metadata_json["confirmed_at"] = utc_now().isoformat()
        metadata_json["valid_rows"] = len(staged_rows)
        metadata_json["invalid_rows"] = invalid_rows
        metadata_json["result_rows"] = sorted(
            result_rows,
            key=lambda row: int(row.get("row_number") or 0),
        )

        import_job = await ImportJobRepository.update_job(
            db=db,
            import_job=import_job,
            job_update=ImportJobUpdate(
                status=final_status,
                total_rows=import_job.total_rows,
                processed_rows=import_job.total_rows,
                successful_rows=successful_rows,
                failed_rows=failed_rows,
                skipped_rows=0,
                completed_at=utc_now(),
                metadata_json=metadata_json,
            ),
        )

        if notify_on_completion:
            if final_status == ImportJobStatus.FAILED:
                await BulkImportCommunicationService.create_failure_notification(
                    db=db,
                    tenant_id=actor.tenant_id,
                    recipient_admin_id=actor.id,
                    import_job=import_job,
                )
            else:
                await BulkImportCommunicationService.create_completion_notification(
                    db=db,
                    tenant_id=actor.tenant_id,
                    recipient_admin_id=actor.id,
                    import_job=import_job,
                )

        if successful_rows > 0:
            await SubscriptionFeatureService.invalidate_tenant_subscription_state(actor.tenant_id)

        await db.commit()
        await AuthIdentityService.invalidate_after_commit(db)

        refreshed_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=import_job.id,
            include_children=True,
        )
        if refreshed_job is None:
            raise NotFoundException(detail="Import job not found after confirmation.")

        return ImportJobDetailResponse.model_validate(refreshed_job)

    @staticmethod
    async def list_jobs(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        skip: int = 0,
        limit: int = 50,
        resource_type: ImportResourceType | None = None,
        status: ImportJobStatus | None = None,
        search: str | None = None,
    ) -> ImportJobListResponse:
        """List tenant import jobs."""

        jobs, total = await ImportJobRepository.list_jobs(
            db=db,
            tenant_id=actor.tenant_id,
            skip=skip,
            limit=limit,
            resource_type=resource_type,
            status=status,
            search=search,
        )

        return ImportJobListResponse(
            items=[ImportJobSummaryResponse.model_validate(job) for job in jobs],
            total=total,
        )

    @staticmethod
    async def get_job(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
    ) -> ImportJobDetailResponse:
        """Return one import job."""

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
            include_children=True,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        return ImportJobDetailResponse.model_validate(import_job)

    @staticmethod
    async def delete_job_history(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
    ) -> None:
        """Delete one non-active import job from tenant-visible history."""

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
            lock=True,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        if import_job.status in {ImportJobStatus.PENDING, ImportJobStatus.PROCESSING}:
            raise BadRequestException(detail="Active import jobs cannot be deleted.")

        if import_job.confirmed_fingerprint:
            raise BadRequestException(
                detail=(
                    "Processed import jobs cannot be deleted because their fingerprint "
                    "protects the school from duplicate student creation."
                )
            )

        await ImportJobRepository.delete_job(db=db, import_job=import_job)
        await db.commit()

    @staticmethod
    async def list_job_errors(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> ImportRowErrorListResponse:
        """Return row errors for one import job."""

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        row_errors, total = await ImportRowErrorRepository.list_errors_by_job(
            db=db,
            tenant_id=actor.tenant_id,
            import_job_id=job_id,
            skip=skip,
            limit=limit,
        )

        return ImportRowErrorListResponse(items=row_errors, total=total)

    @staticmethod
    async def get_result_rows(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
    ) -> tuple[ImportResourceType, list[dict[str, Any]]]:
        """Return persisted result rows for a completed import job."""

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        metadata_json = import_job.metadata_json or {}
        result_rows = metadata_json.get("result_rows") or []

        return import_job.resource_type, list(result_rows)

    @staticmethod
    async def get_error_report_rows(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        job_id: UUID,
    ) -> tuple[ImportResourceType, list[dict[str, Any]]]:
        """Return tenant-scoped row errors for a downloadable error report."""

        import_job = await ImportJobRepository.get_job_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
        )
        if import_job is None:
            raise NotFoundException(detail="Import job not found")

        row_errors, _ = await ImportRowErrorRepository.list_errors_by_job(
            db=db,
            tenant_id=actor.tenant_id,
            import_job_id=job_id,
            skip=0,
            limit=5000,
        )
        return import_job.resource_type, [
            {
                "row_number": row_error.row_number,
                "student_name": " ".join(
                    part
                    for part in [
                        (row_error.normalized_row or {}).get("first_name"),
                        (row_error.normalized_row or {}).get("last_name"),
                    ]
                    if part
                ),
                "field_name": row_error.field_name,
                "error_code": row_error.error_code,
                "error_message": row_error.error_message,
            }
            for row_error in row_errors
        ]

    @staticmethod
    def list_templates(*, file_type: ImportFileType = ImportFileType.XLSX):
        """Return all supported import templates."""

        return list_template_responses(file_type=file_type)

    @staticmethod
    def get_template(
        *,
        resource_type: ImportResourceType,
        file_type: ImportFileType = ImportFileType.XLSX,
    ):
        """Return one supported import template."""

        BulkImportService.ensure_supported_resource_type(resource_type)
        return get_template_response(resource_type=resource_type, file_type=file_type)
