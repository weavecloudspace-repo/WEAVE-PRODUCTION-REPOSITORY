"""Canonical repositories for academic setup, assignments, and results."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.classes.models import AcademicLevel, ArmLabel, ClassRoom
from app.modules.report_cards.models import ReportCard, ReportCardStatus
from app.modules.student_academics.curriculum_models import CurriculumSubject
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicResultStatus,
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermStatus,
    AssessmentComponent,
    GradingScale,
    StudentAssessmentScore,
    StudentProgressionRun,
    StudentSubjectResult,
    TeacherAssignment,
)
from app.modules.students.models import Student, StudentEnrollment
from app.modules.subjects.models import Subject
from app.modules.teachers.models import TeacherAccount, TeacherMembership

FINALIZED_RESULT_STATUSES = (AcademicResultStatus.LOCKED,)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class StudentAcademicRepository:
    @staticmethod
    async def _save(db: AsyncSession, entity):
        db.add(entity)
        await db.flush()
        await db.refresh(entity)
        return entity

    # ------------------------------------------------------------------
    # Sessions and terms
    # ------------------------------------------------------------------
    @staticmethod
    async def create_academic_session(
        db: AsyncSession, academic_session: AcademicSession
    ) -> AcademicSession:
        return await StudentAcademicRepository._save(db, academic_session)

    @staticmethod
    async def get_academic_session_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> AcademicSession | None:
        query = select(AcademicSession).where(
            AcademicSession.tenant_id == tenant_id,
            AcademicSession.id == academic_session_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_academic_session_by_name(
        db: AsyncSession, tenant_id: uuid.UUID, name: str
    ) -> AcademicSession | None:
        return (
            await db.execute(
                select(AcademicSession).where(
                    AcademicSession.tenant_id == tenant_id,
                    AcademicSession.name == name,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_current_academic_session(
        db: AsyncSession, tenant_id: uuid.UUID
    ) -> AcademicSession | None:
        return (
            await db.execute(
                select(AcademicSession).where(
                    AcademicSession.tenant_id == tenant_id,
                    AcademicSession.is_current.is_(True),
                    AcademicSession.status.in_(
                        {AcademicSessionStatus.OPEN, AcademicSessionStatus.CLOSING}
                    ),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_academic_sessions(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        *,
        search: str | None = None,
        status: AcademicSessionStatus | None = None,
        is_current: bool | None = None,
        start_date_from: date | None = None,
        start_date_to: date | None = None,
    ) -> tuple[list[AcademicSession], int]:
        filters = [AcademicSession.tenant_id == tenant_id]
        if search:
            filters.append(
                AcademicSession.name.ilike(f"%{escape_like(search.strip())}%", escape="\\")
            )
        if status is not None:
            filters.append(AcademicSession.status == status)
        if is_current is not None:
            filters.append(AcademicSession.is_current.is_(is_current))
        if start_date_from is not None:
            filters.append(AcademicSession.start_date >= start_date_from)
        if start_date_to is not None:
            filters.append(AcademicSession.start_date <= start_date_to)
        total = (
            await db.execute(select(func.count()).select_from(AcademicSession).where(*filters))
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    select(AcademicSession)
                    .where(*filters)
                    .order_by(
                        AcademicSession.is_current.desc(),
                        AcademicSession.created_at.desc(),
                    )
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    @staticmethod
    async def save_academic_session(
        db: AsyncSession, academic_session: AcademicSession
    ) -> AcademicSession:
        return await StudentAcademicRepository._save(db, academic_session)

    @staticmethod
    async def create_academic_term(db: AsyncSession, academic_term: AcademicTerm) -> AcademicTerm:
        return await StudentAcademicRepository._save(db, academic_term)

    @staticmethod
    async def get_term_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> AcademicTerm | None:
        query = select(AcademicTerm).where(
            AcademicTerm.tenant_id == tenant_id,
            AcademicTerm.id == term_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_term_by_session_and_name(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        name,
    ) -> AcademicTerm | None:
        return (
            await db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.academic_session_id == academic_session_id,
                    AcademicTerm.name == name,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_current_term(db: AsyncSession, tenant_id: uuid.UUID) -> AcademicTerm | None:
        return (
            await db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.is_current.is_(True),
                    AcademicTerm.status.in_({AcademicTermStatus.OPEN, AcademicTermStatus.CLOSING}),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_terms(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        statuses: set[AcademicTermStatus] | None = None,
        *,
        name: str | None = None,
        is_current: bool | None = None,
        start_date_from: date | None = None,
        start_date_to: date | None = None,
    ) -> tuple[list[AcademicTerm], int]:
        return await StudentAcademicRepository._list_terms(
            db,
            tenant_id,
            skip=skip,
            limit=limit,
            statuses=statuses,
            name=name,
            is_current=is_current,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
        )

    @staticmethod
    async def list_terms_by_session(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        statuses: set[AcademicTermStatus] | None = None,
        *,
        name: str | None = None,
        is_current: bool | None = None,
        start_date_from: date | None = None,
        start_date_to: date | None = None,
    ) -> tuple[list[AcademicTerm], int]:
        return await StudentAcademicRepository._list_terms(
            db,
            tenant_id,
            academic_session_id=academic_session_id,
            skip=skip,
            limit=limit,
            statuses=statuses,
            name=name,
            is_current=is_current,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
        )

    @staticmethod
    async def _list_terms(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        statuses: set[AcademicTermStatus] | None = None,
        name: str | None = None,
        is_current: bool | None = None,
        start_date_from: date | None = None,
        start_date_to: date | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[AcademicTerm], int]:
        filters = [AcademicTerm.tenant_id == tenant_id]
        if academic_session_id is not None:
            filters.append(AcademicTerm.academic_session_id == academic_session_id)
        if statuses is None:
            filters.append(AcademicTerm.status != AcademicTermStatus.CLOSED)
        elif statuses:
            filters.append(AcademicTerm.status.in_(statuses))
        if name is not None:
            filters.append(AcademicTerm.name == name)
        if is_current is not None:
            filters.append(AcademicTerm.is_current.is_(is_current))
        if start_date_from is not None:
            filters.append(AcademicTerm.start_date >= start_date_from)
        if start_date_to is not None:
            filters.append(AcademicTerm.start_date <= start_date_to)
        total = (
            await db.execute(select(func.count()).select_from(AcademicTerm).where(*filters))
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    select(AcademicTerm)
                    .where(*filters)
                    .order_by(
                        AcademicTerm.is_current.desc(),
                        AcademicTerm.created_at.desc(),
                    )
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    @staticmethod
    async def save_academic_term(db: AsyncSession, academic_term: AcademicTerm) -> AcademicTerm:
        return await StudentAcademicRepository._save(db, academic_term)

    # ------------------------------------------------------------------
    # Lifecycle dependency counts
    # ------------------------------------------------------------------
    @staticmethod
    async def count_academic_terms(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        statuses: set[AcademicTermStatus] | None = None,
    ) -> int:
        filters = [AcademicTerm.tenant_id == tenant_id]
        if academic_session_id is not None:
            filters.append(AcademicTerm.academic_session_id == academic_session_id)
        if statuses is not None:
            filters.append(AcademicTerm.status.in_(statuses))
        return int(
            (
                await db.execute(select(func.count()).select_from(AcademicTerm).where(*filters))
            ).scalar_one()
        )

    @staticmethod
    async def count_results(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        academic_term_id: uuid.UUID | None = None,
        statuses: set[AcademicResultStatus] | None = None,
    ) -> int:
        filters = [StudentSubjectResult.tenant_id == tenant_id]
        if academic_session_id is not None:
            filters.append(StudentSubjectResult.academic_session_id == academic_session_id)
        if academic_term_id is not None:
            filters.append(StudentSubjectResult.academic_term_id == academic_term_id)
        if statuses is not None:
            filters.append(StudentSubjectResult.status.in_(statuses))
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(StudentSubjectResult).where(*filters)
                )
            ).scalar_one()
        )

    @staticmethod
    async def count_report_cards(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        academic_term_id: uuid.UUID | None = None,
        statuses: set[ReportCardStatus] | None = None,
    ) -> int:
        filters = [ReportCard.tenant_id == tenant_id]
        if academic_session_id is not None:
            filters.append(ReportCard.academic_session_id == academic_session_id)
        if academic_term_id is not None:
            filters.append(ReportCard.academic_term_id == academic_term_id)
        if statuses is not None:
            filters.append(ReportCard.status.in_(statuses))
        return int(
            (
                await db.execute(select(func.count()).select_from(ReportCard).where(*filters))
            ).scalar_one()
        )

    @staticmethod
    async def count_enrollments(
        db: AsyncSession, tenant_id: uuid.UUID, academic_session_id: uuid.UUID
    ) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(StudentEnrollment)
                    .where(
                        StudentEnrollment.tenant_id == tenant_id,
                        StudentEnrollment.academic_session_id == academic_session_id,
                    )
                )
            ).scalar_one()
        )

    @staticmethod
    async def count_progression_runs(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        academic_session_id: uuid.UUID | None = None,
        statuses: set | None = None,
    ) -> int:
        filters = [StudentProgressionRun.tenant_id == tenant_id]
        if academic_session_id is not None:
            filters.append(StudentProgressionRun.academic_session_id == academic_session_id)
        if statuses is not None:
            filters.append(StudentProgressionRun.status.in_(statuses))
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(StudentProgressionRun).where(*filters)
                )
            ).scalar_one()
        )

    @staticmethod
    async def count_inbound_next_sessions(
        db: AsyncSession, tenant_id: uuid.UUID, academic_session_id: uuid.UUID
    ) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(AcademicSession)
                    .where(
                        AcademicSession.tenant_id == tenant_id,
                        AcademicSession.next_academic_session_id == academic_session_id,
                    )
                )
            ).scalar_one()
        )

    @staticmethod
    async def add_academic_lifecycle_audit(
        db: AsyncSession, audit: AcademicLifecycleAudit
    ) -> AcademicLifecycleAudit:
        db.add(audit)
        await db.flush()
        return audit

    @staticmethod
    async def delete_academic_session(db: AsyncSession, session: AcademicSession) -> None:
        await db.delete(session)

    @staticmethod
    async def delete_academic_term(db: AsyncSession, term: AcademicTerm) -> None:
        await db.delete(term)

    # ------------------------------------------------------------------
    # Grading scales
    # ------------------------------------------------------------------
    @staticmethod
    async def create_grading_scale(db: AsyncSession, grading_scale: GradingScale) -> GradingScale:
        return await StudentAcademicRepository._save(db, grading_scale)

    @staticmethod
    async def get_grading_scale_by_id(
        db: AsyncSession, tenant_id: uuid.UUID, grading_scale_id: uuid.UUID
    ) -> GradingScale | None:
        return (
            await db.execute(
                select(GradingScale).where(
                    GradingScale.tenant_id == tenant_id,
                    GradingScale.id == grading_scale_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_grading_scale_by_grade(
        db: AsyncSession, tenant_id: uuid.UUID, grade: str
    ) -> GradingScale | None:
        return (
            await db.execute(
                select(GradingScale).where(
                    GradingScale.tenant_id == tenant_id,
                    GradingScale.grade == grade,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_grading_scales(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> tuple[list[GradingScale], int]:
        filters = [GradingScale.tenant_id == tenant_id]
        if active_only:
            filters.append(GradingScale.is_active.is_(True))
        total = (
            await db.execute(select(func.count()).select_from(GradingScale).where(*filters))
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    select(GradingScale)
                    .where(*filters)
                    .order_by(GradingScale.min_score.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    @staticmethod
    async def find_grade_for_score(
        db: AsyncSession, tenant_id: uuid.UUID, score: Decimal
    ) -> GradingScale | None:
        return (
            await db.execute(
                select(GradingScale).where(
                    GradingScale.tenant_id == tenant_id,
                    GradingScale.is_active.is_(True),
                    GradingScale.min_score <= score,
                    GradingScale.max_score >= score,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def save_grading_scale(db: AsyncSession, grading_scale: GradingScale) -> GradingScale:
        return await StudentAcademicRepository._save(db, grading_scale)

    # ------------------------------------------------------------------
    # Results and component scores
    # ------------------------------------------------------------------
    @staticmethod
    async def upsert_result(db: AsyncSession, result: StudentSubjectResult) -> StudentSubjectResult:
        return await StudentAcademicRepository._save(db, result)

    @staticmethod
    async def save_results_batch(
        db: AsyncSession, results: list[StudentSubjectResult]
    ) -> list[StudentSubjectResult]:
        """Persist new or modified subject results in one flush

        This is used by bulk workflows such as CBT ingestion to avoid
        flushing one StudentSubjectResult at a time
        """

        if not results:
            return []

        db.add_all(results)
        await db.flush()
        return results

    @staticmethod
    async def get_component_scores_batch(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result_ids: set[uuid.UUID],
        assessment_component_id: uuid.UUID,
        *,
        lock: bool = False,
    ):  # -> dict | dict[UUID, StudentAssessmentScore]:
        """
        Load one assessment component score accross many subject results.

        The returned mapping is Keyed by student_subject_result_id
        """

        if not result_ids:
            return {}

        query = select(StudentAssessmentScore).where(
            StudentAssessmentScore.tenant_id == tenant_id,
            StudentAssessmentScore.student_subject_result_id.in_(result_ids),
            StudentAssessmentScore.assessment_component_id == assessment_component_id,
        )

        if lock:
            query = query.with_for_update()

        rows = list((await db.execute(query)).scalars().all())

        return {score.student_subject_result_id: score for score in rows}

    @staticmethod
    async def add_component_scores_batch(
        db: AsyncSession,
        scores: list[StudentAssessmentScore],
    ) -> list[StudentAssessmentScore]:
        """
        Persist new component scores in one flush.

        Callers must only supply scores that have already been classified as
        safe to insert. This method does not overwrite existing scores.
        """

        if not scores:
            return []

        db.add_all(scores)
        await db.flush()

        return scores

    @staticmethod
    async def list_result_component_scores(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result: StudentSubjectResult,
    ) -> list[tuple[AssessmentComponent, StudentAssessmentScore | None]]:
        rows = (
            await db.execute(
                select(AssessmentComponent, StudentAssessmentScore)
                .outerjoin(
                    StudentAssessmentScore,
                    and_(
                        StudentAssessmentScore.tenant_id == tenant_id,
                        StudentAssessmentScore.student_subject_result_id == result.id,
                        StudentAssessmentScore.assessment_component_id == AssessmentComponent.id,
                    ),
                )
                .where(
                    AssessmentComponent.tenant_id == tenant_id,
                    AssessmentComponent.assessment_scheme_id == result.assessment_scheme_id,
                    AssessmentComponent.is_active.is_(True),
                )
                .order_by(AssessmentComponent.position.asc())
            )
        ).all()
        return [(component, score) for component, score in rows]

    @staticmethod
    async def list_result_component_scores_batch(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        results: list[StudentSubjectResult],
    ) -> dict[uuid.UUID, list[tuple[AssessmentComponent, StudentAssessmentScore | None]]]:
        if not results:
            return {}
        scheme_ids = {result.assessment_scheme_id for result in results}
        result_ids = {result.id for result in results}
        components = list(
            (
                await db.execute(
                    select(AssessmentComponent)
                    .where(
                        AssessmentComponent.tenant_id == tenant_id,
                        AssessmentComponent.assessment_scheme_id.in_(scheme_ids),
                        AssessmentComponent.is_active.is_(True),
                    )
                    .order_by(AssessmentComponent.position.asc())
                )
            )
            .scalars()
            .all()
        )
        scores = list(
            (
                await db.execute(
                    select(StudentAssessmentScore).where(
                        StudentAssessmentScore.tenant_id == tenant_id,
                        StudentAssessmentScore.student_subject_result_id.in_(result_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        components_by_scheme: dict[uuid.UUID, list[AssessmentComponent]] = {}
        for component in components:
            components_by_scheme.setdefault(component.assessment_scheme_id, []).append(component)
        scores_by_result = {
            (score.student_subject_result_id, score.assessment_component_id): score
            for score in scores
        }
        return {
            result.id: [
                (component, scores_by_result.get((result.id, component.id)))
                for component in components_by_scheme.get(result.assessment_scheme_id, [])
            ]
            for result in results
        }

    @staticmethod
    async def replace_result_scores(
        db: AsyncSession,
        result: StudentSubjectResult,
        values: dict[uuid.UUID, Decimal],
    ) -> None:
        existing = {
            item.assessment_component_id: item
            for item in (
                (
                    await db.execute(
                        select(StudentAssessmentScore).where(
                            StudentAssessmentScore.tenant_id == result.tenant_id,
                            StudentAssessmentScore.student_subject_result_id == result.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        for component_id, item in existing.items():
            if component_id not in values:
                await db.delete(item)
        for component_id, value in values.items():
            item = existing.get(component_id)
            if item is None:
                db.add(
                    StudentAssessmentScore(
                        tenant_id=result.tenant_id,
                        student_subject_result_id=result.id,
                        assessment_component_id=component_id,
                        score=value,
                    )
                )
            else:
                item.score = value
        await db.flush()

    @staticmethod
    async def get_result_by_id(
        db: AsyncSession, tenant_id: uuid.UUID, result_id: uuid.UUID
    ) -> StudentSubjectResult | None:
        return (
            await db.execute(
                select(StudentSubjectResult).where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.id == result_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _curriculum_subject_id_for_assignment(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
    ) -> uuid.UUID | None:
        return (
            await db.execute(
                select(TeacherAssignment.curriculum_subject_id).where(
                    TeacherAssignment.tenant_id == tenant_id,
                    TeacherAssignment.id == teacher_assignment_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_result_by_scope(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> StudentSubjectResult | None:
        curriculum_subject_id = (
            await StudentAcademicRepository._curriculum_subject_id_for_assignment(
                db, tenant_id, teacher_assignment_id
            )
        )
        if curriculum_subject_id is None:
            return None
        query = select(StudentSubjectResult).where(
            StudentSubjectResult.tenant_id == tenant_id,
            StudentSubjectResult.student_id == student_id,
            StudentSubjectResult.curriculum_subject_id == curriculum_subject_id,
            StudentSubjectResult.academic_session_id == academic_session_id,
            StudentSubjectResult.academic_term_id == academic_term_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_results_by_scope_batch(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_ids: set[uuid.UUID],
        curriculum_subject_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> dict[uuid.UUID, StudentSubjectResult]:
        """
        Load canonical subject results for many students in one academic scope.

        The result scope is uniquely identified by tenant, student,
        curriculum subject, session, and term.
        """

        if not student_ids:
            return {}

        query = select(StudentSubjectResult).where(
            StudentSubjectResult.tenant_id == tenant_id,
            StudentSubjectResult.student_id.in_(student_ids),
            StudentSubjectResult.curriculum_subject_id == curriculum_subject_id,
            StudentSubjectResult.academic_session_id == academic_session_id,
            StudentSubjectResult.academic_term_id == academic_term_id,
        )

        if lock:
            query = query.with_for_update()

        rows = list((await db.execute(query)).scalars().all())

        return {result.student_id: result for result in rows}

    @staticmethod
    async def list_results(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        student_id: uuid.UUID | None = None,
        class_id: uuid.UUID | None = None,
        teacher_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        teacher_assignment_id: uuid.UUID | None = None,
        academic_session_id: uuid.UUID | None = None,
        academic_term_id: uuid.UUID | None = None,
        status: AcademicResultStatus | None = None,
        search: str | None = None,
        is_complete: bool | None = None,
        has_grade: bool | None = None,
        finalized_only: bool = False,
    ) -> tuple[list[StudentSubjectResult], int]:
        filters = [StudentSubjectResult.tenant_id == tenant_id]
        if student_id is not None:
            filters.append(StudentSubjectResult.student_id == student_id)
        if class_id is not None:
            filters.append(StudentSubjectResult.class_id == class_id)
        if teacher_id is not None:
            filters.append(StudentSubjectResult.teacher_membership_id == teacher_id)
        if subject_id is not None:
            filters.append(StudentSubjectResult.subject_id == subject_id)
        if teacher_assignment_id is not None:
            filters.append(StudentSubjectResult.teacher_assignment_id == teacher_assignment_id)
        if academic_session_id is not None:
            filters.append(StudentSubjectResult.academic_session_id == academic_session_id)
        if academic_term_id is not None:
            filters.append(StudentSubjectResult.academic_term_id == academic_term_id)
        if status is not None:
            filters.append(StudentSubjectResult.status == status)
        if finalized_only:
            filters.append(StudentSubjectResult.status.in_(FINALIZED_RESULT_STATUSES))
        search_term = search.strip() if search else ""
        if search_term:
            pattern = f"%{escape_like(search_term)}%"
            student_name = func.concat(
                func.coalesce(Student.first_name, ""),
                " ",
                func.coalesce(Student.last_name, ""),
            )
            filters.append(
                or_(
                    student_name.ilike(pattern, escape="\\"),
                    Student.admission_number.ilike(pattern, escape="\\"),
                    Subject.name.ilike(pattern, escape="\\"),
                    Subject.code.ilike(pattern, escape="\\"),
                )
            )
        if is_complete is not None:
            component_count = (
                select(func.count())
                .select_from(AssessmentComponent)
                .where(
                    AssessmentComponent.tenant_id == tenant_id,
                    AssessmentComponent.assessment_scheme_id
                    == StudentSubjectResult.assessment_scheme_id,
                    AssessmentComponent.is_active.is_(True),
                )
                .correlate(StudentSubjectResult)
                .scalar_subquery()
            )
            score_count = (
                select(func.count())
                .select_from(StudentAssessmentScore)
                .where(
                    StudentAssessmentScore.tenant_id == tenant_id,
                    StudentAssessmentScore.student_subject_result_id == StudentSubjectResult.id,
                )
                .correlate(StudentSubjectResult)
                .scalar_subquery()
            )
            if is_complete:
                filters.append(and_(component_count > 0, score_count == component_count))
            else:
                filters.append(or_(component_count == 0, score_count != component_count))
        if has_grade is not None:
            filters.append(
                StudentSubjectResult.grade.is_not(None)
                if has_grade
                else StudentSubjectResult.grade.is_(None)
            )
        count_query = select(func.count()).select_from(StudentSubjectResult)
        rows_query = select(StudentSubjectResult)
        if search_term:
            count_query = count_query.join(
                Student, Student.id == StudentSubjectResult.student_id
            ).join(Subject, Subject.id == StudentSubjectResult.subject_id)
            rows_query = rows_query.join(
                Student, Student.id == StudentSubjectResult.student_id
            ).join(Subject, Subject.id == StudentSubjectResult.subject_id)
        total = (await db.execute(count_query.where(*filters))).scalar_one()
        rows = (
            (
                await db.execute(
                    rows_query.where(*filters)
                    .order_by(StudentSubjectResult.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    @staticmethod
    async def list_result_subject_options(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        class_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list[dict]:
        """Distinct subjects recorded in this class and period, independent of staffing."""
        rows = (
            await db.execute(
                select(Subject.id, Subject.name, Subject.code)
                .join(StudentSubjectResult, StudentSubjectResult.subject_id == Subject.id)
                .where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    Subject.tenant_id == tenant_id,
                    StudentSubjectResult.class_id == class_id,
                    StudentSubjectResult.academic_session_id == academic_session_id,
                    StudentSubjectResult.academic_term_id == academic_term_id,
                )
                .distinct()
                .order_by(Subject.name.asc(), Subject.id.asc())
            )
        ).all()
        return [{"id": row.id, "name": row.name, "code": row.code} for row in rows]

    # ------------------------------------------------------------------
    # Teacher assignments
    # ------------------------------------------------------------------
    @staticmethod
    async def create_teacher_assignment(
        db: AsyncSession, assignment: TeacherAssignment
    ) -> TeacherAssignment:
        return await StudentAcademicRepository._save(db, assignment)

    @staticmethod
    async def get_teacher_assignment_by_id(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> TeacherAssignment | None:
        query = select(TeacherAssignment).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.id == assignment_id,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_active_teacher_assignment_for_curriculum_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        class_id: uuid.UUID,
        exclude_id: uuid.UUID | None = None,
        lock: bool = False,
    ) -> TeacherAssignment | None:
        """Return the teacher assignment effective today for one class-subject scope."""

        filters = [
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
            TeacherAssignment.class_id == class_id,
            TeacherAssignment.is_active.is_(True),
        ]
        if exclude_id is not None:
            filters.append(TeacherAssignment.id != exclude_id)
        query = (
            select(TeacherAssignment)
            .where(*filters)
            .order_by(TeacherAssignment.effective_from.desc())
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_teacher_assignments_for_classes_on_date(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        class_ids: set[uuid.UUID],
        curriculum_subject_id: uuid.UUID,
        effective_date: date,
        *,
        lock: bool = False,
    ) -> dict[uuid.UUID, TeacherAssignment]:
        """
        Load the teacher assignment effective on a specific date for many classes.

        Teacher ownership is resolved historically using effective_from and
        effective_to rather than the assignment that happens to be current today.
        """

        if not class_ids:
            return {}

        query = select(TeacherAssignment).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.class_id.in_(class_ids),
            TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
            TeacherAssignment.effective_from <= effective_date,
            or_(
                TeacherAssignment.effective_to.is_(None),
                TeacherAssignment.effective_to >= effective_date,
            ),
        )

        if lock:
            query = query.with_for_update()

        rows = list((await db.execute(query)).scalars().all())

        return {assignment.class_id: assignment for assignment in rows}

    @staticmethod
    async def list_teacher_assignments_for_curriculum_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        class_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> list[TeacherAssignment]:
        query = (
            select(TeacherAssignment)
            .where(
                TeacherAssignment.tenant_id == tenant_id,
                TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
                TeacherAssignment.class_id == class_id,
            )
            .order_by(
                TeacherAssignment.effective_from.asc(),
                TeacherAssignment.created_at.asc(),
            )
        )
        if lock:
            query = query.with_for_update()
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def get_later_teacher_assignments(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        class_id: uuid.UUID,
        effective_from: date,
        *,
        exclude_id: uuid.UUID | None = None,
        lock: bool = False,
    ) -> list[TeacherAssignment]:
        filters = [
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.curriculum_subject_id == curriculum_subject_id,
            TeacherAssignment.class_id == class_id,
            TeacherAssignment.effective_from > effective_from,
        ]
        if exclude_id is not None:
            filters.append(TeacherAssignment.id != exclude_id)
        query = (
            select(TeacherAssignment)
            .where(*filters)
            .order_by(TeacherAssignment.effective_from.asc())
        )
        if lock:
            query = query.with_for_update()
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_teacher_assignment_rows(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        teacher_id: uuid.UUID | None = None,
        class_id: uuid.UUID | None = None,
        curriculum_subject_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        status: str | None = None,
        effective_from_from: date | None = None,
        effective_from_to: date | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict], int]:
        filters = [
            TeacherAssignment.tenant_id == tenant_id,
            CurriculumSubject.tenant_id == tenant_id,
        ]
        if teacher_id is not None:
            filters.append(TeacherAssignment.teacher_membership_id == teacher_id)
        if curriculum_subject_id is not None:
            filters.append(TeacherAssignment.curriculum_subject_id == curriculum_subject_id)
        if class_id is not None:
            filters.append(TeacherAssignment.class_id == class_id)
        if subject_id is not None:
            filters.append(CurriculumSubject.subject_id == subject_id)
        today = func.current_date()
        if status == "scheduled":
            filters.append(TeacherAssignment.effective_from > today)
        elif status == "current":
            filters.append(TeacherAssignment.is_active.is_(True))
        elif status == "ended":
            filters.append(
                and_(
                    TeacherAssignment.effective_to.is_not(None),
                    TeacherAssignment.effective_to < today,
                )
            )
        if effective_from_from is not None:
            filters.append(TeacherAssignment.effective_from >= effective_from_from)
        if effective_from_to is not None:
            filters.append(TeacherAssignment.effective_from <= effective_from_to)
        if search:
            pattern = f"%{escape_like(search.strip())}%"
            teacher_name = func.concat(
                func.coalesce(TeacherAccount.first_name, ""),
                " ",
                func.coalesce(TeacherAccount.last_name, ""),
            )
            filters.append(
                or_(
                    teacher_name.ilike(pattern, escape="\\"),
                    TeacherMembership.staff_id.ilike(pattern, escape="\\"),
                    AcademicLevel.name.ilike(pattern, escape="\\"),
                    ArmLabel.label.ilike(pattern, escape="\\"),
                    Subject.name.ilike(pattern, escape="\\"),
                    Subject.code.ilike(pattern, escape="\\"),
                )
            )

        def _base_query():
            return (
                select(TeacherAssignment)
                .join(
                    CurriculumSubject,
                    CurriculumSubject.id == TeacherAssignment.curriculum_subject_id,
                )
                .join(ClassRoom, ClassRoom.id == TeacherAssignment.class_id, isouter=True)
                .join(
                    AcademicLevel,
                    AcademicLevel.id == ClassRoom.academic_level_id,
                    isouter=True,
                )
                .join(ArmLabel, ArmLabel.id == ClassRoom.arm_label_id, isouter=True)
                .join(Subject, Subject.id == CurriculumSubject.subject_id, isouter=True)
                .join(
                    TeacherMembership,
                    TeacherMembership.id == TeacherAssignment.teacher_membership_id,
                    isouter=True,
                )
                .join(
                    TeacherAccount,
                    TeacherAccount.id == TeacherMembership.teacher_account_id,
                    isouter=True,
                )
                .where(*filters)
            )

        total = (
            await db.execute(select(func.count()).select_from(_base_query().subquery()))
        ).scalar_one()
        lifecycle_order = case(
            (TeacherAssignment.is_active.is_(True), 0),
            (TeacherAssignment.effective_from > today, 1),
            else_=2,
        )
        rows = (
            await db.execute(
                select(
                    TeacherAssignment,
                    TeacherAssignment.class_id.label("class_id"),
                    CurriculumSubject.subject_id.label("subject_id"),
                    AcademicLevel.name.label("class_name"),
                    ArmLabel.label.label("class_arm"),
                    Subject.name.label("subject_name"),
                    Subject.code.label("subject_code"),
                    TeacherMembership.staff_id.label("teacher_staff_id"),
                    TeacherAccount.first_name.label("teacher_first_name"),
                    TeacherAccount.last_name.label("teacher_last_name"),
                )
                .join(
                    CurriculumSubject,
                    CurriculumSubject.id == TeacherAssignment.curriculum_subject_id,
                )
                .join(ClassRoom, ClassRoom.id == TeacherAssignment.class_id, isouter=True)
                .join(
                    AcademicLevel,
                    AcademicLevel.id == ClassRoom.academic_level_id,
                    isouter=True,
                )
                .join(ArmLabel, ArmLabel.id == ClassRoom.arm_label_id, isouter=True)
                .join(Subject, Subject.id == CurriculumSubject.subject_id, isouter=True)
                .join(
                    TeacherMembership,
                    TeacherMembership.id == TeacherAssignment.teacher_membership_id,
                    isouter=True,
                )
                .join(
                    TeacherAccount,
                    TeacherAccount.id == TeacherMembership.teacher_account_id,
                    isouter=True,
                )
                .where(*filters)
                .order_by(
                    lifecycle_order.asc(),
                    TeacherAssignment.effective_from.desc(),
                    TeacherAssignment.created_at.desc(),
                )
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [
            {
                "assignment": row[0],
                "class_id": row.class_id,
                "subject_id": row.subject_id,
                "class_name": row.class_name,
                "class_arm": row.class_arm,
                "subject_name": row.subject_name,
                "subject_code": row.subject_code,
                "teacher_staff_id": row.teacher_staff_id,
                "teacher_name": " ".join(
                    part for part in [row.teacher_first_name, row.teacher_last_name] if part
                )
                or None,
            }
            for row in rows
        ], int(total)

    @staticmethod
    async def get_scheduled_takeovers_for_assignments(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        assignments: list[TeacherAssignment],
    ) -> dict[uuid.UUID, dict]:
        """Load adjacent future successors for a page of predecessor rows in one query."""

        predecessors = [
            assignment
            for assignment in assignments
            if assignment.state.value == "current" and assignment.effective_to is not None
        ]
        if not predecessors:
            return {}

        scope_filters = [
            and_(
                TeacherAssignment.class_id == predecessor.class_id,
                TeacherAssignment.curriculum_subject_id == predecessor.curriculum_subject_id,
                TeacherAssignment.effective_from == predecessor.effective_to + date.resolution,
            )
            for predecessor in predecessors
        ]
        rows = (
            await db.execute(
                select(
                    TeacherAssignment,
                    TeacherAccount.first_name.label("teacher_first_name"),
                    TeacherAccount.last_name.label("teacher_last_name"),
                )
                .join(
                    TeacherMembership,
                    TeacherMembership.id == TeacherAssignment.teacher_membership_id,
                    isouter=True,
                )
                .join(
                    TeacherAccount,
                    TeacherAccount.id == TeacherMembership.teacher_account_id,
                    isouter=True,
                )
                .where(
                    TeacherAssignment.tenant_id == tenant_id,
                    TeacherAssignment.effective_from > func.current_date(),
                    or_(*scope_filters),
                )
            )
        ).all()
        predecessor_by_boundary = {
            (
                predecessor.class_id,
                predecessor.curriculum_subject_id,
                predecessor.effective_to + date.resolution,
            ): predecessor.id
            for predecessor in predecessors
        }
        takeovers: dict[uuid.UUID, dict] = {}
        for row in rows:
            successor = row[0]
            predecessor_id = predecessor_by_boundary.get(
                (
                    successor.class_id,
                    successor.curriculum_subject_id,
                    successor.effective_from,
                )
            )
            if predecessor_id is None:
                continue
            takeovers[predecessor_id] = {
                "id": successor.id,
                "class_id": successor.class_id,
                "curriculum_subject_id": successor.curriculum_subject_id,
                "teacher_membership_id": successor.teacher_membership_id,
                "teacher_name": " ".join(
                    part for part in [row.teacher_first_name, row.teacher_last_name] if part
                )
                or None,
                "effective_from": successor.effective_from,
            }
        return takeovers

    @staticmethod
    async def save_teacher_assignment(
        db: AsyncSession, assignment: TeacherAssignment
    ) -> TeacherAssignment:
        return await StudentAcademicRepository._save(db, assignment)

    @staticmethod
    async def has_teacher_assignment_dependencies(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
    ) -> bool:
        return (
            await StudentAcademicRepository.count_scores_for_teacher_assignment(
                db, tenant_id, teacher_assignment_id
            )
            > 0
        )

    @staticmethod
    async def count_teacher_assignment_dependencies(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
    ) -> dict[str, int]:
        from app.modules.report_cards.models import ReportCardSubjectLine

        student_results = await StudentAcademicRepository.count_scores_for_teacher_assignment(
            db, tenant_id, teacher_assignment_id
        )
        report_card_references = (
            await db.execute(
                select(func.count())
                .select_from(ReportCardSubjectLine)
                .join(
                    StudentSubjectResult,
                    StudentSubjectResult.id == ReportCardSubjectLine.student_subject_result_id,
                )
                .where(
                    ReportCardSubjectLine.tenant_id == tenant_id,
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.teacher_assignment_id == teacher_assignment_id,
                )
            )
        ).scalar_one()
        return {
            "student_results": int(student_results),
            "report_card_references": int(report_card_references),
            "other_academic_records": 0,
        }

    @staticmethod
    async def delete_teacher_assignment(db: AsyncSession, assignment: TeacherAssignment) -> None:
        await db.delete(assignment)
        await db.flush()

    @staticmethod
    async def count_scores_for_teacher_assignment(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
    ) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(StudentSubjectResult)
                    .where(
                        StudentSubjectResult.tenant_id == tenant_id,
                        StudentSubjectResult.teacher_assignment_id == teacher_assignment_id,
                    )
                )
            ).scalar_one()
        )

    @staticmethod
    async def get_result_by_teacher_assignment_scope(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        teacher_assignment_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> StudentSubjectResult | None:
        curriculum_subject_id = (
            await StudentAcademicRepository._curriculum_subject_id_for_assignment(
                db, tenant_id, teacher_assignment_id
            )
        )
        if curriculum_subject_id is None:
            return None
        return (
            await db.execute(
                select(StudentSubjectResult).where(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.student_id == student_id,
                    StudentSubjectResult.curriculum_subject_id == curriculum_subject_id,
                    StudentSubjectResult.academic_session_id == academic_session_id,
                    StudentSubjectResult.academic_term_id == academic_term_id,
                )
            )
        ).scalar_one_or_none()
