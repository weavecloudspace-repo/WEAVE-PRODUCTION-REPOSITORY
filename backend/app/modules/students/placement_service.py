"""Canonical immutable student placement workflow.

Initial class placement is deliberately distinct from reassignment. Academic
CBT/TMA attempts and score evidence retain their original enrollment context.
Compatible canonical DRAFT results follow same-level class reassignments.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.classes.models import (
    AcademicLevel,
    AcademicLevelDepartment,
    ArmLabel,
    ClassRoom,
    Department,
)
from app.modules.classes.repository import ClassRoomRepository
from app.modules.report_cards.comment_models import StudentTermTeacherComment, TeacherCommentStatus
from app.modules.report_cards.comment_service import ReportCommentService
from app.modules.report_cards.models import ReportCard
from app.modules.report_cards.cache import ReportReadinessCache
from app.modules.student_academics.curriculum_models import (
    ClassTermDepartmentAssignment,
    StudentElectiveSelection,
)
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.lifecycle_repository import AcademicSessionLifecycleRepository
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermStatus,
    StudentSubjectResult,
)
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.students.enrollment_schemas import (
    PlacementImpactPreviewRequest,
    PlacementImpactPreviewResponse,
    PlacementImpactSubject,
    PlacementResultImpact,
    StudentAcademicLevelReassignmentRequest,
    StudentClassPlacementRequest,
    StudentClassPlacementResponse,
    StudentClassReassignmentRequest,
    StudentUpcomingEnrollmentUpdateRequest,
)
from app.modules.students.models import (
    AcademicStatus,
    StudentEnrollment,
    StudentEnrollmentOutcome,
)
from app.modules.students.enrollment_evidence import StudentEnrollmentEvidenceService
from app.modules.students.result_continuity import AcademicResultContinuityService
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.students.schemas import (
    StudentDetailResponse,
    StudentEnrollmentDetailResponse,
    StudentLifecycleReasonRequest,
)
from app.modules.students.service import StudentService
from app.modules.subjects.repository import SubjectRepository
from app.modules.tenant_admins.models import TenantAdmin


class StudentPlacementService:
    """Own placement history, initial class placement, and reassignment."""

    @staticmethod
    async def list_history(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
    ) -> list[StudentEnrollmentDetailResponse]:
        student = await StudentRepository.get_by_id(
            db, tenant_id, student_id, include_archived=True
        )
        if student is None:
            raise NotFoundException("Student not found.")
        rows = (
            await db.execute(
                select(StudentEnrollment, ClassRoom, AcademicLevel, AcademicSession, ArmLabel)
                .join(AcademicLevel, AcademicLevel.id == StudentEnrollment.academic_level_id)
                .join(AcademicSession, AcademicSession.id == StudentEnrollment.academic_session_id)
                .outerjoin(
                    ClassRoom,
                    and_(
                        ClassRoom.id == StudentEnrollment.class_id,
                        ClassRoom.tenant_id == tenant_id,
                    ),
                )
                .outerjoin(
                    ArmLabel,
                    and_(
                        ArmLabel.id == ClassRoom.arm_label_id,
                        ArmLabel.tenant_id == tenant_id,
                    ),
                )
                .where(
                    StudentEnrollment.tenant_id == tenant_id,
                    StudentEnrollment.student_id == student_id,
                    AcademicLevel.tenant_id == tenant_id,
                    AcademicSession.tenant_id == tenant_id,
                )
                .order_by(
                    StudentEnrollment.started_on.asc(),
                    StudentEnrollment.created_at.asc(),
                )
            )
        ).all()
        output: list[StudentEnrollmentDetailResponse] = []
        for enrollment, classroom, level, session, arm_label in rows:
            base = StudentEnrollmentDetailResponse.model_validate(enrollment).model_dump(
                exclude={
                    "class_name",
                    "class_arm",
                    "academic_level_name",
                    "academic_session_name",
                    "lifecycle_state",
                }
            )
            today = date.today()
            output.append(
                StudentEnrollmentDetailResponse(
                    **base,
                    class_name=level.name if classroom else None,
                    class_arm=arm_label.label if arm_label else None,
                    academic_level_name=level.name,
                    academic_session_name=session.name,
                    lifecycle_state=(
                        "upcoming"
                        if enrollment.started_on > today
                        else "current"
                        if enrollment.ended_on is None or enrollment.ended_on >= today
                        else "historical"
                    ),
                )
            )
        return output

    @staticmethod
    async def _require_open_session(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        academic_session_id: UUID,
    ) -> AcademicSession:
        session = await AcademicSessionLifecycleRepository.get_by_id(
            db, tenant_id, academic_session_id, lock=True
        )
        if (
            session is None
            or not session.is_current
            or session.status != AcademicSessionStatus.OPEN
        ):
            raise NotFoundException("Academic session not found or not open.")
        return session

    @staticmethod
    async def _require_target_class(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        class_id: UUID,
    ) -> ClassRoom:
        classroom = await ClassRoomRepository.get_by_id(db, tenant_id, class_id, lock=True)
        if classroom is None or not classroom.is_active or classroom.archived_at is not None:
            raise NotFoundException("Target class not found.")
        return classroom

    @staticmethod
    async def _create_segment(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        academic_level_id: UUID,
        class_id: UUID,
        academic_session_id: UUID,
        started_on: date,
        outcome: StudentEnrollmentOutcome,
        reason: str,
        acting_admin_id: UUID,
    ) -> StudentEnrollment:
        enrollment = StudentEnrollment(
            tenant_id=tenant_id,
            student_id=student_id,
            academic_level_id=academic_level_id,
            class_id=class_id,
            academic_session_id=academic_session_id,
            started_on=started_on,
            entry_outcome=outcome,
            entry_reason=reason,
            created_by_admin_id=acting_admin_id,
        )
        try:
            return await StudentEnrollmentRepository.add(db, enrollment)
        except IntegrityError as exc:
            raise ConflictException(
                "Student enrollment overlaps existing placement history."
            ) from exc

    @staticmethod
    async def _close_segment(
        db: AsyncSession,
        *,
        enrollment: StudentEnrollment,
        ended_on: date,
        outcome: StudentEnrollmentOutcome,
        reason: str,
        acting_admin_id: UUID,
    ) -> None:
        if ended_on < enrollment.started_on:
            raise ConflictException(
                "Placement effective date must follow the current segment start."
            )
        enrollment.ended_on = ended_on
        enrollment.exit_outcome = outcome
        enrollment.exit_reason = reason
        enrollment.ended_by_admin_id = acting_admin_id
        await StudentEnrollmentRepository.save(db, enrollment)

    @staticmethod
    async def _invalidate_derived_context(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        academic_session_id: UUID,
    ) -> None:
        # Only invalidate Redis after the database transaction commits.
        await ReportCommentService.invalidate_for_placement_change(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            invalidate_readiness_cache=False,
        )
        cards = list(
            (
                await db.execute(
                    select(ReportCard).where(
                        ReportCard.tenant_id == tenant_id,
                        ReportCard.student_id == student_id,
                        ReportCard.academic_session_id == academic_session_id,
                        ReportCard.superseded_at.is_(None),
                    )
                )
            ).scalars()
        )
        for card in cards:
            card.is_outdated = True
            db.add(card)

    @staticmethod
    async def _commit_with_readiness_invalidation(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        academic_session_id: UUID,
    ) -> None:
        await db.commit()
        await ReportReadinessCache.invalidate_student_session(
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
        )

    @staticmethod
    async def _correct_same_day_placement(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        enrollment: StudentEnrollment,
        target_academic_level_id: UUID,
        target_class_id: UUID,
        reason: str,
    ) -> None:
        counts = await StudentEnrollmentEvidenceService.segment_dependency_counts(
            db,
            tenant_id=actor.tenant_id,
            enrollment_id=enrollment.id,
        )
        blockers = {name: count for name, count in counts.items() if count > 0}
        if blockers:
            raise ConflictException(
                "This same-day placement can no longer be corrected because academic activity "
                "already depends on it. Use a later reassignment instead.",
                payload={"dependency_counts": blockers},
            )

        previous_level_id = enrollment.academic_level_id
        previous_class_id = enrollment.class_id
        enrollment.academic_level_id = target_academic_level_id
        enrollment.class_id = target_class_id
        await StudentEnrollmentRepository.save(db, enrollment)
        await StudentAcademicRepository.add_academic_lifecycle_audit(
            db,
            AcademicLifecycleAudit(
                tenant_id=actor.tenant_id,
                entity_type="student",
                entity_id=enrollment.student_id,
                action="student_placement_corrected",
                previous_status="placed",
                new_status="placed",
                acting_admin_id=actor.id,
                reason=reason,
                metadata_json={
                    "enrollment_id": str(enrollment.id),
                    "effective_date": enrollment.started_on.isoformat(),
                    "previous_academic_level_id": str(previous_level_id),
                    "previous_class_id": str(previous_class_id) if previous_class_id else None,
                    "new_academic_level_id": str(target_academic_level_id),
                    "new_class_id": str(target_class_id),
                },
            ),
        )

    @staticmethod
    async def place_class(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        payload: StudentClassPlacementRequest,
    ) -> StudentClassPlacementResponse:
        """Bulk-place only unassigned enrollments; academic evidence never blocks this."""

        tenant_id = actor.tenant_id
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        session = await StudentPlacementService._require_open_session(
            db, tenant_id=tenant_id, academic_session_id=payload.academic_session_id
        )
        target_class = await StudentPlacementService._require_target_class(
            db, tenant_id=tenant_id, class_id=payload.target_class_id
        )
        if target_class.academic_level_id != payload.academic_level_id:
            raise BadRequestException("Target class must belong to the selected academic level.")

        placed_ids: list[UUID] = []
        effective_date = date.today()
        for student_id in payload.student_ids:
            student = await StudentRepository.get_by_id(db, tenant_id, student_id, lock=True)
            if student is None:
                raise NotFoundException(f"Student {student_id} not found.")
            if student.status not in {AcademicStatus.ACTIVE, AcademicStatus.SUSPENDED}:
                raise BadRequestException("Only active or suspended students can be placed.")
            current = await StudentEnrollmentRepository.get_current(
                db, tenant_id, student.id, lock=True
            )
            if current is None or current.academic_session_id != session.id:
                raise ConflictException(
                    "Student has no current enrollment for the selected academic session."
                )
            if current.academic_level_id != payload.academic_level_id:
                raise BadRequestException(
                    "Class placement cannot change the student's academic level."
                )
            if current.class_id is not None:
                raise ConflictException("Student is already classed; use Reassign Class instead.")

            # A fresh/today-or-future enrollment has no meaningful unassigned time
            # to preserve. Mutate only class_id and retain ENROLLED/PROMOTED/etc.
            if current.started_on >= effective_date:
                current.class_id = target_class.id
                await StudentEnrollmentRepository.save(db, current)
            else:
                # Preserve the real unassigned interval as its own immutable segment.
                reason = "Initial class placement"
                await StudentPlacementService._close_segment(
                    db,
                    enrollment=current,
                    ended_on=effective_date - timedelta(days=1),
                    outcome=StudentEnrollmentOutcome.CLASS_PLACED,
                    reason=reason,
                    acting_admin_id=actor.id,
                )
                await StudentPlacementService._create_segment(
                    db,
                    tenant_id=tenant_id,
                    student_id=student.id,
                    academic_level_id=current.academic_level_id,
                    class_id=target_class.id,
                    academic_session_id=current.academic_session_id,
                    started_on=effective_date,
                    outcome=StudentEnrollmentOutcome.CLASS_PLACED,
                    reason=reason,
                    acting_admin_id=actor.id,
                )
            placed_ids.append(student.id)

        await db.commit()
        return StudentClassPlacementResponse(
            placed_student_ids=placed_ids,
            target_class_id=target_class.id,
            placed_count=len(placed_ids),
        )

    @staticmethod
    async def reassign_class(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: StudentClassReassignmentRequest,
    ) -> StudentDetailResponse:
        tenant_id = actor.tenant_id
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        student = await StudentRepository.get_by_id(db, tenant_id, student_id, lock=True)
        if student is None:
            raise NotFoundException("Student not found.")
        if student.status not in {AcademicStatus.ACTIVE, AcademicStatus.SUSPENDED}:
            raise BadRequestException("Only active or suspended students can be reassigned.")
        session = await StudentPlacementService._require_open_session(
            db, tenant_id=tenant_id, academic_session_id=payload.academic_session_id
        )
        target_class = await StudentPlacementService._require_target_class(
            db, tenant_id=tenant_id, class_id=payload.target_class_id
        )
        current = await StudentEnrollmentRepository.get_current(
            db, tenant_id, student.id, lock=True
        )
        if current is None or current.academic_session_id != session.id:
            raise ConflictException("Student has no current enrollment for this session.")
        if (
            await StudentEnrollmentRepository.get_upcoming(
                db,
                tenant_id,
                student.id,
                lock=True,
            )
            is not None
        ):
            raise ConflictException(
                "Student already has an upcoming enrollment. Edit or cancel it first.",
                payload={"code": "UPCOMING_ENROLLMENT_EXISTS"},
            )
        if current.class_id is None:
            raise ConflictException("Unassigned students must use Class Placement.")
        if target_class.academic_level_id != current.academic_level_id:
            raise BadRequestException("Reassign Class cannot change academic level.")
        if target_class.id == current.class_id:
            raise ConflictException("Student is already in the target class.")
        if payload.effective_date == current.started_on == date.today():
            await StudentPlacementService._correct_same_day_placement(
                db,
                actor=actor,
                enrollment=current,
                target_academic_level_id=current.academic_level_id,
                target_class_id=target_class.id,
                reason=payload.reason,
            )
            await StudentPlacementService._invalidate_derived_context(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
            await StudentPlacementService._commit_with_readiness_invalidation(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
            return await StudentService.get_student_profile(db, actor, student.id)
        if payload.effective_date <= current.started_on:
            raise BadRequestException(
                "Reassignment must follow the current placement start. Only a placement that "
                "started today can be corrected on the same date."
            )

        await StudentPlacementService._close_segment(
            db,
            enrollment=current,
            ended_on=payload.effective_date - timedelta(days=1),
            outcome=StudentEnrollmentOutcome.RECLASSIFIED,
            reason=payload.reason,
            acting_admin_id=actor.id,
        )
        destination_enrollment = await StudentPlacementService._create_segment(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_level_id=current.academic_level_id,
            class_id=target_class.id,
            academic_session_id=current.academic_session_id,
            started_on=payload.effective_date,
            outcome=StudentEnrollmentOutcome.RECLASSIFIED,
            reason=payload.reason,
            acting_admin_id=actor.id,
        )
        if payload.effective_date > date.today():
            # The worker revalidates and transfers results only when this
            # immutable destination enrollment becomes effective.
            await StudentAcademicRepository.add_academic_lifecycle_audit(
                db,
                AcademicLifecycleAudit(
                    tenant_id=tenant_id,
                    entity_type="student_enrollment",
                    entity_id=destination_enrollment.id,
                    action="result_continuity_scheduled",
                    acting_admin_id=actor.id,
                    reason=payload.reason,
                    metadata_json={
                        "student_id": str(student.id),
                        "academic_session_id": str(current.academic_session_id),
                        "source_level_id": str(current.academic_level_id),
                        "carry_finalized_results": payload.carry_finalized_results,
                    },
                ),
            )
            await db.commit()
        else:
            await AcademicResultContinuityService.apply(
                db,
                actor_id=actor.id,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
                source_level_id=current.academic_level_id,
                destination_enrollment=destination_enrollment,
                effective_date=payload.effective_date,
                reason=payload.reason,
                carry_finalized_results=payload.carry_finalized_results,
            )
            await StudentPlacementService._invalidate_derived_context(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
            await StudentPlacementService._commit_with_readiness_invalidation(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
        return await StudentService.get_student_profile(db, actor, student.id)

    @staticmethod
    async def reconcile_existing_results(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        academic_session_id: UUID,
        reason: str,
        carry_finalized_results: bool = False,
    ) -> StudentDetailResponse:
        """Repair prior same-level class moves without creating another enrollment."""
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        student = await StudentRepository.get_by_id(db, actor.tenant_id, student_id, lock=True)
        if student is None:
            raise NotFoundException("Student not found.")
        await StudentPlacementService._require_open_session(
            db, tenant_id=actor.tenant_id, academic_session_id=academic_session_id
        )
        current = await StudentEnrollmentRepository.get_current(
            db, actor.tenant_id, student.id, lock=True
        )
        if (
            current is None
            or current.academic_session_id != academic_session_id
            or current.class_id is None
        ):
            raise ConflictException("No current placement exists for this academic session.")
        decisions = await AcademicResultContinuityService.apply(
            db,
            actor_id=actor.id,
            tenant_id=actor.tenant_id,
            student_id=student.id,
            academic_session_id=academic_session_id,
            source_level_id=current.academic_level_id,
            destination_enrollment=current,
            effective_date=date.today(),
            reason=reason,
            carry_finalized_results=carry_finalized_results,
        )
        if any(decision.applied for decision in decisions):
            await StudentPlacementService._invalidate_derived_context(
                db,
                tenant_id=actor.tenant_id,
                student_id=student.id,
                academic_session_id=academic_session_id,
            )
            await StudentPlacementService._commit_with_readiness_invalidation(
                db,
                tenant_id=actor.tenant_id,
                student_id=student.id,
                academic_session_id=academic_session_id,
            )
        else:
            await db.commit()
        return await StudentService.get_student_profile(db, actor, student.id)

    @staticmethod
    async def reassign_academic_level(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: StudentAcademicLevelReassignmentRequest,
    ) -> StudentDetailResponse:
        tenant_id = actor.tenant_id
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        student = await StudentRepository.get_by_id(db, tenant_id, student_id, lock=True)
        if student is None:
            raise NotFoundException("Student not found.")
        if student.status not in {AcademicStatus.ACTIVE, AcademicStatus.SUSPENDED}:
            raise BadRequestException("Only active or suspended students can be reassigned.")
        session = await StudentPlacementService._require_open_session(
            db, tenant_id=tenant_id, academic_session_id=payload.academic_session_id
        )
        target_class = await StudentPlacementService._require_target_class(
            db, tenant_id=tenant_id, class_id=payload.target_class_id
        )
        if target_class.academic_level_id != payload.target_academic_level_id:
            raise BadRequestException("Target class does not belong to the target academic level.")
        current = await StudentEnrollmentRepository.get_current(
            db, tenant_id, student.id, lock=True
        )
        if current is None or current.academic_session_id != session.id:
            raise ConflictException("Student has no current enrollment for this session.")
        if (
            await StudentEnrollmentRepository.get_upcoming(
                db,
                tenant_id,
                student.id,
                lock=True,
            )
            is not None
        ):
            raise ConflictException(
                "Student already has an upcoming enrollment. Edit or cancel it first.",
                payload={"code": "UPCOMING_ENROLLMENT_EXISTS"},
            )
        if current.academic_level_id == payload.target_academic_level_id:
            raise BadRequestException("Use Reassign Class for a same-level move.")
        if payload.effective_date == current.started_on == date.today():
            await StudentPlacementService._correct_same_day_placement(
                db,
                actor=actor,
                enrollment=current,
                target_academic_level_id=payload.target_academic_level_id,
                target_class_id=target_class.id,
                reason=payload.reason,
            )
            await StudentPlacementService._invalidate_derived_context(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
            await StudentPlacementService._commit_with_readiness_invalidation(
                db,
                tenant_id=tenant_id,
                student_id=student.id,
                academic_session_id=current.academic_session_id,
            )
            return await StudentService.get_student_profile(db, actor, student.id)
        if payload.effective_date <= current.started_on:
            raise BadRequestException(
                "Reassignment must follow the current placement start. Only a placement that "
                "started today can be corrected on the same date."
            )

        await StudentPlacementService._close_segment(
            db,
            enrollment=current,
            ended_on=payload.effective_date - timedelta(days=1),
            outcome=StudentEnrollmentOutcome.LEVEL_REASSIGNED,
            reason=payload.reason,
            acting_admin_id=actor.id,
        )
        await StudentPlacementService._create_segment(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_level_id=payload.target_academic_level_id,
            class_id=target_class.id,
            academic_session_id=current.academic_session_id,
            started_on=payload.effective_date,
            outcome=StudentEnrollmentOutcome.LEVEL_REASSIGNED,
            reason=payload.reason,
            acting_admin_id=actor.id,
        )
        await StudentPlacementService._invalidate_derived_context(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_session_id=current.academic_session_id,
        )
        await StudentPlacementService._commit_with_readiness_invalidation(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_session_id=current.academic_session_id,
        )
        return await StudentService.get_student_profile(db, actor, student.id)

    @staticmethod
    async def _require_editable_upcoming(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        enrollment_id: UUID,
    ) -> StudentEnrollment:
        enrollment = await StudentEnrollmentRepository.get_by_id(
            db,
            tenant_id,
            enrollment_id,
            lock=True,
        )
        if enrollment is None or enrollment.student_id != student_id:
            raise NotFoundException("Upcoming enrollment not found.")
        if enrollment.started_on <= date.today():
            raise ConflictException(
                "This enrollment has already become effective and cannot be edited as upcoming.",
                payload={"code": "ENROLLMENT_ALREADY_EFFECTIVE"},
            )
        counts = await StudentEnrollmentEvidenceService.segment_dependency_counts(
            db,
            tenant_id=tenant_id,
            enrollment_id=enrollment.id,
        )
        blockers = {name: count for name, count in counts.items() if count > 0}
        if blockers:
            raise ConflictException(
                "Protected academic evidence prevents changing this upcoming enrollment.",
                payload={
                    "code": "UPCOMING_ENROLLMENT_EVIDENCE_EXISTS",
                    "dependency_counts": blockers,
                },
            )
        return enrollment

    @staticmethod
    def _takeover_predecessor(
        upcoming: StudentEnrollment,
        history: list[StudentEnrollment],
    ) -> StudentEnrollment | None:
        takeover_outcomes = {
            StudentEnrollmentOutcome.RECLASSIFIED,
            StudentEnrollmentOutcome.LEVEL_REASSIGNED,
        }
        if upcoming.entry_outcome not in takeover_outcomes:
            return None
        expected_end = upcoming.started_on - timedelta(days=1)
        return next(
            (
                row
                for row in history
                if row.id != upcoming.id
                and row.ended_on == expected_end
                and row.exit_outcome == upcoming.entry_outcome
            ),
            None,
        )

    @staticmethod
    async def update_upcoming_enrollment(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        enrollment_id: UUID,
        payload: StudentUpcomingEnrollmentUpdateRequest,
    ) -> StudentDetailResponse:
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        student = await StudentRepository.get_by_id(
            db,
            actor.tenant_id,
            student_id,
            lock=True,
            include_archived=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")
        upcoming = await StudentPlacementService._require_editable_upcoming(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            enrollment_id=enrollment_id,
        )
        if payload.effective_date <= date.today():
            raise BadRequestException("Upcoming enrollment must start after today.")
        session = await StudentPlacementService._require_open_session(
            db,
            tenant_id=actor.tenant_id,
            academic_session_id=payload.academic_session_id,
        )
        if session.start_date is not None and payload.effective_date < session.start_date:
            raise BadRequestException("Enrollment cannot start before the academic session.")
        if session.end_date is not None and payload.effective_date > session.end_date:
            raise BadRequestException("Enrollment cannot start after the academic session.")
        classroom = await StudentPlacementService._require_target_class(
            db,
            tenant_id=actor.tenant_id,
            class_id=payload.target_class_id,
        )
        if classroom.academic_level_id != payload.target_academic_level_id:
            raise BadRequestException("Target class does not belong to the target academic level.")

        history = await StudentEnrollmentRepository.list_for_student(
            db,
            actor.tenant_id,
            student_id,
        )
        previous_values = {
            "academic_level_id": str(upcoming.academic_level_id),
            "class_id": str(upcoming.class_id),
            "academic_session_id": str(upcoming.academic_session_id),
            "started_on": upcoming.started_on.isoformat(),
        }
        predecessor = StudentPlacementService._takeover_predecessor(upcoming, history)
        prior_rows = [row for row in history if row.id != upcoming.id]
        if predecessor is not None:
            if payload.effective_date <= predecessor.started_on:
                raise BadRequestException(
                    "Upcoming enrollment must start after the current placement begins."
                )
            predecessor.ended_on = payload.effective_date - timedelta(days=1)
            db.add(predecessor)
        else:
            previous = max(
                (row for row in prior_rows if row.ended_on is not None),
                key=lambda row: row.ended_on,
                default=None,
            )
            if previous is not None and payload.effective_date <= previous.ended_on:
                raise ConflictException(
                    f"This student's previous enrollment ends on {previous.ended_on.isoformat()}. "
                    f"Choose {previous.ended_on + timedelta(days=1)} or later.",
                    payload={"code": "ENROLLMENT_DATE_OVERLAP"},
                )

        upcoming.academic_level_id = payload.target_academic_level_id
        upcoming.class_id = classroom.id
        upcoming.academic_session_id = session.id
        upcoming.started_on = payload.effective_date
        upcoming.entry_reason = payload.reason
        try:
            await StudentEnrollmentRepository.save(db, upcoming)
            await StudentAcademicRepository.add_academic_lifecycle_audit(
                db,
                AcademicLifecycleAudit(
                    tenant_id=actor.tenant_id,
                    entity_type="student_enrollment",
                    entity_id=upcoming.id,
                    action="upcoming_enrollment_updated",
                    acting_admin_id=actor.id,
                    reason=payload.reason,
                    metadata_json={
                        "student_id": str(student.id),
                        "previous": previous_values,
                        "new": {
                            "academic_level_id": str(upcoming.academic_level_id),
                            "class_id": str(upcoming.class_id),
                            "academic_session_id": str(upcoming.academic_session_id),
                            "started_on": upcoming.started_on.isoformat(),
                        },
                    },
                ),
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Student enrollment overlaps existing placement history.",
                payload={"code": "ENROLLMENT_OVERLAP"},
            ) from exc
        return await StudentService.get_student_profile(db, actor, student.id)

    @staticmethod
    async def cancel_upcoming_enrollment(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        enrollment_id: UUID,
        payload: StudentLifecycleReasonRequest,
    ) -> StudentDetailResponse:
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        student = await StudentRepository.get_by_id(
            db,
            actor.tenant_id,
            student_id,
            lock=True,
            include_archived=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")
        upcoming = await StudentPlacementService._require_editable_upcoming(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            enrollment_id=enrollment_id,
        )
        history = await StudentEnrollmentRepository.list_for_student(
            db,
            actor.tenant_id,
            student_id,
        )
        predecessor = StudentPlacementService._takeover_predecessor(upcoming, history)
        identity_deactivated = False
        await db.delete(upcoming)
        await db.flush()
        if predecessor is not None:
            predecessor.ended_on = None
            predecessor.exit_outcome = None
            predecessor.exit_reason = None
            predecessor.ended_by_admin_id = None
            await StudentEnrollmentRepository.save(db, predecessor)
        elif student.status not in {AcademicStatus.ACTIVE, AcademicStatus.SUSPENDED}:
            from app.modules.auth_identity.models import ActorType
            from app.modules.auth_identity.service import AuthIdentityService

            await AuthIdentityService.deactivate_for_actor(
                db,
                actor_type=ActorType.STUDENT,
                actor_id=student.id,
            )
            identity_deactivated = True
        await StudentAcademicRepository.add_academic_lifecycle_audit(
            db,
            AcademicLifecycleAudit(
                tenant_id=actor.tenant_id,
                entity_type="student_enrollment",
                entity_id=enrollment_id,
                action="upcoming_enrollment_cancelled",
                acting_admin_id=actor.id,
                reason=payload.reason,
                metadata_json={"student_id": str(student.id)},
            ),
        )
        await db.commit()
        if identity_deactivated:
            await AuthIdentityService.invalidate_after_commit(db)
        return await StudentService.get_student_profile(db, actor, student.id)

    @staticmethod
    async def _department_name(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        class_id: UUID | None,
        academic_term_id: UUID,
    ) -> str | None:
        if class_id is None:
            return None
        return (
            await db.execute(
                select(Department.name)
                .select_from(ClassTermDepartmentAssignment)
                .join(
                    AcademicLevelDepartment,
                    and_(
                        AcademicLevelDepartment.id
                        == ClassTermDepartmentAssignment.academic_level_department_id,
                        AcademicLevelDepartment.tenant_id == tenant_id,
                    ),
                )
                .join(
                    Department,
                    and_(
                        Department.id == AcademicLevelDepartment.department_id,
                        Department.tenant_id == tenant_id,
                    ),
                )
                .where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.class_id == class_id,
                    ClassTermDepartmentAssignment.academic_term_id == academic_term_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _preview_subjects(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        items: list,
        selected_ids: set[UUID],
    ) -> list[PlacementImpactSubject]:
        output: list[PlacementImpactSubject] = []
        for item in items:
            if item.curriculum_subject_id not in selected_ids:
                continue
            subject = await SubjectRepository.get_subject_by_id(db, tenant_id, item.subject_id)
            output.append(
                PlacementImpactSubject(
                    curriculum_subject_id=item.curriculum_subject_id,
                    subject_id=item.subject_id,
                    subject_name=subject.name if subject else str(item.subject_id),
                )
            )
        return output

    @staticmethod
    async def impact_preview(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: PlacementImpactPreviewRequest,
    ) -> PlacementImpactPreviewResponse:
        tenant_id = actor.tenant_id
        student = await StudentRepository.get_by_id(db, tenant_id, student_id)
        if student is None:
            raise NotFoundException("Student not found.")
        current = await StudentEnrollmentRepository.get_current(db, tenant_id, student.id)
        if current is None or current.academic_session_id != payload.academic_session_id:
            raise ConflictException("Student has no current enrollment for this session.")
        preview_term = (
            await db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.id == payload.academic_term_id,
                    AcademicTerm.academic_session_id == payload.academic_session_id,
                )
            )
        ).scalar_one_or_none()
        if (
            preview_term is None
            or not preview_term.is_current
            or preview_term.status != AcademicTermStatus.OPEN
        ):
            raise BadRequestException(
                "Result placement previews require the current open academic term."
            )
        target_class = await StudentPlacementService._require_target_class(
            db, tenant_id=tenant_id, class_id=payload.target_class_id
        )
        if target_class.academic_level_id != payload.target_academic_level_id:
            raise BadRequestException("Target class does not belong to target academic level.")

        old_subjects = (
            await CurriculumResolutionService.resolve_class_subjects(
                db,
                tenant_id=tenant_id,
                class_id=current.class_id,
                academic_term_id=payload.academic_term_id,
            )
            if current.class_id is not None
            else []
        )
        new_subjects = await CurriculumResolutionService.resolve_class_subjects(
            db,
            tenant_id=tenant_id,
            class_id=target_class.id,
            academic_term_id=payload.academic_term_id,
        )
        old_ids = {item.curriculum_subject_id for item in old_subjects}
        destination_electives = {
            item.curriculum_subject_id
            for item in new_subjects
            if item.is_elective and item.elective_group_id is not None
        }
        selected_electives: set[UUID] = set()
        if destination_electives:
            selected_electives = set(
                (
                    await db.execute(
                        select(StudentElectiveSelection.curriculum_subject_id).where(
                            StudentElectiveSelection.tenant_id == tenant_id,
                            StudentElectiveSelection.student_id == student.id,
                            StudentElectiveSelection.curriculum_subject_id.in_(
                                destination_electives
                            ),
                        )
                    )
                ).scalars()
            )
        new_ids = {
            item.curriculum_subject_id
            for item in new_subjects
            if item.curriculum_subject_id not in destination_electives
            or item.curriculum_subject_id in selected_electives
        }
        result_ids = set(
            (
                await db.execute(
                    select(StudentSubjectResult.curriculum_subject_id).where(
                        StudentSubjectResult.tenant_id == tenant_id,
                        StudentSubjectResult.student_id == student.id,
                        StudentSubjectResult.academic_session_id == payload.academic_session_id,
                        StudentSubjectResult.academic_term_id == payload.academic_term_id,
                    )
                )
            ).scalars()
        )
        current_department = await StudentPlacementService._department_name(
            db,
            tenant_id=tenant_id,
            class_id=current.class_id,
            academic_term_id=payload.academic_term_id,
        )
        destination_department = await StudentPlacementService._department_name(
            db,
            tenant_id=tenant_id,
            class_id=target_class.id,
            academic_term_id=payload.academic_term_id,
        )
        teacher_comment_exists = (
            await db.execute(
                select(StudentTermTeacherComment.id)
                .where(
                    StudentTermTeacherComment.tenant_id == tenant_id,
                    StudentTermTeacherComment.student_id == student.id,
                    StudentTermTeacherComment.academic_session_id == payload.academic_session_id,
                    StudentTermTeacherComment.academic_term_id == payload.academic_term_id,
                    StudentTermTeacherComment.status.in_(
                        [TeacherCommentStatus.SUBMITTED, TeacherCommentStatus.NEEDS_REVIEW]
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None
        report_exists = (
            await db.execute(
                select(ReportCard.id)
                .where(
                    ReportCard.tenant_id == tenant_id,
                    ReportCard.student_id == student.id,
                    ReportCard.academic_session_id == payload.academic_session_id,
                    ReportCard.academic_term_id == payload.academic_term_id,
                    ReportCard.superseded_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

        warnings: list[str] = []
        historical_only = old_ids - new_ids
        destination_without_scores = new_ids - result_ids
        if historical_only:
            warnings.append(
                "Some existing results will remain preserved as historical-only in the destination context."
            )
        if teacher_comment_exists:
            warnings.append("The current teacher comment will require review after reassignment.")
        if report_exists:
            warnings.append(
                "Existing report cards will be marked affected; published revisions remain immutable."
            )
        warnings.append(
            "Class ranking context may change and will be recalculated only on a new draft."
        )
        if payload.effective_date > date.today():
            warnings.append(
                "Scheduled moves retain current result ownership until their effective date."
            )
        result_decisions = await AcademicResultContinuityService.inspect(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            academic_session_id=payload.academic_session_id,
            source_level_id=current.academic_level_id,
            target_class_id=target_class.id,
            effective_date=payload.effective_date,
        )

        return PlacementImpactPreviewResponse(
            current_academic_level_id=current.academic_level_id,
            current_class_id=current.class_id,
            destination_academic_level_id=payload.target_academic_level_id,
            destination_class_id=target_class.id,
            current_department=current_department,
            destination_department=destination_department,
            department_changed=current_department != destination_department,
            subjects_remaining_applicable=await StudentPlacementService._preview_subjects(
                db,
                tenant_id=tenant_id,
                items=new_subjects,
                selected_ids=old_ids & new_ids,
            ),
            subjects_becoming_historical_only=await StudentPlacementService._preview_subjects(
                db,
                tenant_id=tenant_id,
                items=old_subjects,
                selected_ids=historical_only,
            ),
            destination_subjects_without_scores=await StudentPlacementService._preview_subjects(
                db,
                tenant_id=tenant_id,
                items=new_subjects,
                selected_ids=destination_without_scores,
            ),
            teacher_comment_requires_review=teacher_comment_exists,
            report_card_affected=report_exists,
            warnings=warnings,
            result_impacts=[
                PlacementResultImpact(
                    result_id=decision.result.id,
                    curriculum_subject_id=decision.result.curriculum_subject_id,
                    status=decision.result.status.value,
                    action=decision.action,
                    reason=decision.reason,
                )
                for decision in result_decisions
            ],
        )
