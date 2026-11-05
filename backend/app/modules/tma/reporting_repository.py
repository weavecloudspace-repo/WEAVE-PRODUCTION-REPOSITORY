"""Tenant-scoped, paginated read query for assignment participation.

The roster is the union of currently eligible students and historical TMA
participants. Historical attempts survive class, elective or level changes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, exists, func, literal_column, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.classes.models import AcademicLevel, ArmLabel, ClassRoom
from app.modules.student_academics.curriculum_models import StudentElectiveSelection
from app.modules.student_academics.models import StudentAssessmentScore, StudentSubjectResult
from app.modules.students.models import AcademicStatus, Student, StudentEnrollment
from app.modules.tma.models import (
    TMAAssignment,
    TMAAssignmentRevision,
    TMAAttempt,
    TMAAttemptStatus,
    TMAParticipant,
)
from app.modules.tma.schemas import TMAParticipationStatus


class TMAReportingRepository:
    @staticmethod
    def _query(
        assignment: TMAAssignment,
        *,
        authorized_class_ids: set[uuid.UUID] | None = None,
        regular_class_ids: set[uuid.UUID],
        grouped_elective_class_ids: set[uuid.UUID],
        search: str | None = None,
        class_id: uuid.UUID | None = None,
        participation_status: TMAParticipationStatus | None = None,
    ):
        """Build a tenant-bounded query without per-student database lookups."""
        tenant_id = assignment.tenant_id
        enrollment = StudentEnrollment

        conditions = []
        if regular_class_ids:
            conditions.append(enrollment.class_id.in_(regular_class_ids))
        if grouped_elective_class_ids:
            selected = exists(
                select(StudentElectiveSelection.id).where(
                    StudentElectiveSelection.tenant_id == tenant_id,
                    StudentElectiveSelection.student_id == enrollment.student_id,
                    StudentElectiveSelection.curriculum_subject_id
                    == assignment.curriculum_subject_id,
                )
            )
            conditions.append(and_(enrollment.class_id.in_(grouped_elective_class_ids), selected))
        if authorized_class_ids is not None:
            conditions = [
                and_(condition, enrollment.class_id.in_(authorized_class_ids))
                for condition in conditions
            ]
        eligible_condition = or_(*conditions) if conditions else False
        eligible = (
            select(
                enrollment.student_id.label("student_id"),
                enrollment.class_id.label("class_id"),
            )
            .join(
                Student,
                and_(Student.id == enrollment.student_id, Student.tenant_id == tenant_id),
            )
            .where(
                enrollment.tenant_id == tenant_id,
                enrollment.academic_session_id == assignment.academic_session_id,
                enrollment.academic_level_id == assignment.academic_level_id,
                enrollment.is_current.is_(True),
                Student.status == AcademicStatus.ACTIVE,
                Student.is_active.is_(True),
                Student.is_archived.is_(False),
                eligible_condition,
            )
        )
        # Current enrollment is always the live roster. Deadline evidence is
        # preserved for audit and zero-grading, never used to deny access.
        eligible = eligible.subquery("eligible")

        priority = case(
            (TMAAttempt.status == TMAAttemptStatus.SUBMITTED, 2),
            (TMAAttempt.status == TMAAttemptStatus.IN_PROGRESS, 1),
            else_=0,
        )
        ranked = (
            select(
                TMAParticipant.student_id.label("student_id"),
                TMAParticipant.class_id.label("class_id"),
                TMAAttempt.status.label("attempt_status"),
                TMAAttempt.submitted_at.label("submitted_at"),
                TMAAttempt.auto_zeroed_at.label("auto_zeroed_at"),
                TMAAttempt.auto_zero_resolved_at.label("auto_zero_resolved_at"),
                TMAAttempt.started_by_student.label("started_by_student"),
                func.row_number()
                .over(
                    partition_by=TMAParticipant.student_id,
                    order_by=(
                        priority.desc(),
                        TMAAssignmentRevision.revision_number.desc(),
                        TMAParticipant.created_at.desc(),
                        TMAParticipant.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .join(
                TMAAssignmentRevision,
                and_(
                    TMAAssignmentRevision.id == TMAParticipant.revision_id,
                    TMAAssignmentRevision.tenant_id == tenant_id,
                    TMAAssignmentRevision.assignment_id == assignment.id,
                ),
            )
            .outerjoin(
                TMAAttempt,
                and_(
                    TMAAttempt.participant_id == TMAParticipant.id,
                    TMAAttempt.tenant_id == tenant_id,
                ),
            )
            .where(
                TMAParticipant.tenant_id == tenant_id,
                TMAAssignmentRevision.invalidated_at.is_(None),
                TMAAssignmentRevision.revision_number == assignment.current_revision_number,
                *(
                    [TMAParticipant.class_id.in_(authorized_class_ids)]
                    if authorized_class_ids is not None
                    else []
                ),
            )
            .subquery("ranked_participation")
        )
        history = (
            select(
                ranked.c.student_id,
                ranked.c.class_id,
                ranked.c.attempt_status,
                ranked.c.submitted_at,
                ranked.c.auto_zeroed_at,
                ranked.c.auto_zero_resolved_at,
                ranked.c.started_by_student,
            )
            .where(ranked.c.rank == 1)
            .subquery("history")
        )
        student_ids = union(
            select(eligible.c.student_id),
            select(history.c.student_id),
        ).subquery("student_ids")

        display_class_id = func.coalesce(eligible.c.class_id, history.c.class_id)
        status = case(
            (history.c.attempt_status == TMAAttemptStatus.IN_PROGRESS, "in_progress"),
            (
                (history.c.attempt_status == TMAAttemptStatus.SUBMITTED)
                & (
                    history.c.auto_zeroed_at.is_(None)
                    | history.c.auto_zero_resolved_at.is_not(None)
                ),
                "submitted",
            ),
            (
                history.c.auto_zeroed_at.is_not(None) & (history.c.started_by_student.is_(False)),
                "not_started",
            ),
            # Old system-issued attempts with no start provenance remain
            # conservatively MISSED (unknown start), not falsely NOT_STARTED.
            (history.c.auto_zeroed_at.is_not(None), "missed"),
            else_="not_started",
        )
        # Keep the substring expression identical to the immutable trigram index.
        name = func.btrim(
            func.coalesce(Student.first_name, literal_column("''"))
            + literal_column("' '")
            + func.coalesce(Student.last_name, literal_column("''"))
        )
        base = (
            select(
                Student.id.label("student_id"),
                Student.admission_number,
                name.label("student_name"),
                display_class_id.label("class_id"),
                func.concat_ws(" ", AcademicLevel.name, ArmLabel.label).label("class_name"),
                status.label("participation_status"),
                case(
                    (
                        history.c.attempt_status == TMAAttemptStatus.SUBMITTED,
                        StudentAssessmentScore.score,
                    ),
                    else_=None,
                ).label("score"),
                case(
                    (
                        history.c.attempt_status == TMAAttemptStatus.SUBMITTED,
                        history.c.submitted_at,
                    ),
                    else_=None,
                ).label("submitted_at"),
                eligible.c.student_id.is_not(None).label("is_currently_eligible"),
            )
            .select_from(student_ids)
            .join(
                Student,
                and_(
                    Student.id == student_ids.c.student_id,
                    Student.tenant_id == tenant_id,
                ),
            )
            .outerjoin(eligible, eligible.c.student_id == Student.id)
            .outerjoin(history, history.c.student_id == Student.id)
            .outerjoin(
                ClassRoom,
                and_(ClassRoom.id == display_class_id, ClassRoom.tenant_id == tenant_id),
            )
            .outerjoin(
                AcademicLevel,
                and_(
                    AcademicLevel.id == ClassRoom.academic_level_id,
                    AcademicLevel.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                ArmLabel,
                and_(ArmLabel.id == ClassRoom.arm_label_id, ArmLabel.tenant_id == tenant_id),
            )
            .outerjoin(
                StudentSubjectResult,
                and_(
                    StudentSubjectResult.tenant_id == tenant_id,
                    StudentSubjectResult.student_id == Student.id,
                    StudentSubjectResult.curriculum_subject_id == assignment.curriculum_subject_id,
                    StudentSubjectResult.academic_session_id == assignment.academic_session_id,
                    StudentSubjectResult.academic_term_id == assignment.academic_term_id,
                ),
            )
            .outerjoin(
                StudentAssessmentScore,
                and_(
                    StudentAssessmentScore.tenant_id == tenant_id,
                    StudentAssessmentScore.student_subject_result_id == StudentSubjectResult.id,
                    StudentAssessmentScore.assessment_component_id
                    == assignment.assessment_component_id,
                ),
            )
        )
        if class_id is not None:
            base = base.where(display_class_id == class_id)
        if participation_status is not None:
            base = base.where(status == participation_status.value)
        if search:
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            if escaped:
                pattern = f"%{escaped}%"
                base = base.where(
                    or_(
                        name.ilike(pattern, escape="\\"),
                        Student.admission_number.ilike(pattern, escape="\\"),
                    )
                )
        return base

    @classmethod
    async def list_participation(
        cls,
        db: AsyncSession,
        *,
        assignment: TMAAssignment,
        authorized_class_ids: set[uuid.UUID] | None = None,
        regular_class_ids: set[uuid.UUID],
        grouped_elective_class_ids: set[uuid.UUID],
        search: str | None,
        class_id: uuid.UUID | None,
        participation_status: TMAParticipationStatus | None,
        offset: int,
        limit: int,
    ):
        query = cls._query(
            assignment,
            authorized_class_ids=authorized_class_ids,
            regular_class_ids=regular_class_ids,
            grouped_elective_class_ids=grouped_elective_class_ids,
            search=search,
            class_id=class_id,
            participation_status=participation_status,
        )
        count = select(func.count()).select_from(query.subquery())
        total = int((await db.execute(count)).scalar_one())
        order = (
            func.lower(func.coalesce(Student.last_name, "")),
            func.lower(func.coalesce(Student.first_name, "")),
            Student.admission_number,
            Student.id,
        )
        rows = (
            (await db.execute(query.order_by(*order).offset(offset).limit(limit))).mappings().all()
        )
        return list(rows), total
