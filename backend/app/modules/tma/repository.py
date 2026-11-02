"""Tenant-scoped persistence for the TMA domain.

All methods participate in the caller's transaction. Business rules,
authorization, grading, and academic lookups belong to existing services.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, exists, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.classes.models import ClassRoom
from app.modules.student_academics.models import TeacherAssignment
from app.modules.tma.models import (
    TMAAnswer,
    TMAAssignment,
    TMAAssignmentRevision,
    TMAAssignmentStatus,
    TMAAttempt,
    TMAAttemptStatus,
    TMAMediaAsset,
    TMAParticipant,
    TMAQuestion,
    TMAQuestionOption,
)


class TMAAssignmentRepository:
    """Assignment configuration and lifecycle record persistence only."""

    @staticmethod
    async def add(db: AsyncSession, assignment: TMAAssignment) -> TMAAssignment:
        db.add(assignment)
        await db.flush()
        return assignment

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        *,
        lock: bool = False,
        shared_lock: bool = False,
    ) -> TMAAssignment | None:
        query = select(TMAAssignment).where(
            TMAAssignment.tenant_id == tenant_id,
            TMAAssignment.id == assignment_id,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        elif shared_lock:
            # PostgreSQL FOR SHARE allows independent student writes while
            # preventing staff from changing assignment state mid-submit.
            query = query.with_for_update(read=True).execution_options(populate_existing=True)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_component_scope(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_level_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        assessment_component_id: uuid.UUID,
    ) -> TMAAssignment | None:
        return (
            await db.execute(
                select(TMAAssignment).where(
                    TMAAssignment.tenant_id == tenant_id,
                    TMAAssignment.academic_level_id == academic_level_id,
                    TMAAssignment.curriculum_subject_id == curriculum_subject_id,
                    TMAAssignment.academic_session_id == academic_session_id,
                    TMAAssignment.academic_term_id == academic_term_id,
                    TMAAssignment.assessment_component_id == assessment_component_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_for_scope(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        academic_term_id: uuid.UUID | None = None,
        academic_level_id: uuid.UUID | None = None,
        curriculum_subject_id: uuid.UUID | None = None,
        status: TMAAssignmentStatus | None = None,
        statuses: set[TMAAssignmentStatus] | None = None,
        teacher_membership_id: uuid.UUID | None = None,
        authorized_scopes: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TMAAssignment], int]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative and limit must be 1..100")
        filters = [TMAAssignment.tenant_id == tenant_id]
        if teacher_membership_id is not None:
            filters.append(
                exists(
                    select(TeacherAssignment.id)
                    .join(ClassRoom, ClassRoom.id == TeacherAssignment.class_id)
                    .where(
                        TeacherAssignment.tenant_id == tenant_id,
                        TeacherAssignment.teacher_membership_id == teacher_membership_id,
                        TeacherAssignment.curriculum_subject_id
                        == TMAAssignment.curriculum_subject_id,
                        TeacherAssignment.effective_from <= date.today(),
                        (
                            TeacherAssignment.effective_to.is_(None)
                            | (TeacherAssignment.effective_to >= date.today())
                        ),
                        ClassRoom.tenant_id == tenant_id,
                        ClassRoom.academic_level_id == TMAAssignment.academic_level_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                    .correlate(TMAAssignment)
                )
            )
        if authorized_scopes is not None:
            filters.append(
                tuple_(
                    TMAAssignment.academic_term_id,
                    TMAAssignment.academic_level_id,
                    TMAAssignment.curriculum_subject_id,
                ).in_(authorized_scopes)
            )
        if academic_session_id is not None:
            filters.append(TMAAssignment.academic_session_id == academic_session_id)
        if academic_term_id is not None:
            filters.append(TMAAssignment.academic_term_id == academic_term_id)
        if academic_level_id is not None:
            filters.append(TMAAssignment.academic_level_id == academic_level_id)
        if curriculum_subject_id is not None:
            filters.append(TMAAssignment.curriculum_subject_id == curriculum_subject_id)
        if status is not None:
            filters.append(TMAAssignment.status == status)
        if statuses is not None:
            filters.append(TMAAssignment.status.in_(statuses))
        total = (
            await db.execute(select(func.count(TMAAssignment.id)).where(*filters))
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    select(TMAAssignment)
                    .where(*filters)
                    .order_by(TMAAssignment.created_at.desc(), TMAAssignment.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    @staticmethod
    async def save(db: AsyncSession, assignment: TMAAssignment) -> TMAAssignment:
        db.add(assignment)
        await db.flush()
        return assignment


class TMARevisionRepository:
    """Assignment revision history; never used for routine reopen operations."""

    @staticmethod
    async def add(db: AsyncSession, revision: TMAAssignmentRevision) -> TMAAssignmentRevision:
        db.add(revision)
        await db.flush()
        return revision

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TMAAssignmentRevision | None:
        query = select(TMAAssignmentRevision).where(
            TMAAssignmentRevision.tenant_id == tenant_id,
            TMAAssignmentRevision.id == revision_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_number(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        revision_number: int,
    ) -> TMAAssignmentRevision | None:
        return (
            await db.execute(
                select(TMAAssignmentRevision).where(
                    TMAAssignmentRevision.tenant_id == tenant_id,
                    TMAAssignmentRevision.assignment_id == assignment_id,
                    TMAAssignmentRevision.revision_number == revision_number,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_many_by_number(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scopes: set[tuple[uuid.UUID, int]],
    ) -> dict[uuid.UUID, TMAAssignmentRevision]:
        if not scopes:
            return {}
        rows = (
            (
                await db.execute(
                    select(TMAAssignmentRevision).where(
                        TMAAssignmentRevision.tenant_id == tenant_id,
                        tuple_(
                            TMAAssignmentRevision.assignment_id,
                            TMAAssignmentRevision.revision_number,
                        ).in_(scopes),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.assignment_id: row for row in rows}

    @staticmethod
    async def list_for_assignment(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
    ) -> list[TMAAssignmentRevision]:
        return list(
            (
                await db.execute(
                    select(TMAAssignmentRevision)
                    .where(
                        TMAAssignmentRevision.tenant_id == tenant_id,
                        TMAAssignmentRevision.assignment_id == assignment_id,
                    )
                    .order_by(TMAAssignmentRevision.revision_number.desc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def save(
        db: AsyncSession,
        revision: TMAAssignmentRevision,
    ) -> TMAAssignmentRevision:
        db.add(revision)
        await db.flush()
        return revision


class TMAQuestionRepository:
    """Question and option persistence; authorization occurs in services."""

    @staticmethod
    async def next_position(db: AsyncSession, tenant_id: uuid.UUID, revision_id: uuid.UUID) -> int:
        maximum = (
            await db.execute(
                select(func.max(TMAQuestion.position)).where(
                    TMAQuestion.tenant_id == tenant_id,
                    TMAQuestion.revision_id == revision_id,
                )
            )
        ).scalar_one()
        return int(maximum or 0) + 1

    @staticmethod
    async def add_question(db: AsyncSession, question: TMAQuestion) -> TMAQuestion:
        db.add(question)
        await db.flush()
        return question

    @staticmethod
    async def get_question(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        question_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TMAQuestion | None:
        query = select(TMAQuestion).where(
            TMAQuestion.tenant_id == tenant_id,
            TMAQuestion.id == question_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_revision_with_options(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> list[tuple[TMAQuestion, list[TMAQuestionOption]]]:
        """Fetch all questions and options in two queries (no N+1)."""
        questions = list(
            (
                await db.execute(
                    select(TMAQuestion)
                    .where(
                        TMAQuestion.tenant_id == tenant_id,
                        TMAQuestion.revision_id == revision_id,
                    )
                    .order_by(TMAQuestion.position, TMAQuestion.id)
                )
            )
            .scalars()
            .all()
        )
        if not questions:
            return []
        question_ids = [question.id for question in questions]
        options = (
            (
                await db.execute(
                    select(TMAQuestionOption)
                    .where(
                        TMAQuestionOption.tenant_id == tenant_id,
                        TMAQuestionOption.question_id.in_(question_ids),
                    )
                    .order_by(
                        TMAQuestionOption.question_id,
                        TMAQuestionOption.position,
                        TMAQuestionOption.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_question: dict[uuid.UUID, list[TMAQuestionOption]] = {
            question_id: [] for question_id in question_ids
        }
        for option in options:
            by_question[option.question_id].append(option)
        return [(question, by_question[question.id]) for question in questions]

    @staticmethod
    async def replace_options(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        question_id: uuid.UUID,
        options: Sequence[TMAQuestionOption],
    ) -> None:
        """Replace options only after the service validates DRAFT and ownership.

        The service must lock the parent question and check its version.
        Existing submitted answers are protected by RESTRICT foreign keys.
        """
        if any(
            option.tenant_id != tenant_id or option.question_id != question_id for option in options
        ):
            raise ValueError("option scope does not match question")
        await db.execute(
            delete(TMAQuestionOption).where(
                TMAQuestionOption.tenant_id == tenant_id,
                TMAQuestionOption.question_id == question_id,
            )
        )
        await db.flush()
        db.add_all(list(options))
        await db.flush()

    @staticmethod
    async def save_question(db: AsyncSession, question: TMAQuestion) -> TMAQuestion:
        db.add(question)
        await db.flush()
        return question

    @staticmethod
    async def delete_draft_question(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        """Caller must lock/validate that the question is still in DRAFT."""
        question = await TMAQuestionRepository.get_question(
            db,
            tenant_id,
            question_id,
            lock=True,
        )
        if question is None:
            return False
        await db.execute(
            delete(TMAQuestionOption).where(
                TMAQuestionOption.tenant_id == tenant_id,
                TMAQuestionOption.question_id == question_id,
            )
        )
        await db.delete(question)
        await db.flush()
        return True


class TMAMediaAssetRepository:
    """TMA-specific R2 metadata, not generic storage operations."""

    @staticmethod
    async def add(db: AsyncSession, asset: TMAMediaAsset) -> TMAMediaAsset:
        db.add(asset)
        await db.flush()
        return asset

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> TMAMediaAsset | None:
        return (
            await db.execute(
                select(TMAMediaAsset).where(
                    TMAMediaAsset.tenant_id == tenant_id,
                    TMAMediaAsset.id == asset_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_many_for_assignment(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        asset_ids: set[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not asset_ids:
            return set()
        return set(
            (
                await db.execute(
                    select(TMAMediaAsset.id).where(
                        TMAMediaAsset.tenant_id == tenant_id,
                        TMAMediaAsset.assignment_id == assignment_id,
                        TMAMediaAsset.id.in_(asset_ids),
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def get_by_object_key(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        object_key: str,
    ) -> TMAMediaAsset | None:
        return (
            await db.execute(
                select(TMAMediaAsset).where(
                    TMAMediaAsset.tenant_id == tenant_id,
                    TMAMediaAsset.object_key == object_key,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_for_assignment(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
    ) -> list[TMAMediaAsset]:
        return list(
            (
                await db.execute(
                    select(TMAMediaAsset)
                    .where(
                        TMAMediaAsset.tenant_id == tenant_id,
                        TMAMediaAsset.assignment_id == assignment_id,
                    )
                    .order_by(TMAMediaAsset.created_at, TMAMediaAsset.id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def delete_unreferenced(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> bool:
        """Remove metadata only if neither questions nor options use it.

        Actual R2 object deletion is coordinated by the media service.
        """
        question_ref = exists(
            select(TMAQuestion.id).where(
                TMAQuestion.tenant_id == tenant_id,
                TMAQuestion.image_asset_id == asset_id,
            )
        )
        option_ref = exists(
            select(TMAQuestionOption.id).where(
                TMAQuestionOption.tenant_id == tenant_id,
                TMAQuestionOption.image_asset_id == asset_id,
            )
        )
        removed_id = (
            await db.execute(
                delete(TMAMediaAsset)
                .where(
                    TMAMediaAsset.tenant_id == tenant_id,
                    TMAMediaAsset.id == asset_id,
                    ~question_ref,
                    ~option_ref,
                )
                .returning(TMAMediaAsset.id)
            )
        ).scalar_one_or_none()
        return removed_id is not None


class TMAParticipantRepository:
    """Historical registration, not live student eligibility decisions."""

    @staticmethod
    async def insert_missing(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        participants: Sequence[TMAParticipant],
    ) -> list[uuid.UUID]:
        """Insert roster members idempotently without modifying existing history."""
        if not participants:
            return []
        if any(participant.tenant_id != tenant_id for participant in participants):
            raise ValueError("participants must belong to the specified tenant")
        rows = [
            {
                "id": participant.id or uuid.uuid4(),
                "tenant_id": tenant_id,
                "revision_id": participant.revision_id,
                "student_id": participant.student_id,
                "student_enrollment_id": participant.student_enrollment_id,
                "class_id": participant.class_id,
            }
            for participant in participants
        ]
        stmt = (
            insert(TMAParticipant)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_tma_participants_revision_student",
            )
            .returning(TMAParticipant.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_by_revision_student(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> TMAParticipant | None:
        return (
            await db.execute(
                select(TMAParticipant).where(
                    TMAParticipant.tenant_id == tenant_id,
                    TMAParticipant.revision_id == revision_id,
                    TMAParticipant.student_id == student_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_for_revision(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> list[TMAParticipant]:
        return list(
            (
                await db.execute(
                    select(TMAParticipant)
                    .where(
                        TMAParticipant.tenant_id == tenant_id,
                        TMAParticipant.revision_id == revision_id,
                    )
                    .order_by(TMAParticipant.student_id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def list_for_student(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
    ) -> list[TMAParticipant]:
        return list(
            (
                await db.execute(
                    select(TMAParticipant)
                    .where(
                        TMAParticipant.tenant_id == tenant_id,
                        TMAParticipant.student_id == student_id,
                    )
                    .order_by(TMAParticipant.created_at.desc(), TMAParticipant.id.desc())
                )
            )
            .scalars()
            .all()
        )


class TMAAttemptRepository:
    """Persist the single in-progress/submitted attempt per participant."""

    @staticmethod
    async def create(db: AsyncSession, attempt: TMAAttempt) -> TMAAttempt:
        db.add(attempt)
        await db.flush()
        return attempt

    @staticmethod
    async def create_if_missing(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        participant_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> TMAAttempt:
        """Concurrent starts converge on the existing unique participant attempt."""
        statement = (
            insert(TMAAttempt)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                participant_id=participant_id,
                revision_id=revision_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_tma_attempts_tenant_participant",
            )
            .returning(TMAAttempt)
        )
        inserted = (await db.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return inserted
        attempt = await TMAAttemptRepository.get_by_participant(
            db,
            tenant_id,
            participant_id,
            lock=True,
        )
        if attempt is None:
            raise RuntimeError("Concurrent attempt not visible after conflict")
        return attempt

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TMAAttempt | None:
        query = select(TMAAttempt).where(
            TMAAttempt.tenant_id == tenant_id,
            TMAAttempt.id == attempt_id,
        )
        if lock:
            # The attempt may already be in this request's identity map from
            # its initial ownership lookup. Refresh after waiting on the lock.
            query = query.with_for_update().execution_options(populate_existing=True)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_by_participant(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        participant_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TMAAttempt | None:
        query = select(TMAAttempt).where(
            TMAAttempt.tenant_id == tenant_id,
            TMAAttempt.participant_id == participant_id,
        )
        if lock:
            # The attempt may already be in this request's identity map from
            # its initial ownership lookup. Refresh after waiting on the lock.
            query = query.with_for_update().execution_options(populate_existing=True)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_for_participants(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        participant_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, TMAAttempt]:
        if not participant_ids:
            return {}
        attempts = (
            (
                await db.execute(
                    select(TMAAttempt).where(
                        TMAAttempt.tenant_id == tenant_id,
                        TMAAttempt.participant_id.in_(participant_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {attempt.participant_id: attempt for attempt in attempts}

    @staticmethod
    async def list_submitted_for_revision(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> list[TMAAttempt]:
        return list(
            (
                await db.execute(
                    select(TMAAttempt)
                    .where(
                        TMAAttempt.tenant_id == tenant_id,
                        TMAAttempt.revision_id == revision_id,
                        TMAAttempt.status == TMAAttemptStatus.SUBMITTED,
                    )
                    .order_by(TMAAttempt.submitted_at, TMAAttempt.id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def save(db: AsyncSession, attempt: TMAAttempt) -> TMAAttempt:
        db.add(attempt)
        await db.flush()
        return attempt


class TMAAnswerRepository:
    """Answer persistence. Services lock attempts before modifying answers."""

    @staticmethod
    async def list_for_attempt(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        attempt_id: uuid.UUID,
    ) -> list[TMAAnswer]:
        return list(
            (
                await db.execute(
                    select(TMAAnswer)
                    .where(
                        TMAAnswer.tenant_id == tenant_id,
                        TMAAnswer.attempt_id == attempt_id,
                    )
                    .order_by(TMAAnswer.question_id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def save_selection(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        attempt_id: uuid.UUID,
        revision_id: uuid.UUID,
        question_id: uuid.UUID,
        selected_option_id: uuid.UUID,
    ) -> TMAAnswer:
        """Upsert the selection; caller must lock the attempt and check ACTIVE."""
        stmt = (
            insert(TMAAnswer)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                revision_id=revision_id,
                question_id=question_id,
                selected_option_id=selected_option_id,
            )
            .on_conflict_do_update(
                constraint="uq_tma_answers_attempt_question",
                set_={
                    "selected_option_id": selected_option_id,
                    "updated_at": func.now(),
                },
            )
            .returning(TMAAnswer)
        )
        return (await db.execute(stmt)).scalar_one()

    @staticmethod
    async def clear_selection(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        attempt_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        """Remove one selection; caller must lock the IN_PROGRESS attempt."""
        removed_id = (
            await db.execute(
                delete(TMAAnswer)
                .where(
                    TMAAnswer.tenant_id == tenant_id,
                    TMAAnswer.attempt_id == attempt_id,
                    TMAAnswer.question_id == question_id,
                )
                .returning(TMAAnswer.id)
            )
        ).scalar_one_or_none()
        return removed_id is not None
