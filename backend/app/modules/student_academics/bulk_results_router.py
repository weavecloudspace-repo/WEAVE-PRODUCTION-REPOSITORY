from __future__ import annotations

import uuid
from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_tenant_admin
from app.core.exceptions import ConflictException, NotFoundException
from app.modules.report_cards.service import ReportCardService
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicResultStatus,
    AcademicSessionStatus,
    AcademicTermStatus,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.service import StudentAcademicService
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import FeatureCode
from app.modules.tenant_admins.models import TenantAdmin

admin_router = APIRouter(
    prefix="/tenant-admin/academics/results/bulk",
    tags=["Tenant Admin Result Bulk Actions"],
)

CurrentTenantAdmin: TypeAlias = Annotated[
    TenantAdmin,
    Depends(get_current_tenant_admin),
]


async def _ensure_paid_bulk_academics(db: DbSession, tenant_id: uuid.UUID) -> None:
    await SubscriptionFeatureService.ensure_feature_enabled(
        db=db,
        tenant_id=tenant_id,
        feature=FeatureCode.BULK_ACADEMIC_OPERATIONS,
    )


class ResultBulkScope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    class_id: uuid.UUID
    academic_session_id: uuid.UUID
    academic_term_id: uuid.UUID
    teacher_assignment_id: uuid.UUID | None = None


class AdminBulkTransitionRequest(ResultBulkScope):
    target_status: Literal["submitted", "approved", "locked"]
    confirmation: Literal["BULK_TRANSITION_RESULTS"]


class AdminBulkReopenRequest(ResultBulkScope):
    confirmation: Literal["BULK_REOPEN_RESULTS"]
    reason: str = Field(min_length=3, max_length=1000)


class BulkSkippedItem(BaseModel):
    id: uuid.UUID
    reason: str


class BulkResultActionResponse(BaseModel):
    matched: int
    processed: int
    skipped: list[BulkSkippedItem]


