"""Write-side orchestration for CBT -> Weave academic result ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.modules.cbt.auth.schemas import AuthenticatedCBTServer
from app.modules.realtime.publisher import RealtimePublisher
from app.modules.cbt.results.models import (
    CBTExamScoreAllocation,
    CBTResultIngestionBatch,
    CBTResultIngestionItem,
)
from app.modules.cbt.enums import (
    CBTResultIngestionOutcome,
    CBTResultIngestionStatus,
)
from app.modules.cbt.results.repository import CBTResultIngestionRepository
from app.modules.cbt.results.schemas import (
    CBTResultBulkError,
    CBTResultBulkRequest,
    CBTResultBulkResponse,
)
from app.modules.classes.repository import AcademicLevelRepository
from app.modules.student_academics.hybrid_scores import component_is_complete
from app.modules.student_academics.assessment_repository import (
    AssessmentRepository,
)
from app.modules.student_academics.curriculum_v2_repository import (
    CurriculumSubjectRepository,
)
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermStatus,
    AssessmentComponent,
    AssessmentScheme,
    AssessmentSchemeStatus,
    StudentAssessmentScore,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import (
    StudentAcademicRepository,
)
from app.modules.student_academics.write_guard import (
    ensure_academic_write_window,
)
from app.modules.students.repository import (
    StudentEnrollmentRepository,
    StudentRepository,
)


_SCORE_QUANTUM = Decimal("0.01")


@dataclass(slots=True)
class _SharedContext:
    """Canonical context shared by every score in one CBT batch."""

    session: AcademicSession
    term: AcademicTerm
    subject_id: UUID
    component: AssessmentComponent
    scheme: AssessmentScheme


class CBTResultIngestionService:
    """
    Apply CBT component scores to canonical Weave academic results.

    CBT owns exam eligibility.

    Weave ingestion owns:
    - tenant isolation;
    - canonical identity validation;
    - historical enrollment resolution;
    - historical teacher-assignment resolution;
    - assessment-component validation;
    - canonical result lifecycle protection;
    - score-conflict protection;
    - immutable ingestion evidence.
    """

    _REPLAYABLE_STATUSES = {
        CBTResultIngestionStatus.COMPLETED,
        CBTResultIngestionStatus.COMPLETED_WITH_REJECTIONS,
        CBTResultIngestionStatus.REJECTED,
    }

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    @staticmethod
    def _can_fill_unpublished_hybrid(
        record: StudentAssessmentScore, *, component: AssessmentComponent,
        cbt_maximum_score: Decimal,
    ) -> bool:
        """Fill CBT contribution only when hybrid theory evidence is intact.

        The existing record is preserved; this is not a general score overwrite.
        """
        return (
            bool(getattr(component, "is_hybrid", False))
            and record.cbt_score is None
            and record.theory_score is not None
            and record.source_exam_id is None
            and record.cbt_source_batch_id is None
            and record.cbt_maximum_score in (None, cbt_maximum_score)
            and record.score == record.theory_score
        )

    @staticmethod
    def _request_hash(payload: CBTResultBulkRequest) -> str:
        """
        Generate a deterministic SHA-256 hash for a logical CBT batch.

        Score ordering does not affect the hash.
        """

        scores = sorted(
            (
                {
                    "student_id": str(item.student_id),
                    "score": (f"{item.score.quantize(_SCORE_QUANTUM):.2f}"),
                }
                for item in payload.scores
            ),
            key=lambda item: item["student_id"],
        )

        canonical_payload = {
            "batch_id": str(payload.batch_id),
            "source_exam_id": str(payload.source_exam_id),
            "academic_session_id": str(payload.academic_session_id),
            "academic_term_id": str(payload.academic_term_id),
            "academic_level_id": str(payload.academic_level_id),
            "curriculum_subject_id": str(payload.curriculum_subject_id),
            "assessment_component_id": str(payload.assessment_component_id),
            "exam_date": payload.exam_date.isoformat(),
            "scores": scores,
        }

        if payload.cbt_maximum_score is not None:
            canonical_payload["cbt_maximum_score"] = (
                f"{payload.cbt_maximum_score.quantize(_SCORE_QUANTUM):.2f}"
            )

        encoded = json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    async def _response_from_existing_batch(
        cls,
        db: AsyncSession,
        batch: CBTResultIngestionBatch,
    ) -> CBTResultBulkResponse:
        """Rebuild the acknowledgement for an idempotent replay."""

        if batch.status not in cls._REPLAYABLE_STATUSES or batch.processed_at is None:
            raise ConflictException("This CBT result batch has not reached a replayable state.")

        items, _ = await CBTResultIngestionRepository.list_items(
            db,
            tenant_id=batch.tenant_id,
            filters={
                "ingestion_batch_id": batch.id,
            },
            limit=max(batch.received_count, 1),
        )

        errors = [
            CBTResultBulkError(
                student_id=item.submitted_student_id,
                code=item.error_code or "REJECTED",
                detail=(item.error_detail or "The CBT result score was rejected."),
            )
            for item in items
            if item.outcome == CBTResultIngestionOutcome.REJECTED
        ]

        return CBTResultBulkResponse(
            batch_id=batch.batch_id,
            source_exam_id=batch.source_exam_id,
            processed_at=batch.processed_at,
            received=batch.received_count,
            applied=batch.applied_count,
            unchanged=batch.unchanged_count,
            rejected=batch.rejected_count,
            errors=errors,
        )

    @classmethod
    async def _handle_existing_batch(
        cls,
        db: AsyncSession,
        *,
        batch: CBTResultIngestionBatch,
        request_hash: str,
    ) -> CBTResultBulkResponse:
        """
        Handle a batch_id that this CBT server has already submitted.
        """

        if batch.request_hash != request_hash:
            raise ConflictException(
                "This CBT batch_id has already been used with a different payload."
            )

        if batch.status in cls._REPLAYABLE_STATUSES:
            return await cls._response_from_existing_batch(
                db,
                batch,
            )

        if batch.status == CBTResultIngestionStatus.PROCESSING:
            raise ConflictException("This CBT result batch is already being processed.")

        raise ConflictException(
            "A previous attempt using this CBT batch_id failed. "
            "Submit the retry using a new batch_id."
        )

    # ------------------------------------------------------------------
    # Shared canonical context
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_shared_context(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        payload: CBTResultBulkRequest,
    ) -> tuple[
        _SharedContext | None,
        tuple[str, str] | None,
    ]:
        """
        Validate only canonical identities and academic write safety.

        This deliberately does NOT re-evaluate whether the subject was
        applicable to the class/department/specialization.

        CBT owns exam eligibility.
        """

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

        if (
            session is None
            or term is None
            or term.academic_session_id != payload.academic_session_id
        ):
            return None, (
                "INVALID_ACADEMIC_PERIOD",
                "The submitted academic session or term is invalid.",
            )

        # CBT may not silently reopen historical canonical result state.
        if (
            not session.is_current
            or session.status != AcademicSessionStatus.OPEN
            or not term.is_current
            or term.status != AcademicTermStatus.OPEN
        ):
            return None, (
                "ACADEMIC_PERIOD_NOT_WRITABLE",
                "CBT results can only modify the current open session and term.",
            )

        if payload.exam_date > date.today():
            return None, (
                "INVALID_EXAM_DATE",
                "The exam date cannot be in the future.",
            )

        if (session.start_date is not None and payload.exam_date < session.start_date) or (
            session.end_date is not None and payload.exam_date > session.end_date
        ):
            return None, (
                "EXAM_DATE_OUTSIDE_SESSION",
                "The exam date falls outside the academic session.",
            )

        if (term.start_date is not None and payload.exam_date < term.start_date) or (
            term.end_date is not None and payload.exam_date > term.end_date
        ):
            return None, (
                "EXAM_DATE_OUTSIDE_TERM",
                "The exam date falls outside the academic term.",
            )

        # Identity check only.
        #
        # Do NOT require ACTIVE because a delayed CBT sync must not
        # become invalid merely because the level was later changed.
        level = await AcademicLevelRepository.get_by_id(
            db,
            tenant_id,
            payload.academic_level_id,
        )

        if level is None:
            return None, (
                "INVALID_ACADEMIC_LEVEL",
                "The submitted academic level does not exist.",
            )

        # Identity check only.
        #
        # Deliberately no:
        # - curriculum level matching;
        # - specialization resolution;
        # - department resolution;
        # - current applicability;
        # - is_active check.
        curriculum_subject = await CurriculumSubjectRepository.get_by_id(
            db,
            tenant_id,
            payload.curriculum_subject_id,
        )

        if curriculum_subject is None:
            return None, (
                "INVALID_CURRICULUM_SUBJECT",
                "The submitted curriculum subject does not exist.",
            )

        component = await AssessmentRepository.get_component(
            db,
            tenant_id,
            payload.assessment_component_id,
        )

        if component is None or not component.is_active:
            return None, (
                "INVALID_ASSESSMENT_COMPONENT",
                "The submitted assessment component is invalid or inactive.",
            )

        allocation = payload.cbt_maximum_score or component.maximum_score
        if allocation > component.maximum_score or (
            not getattr(component, "is_hybrid", False) and allocation != component.maximum_score
        ):
            return None, (
                "INVALID_CBT_ALLOCATION",
                "The CBT allocation must not exceed the component maximum; only hybrid components allow a split.",
            )

        scheme = await AssessmentRepository.get_scheme(
            db,
            tenant_id,
            component.assessment_scheme_id,
        )

        if scheme is None or scheme.status != AssessmentSchemeStatus.ACTIVE:
            return None, (
                "INVALID_ASSESSMENT_SCHEME",
                "The assessment component does not belong to the active assessment scheme.",
            )

        components = await AssessmentRepository.list_components(
            db,
            tenant_id,
            scheme.id,
        )

        maximum_total = sum(
            (item.maximum_score for item in components),
            Decimal("0"),
        )

        if not components or maximum_total != Decimal("100"):
            return None, (
                "INVALID_ASSESSMENT_SCHEME",
                "The active assessment scheme must contain active components totalling 100.",
            )

        return (
            _SharedContext(
                session=session,
                term=term,
                subject_id=curriculum_subject.subject_id,
                component=component,
                scheme=scheme,
            ),
            None,
        )

    # ------------------------------------------------------------------
    # Whole-batch logical rejection
    # ------------------------------------------------------------------

    @staticmethod
    async def _reject_entire_batch(
        db: AsyncSession,
        *,
        batch: CBTResultIngestionBatch,
        payload: CBTResultBulkRequest,
        code: str,
        detail: str,
    ) -> CBTResultBulkResponse:
        """
        Persist a logical rejection affecting every score in the batch.
        """

        processed_at = datetime.now(timezone.utc)

        items = [
            CBTResultIngestionItem(
                tenant_id=batch.tenant_id,
                ingestion_batch_id=batch.id,
                submitted_student_id=item.student_id,
                resolved_teacher_assignment_id=None,
                incoming_score=item.score,
                previous_score=None,
                resulting_score=None,
                student_subject_result_id=None,
                outcome=CBTResultIngestionOutcome.REJECTED,
                error_code=code,
                error_detail=detail,
                processed_at=processed_at,
            )
            for item in payload.scores
        ]

        await CBTResultIngestionRepository.add_items(
            db,
            items,
        )

        batch.applied_count = 0
        batch.unchanged_count = 0
        batch.rejected_count = len(payload.scores)

        batch.status = CBTResultIngestionStatus.REJECTED
        batch.processed_at = processed_at

        batch.batch_error_code = code
        batch.batch_error_detail = detail

        await CBTResultIngestionRepository.save_batch(
            db,
            batch,
        )

        await db.commit()

        return CBTResultBulkResponse(
            batch_id=payload.batch_id,
            source_exam_id=payload.source_exam_id,
            processed_at=processed_at,
            received=len(payload.scores),
            applied=0,
            unchanged=0,
            rejected=len(payload.scores),
            errors=[
                CBTResultBulkError(
                    student_id=item.student_id,
                    code=code,
                    detail=detail,
                )
                for item in payload.scores
            ],
        )

    # ------------------------------------------------------------------
    # Grade calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _find_grade(
        grading_scales,
        total: Decimal,
    ):
        """Resolve one score against already-loaded grading scales."""

        for scale in grading_scales:
            if scale.min_score <= total <= scale.max_score:
                return scale

        return None

    @classmethod
    async def _recompute_results(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        results: list[StudentSubjectResult],
    ) -> None:
        """
        Recompute canonical totals, grade and remark after CBT inserts.

        Partial DRAFT results keep total_score but have no grade/remark.
        """

        if not results:
            return

        component_rows = await StudentAcademicRepository.list_result_component_scores_batch(
            db,
            tenant_id,
            results,
        )

        grading_scales, _ = await StudentAcademicRepository.list_grading_scales(
            db,
            tenant_id,
            limit=1000,
            active_only=True,
        )

        for result in results:
            rows = component_rows.get(
                result.id,
                [],
            )

            total = sum(
                (score.score for _component, score in rows if score is not None),
                Decimal("0"),
            )

            complete = bool(rows) and all(
                component_is_complete(component, score) for component, score in rows
            )

            result.total_score = total

            result.grade = None
            result.remark = None
            result.grading_scale_id = None

            if complete:
                scale = cls._find_grade(
                    grading_scales,
                    total,
                )

                if scale is not None:
                    result.grade = scale.grade
                    result.remark = scale.remark
                    result.grading_scale_id = scale.id

        await StudentAcademicRepository.save_results_batch(
            db,
            results,
        )

    @staticmethod
    async def _invalidate_report_derivations(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        results: list[StudentSubjectResult],
    ) -> None:
        """Invalidate every report/comment derivation touched by applied CBT scores."""

        if not results:
            return

        # Local import keeps the CBT ingestion module independent at import time
        # while reusing the same invalidation contract as manual result writes.
        from app.modules.report_cards.service import ReportCardService

        contexts = {
            (
                result.student_id,
                result.academic_session_id,
                result.academic_term_id,
            )
            for result in results
        }
        for student_id, academic_session_id, academic_term_id in contexts:
            await ReportCardService.mark_outdated_for_score_change(
                db,
                tenant_id,
                student_id,
                academic_session_id,
                academic_term_id,
            )

    # ------------------------------------------------------------------
    # Main ingestion
    # ------------------------------------------------------------------

    @classmethod
    async def ingest(
        cls,
        db: AsyncSession,
        *,
        server: AuthenticatedCBTServer,
        payload: CBTResultBulkRequest,
    ) -> CBTResultBulkResponse:
        """
        Process one CBT component-score batch.

        CBT may fill a missing canonical score.

        CBT may NEVER silently replace an existing differing
        canonical Weave score.
        """

        tenant_id = server.tenant_id

        request_hash = cls._request_hash(payload)

        # --------------------------------------------------------------
        # Idempotency lookup
        # --------------------------------------------------------------

        existing_batch = await CBTResultIngestionRepository.get_by_client_batch_id(
            db,
            tenant_id=tenant_id,
            cbt_server_id=server.server_id,
            batch_id=payload.batch_id,
        )

        if existing_batch is not None:
            return await cls._handle_existing_batch(
                db,
                batch=existing_batch,
                request_hash=request_hash,
            )

        # --------------------------------------------------------------
        # Create forensic batch envelope first
        # --------------------------------------------------------------

        batch = CBTResultIngestionBatch(
            tenant_id=tenant_id,
            cbt_server_id=server.server_id,
            credential_id=server.credential_id,
            batch_id=payload.batch_id,
            source_exam_id=payload.source_exam_id,
            request_hash=request_hash,
            cbt_maximum_score=payload.cbt_maximum_score,
            academic_session_id=payload.academic_session_id,
            academic_term_id=payload.academic_term_id,
            academic_level_id=payload.academic_level_id,
            curriculum_subject_id=payload.curriculum_subject_id,
            assessment_component_id=(payload.assessment_component_id),
            exam_date=payload.exam_date,
            status=CBTResultIngestionStatus.PROCESSING,
            received_count=len(payload.scores),
            applied_count=0,
            unchanged_count=0,
            rejected_count=0,
            processed_at=None,
            batch_error_code=None,
            batch_error_detail=None,
        )

        try:
            await CBTResultIngestionRepository.create_batch(
                db,
                batch,
            )

        except IntegrityError as exc:
            # Another request may have won the same
            # tenant/server/batch_id race.
            await db.rollback()

            winner = await CBTResultIngestionRepository.get_by_client_batch_id(
                db,
                tenant_id=tenant_id,
                cbt_server_id=server.server_id,
                batch_id=payload.batch_id,
            )

            if winner is not None:
                return await cls._handle_existing_batch(
                    db,
                    batch=winner,
                    request_hash=request_hash,
                )

            raise ConflictException("Concurrent CBT batch creation detected.") from exc

        try:
            # ----------------------------------------------------------
            # Academic lifecycle serialization
            # ----------------------------------------------------------

            try:
                await ensure_academic_write_window(
                    db,
                    tenant_id=tenant_id,
                )

            except ConflictException:
                return await cls._reject_entire_batch(
                    db,
                    batch=batch,
                    payload=payload,
                    code="ACADEMIC_WRITES_PAUSED",
                    detail=(
                        "Academic result writes are currently paused "
                        "while the school academic lifecycle is changing."
                    ),
                )

            # ----------------------------------------------------------
            # Shared context
            # ----------------------------------------------------------

            context, context_error = await cls._load_shared_context(
                db,
                tenant_id=tenant_id,
                payload=payload,
            )

            if context_error is not None:
                code, detail = context_error

                return await cls._reject_entire_batch(
                    db,
                    batch=batch,
                    payload=payload,
                    code=code,
                    detail=detail,
                )

            assert context is not None

            # One immutable allocation for all batches of the same local exam.
            # A local server may publish different batches at different times.
            allocation = payload.cbt_maximum_score or context.component.maximum_score
            exam_allocation = (
                await db.execute(
                    select(CBTExamScoreAllocation)
                    .where(
                        CBTExamScoreAllocation.tenant_id == tenant_id,
                        CBTExamScoreAllocation.cbt_server_id == server.server_id,
                        CBTExamScoreAllocation.source_exam_id == payload.source_exam_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if exam_allocation is None:
                db.add(
                    CBTExamScoreAllocation(
                        tenant_id=tenant_id,
                        cbt_server_id=server.server_id,
                        source_exam_id=payload.source_exam_id,
                        academic_session_id=payload.academic_session_id,
                        academic_term_id=payload.academic_term_id,
                        academic_level_id=payload.academic_level_id,
                        curriculum_subject_id=payload.curriculum_subject_id,
                        assessment_component_id=payload.assessment_component_id,
                        component_maximum_score=context.component.maximum_score,
                        cbt_maximum_score=allocation,
                    )
                )
                await db.flush()
            elif (
                exam_allocation.academic_session_id != payload.academic_session_id
                or exam_allocation.academic_term_id != payload.academic_term_id
                or exam_allocation.academic_level_id != payload.academic_level_id
                or exam_allocation.curriculum_subject_id != payload.curriculum_subject_id
                or exam_allocation.assessment_component_id != payload.assessment_component_id
                or exam_allocation.component_maximum_score != context.component.maximum_score
                or exam_allocation.cbt_maximum_score != allocation
            ):
                return await cls._reject_entire_batch(
                    db,
                    batch=batch,
                    payload=payload,
                    code="EXAM_ALLOCATION_CONFLICT",
                    detail="This CBT examination already has a different synchronized academic scope or score allocation.",
                )

            # ----------------------------------------------------------
            # In-memory processing state
            # ----------------------------------------------------------

            audit_items: list[CBTResultIngestionItem] = []

            errors_by_student: dict[
                UUID,
                CBTResultBulkError,
            ] = {}

            finished_students: set[UUID] = set()

            def reject(
                *,
                student_id: UUID,
                incoming_score: Decimal,
                code: str,
                detail: str,
                resolved_teacher_assignment_id: UUID | None = None,
                student_subject_result_id: UUID | None = None,
                previous_score: Decimal | None = None,
                resulting_score: Decimal | None = None,
            ) -> None:
                """
                Record one student-level logical rejection in memory.
                """

                processed_at = datetime.now(timezone.utc)

                audit_items.append(
                    CBTResultIngestionItem(
                        tenant_id=tenant_id,
                        ingestion_batch_id=batch.id,
                        submitted_student_id=student_id,
                        resolved_teacher_assignment_id=(resolved_teacher_assignment_id),
                        incoming_score=incoming_score,
                        previous_score=previous_score,
                        resulting_score=resulting_score,
                        student_subject_result_id=(student_subject_result_id),
                        outcome=(CBTResultIngestionOutcome.REJECTED),
                        error_code=code,
                        error_detail=detail,
                        processed_at=processed_at,
                    )
                )

                errors_by_student[student_id] = CBTResultBulkError(
                    student_id=student_id,
                    code=code,
                    detail=detail,
                )

                finished_students.add(student_id)

            submitted_student_ids = {item.student_id for item in payload.scores}

            # ----------------------------------------------------------
            # 1. Resolve tenant-owned students
            # ----------------------------------------------------------

            students = await StudentRepository.get_by_ids(
                db,
                tenant_id,
                submitted_student_ids,
            )

            known_student_ids = set(students)

            # ----------------------------------------------------------
            # 2. Resolve historical placement on exam_date
            # ----------------------------------------------------------

            enrollments = await StudentEnrollmentRepository.get_for_students_on_date(
                db,
                tenant_id,
                known_student_ids,
                payload.academic_session_id,
                payload.exam_date,
                lock=True,
            )

            for item in payload.scores:
                if item.student_id not in students:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        code="STUDENT_NOT_FOUND",
                        detail=("The submitted student does not exist within this tenant."),
                    )
                    continue

                enrollment = enrollments.get(item.student_id)

                if enrollment is None:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        code="ENROLLMENT_NOT_FOUND",
                        detail=(
                            "The student had no authoritative enrollment covering the exam date."
                        ),
                    )
                    continue

                # This is NOT curriculum eligibility.
                #
                # It merely proves the CBT batch's claimed level agrees
                # with the student's historical placement.
                if enrollment.academic_level_id != payload.academic_level_id:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        code="ACADEMIC_LEVEL_MISMATCH",
                        detail=(
                            "The student's exam-date enrollment "
                            "does not match the academic level "
                            "submitted by CBT."
                        ),
                    )
                    continue

                if enrollment.class_id is None:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        code="CLASS_NOT_FOUND",
                        detail=("The student's exam-date enrollment does not contain a class."),
                    )

            # ----------------------------------------------------------
            # NO CURRICULUM ELIGIBILITY RESOLUTION HERE
            # ----------------------------------------------------------
            #
            # Deliberately absent:
            #
            # resolve_student_subjects(...)
            # resolve_class_subjects(...)
            # resolve_subject_eligible_classes(...)
            # department checks
            # specialization checks
            #
            # CBT already determined whether the student was entitled
            # to sit this exam.

            # ----------------------------------------------------------
            # 3. Resolve teacher ownership on exam_date
            # ----------------------------------------------------------

            remaining_class_ids = {
                enrollments[item.student_id].class_id
                for item in payload.scores
                if item.student_id not in finished_students
                and enrollments[item.student_id].class_id is not None
            }

            assignments = (
                await StudentAcademicRepository.get_teacher_assignments_for_classes_on_date(
                    db,
                    tenant_id,
                    remaining_class_ids,
                    payload.curriculum_subject_id,
                    payload.exam_date,
                    lock=True,
                )
            )

            for item in payload.scores:
                if item.student_id in finished_students:
                    continue

                enrollment = enrollments[item.student_id]

                assignment = assignments.get(enrollment.class_id)

                if assignment is None:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        code="TEACHER_ASSIGNMENT_NOT_FOUND",
                        detail=(
                            "No teacher assignment covered this class and subject on the exam date."
                        ),
                    )
                    continue

                if item.score > allocation:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        resolved_teacher_assignment_id=(assignment.id),
                        code="SCORE_EXCEEDS_COMPONENT_MAXIMUM",
                        detail=(f"{context.component.name} score cannot exceed {allocation}."),
                    )

            candidate_student_ids = {
                item.student_id
                for item in payload.scores
                if item.student_id not in finished_students
            }

            # ----------------------------------------------------------
            # 4. Lock/load existing canonical result parents
            # ----------------------------------------------------------

            existing_results = await StudentAcademicRepository.get_results_by_scope_batch(
                db,
                tenant_id,
                candidate_student_ids,
                payload.curriculum_subject_id,
                payload.academic_session_id,
                payload.academic_term_id,
                lock=True,
            )

            existing_result_ids = {result.id for result in existing_results.values()}

            # ----------------------------------------------------------
            # 5. Lock/load target component scores
            # ----------------------------------------------------------

            existing_component_scores = await StudentAcademicRepository.get_component_scores_batch(
                db,
                tenant_id,
                existing_result_ids,
                payload.assessment_component_id,
                lock=True,
            )

            apply_existing: set[UUID] = set()
            restore_hybrid: dict[UUID, StudentAssessmentScore] = {}
            create_new: set[UUID] = set()

            # ----------------------------------------------------------
            # 6. Classify each candidate
            # ----------------------------------------------------------

            for item in payload.scores:
                if item.student_id in finished_students:
                    continue

                enrollment = enrollments[item.student_id]

                assignment = assignments[enrollment.class_id]

                result = existing_results.get(item.student_id)

                # No canonical result yet.
                if result is None:
                    create_new.add(item.student_id)
                    continue

                previous_component = existing_component_scores.get(result.id)

                previous_score = (
                    previous_component.score if previous_component is not None else None
                )

                # CBT only writes DRAFT canonical state.
                if result.status != AcademicResultStatus.DRAFT:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        resolved_teacher_assignment_id=(assignment.id),
                        student_subject_result_id=result.id,
                        previous_score=previous_score,
                        resulting_score=previous_score,
                        code="RESULT_NOT_DRAFT",
                        detail=(
                            "CBT cannot modify a submitted, approved or locked canonical result."
                        ),
                    )
                    continue

                # Existing parent result must use the same scheme as
                # the CBT component being ingested.
                if result.assessment_scheme_id != context.scheme.id:
                    reject(
                        student_id=item.student_id,
                        incoming_score=item.score,
                        resolved_teacher_assignment_id=(assignment.id),
                        student_subject_result_id=result.id,
                        previous_score=previous_score,
                        resulting_score=previous_score,
                        code="ASSESSMENT_SCHEME_CONFLICT",
                        detail=("The canonical result belongs to a different assessment scheme."),
                    )
                    continue

                # ------------------------------------------------------
                # Existing target component
                # ------------------------------------------------------

                if previous_component is not None:
                    if cls._can_fill_unpublished_hybrid(
                        previous_component, component=context.component,
                        cbt_maximum_score=allocation,
                    ):
                        # A withdrawn CBT contribution leaves the theory mark
                        # in place. Restore just the missing CBT portion.
                        restore_hybrid[item.student_id] = previous_component
                        apply_existing.add(item.student_id)
                        continue
                    # Exact duplicate = idempotent at score level.
                    if (
                        (
                            previous_component.cbt_score
                            if previous_component.cbt_score is not None
                            else previous_component.score
                        )
                        == item.score
                        and (previous_component.source_exam_id in (None, payload.source_exam_id))
                        and (previous_component.cbt_maximum_score in (None, allocation))
                        and (
                            not getattr(context.component, "is_hybrid", False)
                            or previous_component.cbt_score is not None
                        )
                    ):
                        processed_at = datetime.now(timezone.utc)

                        audit_items.append(
                            CBTResultIngestionItem(
                                tenant_id=tenant_id,
                                ingestion_batch_id=batch.id,
                                submitted_student_id=(item.student_id),
                                resolved_teacher_assignment_id=(assignment.id),
                                incoming_score=item.score,
                                previous_score=(previous_component.score),
                                resulting_score=(previous_component.score),
                                student_subject_result_id=(result.id),
                                outcome=(CBTResultIngestionOutcome.UNCHANGED),
                                error_code=None,
                                error_detail=None,
                                processed_at=processed_at,
                            )
                        )

                        finished_students.add(item.student_id)

                    # Different existing canonical value:
                    # ADMINISTRATIVE/CANONICAL DECISION WINS.
                    else:
                        reject(
                            student_id=item.student_id,
                            incoming_score=item.score,
                            resolved_teacher_assignment_id=(assignment.id),
                            student_subject_result_id=(result.id),
                            previous_score=(previous_component.score),
                            resulting_score=(previous_component.score),
                            code="SCORE_CONFLICT",
                            detail=(
                                "A different canonical Weave "
                                "score already exists for this "
                                "assessment component."
                            ),
                        )

                    continue

                # Existing result, but this component is absent.
                apply_existing.add(item.student_id)

            # ----------------------------------------------------------
            # 7. Create missing StudentSubjectResult parents
            # ----------------------------------------------------------

            new_results: list[StudentSubjectResult] = []

            for item in payload.scores:
                if item.student_id not in create_new:
                    continue

                enrollment = enrollments[item.student_id]

                assignment = assignments[enrollment.class_id]

                new_results.append(
                    StudentSubjectResult(
                        tenant_id=tenant_id,
                        student_id=item.student_id,
                        class_id=enrollment.class_id,
                        subject_id=context.subject_id,
                        teacher_membership_id=(assignment.teacher_membership_id),
                        curriculum_subject_id=(payload.curriculum_subject_id),
                        teacher_assignment_id=assignment.id,
                        student_enrollment_id=enrollment.id,
                        academic_session_id=(payload.academic_session_id),
                        academic_term_id=(payload.academic_term_id),
                        grading_scale_id=None,
                        assessment_scheme_id=context.scheme.id,
                        total_score=Decimal("0"),
                        grade=None,
                        remark=None,
                        status=AcademicResultStatus.DRAFT,
                        recorded_by_actor_type="cbt_server",
                        recorded_by_actor_id=server.server_id,
                    )
                )

            await StudentAcademicRepository.save_results_batch(
                db,
                new_results,
            )

            new_results_by_student = {result.student_id: result for result in new_results}

            all_results = {
                **existing_results,
                **new_results_by_student,
            }

            # ----------------------------------------------------------
            # 8. Insert only genuinely missing component scores
            # ----------------------------------------------------------

            applied_student_ids = apply_existing | create_new

            score_by_student = {item.student_id: item for item in payload.scores}

            new_component_scores: list[StudentAssessmentScore] = []

            for student_id in applied_student_ids:
                result = all_results[student_id]
                incoming = score_by_student[student_id]
                if student_id in restore_hybrid:
                    existing = restore_hybrid[student_id]
                    existing.cbt_score = incoming.score
                    existing.cbt_maximum_score = allocation
                    existing.source_exam_id = payload.source_exam_id
                    existing.cbt_source_batch_id = payload.batch_id
                    existing.score = incoming.score + existing.theory_score
                    continue

                new_component_scores.append(
                    StudentAssessmentScore(
                        tenant_id=tenant_id,
                        student_subject_result_id=result.id,
                        assessment_component_id=(payload.assessment_component_id),
                        score=incoming.score,
                        cbt_score=incoming.score,
                        cbt_maximum_score=allocation,
                        source_exam_id=payload.source_exam_id,
                        cbt_source_batch_id=payload.batch_id,
                    )
                )

            await StudentAcademicRepository.add_component_scores_batch(
                db,
                new_component_scores,
            )

            # ----------------------------------------------------------
            # 9. Recompute affected result totals / grades
            # ----------------------------------------------------------

            changed_results = [all_results[student_id] for student_id in applied_student_ids]

            await cls._recompute_results(
                db,
                tenant_id=tenant_id,
                results=changed_results,
            )
            await cls._invalidate_report_derivations(
                db,
                tenant_id=tenant_id,
                results=changed_results,
            )

            # ----------------------------------------------------------
            # 10. APPLIED forensic items
            # ----------------------------------------------------------

            for student_id in applied_student_ids:
                incoming = score_by_student[student_id]
                enrollment = enrollments[student_id]

                assignment = assignments[enrollment.class_id]

                result = all_results[student_id]

                audit_items.append(
                    CBTResultIngestionItem(
                        tenant_id=tenant_id,
                        ingestion_batch_id=batch.id,
                        submitted_student_id=student_id,
                        resolved_teacher_assignment_id=(assignment.id),
                        incoming_score=incoming.score,
                        previous_score=None,
                        resulting_score=incoming.score,
                        student_subject_result_id=result.id,
                        outcome=(CBTResultIngestionOutcome.APPLIED),
                        error_code=None,
                        error_detail=None,
                        processed_at=datetime.now(timezone.utc),
                    )
                )

                finished_students.add(student_id)

            # ----------------------------------------------------------
            # 11. Persist forensic item ledger
            # ----------------------------------------------------------

            await CBTResultIngestionRepository.add_items(
                db,
                audit_items,
            )

            applied_count = sum(
                item.outcome == CBTResultIngestionOutcome.APPLIED for item in audit_items
            )

            unchanged_count = sum(
                item.outcome == CBTResultIngestionOutcome.UNCHANGED for item in audit_items
            )

            rejected_count = sum(
                item.outcome == CBTResultIngestionOutcome.REJECTED for item in audit_items
            )

            processed_at = datetime.now(timezone.utc)

            # ----------------------------------------------------------
            # 12. Finalize batch
            # ----------------------------------------------------------

            if rejected_count == len(payload.scores):
                batch.status = CBTResultIngestionStatus.REJECTED

            elif rejected_count:
                batch.status = CBTResultIngestionStatus.COMPLETED_WITH_REJECTIONS

            else:
                batch.status = CBTResultIngestionStatus.COMPLETED

            batch.applied_count = applied_count
            batch.unchanged_count = unchanged_count
            batch.rejected_count = rejected_count
            batch.processed_at = processed_at

            await CBTResultIngestionRepository.save_batch(
                db,
                batch,
            )

            # Canonical results + ledger commit together.
            await db.commit()

            # Only newly applied scores are announced. Actor-specific signals
            # contain no marks; clients re-read the authorized subject cards.
            for student_id in applied_student_ids:
                RealtimePublisher.defer_to_actor(
                    db,
                    event_type="academic.component_score.updated",
                    actor_type="student",
                    actor_id=student_id,
                    tenant_id=tenant_id,
                    data={"academic_term_id": str(payload.academic_term_id)},
                )

            errors = [
                errors_by_student[item.student_id]
                for item in payload.scores
                if item.student_id in errors_by_student
            ]

            return CBTResultBulkResponse(
                batch_id=payload.batch_id,
                source_exam_id=payload.source_exam_id,
                processed_at=processed_at,
                received=len(payload.scores),
                applied=applied_count,
                unchanged=unchanged_count,
                rejected=rejected_count,
                errors=errors,
            )

        except IntegrityError as exc:
            # Includes concurrent parent/component creation races.
            #
            # Roll everything back. The same CBT payload can safely
            # retry because no partial canonical write commits.
            await db.rollback()

            raise ConflictException(
                "Concurrent modification of CBT academic results detected. Retry the batch."
            ) from exc

        except Exception:
            await db.rollback()
            raise
