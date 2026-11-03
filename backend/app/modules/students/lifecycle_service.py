"""Student lifecycle integration for immutable enrollment segments."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.auth_identity.models import ActorType, IdentifierType
from app.modules.auth_identity.schemas import AuthIdentityCreate
from app.modules.auth_identity.service import AuthIdentityService
from app.modules.classes.repository import ClassRoomRepository
from app.modules.parents.models import ParentMembershipStatus
from app.modules.parents.repository import ParentMembershipRepository
from app.modules.student_academics.lifecycle_repository import (
    AcademicSessionLifecycleRepository,
    StudentProgressionRepository,
)
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicSessionStatus,
    StudentProgressionItem,
    StudentProgressionItemStatus,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.students.enrollment_evidence import StudentEnrollmentEvidenceService
from app.modules.students.models import (
    AcademicStatus,
    Student,
    StudentAccountStatus,
    StudentEnrollment,
    StudentEnrollmentOutcome,
    StudentParentLinkStatus,
)
from app.modules.students.repository import (
    StudentEnrollmentRepository,
    StudentParentLinkRepository,
    StudentRepository,
)
from app.modules.students.schemas import (
    StudentHardDeleteEligibilityResponse,
    StudentLifecycleCapabilities,
    StudentLifecycleTransitionResponse,
    StudentReturnEnrollmentRequest,
    StudentResponse,
)
from app.modules.students.service import (
    StudentLifecycleService as LegacyStudentLifecycleService,
    StudentService,
)
from app.modules.subscriptions.quota_lock import acquire_resource_quota_lock
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import ResourceLimitCode
from app.modules.tenant_admins.models import TenantAdmin


class StudentLifecycleService(LegacyStudentLifecycleService):
    """Lifecycle operations that preserve placement chronology."""

    UNDO_WINDOW = timedelta(hours=24)
    TERMINAL_ACTIONS = {
        AcademicStatus.WITHDRAWN: "student_withdrawn",
        AcademicStatus.EXPELLED: "student_expelled",
        AcademicStatus.GRADUATED: "student_graduated",
    }
    RELEVANT_ACTIONS = {
        *TERMINAL_ACTIONS.values(),
        "student_withdrawal_undone",
        "student_expulsion_undone",
        "student_graduation_undone",
        "student_readmitted",
        "student_expelled_reinstated",
        "student_graduate_reenrolled",
    }

    @staticmethod
    async def _latest_lifecycle_audit(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        lock: bool = False,
    ) -> AcademicLifecycleAudit | None:
        query = (
            select(AcademicLifecycleAudit)
            .where(
                AcademicLifecycleAudit.tenant_id == tenant_id,
                AcademicLifecycleAudit.entity_type == "student",
                AcademicLifecycleAudit.entity_id == student_id,
                AcademicLifecycleAudit.action.in_(StudentLifecycleService.RELEVANT_ACTIONS),
            )
            .order_by(AcademicLifecycleAudit.created_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    def _matches_snapshot(current: object, snapshot: dict, fields: tuple[str, ...]) -> bool:
        for field in fields:
            value = getattr(current, field)
            if hasattr(value, "value"):
                value = value.value
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            elif isinstance(value, UUID):
                value = str(value)
            if value != snapshot.get(field):
                return False
        return True

    @staticmethod
    async def _undo_eligibility(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        status: AcademicStatus,
    ) -> tuple[bool, str | None, AcademicLifecycleAudit | None]:
        audit = await StudentLifecycleService._latest_lifecycle_audit(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
        )
        expected_action = StudentLifecycleService.TERMINAL_ACTIONS[status]
        if audit is None or audit.action != expected_action:
            return (
                False,
                "The terminal action is historical and must use a formal return flow.",
                audit,
            )
        created_at = audit.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created_at > StudentLifecycleService.UNDO_WINDOW:
            return False, "The 24-hour correction window has passed.", audit

        metadata = audit.metadata_json or {}
        enrollment_snapshot = metadata.get("enrollment")
        if not isinstance(enrollment_snapshot, dict):
            return False, "This historical action has no reversible enrollment snapshot.", audit
        enrollment_id = enrollment_snapshot.get("id")
        try:
            enrollment_uuid = UUID(str(enrollment_id))
        except (TypeError, ValueError):
            return False, "This historical action has no reversible enrollment snapshot.", audit
        history = await StudentEnrollmentRepository.list_for_student(db, tenant_id, student_id)
        if not history or history[-1].id != enrollment_uuid:
            return False, "A later enrollment or progression now depends on this exit.", audit
        enrollment = history[-1]
        after = enrollment_snapshot.get("after") or {}
        if not StudentLifecycleService._matches_snapshot(
            enrollment,
            after,
            ("ended_on", "exit_outcome", "exit_reason", "ended_by_admin_id"),
        ):
            return (
                False,
                "The enrollment changed after this exit and cannot be safely undone.",
                audit,
            )

        activity = await StudentEnrollmentEvidenceService.student_activity_counts_after(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            after=created_at,
        )
        blockers = {name: count for name, count in activity.items() if count > 0}
        if blockers:
            return False, "Later protected academic activity makes Undo unsafe.", audit
        return True, None, audit

    @staticmethod
    async def capabilities(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
    ) -> StudentLifecycleCapabilities:
        student = await StudentRepository.get_by_id(
            db,
            tenant_id,
            student_id,
            include_archived=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")
        if student.is_archived or student.status not in StudentLifecycleService.TERMINAL_ACTIONS:
            return StudentLifecycleCapabilities()

        undoable, reason, _ = await StudentLifecycleService._undo_eligibility(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            status=student.status,
        )
        no_current = (
            await StudentEnrollmentRepository.get_current(db, tenant_id, student_id)
        ) is None
        no_upcoming = (
            await StudentEnrollmentRepository.get_upcoming(db, tenant_id, student_id)
        ) is None
        can_formally_return = not undoable and no_current and no_upcoming
        return StudentLifecycleCapabilities(
            can_undo_withdrawal=undoable and student.status == AcademicStatus.WITHDRAWN,
            can_undo_expulsion=undoable and student.status == AcademicStatus.EXPELLED,
            can_undo_graduation=undoable and student.status == AcademicStatus.GRADUATED,
            can_readmit=(can_formally_return and student.status == AcademicStatus.WITHDRAWN),
            can_reinstate_expelled=(
                can_formally_return and student.status == AcademicStatus.EXPELLED
            ),
            can_reenrol_graduate=(
                can_formally_return and student.status == AcademicStatus.GRADUATED
            ),
            undo_block_reason=reason,
        )

    @staticmethod
    async def _ensure_terminal_exit_safe(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
        effective_date: date,
    ) -> None:
        upcoming = await StudentEnrollmentRepository.get_upcoming(
            db,
            tenant_id,
            student_id,
            lock=True,
        )
        if upcoming is not None:
            raise ConflictException(
                "Cancel the student's upcoming enrollment before applying a terminal action.",
                payload={"code": "UPCOMING_ENROLLMENT_EXISTS"},
            )
        current = await StudentEnrollmentRepository.get_current(
            db,
            tenant_id,
            student_id,
            lock=True,
        )
        if current is None:
            return
        if effective_date < current.started_on:
            raise ConflictException("Lifecycle exit cannot predate the current enrollment.")

        if effective_date < date.today():
            counts = await StudentEnrollmentEvidenceService.segment_dependency_counts(
                db,
                tenant_id=tenant_id,
                enrollment_id=current.id,
                on_or_after=effective_date + timedelta(days=1),
            )
            blockers = {key: value for key, value in counts.items() if value > 0}
            if blockers:
                raise ConflictException(
                    "The lifecycle exit cannot be backdated across preserved academic evidence.",
                    payload={"dependency_counts": blockers},
                )

    @staticmethod
    async def suspend(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
        promotion_hold: bool = True,
    ) -> StudentLifecycleTransitionResponse:
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        return await LegacyStudentLifecycleService.suspend(
            db,
            actor=actor,
            student_id=student_id,
            reason=reason,
            promotion_hold=promotion_hold,
        )

    @staticmethod
    async def reinstate(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentLifecycleTransitionResponse:
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        return await LegacyStudentLifecycleService.reinstate(
            db,
            actor=actor,
            student_id=student_id,
            reason=reason,
        )

    @staticmethod
    async def withdraw(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentLifecycleTransitionResponse:
        effective_date = date.today()
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        await StudentLifecycleService._ensure_terminal_exit_safe(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            effective_date=effective_date,
        )
        return await LegacyStudentLifecycleService._transition(
            db,
            actor=actor,
            student_id=student_id,
            target_status=AcademicStatus.WITHDRAWN,
            reason=reason,
            effective_date=effective_date,
        )

    @staticmethod
    async def expel(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentLifecycleTransitionResponse:
        effective_date = date.today()
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        await StudentLifecycleService._ensure_terminal_exit_safe(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            effective_date=effective_date,
        )
        return await LegacyStudentLifecycleService._transition(
            db,
            actor=actor,
            student_id=student_id,
            target_status=AcademicStatus.EXPELLED,
            reason=reason,
            effective_date=effective_date,
        )

    @staticmethod
    async def graduate(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentLifecycleTransitionResponse:
        graduation_date = date.today()
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        await StudentLifecycleService._ensure_terminal_exit_safe(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            effective_date=graduation_date,
        )
        return await LegacyStudentLifecycleService._transition(
            db,
            actor=actor,
            student_id=student_id,
            target_status=AcademicStatus.GRADUATED,
            reason=reason,
            effective_date=graduation_date,
        )

    @staticmethod
    async def archive(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentResponse:
        await ensure_academic_write_window(db, tenant_id=actor.tenant_id)
        current = await StudentEnrollmentRepository.get_current(
            db,
            actor.tenant_id,
            student_id,
            lock=True,
        )
        upcoming = await StudentEnrollmentRepository.get_upcoming(
            db,
            actor.tenant_id,
            student_id,
            lock=True,
        )
        if current is not None or upcoming is not None:
            raise ConflictException(
                "End the student's current or upcoming academic enrollment before archiving the profile."
            )
        return await LegacyStudentLifecycleService.archive(
            db,
            actor=actor,
            student_id=student_id,
            reason=reason,
        )

    @staticmethod
    async def restore(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        reason: str,
    ) -> StudentResponse:
        student = await StudentRepository.get_by_id(
            db,
            actor.tenant_id,
            student_id,
            include_archived=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")
        if student.is_archived:
            await acquire_resource_quota_lock(
                db,
                tenant_id=actor.tenant_id,
                resource=ResourceLimitCode.STUDENTS,
            )
            await SubscriptionFeatureService.ensure_resource_limit_available(
                db,
                actor.tenant_id,
                ResourceLimitCode.STUDENTS,
            )
        return await LegacyStudentLifecycleService.restore(
            db,
            actor=actor,
            student_id=student_id,
            reason=reason,
        )

    @staticmethod
    async def _record_lifecycle_audit(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        action: str,
        previous_status: AcademicStatus,
        new_status: AcademicStatus,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        await StudentAcademicRepository.add_academic_lifecycle_audit(
            db,
            AcademicLifecycleAudit(
                tenant_id=actor.tenant_id,
                entity_type="student",
                entity_id=student_id,
                action=action,
                previous_status=previous_status.value,
                new_status=new_status.value,
                acting_admin_id=actor.id,
                reason=reason,
                metadata_json=metadata,
            ),
        )

    @staticmethod
    def _restore_snapshot_fields(record: object, before: dict, after: dict) -> None:
        enum_fields = {
            "status": {
                "student": AcademicStatus,
                "link": StudentParentLinkStatus,
                "membership": ParentMembershipStatus,
                "progression": StudentProgressionItemStatus,
            },
            "account_status": {"student": StudentAccountStatus},
        }
        if hasattr(record, "admission_number"):
            kind = "student"
        elif hasattr(record, "parent_membership_id"):
            kind = "link"
        elif hasattr(record, "parent_account_id"):
            kind = "membership"
        else:
            kind = "progression"
        for field, before_value in before.items():
            if field not in after or not hasattr(record, field):
                continue
            current_value = getattr(record, field)
            comparable = current_value.value if hasattr(current_value, "value") else current_value
            if isinstance(comparable, (date, datetime)):
                comparable = comparable.isoformat()
            elif isinstance(comparable, UUID):
                comparable = str(comparable)
            if comparable != after[field]:
                continue
            enum_type = enum_fields.get(field, {}).get(kind)
            if enum_type is not None and before_value is not None:
                restored = enum_type(before_value)
            elif field == "ended_on" or field == "graduation_date":
                restored = date.fromisoformat(before_value) if before_value else None
            elif field in {"ended_at", "processed_at"}:
                restored = datetime.fromisoformat(before_value) if before_value else None
            elif field.endswith("_id"):
                restored = UUID(before_value) if before_value else None
            else:
                restored = before_value
            setattr(record, field, restored)

    @staticmethod
    async def _undo_terminal(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        status: AcademicStatus,
        reason: str,
    ) -> StudentLifecycleTransitionResponse:
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
        if student.is_archived:
            raise ConflictException("Restore the archived student before correcting lifecycle.")
        if student.status != status:
            raise BadRequestException(f"Only {status.value} students can use this Undo action.")

        undoable, block_reason, audit = await StudentLifecycleService._undo_eligibility(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            status=status,
        )
        if not undoable or audit is None:
            raise ConflictException(
                block_reason
                or "This lifecycle action can no longer be undone; use the formal return flow."
            )
        metadata = audit.metadata_json or {}
        previous_status = AcademicStatus(metadata["student_before"]["status"])

        enrollment_snapshot = metadata["enrollment"]
        enrollment = await StudentEnrollmentRepository.get_by_id(
            db,
            actor.tenant_id,
            UUID(enrollment_snapshot["id"]),
            lock=True,
        )
        if enrollment is None:
            raise ConflictException("The enrollment changed after this exit and cannot be undone.")
        StudentLifecycleService._restore_snapshot_fields(
            enrollment,
            enrollment_snapshot["before"],
            enrollment_snapshot["after"],
        )
        await StudentEnrollmentRepository.save(db, enrollment)

        StudentLifecycleService._restore_snapshot_fields(
            student,
            metadata["student_before"],
            metadata["student_after"],
        )
        await StudentRepository.save(db, student)

        affected_links = 0
        membership_ids: set[UUID] = set()
        for snapshot in metadata.get("parent_links", []):
            link = await StudentParentLinkRepository.get_by_id(
                db,
                actor.tenant_id,
                UUID(snapshot["id"]),
                lock=True,
            )
            if link is None:
                continue
            if StudentLifecycleService._matches_snapshot(
                link,
                snapshot["after"],
                ("status", "ended_at", "end_reason"),
            ):
                StudentLifecycleService._restore_snapshot_fields(
                    link,
                    snapshot["before"],
                    snapshot["after"],
                )
                await StudentParentLinkRepository.save(db, link)
                affected_links += 1
                membership_ids.add(link.parent_membership_id)

        membership_recalculations = 0
        for snapshot in metadata.get("parent_memberships", []):
            membership = await ParentMembershipRepository.get_by_id(
                db,
                UUID(snapshot["id"]),
                tenant_id=actor.tenant_id,
                lock=True,
            )
            if membership is None:
                continue
            if StudentLifecycleService._matches_snapshot(
                membership,
                snapshot["after"],
                ("status", "ended_at", "end_reason"),
            ):
                StudentLifecycleService._restore_snapshot_fields(
                    membership,
                    snapshot["before"],
                    snapshot["after"],
                )
                await ParentMembershipRepository.save(db, membership)
                membership_recalculations += 1
                membership_ids.discard(membership.id)
        for membership_id in membership_ids:
            membership = await ParentMembershipRepository.get_by_id(
                db,
                membership_id,
                tenant_id=actor.tenant_id,
                lock=True,
            )
            if membership is not None:
                await StudentLifecycleService._recalculate_parent_membership(db, membership)
                membership_recalculations += 1

        progression_snapshot = metadata.get("progression")
        if isinstance(progression_snapshot, dict):
            progression = (
                await db.execute(
                    select(StudentProgressionItem)
                    .where(
                        StudentProgressionItem.tenant_id == actor.tenant_id,
                        StudentProgressionItem.id == UUID(progression_snapshot["id"]),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if progression is not None and StudentLifecycleService._matches_snapshot(
                progression,
                progression_snapshot["after"],
                ("status", "reason", "processed_at"),
            ):
                StudentLifecycleService._restore_snapshot_fields(
                    progression,
                    progression_snapshot["before"],
                    progression_snapshot["after"],
                )
                await StudentProgressionRepository.save_item(db, progression)

        if student.is_active and student.account_status == StudentAccountStatus.ACTIVE:
            await AuthIdentityService.ensure_for_actor(
                db,
                tenant_id=actor.tenant_id,
                payload=AuthIdentityCreate(
                    identifier=student.admission_number,
                    identifier_type=IdentifierType.ADMISSION_NUMBER,
                    actor_type=ActorType.STUDENT,
                    actor_id=student.id,
                    is_active=True,
                ),
            )

        noun = {
            AcademicStatus.WITHDRAWN: "withdrawal",
            AcademicStatus.EXPELLED: "expulsion",
            AcademicStatus.GRADUATED: "graduation",
        }[status]
        await StudentLifecycleService._record_lifecycle_audit(
            db,
            actor=actor,
            student_id=student.id,
            action=f"student_{noun}_undone",
            previous_status=status,
            new_status=previous_status,
            reason=reason,
            metadata={"reversed_audit_id": str(audit.id)},
        )
        await db.commit()
        await AuthIdentityService.invalidate_after_commit(db)
        await db.refresh(student)
        return StudentLifecycleTransitionResponse(
            student=await StudentService._build_detail_response(db, student),
            previous_status=status,
            new_status=student.status,
            session_revoked=False,
            access_codes_revoked=0,
            affected_parent_links=affected_links,
            membership_recalculations=membership_recalculations,
        )

    @staticmethod
    async def undo_withdrawal(
        db: AsyncSession, *, actor: TenantAdmin, student_id: UUID, reason: str
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._undo_terminal(
            db, actor=actor, student_id=student_id, status=AcademicStatus.WITHDRAWN, reason=reason
        )

    @staticmethod
    async def undo_expulsion(
        db: AsyncSession, *, actor: TenantAdmin, student_id: UUID, reason: str
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._undo_terminal(
            db, actor=actor, student_id=student_id, status=AcademicStatus.EXPELLED, reason=reason
        )

    @staticmethod
    async def undo_graduation(
        db: AsyncSession, *, actor: TenantAdmin, student_id: UUID, reason: str
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._undo_terminal(
            db, actor=actor, student_id=student_id, status=AcademicStatus.GRADUATED, reason=reason
        )

    @staticmethod
    async def _restore_parent_links_after_return(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student: Student,
        previous_status: AcademicStatus,
        terminal_audit: AcademicLifecycleAudit | None,
    ) -> tuple[int, int]:
        affected_links = 0
        membership_ids: set[UUID] = set()
        metadata = terminal_audit.metadata_json if terminal_audit is not None else {}
        link_snapshots = metadata.get("parent_links", []) if isinstance(metadata, dict) else []
        for snapshot in link_snapshots:
            link = await StudentParentLinkRepository.get_by_id(
                db,
                tenant_id,
                UUID(snapshot["id"]),
                lock=True,
            )
            if link is None or not StudentLifecycleService._matches_snapshot(
                link,
                snapshot["after"],
                ("status", "ended_at", "end_reason"),
            ):
                continue
            link.status = StudentParentLinkStatus.ACTIVE
            link.ended_at = None
            link.end_reason = None
            await StudentParentLinkRepository.save(db, link)
            affected_links += 1
            membership_ids.add(link.parent_membership_id)

        if not link_snapshots and previous_status != AcademicStatus.EXPELLED:
            eligible_status = (
                StudentParentLinkStatus.READ_ONLY
                if previous_status == AcademicStatus.WITHDRAWN
                else StudentParentLinkStatus.ALUMNI_READ_ONLY
            )
            links = await StudentParentLinkRepository.list_for_student(
                db,
                tenant_id,
                student.id,
                statuses=[eligible_status],
                lock=True,
            )
            for link in links:
                link.status = StudentParentLinkStatus.ACTIVE
                link.ended_at = None
                link.end_reason = None
                await StudentParentLinkRepository.save(db, link)
                affected_links += 1
                membership_ids.add(link.parent_membership_id)

        recalculations = 0
        for membership_id in membership_ids:
            membership = await ParentMembershipRepository.get_by_id(
                db,
                membership_id,
                tenant_id=tenant_id,
                lock=True,
            )
            if membership is not None:
                await StudentLifecycleService._recalculate_parent_membership(db, membership)
                recalculations += 1
        return affected_links, recalculations

    @staticmethod
    async def activate_due_return(
        db: AsyncSession,
        *,
        student: Student,
        commit: bool = True,
    ) -> bool:
        """Materialize access state once a scheduled return enrollment is effective."""

        if student.status not in StudentLifecycleService.TERMINAL_ACTIONS:
            return False
        enrollment = await StudentEnrollmentRepository.get_current(
            db,
            student.tenant_id,
            student.id,
            lock=True,
        )
        if enrollment is None:
            return False
        # Terminal exits end the old enrollment on an inclusive last day, so that
        # segment can still satisfy the generic current-enrollment predicate today.
        # It is not a return. A due formal return is represented by a new open
        # enrollment segment; never reactivate from a segment that has already ended.
        if getattr(enrollment, "ended_on", None) is not None:
            return False

        previous_status = student.status
        terminal_audit = (
            await db.execute(
                select(AcademicLifecycleAudit)
                .where(
                    AcademicLifecycleAudit.tenant_id == student.tenant_id,
                    AcademicLifecycleAudit.entity_type == "student",
                    AcademicLifecycleAudit.entity_id == student.id,
                    AcademicLifecycleAudit.action
                    == StudentLifecycleService.TERMINAL_ACTIONS[previous_status],
                )
                .order_by(AcademicLifecycleAudit.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        student.status = AcademicStatus.ACTIVE
        student.promotion_hold = False
        student.is_active = True
        student.account_status = StudentAccountStatus.ACTIVE
        student.graduation_date = None
        await StudentRepository.save(db, student)
        await AuthIdentityService.ensure_for_actor(
            db,
            tenant_id=student.tenant_id,
            payload=AuthIdentityCreate(
                identifier=student.admission_number,
                identifier_type=IdentifierType.ADMISSION_NUMBER,
                actor_type=ActorType.STUDENT,
                actor_id=student.id,
                is_active=True,
            ),
        )
        await StudentLifecycleService._restore_parent_links_after_return(
            db,
            tenant_id=student.tenant_id,
            student=student,
            previous_status=previous_status,
            terminal_audit=terminal_audit,
        )
        if commit:
            await db.commit()
            await AuthIdentityService.invalidate_after_commit(db)
            await db.refresh(student)
        return True

    @staticmethod
    async def activate_due_returns_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
    ) -> int:
        """Materialize all date-effective formal returns for one tenant."""

        students = list(
            (
                await db.execute(
                    select(Student)
                    .join(
                        StudentEnrollment,
                        (StudentEnrollment.tenant_id == Student.tenant_id)
                        & (StudentEnrollment.student_id == Student.id),
                    )
                    .where(
                        Student.tenant_id == tenant_id,
                        Student.status.in_(StudentLifecycleService.TERMINAL_ACTIONS),
                        StudentEnrollment.is_current.is_(True),
                        # A terminal enrollment whose inclusive last day is today
                        # is not a due return; do not lock it during request auth.
                        StudentEnrollment.ended_on.is_(None),
                    )
                    # This scan also runs in the authentication dependency.
                    # Skip rows a concurrent request is already activating,
                    # and avoid locking joined enrollment rows unnecessarily.
                    .with_for_update(of=Student, skip_locked=True)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        changed = 0
        for student in students:
            changed += int(
                await StudentLifecycleService.activate_due_return(
                    db,
                    student=student,
                    commit=False,
                )
            )
        if changed:
            await db.commit()
            await AuthIdentityService.invalidate_after_commit(db)
        return changed

    @staticmethod
    async def _return_after_terminal(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        expected_status: AcademicStatus,
        payload: StudentReturnEnrollmentRequest,
        action: str,
    ) -> StudentLifecycleTransitionResponse:
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
        if student.is_archived:
            raise ConflictException("Restore the archived student before returning them to school.")
        if student.status != expected_status:
            raise BadRequestException(
                f"Only {expected_status.value} students can use this return flow."
            )

        undoable, _, terminal_audit = await StudentLifecycleService._undo_eligibility(
            db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
            status=expected_status,
        )
        if undoable:
            noun = {
                AcademicStatus.WITHDRAWN: "withdrawal",
                AcademicStatus.EXPELLED: "expulsion",
                AcademicStatus.GRADUATED: "graduation",
            }[expected_status]
            raise ConflictException(
                f"This student's previous enrollment ended on "
                f"{(terminal_audit.metadata_json or {}).get('effective_date')}. "
                f"A new return enrollment must begin after that enrollment. If the {noun} "
                f"was made by mistake, use Undo {noun} instead."
            )
        if (
            await StudentEnrollmentRepository.get_current(
                db,
                actor.tenant_id,
                student_id,
                lock=True,
            )
            is not None
        ):
            raise ConflictException("Student already has a current enrollment.")
        if (
            await StudentEnrollmentRepository.get_upcoming(
                db,
                actor.tenant_id,
                student_id,
                lock=True,
            )
            is not None
        ):
            raise ConflictException("Student already has an upcoming enrollment.")

        session = await AcademicSessionLifecycleRepository.get_by_id(
            db,
            actor.tenant_id,
            payload.academic_session_id,
            lock=True,
        )
        if (
            session is None
            or not session.is_current
            or session.status != AcademicSessionStatus.OPEN
        ):
            raise ConflictException(
                "A return enrollment requires the current open academic session."
            )
        if session.start_date is not None and payload.effective_date < session.start_date:
            raise BadRequestException(
                "Return enrollment effective date cannot be before the current session starts."
            )
        if session.end_date is not None and payload.effective_date > session.end_date:
            raise BadRequestException(
                "Return enrollment effective date cannot be after the current session ends."
            )

        classroom = await ClassRoomRepository.get_by_id(
            db,
            actor.tenant_id,
            payload.target_class_id,
            lock=True,
        )
        if classroom is None or not classroom.is_active or classroom.archived_at is not None:
            raise NotFoundException("Target class not found or inactive.")
        if classroom.academic_level_id != payload.target_academic_level_id:
            raise BadRequestException(
                "Target class does not belong to the selected academic level."
            )

        history = await StudentEnrollmentRepository.list_for_student(
            db,
            actor.tenant_id,
            student_id,
        )
        previous = max(history, key=lambda row: row.ended_on or date.max, default=None)
        if previous is not None:
            if previous.ended_on is None:
                raise ConflictException("Student already has a current enrollment.")
            if payload.effective_date <= previous.ended_on:
                action_label = {
                    AcademicStatus.WITHDRAWN: "readmission",
                    AcademicStatus.EXPELLED: "reinstatement",
                    AcademicStatus.GRADUATED: "re-enrollment",
                }[expected_status]
                raise ConflictException(
                    f"This student's previous enrollment ended on {previous.ended_on.isoformat()}. "
                    f"A new {action_label} cannot begin on the same date. If the previous exit "
                    f"was a mistake, use Undo. Otherwise choose "
                    f"{previous.ended_on + timedelta(days=1)} or later.",
                    payload={"code": "ENROLLMENT_DATE_OVERLAP"},
                )

        entry_outcome = (
            StudentEnrollmentOutcome.REINSTATED
            if expected_status == AcademicStatus.EXPELLED
            else StudentEnrollmentOutcome.ENROLLED
        )
        enrollment = StudentEnrollment(
            tenant_id=actor.tenant_id,
            student_id=student.id,
            academic_level_id=payload.target_academic_level_id,
            class_id=classroom.id,
            academic_session_id=session.id,
            started_on=payload.effective_date,
            entry_outcome=entry_outcome,
            entry_reason=payload.reason,
            created_by_admin_id=actor.id,
        )
        await StudentEnrollmentRepository.add(db, enrollment)

        previous_status = student.status
        activates_now = payload.effective_date <= date.today()
        if activates_now:
            student.status = AcademicStatus.ACTIVE
            student.promotion_hold = False
            student.is_active = True
            student.account_status = StudentAccountStatus.ACTIVE
            student.graduation_date = None
            await StudentRepository.save(db, student)
        await AuthIdentityService.ensure_for_actor(
            db,
            tenant_id=actor.tenant_id,
            payload=AuthIdentityCreate(
                identifier=student.admission_number,
                identifier_type=IdentifierType.ADMISSION_NUMBER,
                actor_type=ActorType.STUDENT,
                actor_id=student.id,
                is_active=True,
            ),
        )

        affected_links = 0
        recalculations = 0
        if activates_now:
            (
                affected_links,
                recalculations,
            ) = await StudentLifecycleService._restore_parent_links_after_return(
                db,
                tenant_id=actor.tenant_id,
                student=student,
                previous_status=expected_status,
                terminal_audit=terminal_audit,
            )

        await StudentLifecycleService._record_lifecycle_audit(
            db,
            actor=actor,
            student_id=student.id,
            action=action,
            previous_status=previous_status,
            new_status=AcademicStatus.ACTIVE if activates_now else previous_status,
            reason=payload.reason,
            metadata={
                "new_enrollment_id": str(enrollment.id),
                "academic_session_id": str(session.id),
                "academic_level_id": str(payload.target_academic_level_id),
                "class_id": str(classroom.id),
                "effective_date": payload.effective_date.isoformat(),
                "scheduled": not activates_now,
            },
        )
        await db.commit()
        await AuthIdentityService.invalidate_after_commit(db)
        await db.refresh(student)
        return StudentLifecycleTransitionResponse(
            student=await StudentService._build_detail_response(db, student),
            previous_status=previous_status,
            new_status=AcademicStatus.ACTIVE if activates_now else previous_status,
            session_revoked=False,
            access_codes_revoked=0,
            affected_parent_links=affected_links,
            membership_recalculations=recalculations,
        )

    @staticmethod
    async def readmit(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: StudentReturnEnrollmentRequest,
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._return_after_terminal(
            db,
            actor=actor,
            student_id=student_id,
            expected_status=AcademicStatus.WITHDRAWN,
            payload=payload,
            action="student_readmitted",
        )

    @staticmethod
    async def reinstate_expelled(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: StudentReturnEnrollmentRequest,
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._return_after_terminal(
            db,
            actor=actor,
            student_id=student_id,
            expected_status=AcademicStatus.EXPELLED,
            payload=payload,
            action="student_expelled_reinstated",
        )

    @staticmethod
    async def reenrol_graduate(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
        payload: StudentReturnEnrollmentRequest,
    ) -> StudentLifecycleTransitionResponse:
        return await StudentLifecycleService._return_after_terminal(
            db,
            actor=actor,
            student_id=student_id,
            expected_status=AcademicStatus.GRADUATED,
            payload=payload,
            action="student_graduate_reenrolled",
        )

    @staticmethod
    async def hard_delete_eligibility(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        student_id: UUID,
    ) -> StudentHardDeleteEligibilityResponse:
        base = await LegacyStudentLifecycleService.hard_delete_eligibility(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
        )
        student = await StudentRepository.get_by_id(
            db,
            tenant_id,
            student_id,
            include_archived=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")

        blockers = list(base.blocking_dependencies)
        if student.last_login_at is not None and "login_history" not in blockers:
            blockers.append("login_history")
        eligible = not blockers
        return base.model_copy(
            update={
                "eligible": eligible,
                "blocking_dependencies": blockers,
                "recommendation": "hard_delete" if eligible else "archive",
            }
        )

    @staticmethod
    async def hard_delete(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student_id: UUID,
    ) -> None:
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
        if student.last_login_at is not None:
            raise ConflictException("Student has login history and must be archived.")
        await LegacyStudentLifecycleService.hard_delete(
            db,
            actor=actor,
            student_id=student_id,
        )