class BulkResultLifecycleService:
    _PREVIOUS_STATUS = {
        AcademicResultStatus.SUBMITTED: AcademicResultStatus.DRAFT,
        AcademicResultStatus.APPROVED: AcademicResultStatus.SUBMITTED,
        AcademicResultStatus.LOCKED: AcademicResultStatus.APPROVED,
    }

    @staticmethod
    async def _validate_period(
        db: DbSession,
        tenant_id: uuid.UUID,
        payload: ResultBulkScope,
    ) -> None:
        session = await StudentAcademicRepository.get_academic_session_by_id(
            db,
            tenant_id,
            payload.academic_session_id,
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db,
            tenant_id,
            payload.academic_term_id,
        )
        if session is None or term is None or term.academic_session_id != session.id:
            raise NotFoundException("Academic session or term is invalid.")
        if not session.is_current or session.status != AcademicSessionStatus.OPEN:
            raise ConflictException("Results can only be changed in the current open session.")
        if not term.is_current or term.status != AcademicTermStatus.OPEN:
            raise ConflictException("Results can only be changed in the current open term.")

    @staticmethod
    async def _load_scope(
        db: DbSession,
        *,
        tenant_id: uuid.UUID,
        payload: ResultBulkScope,
        result_status: AcademicResultStatus,
        teacher_id: uuid.UUID | None = None,
    ) -> list[StudentSubjectResult]:
        filters = [
            StudentSubjectResult.tenant_id == tenant_id,
            StudentSubjectResult.class_id == payload.class_id,
            StudentSubjectResult.academic_session_id == payload.academic_session_id,
            StudentSubjectResult.academic_term_id == payload.academic_term_id,
            StudentSubjectResult.status == result_status,
        ]
        if payload.teacher_assignment_id is not None:
            filters.append(
                StudentSubjectResult.teacher_assignment_id == payload.teacher_assignment_id
            )
        if teacher_id is not None:
            filters.append(StudentSubjectResult.teacher_membership_id == teacher_id)
        rows = (
            (
                await db.execute(
                    select(StudentSubjectResult)
                    .where(*filters)
                    .order_by(StudentSubjectResult.created_at.asc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def _audit(
        db: DbSession,
        *,
        result: StudentSubjectResult,
        action: str,
        previous_status: AcademicResultStatus,
        new_status: AcademicResultStatus,
        acting_admin_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> None:
        await StudentAcademicRepository.add_academic_lifecycle_audit(
            db,
            AcademicLifecycleAudit(
                tenant_id=result.tenant_id,
                entity_type="student_result",
                entity_id=result.id,
                action=action,
                previous_status=previous_status.value,
                new_status=new_status.value,
                acting_admin_id=acting_admin_id,
                reason=reason,
            ),
        )

    @staticmethod
    async def admin_transition(
        db: DbSession,
        actor: TenantAdmin,
        payload: AdminBulkTransitionRequest,
    ) -> BulkResultActionResponse:
        await BulkResultLifecycleService._validate_period(
            db,
            actor.tenant_id,
            payload,
        )
        target = AcademicResultStatus(payload.target_status)
        source = BulkResultLifecycleService._PREVIOUS_STATUS[target]
        results = await BulkResultLifecycleService._load_scope(
            db,
            tenant_id=actor.tenant_id,
            payload=payload,
            result_status=source,
        )
        processed = 0
        skipped: list[BulkSkippedItem] = []
        action = {
            AcademicResultStatus.SUBMITTED: "bulk_submit",
            AcademicResultStatus.APPROVED: "bulk_approve",
            AcademicResultStatus.LOCKED: "bulk_lock",
        }[target]

        for result in results:
            result_id = result.id
            try:
                async with db.begin_nested():
                    StudentAcademicService._ensure_forward_result_transition(
                        result.status,
                        target,
                    )
                    if target == AcademicResultStatus.SUBMITTED:
                        await StudentAcademicService._ensure_result_complete(db, result)
                    if (
                        target
                        in {
                            AcademicResultStatus.APPROVED,
                            AcademicResultStatus.LOCKED,
                        }
                        and not result.grade
                    ):
                        raise ConflictException(
                            "Result must have a grade before approval or locking."
                        )
                    previous = result.status
                    result.status = target
                    StudentAcademicService._apply_result_lifecycle_metadata(
                        result,
                        actor=actor,
                        next_status=target,
                    )
                    await StudentAcademicRepository.upsert_result(db, result)
                    await BulkResultLifecycleService._audit(
                        db,
                        result=result,
                        action=action,
                        previous_status=previous,
                        new_status=target,
                        acting_admin_id=actor.id,
                    )
                processed += 1
            except Exception as exc:
                skipped.append(BulkSkippedItem(id=result_id, reason=str(exc)))

        await db.commit()
        return BulkResultActionResponse(
            matched=len(results),
            processed=processed,
            skipped=skipped,
        )

    async def admin_reopen(
        db: DbSession,
        actor: TenantAdmin,
        payload: AdminBulkReopenRequest,
    ) -> BulkResultActionResponse:
        await BulkResultLifecycleService._validate_period(
            db,
            actor.tenant_id,
            payload,
        )
        results = await BulkResultLifecycleService._load_scope(
            db,
            tenant_id=actor.tenant_id,
            payload=payload,
            result_status=AcademicResultStatus.LOCKED,
        )
        processed = 0
        skipped: list[BulkSkippedItem] = []

        for result in results:
            try:
                async with db.begin_nested():
                    await ReportCardService.mark_outdated_for_score_change(
                        db,
                        result.tenant_id,
                        result.student_id,
                        result.academic_session_id,
                        result.academic_term_id,
                    )
                    previous = result.status
                    result.status = AcademicResultStatus.DRAFT
                    result.submitted_at = None
                    result.submitted_by_actor_type = None
                    result.submitted_by_actor_id = None
                    result.approved_at = None
                    result.approved_by_admin_id = None
                    result.locked_at = None
                    result.locked_by_admin_id = None
                    await StudentAcademicRepository.upsert_result(db, result)
                    await BulkResultLifecycleService._audit(
                        db,
                        result=result,
                        action="bulk_reopen",
                        previous_status=previous,
                        new_status=AcademicResultStatus.DRAFT,
                        acting_admin_id=actor.id,
                        reason=payload.reason,
                    )
                processed += 1
            except Exception as exc:
                skipped.append(BulkSkippedItem(id=result.id, reason=str(exc)))

        await db.commit()
        return BulkResultActionResponse(
            matched=len(results),
            processed=processed,
            skipped=skipped,
        )


@admin_router.post("/transition", response_model=BulkResultActionResponse)
async def bulk_transition_results(
    payload: AdminBulkTransitionRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> BulkResultActionResponse:
    await _ensure_paid_bulk_academics(db, current_admin.tenant_id)
    return await BulkResultLifecycleService.admin_transition(
        db,
        current_admin,
        payload,
    )


@admin_router.post("/reopen", response_model=BulkResultActionResponse)
async def bulk_reopen_results(
    payload: AdminBulkReopenRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> BulkResultActionResponse:
    await _ensure_paid_bulk_academics(db, current_admin.tenant_id)
    return await BulkResultLifecycleService.admin_reopen(
        db,
        current_admin,
        payload,
    )
