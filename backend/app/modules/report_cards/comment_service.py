"""Authoritative performance-range comment and teacher-term workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.classes.models import ClassRoom
from app.modules.report_cards.cache import ReportReadinessCache
from app.modules.report_cards.comment_models import (
    CommentTemplate,
    CommentTemplateOwnerType,
    CommentTemplateStatus,
    StudentTermTeacherComment,
    TeacherCommentOverride,
    TeacherCommentSource,
    TeacherCommentStatus,
)
from app.modules.report_cards.comment_schemas import (
    CommentTemplateCreate,
    CommentTemplateResponse,
    CommentTemplateUpdate,
    TeacherCommentOverrideRequest,
    TeacherCommentOverrideResponse,
    TeacherCommentResponse,
    TeacherCommentWrite,
    TeacherStudentCommentListResponse,
    TeacherStudentCommentRow,
)
from app.modules.report_cards.models import ReportCard
from app.modules.report_cards.readiness_service import ReportReadinessService
from app.modules.report_cards.repository import ReportCardRepository
from app.modules.student_academics.models import GradingScale
from app.modules.students.models import StudentEnrollment
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.teachers.models import TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin


class ReportCommentService:
    """Own comment readiness, range templates, authorship and audited overrides."""

    @staticmethod
    async def _is_current_class_teacher(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        teacher_membership_id: uuid.UUID,
        class_id: uuid.UUID | None = None,
    ) -> bool:
        filters = [
            ClassRoom.tenant_id == tenant_id,
            ClassRoom.teacher_membership_id == teacher_membership_id,
            ClassRoom.is_active.is_(True),
            ClassRoom.archived_at.is_(None),
        ]
        if class_id is not None:
            filters.append(ClassRoom.id == class_id)
        return (
            await db.execute(select(ClassRoom.id).where(*filters).limit(1))
        ).scalar_one_or_none() is not None

    @staticmethod
    async def _require_class_teacher_capability(
        db: AsyncSession,
        teacher: TeacherMembership,
        *,
        class_id: uuid.UUID | None = None,
    ) -> None:
        if not await ReportCommentService._is_current_class_teacher(
            db,
            tenant_id=teacher.tenant_id,
            teacher_membership_id=teacher.id,
            class_id=class_id,
        ):
            raise ForbiddenException(
                "Only a currently assigned class teacher can use teacher comments and templates."
            )

    @staticmethod
    def _owner_filters(
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
    ) -> list:
        if owner_type == CommentTemplateOwnerType.TENANT_ADMIN:
            return [
                CommentTemplate.owner_type == owner_type,
                CommentTemplate.tenant_admin_id == owner_id,
                CommentTemplate.teacher_membership_id.is_(None),
            ]
        return [
            CommentTemplate.owner_type == owner_type,
            CommentTemplate.teacher_membership_id == owner_id,
            CommentTemplate.tenant_admin_id.is_(None),
        ]

    @staticmethod
    def _actor_owner(
        actor: TenantAdmin | TeacherMembership,
    ) -> tuple[CommentTemplateOwnerType, uuid.UUID]:
        if isinstance(actor, TenantAdmin):
            return CommentTemplateOwnerType.TENANT_ADMIN, actor.id
        return CommentTemplateOwnerType.TEACHER, actor.id

    @staticmethod
    def _template_response(template: CommentTemplate) -> CommentTemplateResponse:
        return CommentTemplateResponse.model_validate(template)

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        include_archived: bool = False,
    ) -> list[CommentTemplateResponse]:
        filters = [
            CommentTemplate.tenant_id == tenant_id,
            *ReportCommentService._owner_filters(owner_type, owner_id),
        ]
        if not include_archived:
            filters.append(CommentTemplate.status != CommentTemplateStatus.ARCHIVED)
        templates = list(
            (
                await db.execute(
                    select(CommentTemplate)
                    .where(*filters)
                    .order_by(
                        CommentTemplate.minimum_score.desc(),
                        CommentTemplate.maximum_score.desc(),
                        CommentTemplate.is_default.desc(),
                        CommentTemplate.created_at.asc(),
                    )
                )
            ).scalars()
        )
        return [ReportCommentService._template_response(item) for item in templates]

    @staticmethod
    async def _owned_template(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        template_id: uuid.UUID,
        lock: bool = False,
    ) -> CommentTemplate:
        query = select(CommentTemplate).where(
            CommentTemplate.tenant_id == tenant_id,
            CommentTemplate.id == template_id,
            *ReportCommentService._owner_filters(owner_type, owner_id),
        )
        if lock:
            query = query.with_for_update()
        template = (await db.execute(query)).scalar_one_or_none()
        if template is None:
            raise NotFoundException("Comment template not found.")
        return template

    @staticmethod
    async def _validate_non_overlapping_range(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        minimum_score: Decimal,
        maximum_score: Decimal,
        excluding_template_id: uuid.UUID | None = None,
    ) -> None:
        """Reject inclusive overlap while allowing duplicate exact ranges.

        The Alembic trigger enforces the same rule under concurrent writes. This
        service validation exists to return a useful HTTP conflict before flush.
        """

        if minimum_score < 0 or maximum_score > 100 or minimum_score > maximum_score:
            raise BadRequestException("Comment score ranges must stay between 0 and 100.")

        query = (
            select(CommentTemplate)
            .where(
                CommentTemplate.tenant_id == tenant_id,
                CommentTemplate.status != CommentTemplateStatus.ARCHIVED,
                *ReportCommentService._owner_filters(owner_type, owner_id),
            )
            .with_for_update()
        )
        if excluding_template_id is not None:
            query = query.where(CommentTemplate.id != excluding_template_id)
        rows = list((await db.execute(query)).scalars())
        for row in rows:
            row_min = Decimal(row.minimum_score)
            row_max = Decimal(row.maximum_score)
            if row_min == minimum_score and row_max == maximum_score:
                continue
            if minimum_score <= row_max and maximum_score >= row_min:
                raise ConflictException(
                    f"Performance range {minimum_score}-{maximum_score}% overlaps "
                    f"the existing {row_min}-{row_max}% range."
                )

    @staticmethod
    async def _ensure_exact_range_default(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        minimum_score: Decimal,
        maximum_score: Decimal,
        preferred_template_id: uuid.UUID | None = None,
    ) -> None:
        rows = list(
            (
                await db.execute(
                    select(CommentTemplate)
                    .where(
                        CommentTemplate.tenant_id == tenant_id,
                        CommentTemplate.status == CommentTemplateStatus.ACTIVE,
                        CommentTemplate.minimum_score == minimum_score,
                        CommentTemplate.maximum_score == maximum_score,
                        *ReportCommentService._owner_filters(owner_type, owner_id),
                    )
                    .order_by(CommentTemplate.created_at.asc(), CommentTemplate.id.asc())
                    .with_for_update()
                )
            ).scalars()
        )
        if not rows:
            return

        preferred = None
        if preferred_template_id is not None:
            preferred = next((row for row in rows if row.id == preferred_template_id), None)
        if preferred is None:
            preferred = next((row for row in rows if row.is_default), None) or rows[0]

        for row in rows:
            target = row.id == preferred.id
            if row.is_default != target:
                row.is_default = target
                db.add(row)

    @staticmethod
    async def create_template(
        db: AsyncSession,
        *,
        actor: TenantAdmin | TeacherMembership,
        payload: CommentTemplateCreate,
    ) -> CommentTemplateResponse:
        owner_type, owner_id = ReportCommentService._actor_owner(actor)
        if isinstance(actor, TeacherMembership):
            await ReportCommentService._require_class_teacher_capability(db, actor)

        minimum_score = Decimal(payload.minimum_score)
        maximum_score = Decimal(payload.maximum_score)
        await ReportCommentService._validate_non_overlapping_range(
            db,
            tenant_id=actor.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            minimum_score=minimum_score,
            maximum_score=maximum_score,
        )
        template = CommentTemplate(
            tenant_id=actor.tenant_id,
            text=payload.text,
            minimum_score=minimum_score,
            maximum_score=maximum_score,
            is_default=False,
            owner_type=owner_type,
            tenant_admin_id=actor.id if isinstance(actor, TenantAdmin) else None,
            teacher_membership_id=actor.id if isinstance(actor, TeacherMembership) else None,
        )
        db.add(template)
        await db.flush()
        await ReportCommentService._ensure_exact_range_default(
            db,
            tenant_id=actor.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            minimum_score=minimum_score,
            maximum_score=maximum_score,
            preferred_template_id=template.id if payload.is_default else None,
        )
        await db.commit()
        await db.refresh(template)
        return ReportCommentService._template_response(template)

    @staticmethod
    async def update_template(
        db: AsyncSession,
        *,
        actor: TenantAdmin | TeacherMembership,
        template_id: uuid.UUID,
        payload: CommentTemplateUpdate,
    ) -> CommentTemplateResponse:
        owner_type, owner_id = ReportCommentService._actor_owner(actor)
        if (
            isinstance(actor, TeacherMembership)
            and payload.status != CommentTemplateStatus.ARCHIVED
        ):
            await ReportCommentService._require_class_teacher_capability(db, actor)

        template = await ReportCommentService._owned_template(
            db,
            tenant_id=actor.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            template_id=template_id,
            lock=True,
        )
        if template.status == CommentTemplateStatus.ARCHIVED:
            raise BadRequestException("Archived templates are immutable.")

        old_min = Decimal(template.minimum_score)
        old_max = Decimal(template.maximum_score)
        old_default = bool(template.is_default)
        new_min = Decimal(payload.minimum_score) if payload.minimum_score is not None else old_min
        new_max = Decimal(payload.maximum_score) if payload.maximum_score is not None else old_max
        target_status = payload.status or template.status

        if target_status != CommentTemplateStatus.ARCHIVED:
            await ReportCommentService._validate_non_overlapping_range(
                db,
                tenant_id=actor.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                minimum_score=new_min,
                maximum_score=new_max,
                excluding_template_id=template.id,
            )
        if payload.is_default is True and target_status != CommentTemplateStatus.ACTIVE:
            raise ConflictException("Only an active comment can be the default for a range.")

        if payload.text is not None:
            template.text = payload.text
        template.minimum_score = new_min
        template.maximum_score = new_max
        template.status = target_status

        range_changed = old_min != new_min or old_max != new_max
        if target_status != CommentTemplateStatus.ACTIVE:
            template.is_default = False
        elif payload.is_default is True:
            template.is_default = True
        elif payload.is_default is False:
            template.is_default = False
        elif range_changed:
            template.is_default = False
        else:
            template.is_default = old_default

        db.add(template)
        await db.flush()

        if range_changed or target_status != CommentTemplateStatus.ACTIVE:
            await ReportCommentService._ensure_exact_range_default(
                db,
                tenant_id=actor.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                minimum_score=old_min,
                maximum_score=old_max,
            )
        if target_status == CommentTemplateStatus.ACTIVE:
            preferred = template.id if payload.is_default is True else None
            await ReportCommentService._ensure_exact_range_default(
                db,
                tenant_id=actor.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                minimum_score=new_min,
                maximum_score=new_max,
                preferred_template_id=preferred,
            )

        await db.commit()
        await db.refresh(template)
        return ReportCommentService._template_response(template)

    @staticmethod
    async def delete_template(
        db: AsyncSession,
        *,
        actor: TenantAdmin | TeacherMembership,
        template_id: uuid.UUID,
    ) -> None:
        owner_type, owner_id = ReportCommentService._actor_owner(actor)
        template = await ReportCommentService._owned_template(
            db,
            tenant_id=actor.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            template_id=template_id,
            lock=True,
        )
        teacher_ref = (
            await db.execute(
                select(StudentTermTeacherComment.id)
                .where(
                    StudentTermTeacherComment.tenant_id == actor.tenant_id,
                    StudentTermTeacherComment.source_template_id == template.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        report_ref = (
            await db.execute(
                select(ReportCard.id)
                .where(
                    ReportCard.tenant_id == actor.tenant_id,
                    ReportCard.principal_comment_source_template_id == template.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if teacher_ref is not None or report_ref is not None:
            raise ConflictException(
                "Referenced templates cannot be deleted; deactivate or archive the template instead."
            )

        minimum_score = Decimal(template.minimum_score)
        maximum_score = Decimal(template.maximum_score)
        was_active = template.status == CommentTemplateStatus.ACTIVE
        await db.delete(template)
        await db.flush()
        if was_active:
            await ReportCommentService._ensure_exact_range_default(
                db,
                tenant_id=actor.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                minimum_score=minimum_score,
                maximum_score=maximum_score,
            )
        await db.commit()

    @staticmethod
    async def templates_for_performance(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        performance_percentage: Decimal,
    ) -> list[CommentTemplateResponse]:
        score = Decimal(performance_percentage)
        rows = list(
            (
                await db.execute(
                    select(CommentTemplate)
                    .where(
                        CommentTemplate.tenant_id == tenant_id,
                        CommentTemplate.status == CommentTemplateStatus.ACTIVE,
                        CommentTemplate.minimum_score <= score,
                        CommentTemplate.maximum_score >= score,
                        *ReportCommentService._owner_filters(owner_type, owner_id),
                    )
                    .order_by(CommentTemplate.is_default.desc(), CommentTemplate.created_at.asc())
                )
            ).scalars()
        )
        if not rows:
            return []
        ranges = {(Decimal(row.minimum_score), Decimal(row.maximum_score)) for row in rows}
        if len(ranges) > 1:
            raise ConflictException(
                "Overlapping active performance comment ranges exist. Resolve the range configuration."
            )
        return [ReportCommentService._template_response(row) for row in rows]

    @staticmethod
    async def default_template_for_performance(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        owner_type: CommentTemplateOwnerType,
        owner_id: uuid.UUID,
        performance_percentage: Decimal,
    ) -> CommentTemplateResponse | None:
        matches = await ReportCommentService.templates_for_performance(
            db,
            tenant_id=tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            performance_percentage=performance_percentage,
        )
        if not matches:
            return None
        defaults = [item for item in matches if item.is_default]
        if len(defaults) != 1:
            raise ConflictException(
                "Every active performance range must have exactly one default comment."
            )
        return defaults[0]

    @staticmethod
    async def _academic_readiness(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> tuple[bool, Decimal | None, GradingScale | None]:
        snapshot = await ReportReadinessService.resolve_result_readiness(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        if not snapshot.complete or snapshot.performance_percentage is None:
            return False, snapshot.performance_percentage, None
        grading_scale = await ReportReadinessService.grading_scale_for_snapshot(
            db,
            tenant_id=tenant_id,
            snapshot=snapshot,
        )
        if grading_scale is None:
            return False, snapshot.performance_percentage, None
        return True, snapshot.performance_percentage, grading_scale

    @staticmethod
    async def _current_comment_context(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
    ) -> tuple[StudentEnrollment, ClassRoom]:
        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db,
            tenant_id,
            student_id,
            academic_session_id,
        )
        if enrollment is None or enrollment.class_id is None:
            raise BadRequestException("A resolved class placement is required.")
        classroom = (
            await db.execute(
                select(ClassRoom).where(
                    ClassRoom.tenant_id == tenant_id,
                    ClassRoom.id == enrollment.class_id,
                )
            )
        ).scalar_one_or_none()
        if classroom is None:
            raise NotFoundException("Student class not found.")
        return enrollment, classroom

    @staticmethod
    async def _active_teacher_template_for_performance(
        db: AsyncSession,
        *,
        teacher: TeacherMembership,
        template_id: uuid.UUID,
        performance_percentage: Decimal,
    ) -> CommentTemplate:
        template = await ReportCommentService._owned_template(
            db,
            tenant_id=teacher.tenant_id,
            owner_type=CommentTemplateOwnerType.TEACHER,
            owner_id=teacher.id,
            template_id=template_id,
        )
        if template.status != CommentTemplateStatus.ACTIVE:
            raise BadRequestException("Inactive or archived templates cannot be used.")
        if not (
            Decimal(template.minimum_score)
            <= performance_percentage
            <= Decimal(template.maximum_score)
        ):
            raise BadRequestException(
                "The selected saved comment does not match this student's overall performance range."
            )
        return template

    @staticmethod
    async def save_teacher_comment(
        db: AsyncSession,
        *,
        teacher: TeacherMembership,
        student_id: uuid.UUID,
        payload: TeacherCommentWrite,
        submit: bool,
    ) -> TeacherCommentResponse:
        enrollment, classroom = await ReportCommentService._current_comment_context(
            db,
            tenant_id=teacher.tenant_id,
            student_id=student_id,
            academic_session_id=payload.academic_session_id,
        )
        await ReportCommentService._require_class_teacher_capability(
            db,
            teacher,
            class_id=classroom.id,
        )
        if classroom.teacher_membership_id != teacher.id:
            raise ForbiddenException("Only the student's explicit class teacher can comment.")

        (
            ready,
            performance_percentage,
            grading_scale,
        ) = await ReportCommentService._academic_readiness(
            db,
            tenant_id=teacher.tenant_id,
            student_id=student_id,
            academic_session_id=payload.academic_session_id,
            academic_term_id=payload.academic_term_id,
        )
        if not ready or performance_percentage is None or grading_scale is None:
            if submit:
                raise BadRequestException(
                    "Teacher comments cannot be submitted until all expected results are locked."
                )
            performance_percentage = performance_percentage or Decimal("0")
            grade_snapshot = grading_scale.grade if grading_scale else "Pending"
        else:
            grade_snapshot = grading_scale.grade

        if payload.source_template_id is not None:
            await ReportCommentService._active_teacher_template_for_performance(
                db,
                teacher=teacher,
                template_id=payload.source_template_id,
                performance_percentage=performance_percentage,
            )

        comment = (
            await db.execute(
                select(StudentTermTeacherComment).where(
                    StudentTermTeacherComment.tenant_id == teacher.tenant_id,
                    StudentTermTeacherComment.student_id == student_id,
                    StudentTermTeacherComment.student_enrollment_id == enrollment.id,
                    StudentTermTeacherComment.academic_term_id == payload.academic_term_id,
                    StudentTermTeacherComment.teacher_membership_id == teacher.id,
                )
            )
        ).scalar_one_or_none()
        if comment is None:
            comment = StudentTermTeacherComment(
                tenant_id=teacher.tenant_id,
                student_id=student_id,
                student_enrollment_id=enrollment.id,
                class_id=classroom.id,
                academic_session_id=payload.academic_session_id,
                academic_term_id=payload.academic_term_id,
                teacher_membership_id=teacher.id,
                average_snapshot=performance_percentage,
                grade_snapshot=grade_snapshot,
                comment_text=payload.comment_text,
                source_template_id=payload.source_template_id,
            )
        else:
            comment.average_snapshot = performance_percentage
            comment.grade_snapshot = grade_snapshot
            comment.comment_text = payload.comment_text
            comment.source_template_id = payload.source_template_id
        comment.status = TeacherCommentStatus.SUBMITTED if submit else TeacherCommentStatus.DRAFT
        comment.submitted_at = datetime.now(timezone.utc) if submit else None
        db.add(comment)

        # A report snapshot is no longer authoritative if its effective teacher
        # comment changes after generation.
        await ReportCardRepository.mark_outdated_for_student_period(
            db,
            teacher.tenant_id,
            student_id,
            payload.academic_session_id,
            payload.academic_term_id,
        )
        await db.commit()
        await db.refresh(comment)
        return TeacherCommentResponse.model_validate(comment)

    @staticmethod
    async def list_teacher_students(
        db: AsyncSession,
        *,
        teacher: TeacherMembership,
        class_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> TeacherStudentCommentListResponse:
        await ReportCommentService._require_class_teacher_capability(
            db,
            teacher,
            class_id=class_id,
        )
        enrollments = await StudentEnrollmentRepository.list_current_for_class_session(
            db,
            teacher.tenant_id,
            class_id,
            academic_session_id,
        )
        rows: list[TeacherStudentCommentRow] = []
        for enrollment in enrollments:
            student = await StudentRepository.get_by_id(
                db,
                teacher.tenant_id,
                enrollment.student_id,
            )
            if student is None:
                continue
            (
                ready,
                performance_percentage,
                grading_scale,
            ) = await ReportCommentService._academic_readiness(
                db,
                tenant_id=teacher.tenant_id,
                student_id=student.id,
                academic_session_id=academic_session_id,
                academic_term_id=academic_term_id,
            )
            comment = (
                (
                    await db.execute(
                        select(StudentTermTeacherComment)
                        .where(
                            StudentTermTeacherComment.tenant_id == teacher.tenant_id,
                            StudentTermTeacherComment.student_id == student.id,
                            StudentTermTeacherComment.student_enrollment_id == enrollment.id,
                            StudentTermTeacherComment.academic_term_id == academic_term_id,
                            StudentTermTeacherComment.teacher_membership_id == teacher.id,
                        )
                        .order_by(StudentTermTeacherComment.updated_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            if comment is not None and comment.status == TeacherCommentStatus.SUBMITTED:
                if (
                    not ready
                    or performance_percentage != comment.average_snapshot
                    or grading_scale is None
                    or grading_scale.grade != comment.grade_snapshot
                ):
                    comment.status = TeacherCommentStatus.NEEDS_REVIEW
                    db.add(comment)

            suggested = None
            if performance_percentage is not None:
                suggested = await ReportCommentService.default_template_for_performance(
                    db,
                    tenant_id=teacher.tenant_id,
                    owner_type=CommentTemplateOwnerType.TEACHER,
                    owner_id=teacher.id,
                    performance_percentage=performance_percentage,
                )
            status = (
                comment.status.value
                if comment is not None
                else ("ready_for_comment" if ready else "waiting_for_results")
            )
            rows.append(
                TeacherStudentCommentRow(
                    student_id=student.id,
                    student_name=" ".join(
                        part for part in [student.first_name, student.last_name] if part
                    ).strip()
                    or None,
                    admission_number=student.admission_number,
                    academic_ready=ready,
                    readiness_label="READY FOR COMMENT" if ready else "WAITING FOR RESULTS",
                    average=performance_percentage,
                    overall_grade=grading_scale.grade if grading_scale else None,
                    comment=(TeacherCommentResponse.model_validate(comment) if comment else None),
                    comment_status=status,
                    suggested_template=suggested,
                )
            )
        await db.commit()
        return TeacherStudentCommentListResponse(
            class_id=class_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            items=rows,
        )

    @staticmethod
    async def invalidate_for_result_change(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> None:
        await ReportReadinessCache.invalidate_context(
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        comments = list(
            (
                await db.execute(
                    select(StudentTermTeacherComment).where(
                        StudentTermTeacherComment.tenant_id == tenant_id,
                        StudentTermTeacherComment.student_id == student_id,
                        StudentTermTeacherComment.academic_session_id == academic_session_id,
                        StudentTermTeacherComment.academic_term_id == academic_term_id,
                        StudentTermTeacherComment.status == TeacherCommentStatus.SUBMITTED,
                    )
                )
            ).scalars()
        )
        for comment in comments:
            comment.status = TeacherCommentStatus.NEEDS_REVIEW
            db.add(comment)

    @staticmethod
    async def invalidate_for_placement_change(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        invalidate_readiness_cache: bool = True,
    ) -> None:
        if invalidate_readiness_cache:
            await ReportReadinessCache.invalidate_student_session(
                tenant_id=tenant_id,
                student_id=student_id,
                academic_session_id=academic_session_id,
            )
        comments = list(
            (
                await db.execute(
                    select(StudentTermTeacherComment).where(
                        StudentTermTeacherComment.tenant_id == tenant_id,
                        StudentTermTeacherComment.student_id == student_id,
                        StudentTermTeacherComment.academic_session_id == academic_session_id,
                        StudentTermTeacherComment.status == TeacherCommentStatus.SUBMITTED,
                    )
                )
            ).scalars()
        )
        for comment in comments:
            comment.status = TeacherCommentStatus.NEEDS_REVIEW
            db.add(comment)

    @staticmethod
    async def create_override(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        payload: TeacherCommentOverrideRequest,
    ) -> TeacherCommentOverrideResponse:
        enrollment, classroom = await ReportCommentService._current_comment_context(
            db,
            tenant_id=admin.tenant_id,
            student_id=payload.student_id,
            academic_session_id=payload.academic_session_id,
        )
        override = TeacherCommentOverride(
            tenant_id=admin.tenant_id,
            student_id=payload.student_id,
            student_enrollment_id=enrollment.id,
            class_id=classroom.id,
            academic_session_id=payload.academic_session_id,
            academic_term_id=payload.academic_term_id,
            admin_id=admin.id,
            comment_text=payload.comment_text,
            reason=payload.reason,
        )
        db.add(override)
        await ReportCardRepository.mark_outdated_for_student_period(
            db,
            admin.tenant_id,
            payload.student_id,
            payload.academic_session_id,
            payload.academic_term_id,
        )
        await db.commit()
        await db.refresh(override)
        return TeacherCommentOverrideResponse.model_validate(override)

    @staticmethod
    async def effective_teacher_comment(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> tuple[str, TeacherCommentSource, uuid.UUID, str | None, uuid.UUID | None, datetime | None]:
        enrollment, classroom = await ReportCommentService._current_comment_context(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
        )
        override = (
            await db.execute(
                select(TeacherCommentOverride)
                .where(
                    TeacherCommentOverride.tenant_id == tenant_id,
                    TeacherCommentOverride.student_id == student_id,
                    TeacherCommentOverride.student_enrollment_id == enrollment.id,
                    TeacherCommentOverride.class_id == classroom.id,
                    TeacherCommentOverride.academic_session_id == academic_session_id,
                    TeacherCommentOverride.academic_term_id == academic_term_id,
                )
                .order_by(TeacherCommentOverride.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if override is not None:
            return (
                override.comment_text,
                TeacherCommentSource.ADMIN_OVERRIDE,
                override.id,
                override.reason,
                override.admin_id,
                override.created_at,
            )
        if classroom.teacher_membership_id is None:
            raise BadRequestException(
                "Teacher comment is missing; an explicit admin override is required."
            )
        comment = (
            await db.execute(
                select(StudentTermTeacherComment)
                .where(
                    StudentTermTeacherComment.tenant_id == tenant_id,
                    StudentTermTeacherComment.student_id == student_id,
                    StudentTermTeacherComment.student_enrollment_id == enrollment.id,
                    StudentTermTeacherComment.class_id == classroom.id,
                    StudentTermTeacherComment.academic_session_id == academic_session_id,
                    StudentTermTeacherComment.academic_term_id == academic_term_id,
                    StudentTermTeacherComment.teacher_membership_id
                    == classroom.teacher_membership_id,
                    StudentTermTeacherComment.status == TeacherCommentStatus.SUBMITTED,
                )
                .order_by(StudentTermTeacherComment.submitted_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if comment is None:
            raise BadRequestException(
                "Teacher comment is missing or needs review; an explicit admin override is required."
            )
        (
            ready,
            performance_percentage,
            grading_scale,
        ) = await ReportCommentService._academic_readiness(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        if (
            not ready
            or performance_percentage != comment.average_snapshot
            or grading_scale is None
            or grading_scale.grade != comment.grade_snapshot
        ):
            comment.status = TeacherCommentStatus.NEEDS_REVIEW
            db.add(comment)
            await db.flush()
            raise BadRequestException(
                "Teacher comment needs review after academic results changed."
            )
        return (
            comment.comment_text,
            TeacherCommentSource.TEACHER_SUBMISSION,
            comment.id,
            None,
            None,
            comment.submitted_at,
        )

    @staticmethod
    async def principal_default_for_performance(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        performance_percentage: Decimal,
    ) -> CommentTemplateResponse | None:
        return await ReportCommentService.default_template_for_performance(
            db,
            tenant_id=admin.tenant_id,
            owner_type=CommentTemplateOwnerType.TENANT_ADMIN,
            owner_id=admin.id,
            performance_percentage=performance_percentage,
        )
