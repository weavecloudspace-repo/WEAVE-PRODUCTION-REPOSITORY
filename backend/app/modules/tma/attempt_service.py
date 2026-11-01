"""Simple one-attempt TMA student workflow: list, start, autosave, submit."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache.events import flush_cache_invalidation_events

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.models import AcademicTermStatus
from app.modules.students.models import Student
from app.modules.students.repository import StudentEnrollmentRepository
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.tma.authorization import TMAAuthorizationService
from app.modules.tma.grading_service import TMAGradingService
from app.modules.tma.models import TMAAssignmentStatus, TMAAttempt, TMAAttemptStatus, TMAParticipant
from app.modules.tma.repository import (
    TMAAnswerRepository,
    TMAAssignmentRepository,
    TMAAttemptRepository,
    TMAParticipantRepository,
    TMAQuestionRepository,
    TMARevisionRepository,
)
from app.modules.tma.schemas import (
    TMAAnswerResponse,
    TMAAnswerSaveRequest,
    TMAAnswerSaveResponse,
    TMAAttemptResponse,
    TMAStartResponse,
    TMAStudentAssignmentResponse,
    TMAStudentOptionResponse,
    TMAStudentQuestionResponse,
    TMASubmitResponse,
)


class TMAAttemptService:
    @staticmethod
    async def _active_assignment(
        db: AsyncSession,
        *,
        student: Student,
        assignment_id: uuid.UUID,
        lock: bool = False,
    ):
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            student.tenant_id,
            assignment_id,
            lock=lock,
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        if assignment.status != TMAAssignmentStatus.ACTIVE:
            raise ConflictException("This assignment is not active.")
        await TMAAuthorizationService.require_open_term(db, assignment)
        enrollment = await TMAAuthorizationService.require_student_eligibility(
            db,
            student=student,
            assignment=assignment,
        )
        revision = await TMARevisionRepository.get_by_number(
            db,
            student.tenant_id,
            assignment.id,
            assignment.current_revision_number,
        )
        if revision is None or revision.published_at is None or revision.invalidated_at is not None:
            raise ConflictException("The assignment revision is not published.")
        return assignment, revision, enrollment

    @staticmethod
    async def list_available_assignments(
        db: AsyncSession,
        *,
        student: Student,
    ) -> list[TMAStudentAssignmentResponse]:
        term = await StudentAcademicRepository.get_current_term(db, student.tenant_id)
        if term is None or term.status != AcademicTermStatus.OPEN or not term.is_current:
            return []
        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db,
            student.tenant_id,
            student.id,
            term.academic_session_id,
        )
        if enrollment is None:
            return []
        allowed = {
            row.curriculum_subject_id
            for row in await CurriculumResolutionService.resolve_student_subjects(
                db,
                tenant_id=student.tenant_id,
                student_id=student.id,
                academic_term_id=term.id,
            )
        }
        rows, _ = await TMAAssignmentRepository.list_for_scope(
            db,
            student.tenant_id,
            academic_term_id=term.id,
            academic_level_id=enrollment.academic_level_id,
            status=TMAAssignmentStatus.ACTIVE,
            limit=100,
        )
        history = await TMAParticipantRepository.list_for_student(
            db,
            student.tenant_id,
            student.id,
        )
        attempts = await TMAAttemptRepository.list_for_participants(
            db,
            student.tenant_id,
            {participant.id for participant in history},
        )
        revisions = {participant.revision_id: participant for participant in history}
        scheme = await AssessmentRepository.get_active_scheme(db, student.tenant_id)
        items = []
        for assignment in rows:
            if assignment.curriculum_subject_id not in allowed:
                continue
            revision = await TMARevisionRepository.get_by_number(
                db,
                student.tenant_id,
                assignment.id,
                assignment.current_revision_number,
            )
            if revision is None or revision.published_at is None or revision.invalidated_at:
                continue
            component = await AssessmentRepository.get_component(
                db,
                student.tenant_id,
                assignment.assessment_component_id,
            )
            if component is None or scheme is None or component.assessment_scheme_id != scheme.id:
                continue
            participant = revisions.get(revision.id)
            attempt = attempts.get(participant.id) if participant else None
            items.append(
                TMAStudentAssignmentResponse(
                    assignment_id=assignment.id,
                    academic_term_id=assignment.academic_term_id,
                    curriculum_subject_id=assignment.curriculum_subject_id,
                    assessment_component_id=assignment.assessment_component_id,
                    status=assignment.status,
                    attempt_status=attempt.status if attempt else None,
                    closes_at=assignment.closes_at,
                    can_start_or_resume=attempt is None
                    or attempt.status == TMAAttemptStatus.IN_PROGRESS,
                    component_maximum_score=component.maximum_score,
                )
            )
        return items

    @staticmethod
    async def _load_owned_attempt(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
        lock: bool = False,
    ):
        attempt = await TMAAttemptRepository.get_by_id(
            db,
            student.tenant_id,
            attempt_id,
            lock=lock,
        )
        if attempt is None:
            raise NotFoundException("Attempt not found.")
        participant = next(
            (
                row
                for row in await TMAParticipantRepository.list_for_student(
                    db,
                    student.tenant_id,
                    student.id,
                )
                if row.id == attempt.participant_id
            ),
            None,
        )
        if participant is None or participant.revision_id != attempt.revision_id:
            raise NotFoundException("Attempt not found.")
        revision = await TMARevisionRepository.get_by_id(
            db,
            student.tenant_id,
            attempt.revision_id,
        )
        if revision is None:
            raise NotFoundException("Assignment revision not found.")
        return attempt, participant, revision

    @staticmethod
    async def _build_start_response(
        db: AsyncSession,
        student: Student,
        attempt: TMAAttempt,
    ) -> TMAStartResponse:
        questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            student.tenant_id,
            attempt.revision_id,
        )

        # Deterministic order makes reconnect/resume stable, without storing
        # per-user order or leaking correct-option fields.
        def order_key(identifier: uuid.UUID) -> bytes:
            return hashlib.sha256(f"{attempt.id}:{identifier}".encode()).digest()

        shuffled = sorted(questions, key=lambda pair: order_key(pair[0].id))
        student_questions = [
            TMAStudentQuestionResponse(
                id=question.id,
                question_text=question.question_text,
                image_asset_id=question.image_asset_id,
                options=[
                    TMAStudentOptionResponse.model_validate(option)
                    for option in sorted(options, key=lambda item: order_key(item.id))
                ],
            )
            for question, options in shuffled
        ]
        answers = await TMAAnswerRepository.list_for_attempt(
            db,
            student.tenant_id,
            attempt.id,
        )
        return TMAStartResponse(
            attempt=TMAAttemptResponse.model_validate(attempt),
            questions=student_questions,
            saved_answers=[TMAAnswerResponse.model_validate(row) for row in answers],
        )

    @staticmethod
    async def start_or_resume_attempt(
        db: AsyncSession,
        *,
        student: Student,
        assignment_id: uuid.UUID,
    ) -> TMAStartResponse:
        assignment, revision, enrollment = await TMAAttemptService._active_assignment(
            db,
            student=student,
            assignment_id=assignment_id,
            lock=True,
        )
        if enrollment.class_id is None:
            raise ForbiddenException("You must have a current classroom.")
        participant = await TMAParticipantRepository.get_by_revision_student(
            db,
            student.tenant_id,
            revision.id,
            student.id,
        )
        if participant is None:
            await TMAParticipantRepository.insert_missing(
                db,
                student.tenant_id,
                [
                    TMAParticipant(
                        tenant_id=student.tenant_id,
                        revision_id=revision.id,
                        student_id=student.id,
                        student_enrollment_id=enrollment.id,
                        class_id=enrollment.class_id,
                    )
                ],
            )
            participant = await TMAParticipantRepository.get_by_revision_student(
                db,
                student.tenant_id,
                revision.id,
                student.id,
            )
        if participant is None:
            raise ConflictException("Unable to register participation.")
        attempt = await TMAAttemptRepository.create_if_missing(
            db,
            student.tenant_id,
            participant.id,
            revision.id,
        )
        if attempt.status == TMAAttemptStatus.SUBMITTED:
            raise ConflictException("This assignment has already been submitted.")
        try:
            await db.commit()
            await flush_cache_invalidation_events(db)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Attempt was started concurrently. Reload it.") from exc
        await db.refresh(attempt)
        return await TMAAttemptService._build_start_response(db, student, attempt)

    @staticmethod
    async def get_attempt(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
    ) -> TMAStartResponse:
        attempt, _, revision = await TMAAttemptService._load_owned_attempt(
            db,
            student=student,
            attempt_id=attempt_id,
        )
        await TMAAttemptService._active_assignment(
            db,
            student=student,
            assignment_id=revision.assignment_id,
            lock=True,
        )
        if attempt.status != TMAAttemptStatus.IN_PROGRESS:
            raise ConflictException("Assignment already submitted.")
        return await TMAAttemptService._build_start_response(db, student, attempt)

    @staticmethod
    async def save_answer(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
        payload: TMAAnswerSaveRequest,
    ) -> TMAAnswerSaveResponse:
        attempt, _, revision = await TMAAttemptService._load_owned_attempt(
            db,
            student=student,
            attempt_id=attempt_id,
            lock=True,
        )
        await TMAAttemptService._active_assignment(
            db,
            student=student,
            assignment_id=revision.assignment_id,
            lock=True,
        )
        if attempt.status != TMAAttemptStatus.IN_PROGRESS:
            raise ConflictException("Submitted answers cannot be changed.")
        questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            student.tenant_id,
            revision.id,
        )
        found = next(
            (options for question, options in questions if question.id == payload.question_id),
            None,
        )
        if found is None:
            raise NotFoundException("Question does not belong to this attempt.")
        if payload.selected_option_id is None:
            await TMAAnswerRepository.clear_selection(
                db,
                student.tenant_id,
                attempt.id,
                payload.question_id,
            )
        else:
            if payload.selected_option_id not in {option.id for option in found}:
                raise ConflictException("The selected option belongs to another question.")
            await TMAAnswerRepository.save_selection(
                db,
                student.tenant_id,
                attempt.id,
                attempt.revision_id,
                payload.question_id,
                payload.selected_option_id,
            )
        await db.commit()
        await flush_cache_invalidation_events(db)
        return TMAAnswerSaveResponse(
            attempt_id=attempt.id,
            question_id=payload.question_id,
            selected_option_id=payload.selected_option_id,
            saved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    async def submit_attempt(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
    ) -> TMASubmitResponse:
        attempt, _, revision = await TMAAttemptService._load_owned_attempt(
            db,
            student=student,
            attempt_id=attempt_id,
            lock=True,
        )
        if attempt.status == TMAAttemptStatus.SUBMITTED:
            return await TMAAttemptService.get_submission_result(
                db,
                student=student,
                attempt_id=attempt.id,
            )
        assignment, active_revision, enrollment = await TMAAttemptService._active_assignment(
            db,
            student=student,
            assignment_id=revision.assignment_id,
            lock=True,
        )
        if active_revision.id != revision.id:
            raise ConflictException("This is not the current published revision.")
        questions = await TMAQuestionRepository.list_for_revision_with_options(
            db,
            student.tenant_id,
            revision.id,
        )
        if not questions:
            raise ConflictException("Assignment has no questions.")
        answers = await TMAAnswerRepository.list_for_attempt(
            db,
            student.tenant_id,
            attempt.id,
        )
        correct, total = TMAGradingService.calculate_raw_score(
            questions,
            {row.question_id: row.selected_option_id for row in answers},
        )
        try:
            component_score = await TMAGradingService.persist_component_score(
                db,
                tenant_id=student.tenant_id,
                student_id=student.id,
                enrollment=enrollment,
                assignment=assignment,
                correct=correct,
                total=total,
                attempt=attempt,
            )
            attempt.status = TMAAttemptStatus.SUBMITTED
            attempt.submitted_at = datetime.now(timezone.utc)
            attempt.correct_answers = correct
            attempt.total_questions = total
            await TMAAttemptRepository.save(db, attempt)
            await db.commit()
            await flush_cache_invalidation_events(db)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Concurrent submission or score creation conflict.") from exc
        return TMASubmitResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            correct_answers=correct,
            total_questions=total,
            component_score=component_score,
            submitted_at=attempt.submitted_at,
        )

    @staticmethod
    async def get_submission_result(
        db: AsyncSession,
        *,
        student: Student,
        attempt_id: uuid.UUID,
    ) -> TMASubmitResponse:
        attempt, _, revision = await TMAAttemptService._load_owned_attempt(
            db,
            student=student,
            attempt_id=attempt_id,
        )
        if (
            getattr(revision, "invalidated_at", None) is not None
            or getattr(attempt, "score_reversed_at", None) is not None
        ):
            raise ConflictException("This TMA revision was cancelled.")
        if (
            attempt.status != TMAAttemptStatus.SUBMITTED
            or attempt.correct_answers is None
            or attempt.total_questions is None
            or attempt.submitted_at is None
        ):
            raise ConflictException("Assignment has not been submitted.")
        assignment = await TMAAssignmentRepository.get_by_id(
            db,
            student.tenant_id,
            revision.assignment_id,
        )
        if assignment is None:
            raise NotFoundException("Assignment not found.")
        results = await StudentAcademicRepository.get_results_by_scope_batch(
            db,
            student.tenant_id,
            {student.id},
            assignment.curriculum_subject_id,
            assignment.academic_session_id,
            assignment.academic_term_id,
        )
        result = results.get(student.id)
        if result is None:
            raise ConflictException("Submitted TMA has no academic result.")
        component_scores = await StudentAcademicRepository.get_component_scores_batch(
            db,
            student.tenant_id,
            {result.id},
            assignment.assessment_component_id,
        )
        stored = component_scores.get(result.id)
        if stored is None:
            raise ConflictException("Submitted TMA component score is missing.")
        return TMASubmitResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            correct_answers=attempt.correct_answers,
            total_questions=attempt.total_questions,
            component_score=stored.score,
            submitted_at=attempt.submitted_at,
        )
