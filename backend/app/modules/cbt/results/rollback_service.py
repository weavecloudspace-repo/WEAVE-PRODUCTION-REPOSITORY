"""Durable, per-student withdrawal of published CBT score contributions.

Only a verified APPLIED publication still owning a DRAFT academic component may
be withdrawn. Every student is processed atomically, with immutable ingestion
history and idempotent rollback operation IDs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor, AuthenticatedCBTServer
from app.modules.cbt.enums import CBTResultIngestionOutcome, CBTResultIngestionStatus
from app.modules.cbt.results.models import CBTResultIngestionBatch, CBTResultIngestionItem
from app.modules.cbt.results.rollback_models import CBTResultRollbackOperation, CBTResultRollbackItem
from app.modules.cbt.results.rollback_schemas import (
    CBTResultRollbackRequest, CBTResultRollbackResponse, CBTResultRollbackItemResponse,
)
from app.modules.cbt.results.service import CBTResultIngestionService
from app.modules.realtime.publisher import RealtimePublisher
from app.modules.student_academics.models import (
    AcademicResultStatus, StudentSubjectResult, StudentAssessmentScore, AssessmentComponent,
)
from app.modules.student_academics.write_guard import ensure_academic_write_window


class CBTResultRollbackService:
    BATCH_SIZE = 25
    SOURCE_TERMINAL = {
        CBTResultIngestionStatus.COMPLETED,
        CBTResultIngestionStatus.COMPLETED_WITH_REJECTIONS,
    }

    @staticmethod
    def fingerprint(payload: CBTResultRollbackRequest) -> str:
        content = {
            "source_batch_id": str(payload.source_batch_id),
            "student_ids": (
                sorted(str(value) for value in payload.student_ids)
                if payload.student_ids is not None else None
            ),
            "reason": payload.reason,
        }
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def publication_conflict(*, parent, score, batch, item, component) -> str | None:
        """Call under the parent and score row locks immediately before withdrawal."""
        if parent.status != AcademicResultStatus.DRAFT:
            return "RESULT_NOT_DRAFT"
        if score is None:
            return "SCORE_MISSING"
        if item.outcome != CBTResultIngestionOutcome.APPLIED:
            return "NOT_ORIGINAL_PUBLICATION"
        if score.cbt_source_batch_id != batch.batch_id:
            return "PUBLICATION_NOT_CURRENT"
        if score.source_exam_id != batch.source_exam_id:
            return "SOURCE_EXAM_CHANGED"
        if score.cbt_score != item.incoming_score:
            return "SCORE_CHANGED"
        if getattr(component, "is_hybrid", False):
            if score.score != score.cbt_score + (score.theory_score or Decimal("0")):
                return "SCORE_CHANGED"
        elif score.score != score.cbt_score or score.theory_score is not None:
            return "SCORE_CHANGED"
        return None

    @classmethod
    async def register(
        cls, db: AsyncSession, *, server: AuthenticatedCBTServer,
        actor: AuthenticatedCBTActor, payload: CBTResultRollbackRequest,
    ) -> CBTResultRollbackResponse:
        if actor.role != "admin" or actor.tenant_id != server.tenant_id:
            raise ForbiddenException("An authorized school administrator is required for CBT rollback")
        digest = cls.fingerprint(payload)
        existing = await db.scalar(select(CBTResultRollbackOperation).where(
            CBTResultRollbackOperation.tenant_id == server.tenant_id,
            CBTResultRollbackOperation.cbt_server_id == server.server_id,
            CBTResultRollbackOperation.operation_id == payload.operation_id,
        ))
        if existing is not None:
            if existing.request_hash != digest:
                raise ConflictException("Rollback operation ID was already used for different targets")
            return await cls.response(db, existing)
        batch = await db.scalar(select(CBTResultIngestionBatch).where(
            CBTResultIngestionBatch.tenant_id == server.tenant_id,
            CBTResultIngestionBatch.cbt_server_id == server.server_id,
            CBTResultIngestionBatch.batch_id == payload.source_batch_id,
        ))
        if batch is None or batch.status not in cls.SOURCE_TERMINAL:
            raise ConflictException("No completed CBT result batch exists for this server and school")
        ingested = list((await db.execute(select(CBTResultIngestionItem).where(
            CBTResultIngestionItem.tenant_id == server.tenant_id,
            CBTResultIngestionItem.ingestion_batch_id == batch.id,
        ))).scalars().all())
        by_student = {row.submitted_student_id: row for row in ingested}
        targets = sorted(
            payload.student_ids if payload.student_ids is not None else
            [key for key, value in by_student.items()
             if value.outcome != CBTResultIngestionOutcome.REJECTED],
            key=str,
        )
        if not targets or any(student not in by_student for student in targets):
            raise ConflictException("Rollback targets must be members of the original batch")
        operation = CBTResultRollbackOperation(
            tenant_id=server.tenant_id, operation_id=payload.operation_id,
            cbt_server_id=server.server_id, actor_id=actor.actor_id,
            source_batch_id=batch.batch_id, request_hash=digest,
            reason=payload.reason, status="pending",
            target_count=len(targets), completed_count=0, rejected_count=0,
        )
        db.add(operation)
        await db.flush()
        db.add_all([
            CBTResultRollbackItem(
                tenant_id=server.tenant_id, rollback_operation_id=operation.id,
                student_id=student, status="pending",
            ) for student in targets
        ])
        await db.commit()
        return await cls.response(db, operation)

    @staticmethod
    async def response(db: AsyncSession, operation: CBTResultRollbackOperation) -> CBTResultRollbackResponse:
        items = list((await db.execute(select(CBTResultRollbackItem).where(
            CBTResultRollbackItem.tenant_id == operation.tenant_id,
            CBTResultRollbackItem.rollback_operation_id == operation.id,
        ).order_by(CBTResultRollbackItem.student_id))).scalars().all())
        return CBTResultRollbackResponse(
            operation_id=operation.operation_id, source_batch_id=operation.source_batch_id,
            status=operation.status, target_count=operation.target_count,
            completed_count=operation.completed_count, rejected_count=operation.rejected_count,
            completed_at=operation.completed_at,
            items=[CBTResultRollbackItemResponse.model_validate(item) for item in items],
        )

    @staticmethod
    async def get_operation(
        db: AsyncSession, *, server: AuthenticatedCBTServer, operation_id: UUID,
    ) -> CBTResultRollbackOperation:
        operation = await db.scalar(select(CBTResultRollbackOperation).where(
            CBTResultRollbackOperation.tenant_id == server.tenant_id,
            CBTResultRollbackOperation.cbt_server_id == server.server_id,
            CBTResultRollbackOperation.operation_id == operation_id,
        ))
        if operation is None:
            raise ConflictException("Rollback operation does not exist for this server")
        return operation

    @classmethod
    async def _withdraw_one(cls, db: AsyncSession, *, operation_pk: UUID, student_id: UUID) -> None:
        # Lock ordering mirrors normal result ingestion (academic lifecycle, parent, score).
        tenant_id = await db.scalar(select(CBTResultRollbackOperation.tenant_id).where(
            CBTResultRollbackOperation.id == operation_pk
        ))
        if tenant_id is None:
            return
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        operation = await db.scalar(select(CBTResultRollbackOperation).where(
            CBTResultRollbackOperation.id == operation_pk,
            CBTResultRollbackOperation.tenant_id == tenant_id,
        ).with_for_update())
        if operation is None:
            await db.rollback()
            return
        item = await db.scalar(select(CBTResultRollbackItem).where(
            CBTResultRollbackItem.tenant_id == tenant_id,
            CBTResultRollbackItem.rollback_operation_id == operation.id,
            CBTResultRollbackItem.student_id == student_id,
        ).with_for_update())
        if item is None or item.status != "pending":
            await db.rollback()
            return

        batch = await db.scalar(select(CBTResultIngestionBatch).where(
            CBTResultIngestionBatch.tenant_id == tenant_id,
            CBTResultIngestionBatch.cbt_server_id == operation.cbt_server_id,
            CBTResultIngestionBatch.batch_id == operation.source_batch_id,
        ))
        source_item = await db.scalar(select(CBTResultIngestionItem).where(
            CBTResultIngestionItem.tenant_id == tenant_id,
            CBTResultIngestionItem.ingestion_batch_id == batch.id,
            CBTResultIngestionItem.submitted_student_id == student_id,
        ))
        error = (
            "NOT_ORIGINAL_PUBLICATION"
            if source_item is None or source_item.outcome != CBTResultIngestionOutcome.APPLIED
            else None
        )
        parent = score = component = None
        if error is None:
            parent = await db.scalar(select(StudentSubjectResult).where(
                StudentSubjectResult.tenant_id == tenant_id,
                StudentSubjectResult.id == source_item.student_subject_result_id,
                StudentSubjectResult.student_id == student_id,
                StudentSubjectResult.academic_session_id == batch.academic_session_id,
                StudentSubjectResult.academic_term_id == batch.academic_term_id,
                StudentSubjectResult.curriculum_subject_id == batch.curriculum_subject_id,
            ).with_for_update())
            if parent is None:
                error = "ACADEMIC_RESULT_MISSING"
        if error is None:
            score = await db.scalar(select(StudentAssessmentScore).where(
                StudentAssessmentScore.tenant_id == tenant_id,
                StudentAssessmentScore.student_subject_result_id == parent.id,
                StudentAssessmentScore.assessment_component_id == batch.assessment_component_id,
            ).with_for_update())
            component = await db.scalar(select(AssessmentComponent).where(
                AssessmentComponent.tenant_id == tenant_id,
                AssessmentComponent.id == batch.assessment_component_id,
                AssessmentComponent.assessment_scheme_id == parent.assessment_scheme_id,
            ))
            if component is None:
                error = "ASSESSMENT_COMPONENT_CHANGED"
            else:
                error = cls.publication_conflict(
                    parent=parent, score=score, batch=batch,
                    item=source_item, component=component,
                )

        if error is None:
            if getattr(component, "is_hybrid", False) and score.theory_score is not None:
                # Keep the theory contribution and frozen CBT allocation.
                score.score = score.theory_score
                score.cbt_score = None
                score.source_exam_id = None
                score.cbt_source_batch_id = None
            else:
                await db.delete(score)
            await db.flush()
            await CBTResultIngestionService._recompute_results(
                db, tenant_id=tenant_id, results=[parent]
            )
            await CBTResultIngestionService._invalidate_report_derivations(
                db, tenant_id=tenant_id, results=[parent]
            )
            RealtimePublisher.defer_to_actor(
                db, event_type="academic.component_score.updated", actor_type="student",
                actor_id=student_id, tenant_id=tenant_id,
                data={"academic_term_id": str(batch.academic_term_id)},
            )
            item.status = "completed"
        else:
            item.status = "rejected"
            item.error_code = error
            item.error_detail = {
                "RESULT_NOT_DRAFT": "Only DRAFT academic results can be rolled back.",
                "PUBLICATION_NOT_CURRENT": "This batch no longer owns the current CBT score.",
                "SCORE_CHANGED": "The CBT score was changed since synchronization.",
            }.get(error, "The current academic component cannot be withdrawn safely.")
        item.processed_at = datetime.now(timezone.utc)
        operation.completed_count += int(item.status == "completed")
        operation.rejected_count += int(item.status == "rejected")
        if operation.completed_count + operation.rejected_count == operation.target_count:
            operation.status = (
                "completed" if operation.rejected_count == 0
                else "rejected" if operation.completed_count == 0
                else "partially_completed"
            )
            operation.completed_at = datetime.now(timezone.utc)
        else:
            operation.status = "processing"
        await db.commit()
        if item.status == "completed":
            await RealtimePublisher.publish_deferred_after_commit(db)

    @classmethod
    async def process_pending(cls, db_factory, *, operation_id: UUID) -> int:
        async with db_factory() as db:
            operation = await db.scalar(select(CBTResultRollbackOperation).where(
                CBTResultRollbackOperation.operation_id == operation_id
            ))
            if operation is None or operation.status not in ("pending", "processing"):
                return 0
            operation_pk = operation.id
            rows = list((await db.execute(select(CBTResultRollbackItem.student_id).where(
                CBTResultRollbackItem.rollback_operation_id == operation_pk,
                CBTResultRollbackItem.status == "pending",
            ).order_by(CBTResultRollbackItem.student_id).limit(cls.BATCH_SIZE))).scalars().all())
            await db.rollback()
        for student_id in rows:
            async with db_factory() as db:
                await cls._withdraw_one(db, operation_pk=operation_pk, student_id=student_id)
        return len(rows)
