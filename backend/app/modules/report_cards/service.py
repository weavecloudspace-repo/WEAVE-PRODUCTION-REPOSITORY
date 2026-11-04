from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.modules.auth_identity.models import ActorType
from app.modules.classes.models import (
    AcademicLevel,
    AcademicLevelDepartment,
    ArmLabel,
    ClassRoom,
    Department,
)
from app.modules.parents.models import Parent
from app.modules.report_cards.cache import ReportReadinessCache
from app.modules.report_cards.comment_models import TeacherCommentSource
from app.modules.report_cards.comment_service import ReportCommentService
from app.modules.report_cards.models import (
    ReportCard,
    ReportCardStatus,
    ReportCardSubjectComponent,
    ReportCardSubjectLine,
)
from app.modules.report_cards.performance_service import calculate_report_performance
from app.modules.report_cards.principal_comment_policy import require_admin_template_for_performance
from app.modules.report_cards.readiness_service import ReportReadinessService
from app.modules.report_cards.repository import ReportCardRepository
from app.modules.report_cards.schemas import (
    ReportCardBulkGenerateResponse,
    ReportCardClassOverviewResponse,
    ReportCardClassOverviewRow,
    ReportCardGenerateRequest,
    ReportCardPrincipalCommentUpdate,
    ReportCardResponse,
    ReportCardSubjectComponentResponse,
    ReportCardSubjectLineResponse,
)
from app.modules.student_academics.curriculum_models import ClassTermDepartmentAssignment
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.models import AcademicResultStatus
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.students.models import Student
from app.modules.students.repository import (
    StudentEnrollmentRepository,
    StudentParentLinkRepository,
    StudentRepository,
)
from app.modules.subjects.repository import SubjectRepository
from app.modules.teachers.repository import TeacherRepository
from app.modules.tenant_admins.models import TenantAdmin


BULK_REPORT_GENERATION_BATCH_SIZE = 50
PERCENT_QUANTUM = Decimal("0.01")


class ReportCardService:
    """Single authoritative report readiness, generation and revision policy."""

    @staticmethod
    async def mark_outdated_for_score_change(
        db: AsyncSession,
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
        await ReportCommentService.invalidate_for_result_change(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        await ReportCardRepository.mark_outdated_for_student_period(
            db,
            tenant_id,
            student_id,
            academic_session_id,
            academic_term_id,
        )

    @staticmethod
    async def mark_outdated_for_placement_change(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
    ) -> None:
        """Central invalidation used when one student's placement context changes."""

        await ReportReadinessCache.invalidate_student_session(
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
        )
        await ReportCommentService.invalidate_for_placement_change(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
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
        await db.flush()

    @staticmethod
    async def _expected_curriculum_subjects(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list:
        return await CurriculumResolutionService.resolve_student_curriculum(
            db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_term_id=academic_term_id,
        )

    @staticmethod
    async def _finalized_results_for_student(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list:
        results, _ = await StudentAcademicRepository.list_results(
            db=db,
            tenant_id=tenant_id,
            student_id=student_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            finalized_only=True,
            limit=500,
        )
        return results

    @staticmethod
    async def _ready_results(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> tuple[list, list, list[str]]:
        expected = await ReportCardService._expected_curriculum_subjects(
            db,
            tenant_id,
            student_id,
            academic_term_id,
        )
        if not expected:
            raise BadRequestException("Expected curriculum could not be resolved for this student.")

        results = await ReportCardService._finalized_results_for_student(
            db,
            tenant_id,
            student_id,
            academic_session_id,
            academic_term_id,
        )
        by_curriculum_id = {item.curriculum_subject_id: item for item in results}
        missing_names: list[str] = []
        applicable: list = []
        for expected_item in expected:
            result = by_curriculum_id.get(expected_item.curriculum_subject_id)
            if result is None or result.status != AcademicResultStatus.LOCKED:
                subject = await SubjectRepository.get_subject_by_id(
                    db,
                    tenant_id,
                    expected_item.subject_id,
                )
                missing_names.append(subject.name if subject else str(expected_item.subject_id))
                continue
            applicable.append(result)

        if missing_names:
            raise BadRequestException(f"Missing locked scores for: {', '.join(missing_names)}")
        return expected, applicable, missing_names

    @staticmethod
    def _dense_rank(values: list[tuple[uuid.UUID, Decimal]]) -> dict[uuid.UUID, int]:
        sorted_values = sorted(values, key=lambda item: item[1], reverse=True)
        ranks: dict[uuid.UUID, int] = {}
        current_rank = 0
        previous_score: Decimal | None = None
        for student_id, score in sorted_values:
            if previous_score is None or score != previous_score:
                current_rank += 1
                previous_score = score
            ranks[student_id] = current_rank
        return ranks

    @staticmethod
    async def _teacher_name_for_result(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result,
    ) -> str | None:
        teacher = None
        if result.teacher_assignment_id is not None:
            assignment = await StudentAcademicRepository.get_teacher_assignment_by_id(
                db=db,
                tenant_id=tenant_id,
                assignment_id=result.teacher_assignment_id,
            )
            if assignment is not None:
                teacher = await TeacherRepository.get_teacher_by_id(
                    db=db,
                    tenant_id=tenant_id,
                    teacher_id=assignment.teacher_membership_id,
                )
        if teacher is None:
            teacher = await TeacherRepository.get_teacher_by_id(
                db=db,
                tenant_id=tenant_id,
                teacher_id=result.teacher_membership_id,
            )
        if teacher is None:
            return None
        return (
            " ".join(part for part in [teacher.first_name, teacher.last_name] if part).strip()
            or None
        )

    @staticmethod
    async def _placement_snapshot(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> dict[str, object | None]:
        enrollment = await StudentEnrollmentRepository.get_authoritative_for_session(
            db,
            tenant_id,
            student_id,
            academic_session_id,
        )
        if enrollment is None or enrollment.class_id is None:
            raise BadRequestException("Resolved class placement is required for report generation.")

        row = (
            await db.execute(
                select(ClassRoom, AcademicLevel, ArmLabel)
                .join(
                    AcademicLevel,
                    and_(
                        AcademicLevel.id == ClassRoom.academic_level_id,
                        AcademicLevel.tenant_id == tenant_id,
                    ),
                )
                .join(
                    ArmLabel,
                    and_(
                        ArmLabel.id == ClassRoom.arm_label_id,
                        ArmLabel.tenant_id == tenant_id,
                    ),
                )
                .where(
                    ClassRoom.tenant_id == tenant_id,
                    ClassRoom.id == enrollment.class_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise BadRequestException("Current class placement is invalid.")
        classroom, level, arm = row

        department_row = (
            await db.execute(
                select(AcademicLevelDepartment.id, Department.name)
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
                    ClassTermDepartmentAssignment.class_id == classroom.id,
                    ClassTermDepartmentAssignment.academic_term_id == academic_term_id,
                )
            )
        ).one_or_none()

        teacher_name = None
        if classroom.teacher_membership_id is not None:
            teacher = await TeacherRepository.get_teacher_by_id(
                db=db,
                tenant_id=tenant_id,
                teacher_id=classroom.teacher_membership_id,
            )
            if teacher is not None:
                teacher_name = (
                    " ".join(
                        part for part in [teacher.first_name, teacher.last_name] if part
                    ).strip()
                    or None
                )

        return {
            "enrollment_id": enrollment.id,
            "class_id": classroom.id,
            "academic_level_id": level.id,
            "academic_level_name": level.name,
            "class_name": level.name,
            "class_arm": arm.label,
            "academic_level_department_id": department_row[0] if department_row else None,
            "department_name": department_row[1] if department_row else None,
            "teacher_name": teacher_name,
        }

    @staticmethod
    async def _principal_comment(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        performance_percentage: Decimal,
        principal_comment: str | None,
        principal_template_id: uuid.UUID | None,
        apply_default: bool,
    ) -> tuple[str | None, uuid.UUID | None]:
        if principal_template_id is not None:
            template = await require_admin_template_for_performance(
                db,
                admin=actor,
                template_id=principal_template_id,
                performance_percentage=performance_percentage,
            )
            # A template source means the persisted wording is exactly the selected
            # template. Edited text is manual wording and must not keep template provenance.
            return template.text, template.id

        if apply_default:
            template = await ReportCommentService.principal_default_for_performance(
                db,
                admin=actor,
                performance_percentage=performance_percentage,
            )
            if template is not None:
                return template.text, template.id
        return principal_comment, None

    @staticmethod
    def _subject_percentage(result, components: list[tuple[object, object]]) -> Decimal | None:
        possible = sum(
            (Decimal(str(getattr(component, "maximum_score", "0"))) for component, _ in components),
            Decimal("0"),
        )
        if possible <= 0:
            return None
        return ((Decimal(str(result.total_score)) / possible) * Decimal("100")).quantize(
            PERCENT_QUANTUM, rounding=ROUND_HALF_UP
        )

    @staticmethod
    async def _create_card_from_results(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        student: Student,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        principal_comment: str | None,
        principal_template_id: uuid.UUID | None,
        apply_default_principal_template: bool,
        replaces: ReportCard | None = None,
    ) -> ReportCard:
        placement = await ReportCardService._placement_snapshot(
            db,
            tenant_id=actor.tenant_id,
            student_id=student.id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        _, ready_results, _ = await ReportCardService._ready_results(
            db,
            tenant_id=actor.tenant_id,
            student_id=student.id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )

        component_scores = await StudentAcademicRepository.list_result_component_scores_batch(
            db,
            actor.tenant_id,
            ready_results,
        )
        performance = calculate_report_performance(ready_results, component_scores)
        if performance is None:
            raise BadRequestException(
                "Overall performance could not be calculated from the finalized assessment components."
            )

        (
            teacher_comment,
            teacher_source,
            teacher_source_id,
            override_reason,
            override_admin_id,
            override_at,
        ) = await ReportCommentService.effective_teacher_comment(
            db,
            tenant_id=actor.tenant_id,
            student_id=student.id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
        )
        principal_text, principal_source_template_id = await ReportCardService._principal_comment(
            db,
            actor=actor,
            performance_percentage=performance.percentage,
            principal_comment=principal_comment,
            principal_template_id=principal_template_id,
            apply_default=apply_default_principal_template,
        )

        version = await ReportCardRepository.next_version(
            db,
            actor.tenant_id,
            student.id,
            academic_session_id,
            academic_term_id,
        )
        if replaces is not None and replaces.status == ReportCardStatus.DRAFT:
            replaces.is_outdated = True
            replaces.superseded_at = datetime.now(timezone.utc)
            replaces.status = ReportCardStatus.ARCHIVED
            await ReportCardRepository.save(db, replaces)

        card = await ReportCardRepository.create(
            db,
            ReportCard(
                tenant_id=actor.tenant_id,
                student_id=student.id,
                class_id=placement["class_id"],
                academic_level_id=placement["academic_level_id"],
                academic_level_department_id=placement["academic_level_department_id"],
                academic_session_id=academic_session_id,
                academic_term_id=academic_term_id,
                academic_level_name_snapshot=placement["academic_level_name"],
                class_name_snapshot=placement["class_name"],
                class_arm_snapshot=placement["class_arm"],
                department_name_snapshot=placement["department_name"],
                teacher_name_snapshot=placement["teacher_name"],
                total_score=performance.earned_score,
                average_score=performance.percentage,
                class_teacher_comment=teacher_comment,
                teacher_comment_source=teacher_source.value,
                teacher_comment_source_id=teacher_source_id,
                teacher_comment_override_reason=override_reason,
                teacher_comment_override_admin_id=override_admin_id,
                teacher_comment_override_at=(
                    override_at if teacher_source == TeacherCommentSource.ADMIN_OVERRIDE else None
                ),
                principal_comment=principal_text,
                principal_comment_source_template_id=principal_source_template_id,
                version=version,
                replaces_report_card_id=replaces.id if replaces else None,
                is_outdated=False,
                status=ReportCardStatus.DRAFT,
                generated_by_actor_type=ActorType.TENANT_ADMIN.value,
                generated_by_actor_id=actor.id,
            ),
        )

        for result in ready_results:
            subject = await SubjectRepository.get_subject_by_id(
                db,
                actor.tenant_id,
                result.subject_id,
            )
            result_components = component_scores.get(result.id, [])
            if not result_components:
                raise BadRequestException(
                    f"Assessment components are missing for {subject.name if subject else 'subject'}."
                )
            for component, score in result_components:
                if score is None:
                    raise BadRequestException(
                        f"{component.name} is missing for {subject.name if subject else 'subject'}."
                    )

            grade = result.grade
            remark = result.remark
            if grade is None:
                subject_percentage = ReportCardService._subject_percentage(
                    result, result_components
                )
                if subject_percentage is not None:
                    scale = await StudentAcademicRepository.find_grade_for_score(
                        db=db,
                        tenant_id=actor.tenant_id,
                        score=subject_percentage,
                    )
                    if scale is not None:
                        grade = scale.grade
                        remark = remark or scale.remark

            line = await ReportCardRepository.create_line(
                db,
                ReportCardSubjectLine(
                    tenant_id=actor.tenant_id,
                    report_card_id=card.id,
                    student_subject_result_id=result.id,
                    subject_id=result.subject_id,
                    subject_name=subject.name if subject else "Unknown subject",
                    subject_code=subject.code if subject else None,
                    teacher_name=await ReportCardService._teacher_name_for_result(
                        db,
                        actor.tenant_id,
                        result,
                    ),
                    total_score=result.total_score,
                    grade=grade or "Pending",
                    remark=remark,
                ),
            )
            for component, score in result_components:
                await ReportCardRepository.create_component(
                    db,
                    ReportCardSubjectComponent(
                        tenant_id=actor.tenant_id,
                        report_card_subject_line_id=line.id,
                        assessment_component_id=component.id,
                        name=component.name,
                        code=component.code,
                        position=component.position,
                        maximum_score=component.maximum_score,
                        score=score.score,
                    ),
                )
        return card

    @staticmethod
    async def _apply_class_positions(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        class_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> None:
        cards = await ReportCardRepository.list_current_drafts_for_class_period(
            db,
            tenant_id,
            class_id,
            academic_session_id,
            academic_term_id,
        )
        ranks = ReportCardService._dense_rank(
            [(card.student_id, card.average_score) for card in cards]
        )
        for card in cards:
            card.position = ranks.get(card.student_id)
            card.position_out_of = len(cards)
            await ReportCardRepository.save(db, card)

    @staticmethod
    async def generate(
        db: AsyncSession,
        actor: TenantAdmin,
        payload: ReportCardGenerateRequest,
    ) -> ReportCardResponse | ReportCardBulkGenerateResponse:
        if payload.class_id is None:
            assert payload.student_id is not None
            return await ReportCardService.generate_for_student(
                db,
                actor,
                student_id=payload.student_id,
                academic_session_id=payload.academic_session_id,
                academic_term_id=payload.academic_term_id,
                principal_comment=payload.principal_comment,
                principal_template_id=payload.principal_template_id,
                apply_default_principal_template=payload.apply_default_principal_template,
            )

        # Freeze the population once, then process bounded batches. This avoids
        # offset drift while keeping each transaction small for large schools.
        student_ids = list(
            (
                await db.execute(
                    select(Student.id)
                    .where(
                        Student.tenant_id == actor.tenant_id,
                        Student.class_id == payload.class_id,
                        Student.is_archived.is_(False),
                    )
                    .order_by(Student.id.asc())
                )
            ).scalars()
        )
        generated_ids: list[uuid.UUID] = []
        skipped: list[dict] = []

        for start in range(0, len(student_ids), BULK_REPORT_GENERATION_BATCH_SIZE):
            batch = student_ids[start : start + BULK_REPORT_GENERATION_BATCH_SIZE]
            for student_id in batch:
                try:
                    async with db.begin_nested():
                        response = await ReportCardService.generate_for_student(
                            db,
                            actor,
                            student_id=student_id,
                            academic_session_id=payload.academic_session_id,
                            academic_term_id=payload.academic_term_id,
                            principal_comment=None,
                            principal_template_id=None,
                            apply_default_principal_template=payload.apply_default_principal_template,
                            commit=False,
                            apply_positions=False,
                        )
                    # Only record success after the savepoint itself released.
                    # A failure during savepoint release must not leave a phantom ID
                    # in the response bookkeeping.
                    generated_ids.append(response.id)
                except BadRequestException as exc:
                    skipped.append({"student_id": str(student_id), "reason": str(exc)})
            await db.commit()

        await ReportCardService._apply_class_positions(
            db,
            actor.tenant_id,
            payload.class_id,
            payload.academic_session_id,
            payload.academic_term_id,
        )
        await db.commit()
        generated = [
            await ReportCardService.get(db, actor, report_card_id)
            for report_card_id in generated_ids
        ]
        return ReportCardBulkGenerateResponse(generated=generated, skipped=skipped)

    @staticmethod
    async def generate_for_student(
        db: AsyncSession,
        actor: TenantAdmin,
        *,
        student_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        principal_comment: str | None = None,
        principal_template_id: uuid.UUID | None = None,
        apply_default_principal_template: bool = False,
        commit: bool = True,
        apply_positions: bool = True,
    ) -> ReportCardResponse:
        student = await StudentRepository.get_student_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            student_id=student_id,
        )
        if student is None:
            raise NotFoundException("Student not found.")

        existing_draft = await ReportCardRepository.get_current_draft(
            db,
            actor.tenant_id,
            student_id,
            academic_session_id,
            academic_term_id,
        )
        if existing_draft is not None:
            raise BadRequestException("A current report draft already exists for this student.")

        published = await ReportCardRepository.get_current_published(
            db,
            actor.tenant_id,
            student_id,
            academic_session_id,
            academic_term_id,
        )
        if published is not None and not published.is_outdated:
            raise BadRequestException("The current published report is still authoritative.")

        card = await ReportCardService._create_card_from_results(
            db,
            actor=actor,
            student=student,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            principal_comment=principal_comment,
            principal_template_id=principal_template_id,
            apply_default_principal_template=apply_default_principal_template,
            replaces=published,
        )
        if apply_positions and card.class_id is not None:
            await ReportCardService._apply_class_positions(
                db,
                actor.tenant_id,
                card.class_id,
                academic_session_id,
                academic_term_id,
            )
        if commit:
            await db.commit()
        return await ReportCardService.get(db, actor, card.id)

    @staticmethod
    async def regenerate(
        db: AsyncSession,
        actor: TenantAdmin,
        report_card_id: uuid.UUID,
    ) -> ReportCardResponse:
        existing = await ReportCardRepository.get_by_id(db, actor.tenant_id, report_card_id)
        if existing is None or existing.superseded_at is not None:
            raise NotFoundException("Report card not found.")
        if existing.status == ReportCardStatus.ARCHIVED:
            raise BadRequestException("Archived report cards cannot be regenerated.")

        student = await StudentRepository.get_student_by_id(
            db=db,
            tenant_id=actor.tenant_id,
            student_id=existing.student_id,
        )
        if student is None:
            raise NotFoundException("Student not found.")

        current_draft = await ReportCardRepository.get_current_draft(
            db,
            actor.tenant_id,
            existing.student_id,
            existing.academic_session_id,
            existing.academic_term_id,
        )
        if current_draft is not None and current_draft.id != existing.id:
            raise BadRequestException("A replacement draft already exists.")

        card = await ReportCardService._create_card_from_results(
            db,
            actor=actor,
            student=student,
            academic_session_id=existing.academic_session_id,
            academic_term_id=existing.academic_term_id,
            principal_comment=existing.principal_comment,
            principal_template_id=None,
            apply_default_principal_template=False,
            replaces=existing,
        )
        if card.class_id is not None:
            await ReportCardService._apply_class_positions(
                db,
                actor.tenant_id,
                card.class_id,
                card.academic_session_id,
                card.academic_term_id,
            )
        await db.commit()
        return await ReportCardService.get(db, actor, card.id)

    @staticmethod
    async def update_principal_comment(
        db: AsyncSession,
        actor: TenantAdmin,
        report_card_id: uuid.UUID,
        payload: ReportCardPrincipalCommentUpdate,
    ) -> ReportCardResponse:
        card = await ReportCardRepository.get_by_id(db, actor.tenant_id, report_card_id)
        if card is None or card.superseded_at is not None:
            raise NotFoundException("Report card not found.")
        if card.status != ReportCardStatus.DRAFT:
            raise BadRequestException("Published report revisions are immutable.")

        principal_text, template_id = await ReportCardService._principal_comment(
            db,
            actor=actor,
            performance_percentage=card.average_score,
            principal_comment=payload.principal_comment,
            principal_template_id=payload.principal_template_id,
            apply_default=False,
        )
        card.principal_comment = principal_text
        card.principal_comment_source_template_id = template_id
        await ReportCardRepository.save(db, card)
        await db.commit()
        return await ReportCardService.get(db, actor, card.id)

    @staticmethod
    async def class_overview(
        db: AsyncSession,
        actor: TenantAdmin,
        *,
        class_id: uuid.UUID,
        academic_session_id: uuid.UUID,
        academic_term_id: uuid.UUID,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> ReportCardClassOverviewResponse:
        page_limit = max(1, min(limit, 100))
        page_offset = max(0, offset)
        students, total = await StudentRepository.list_for_tenant(
            db=db,
            tenant_id=actor.tenant_id,
            class_id=class_id,
            search=search,
            offset=page_offset,
            limit=page_limit,
        )

        student_ids = {student.id for student in students}
        cards: list[ReportCard] = []
        if student_ids:
            cards = list(
                (
                    await db.execute(
                        select(ReportCard).where(
                            ReportCard.tenant_id == actor.tenant_id,
                            ReportCard.class_id == class_id,
                            ReportCard.academic_session_id == academic_session_id,
                            ReportCard.academic_term_id == academic_term_id,
                            ReportCard.student_id.in_(student_ids),
                            ReportCard.superseded_at.is_(None),
                        )
                    )
                ).scalars()
            )

        cards_by_student: dict[uuid.UUID, ReportCard] = {}
        for card in cards:
            current = cards_by_student.get(card.student_id)
            if current is None or card.status == ReportCardStatus.DRAFT:
                cards_by_student[card.student_id] = card

        rows: list[ReportCardClassOverviewRow] = []
        expected_counts: list[int] = []
        for student in students:
            readiness = await ReportReadinessService.resolve_result_readiness(
                db,
                tenant_id=actor.tenant_id,
                student_id=student.id,
                academic_session_id=academic_session_id,
                academic_term_id=academic_term_id,
            )
            expected_counts.append(readiness.expected_count)

            teacher_status = "missing"
            try:
                await ReportCommentService.effective_teacher_comment(
                    db,
                    tenant_id=actor.tenant_id,
                    student_id=student.id,
                    academic_session_id=academic_session_id,
                    academic_term_id=academic_term_id,
                )
                teacher_status = "submitted_or_overridden"
            except BadRequestException as exc:
                if "needs review" in str(exc).lower():
                    teacher_status = "needs_review"

            principal_default = None
            if readiness.performance_percentage is not None:
                principal_default = await ReportCommentService.principal_default_for_performance(
                    db,
                    admin=actor,
                    performance_percentage=readiness.performance_percentage,
                )

            card = cards_by_student.get(student.id)
            results_status = "complete" if readiness.complete else "incomplete"
            ready = results_status == "complete" and teacher_status == "submitted_or_overridden"
            rows.append(
                ReportCardClassOverviewRow(
                    student_id=student.id,
                    student_name=(
                        " ".join(
                            part for part in [student.first_name, student.last_name] if part
                        ).strip()
                        or None
                    ),
                    admission_number=student.admission_number,
                    results_readiness=results_status,
                    submitted_count=readiness.locked_count,
                    expected_count=readiness.expected_count,
                    teacher_comment_status=teacher_status,
                    performance_percentage=readiness.performance_percentage,
                    overall_grade=readiness.overall_grade,
                    principal_comment_status=(
                        "available" if principal_default is not None else "manual"
                    ),
                    report_readiness=(
                        "ready"
                        if ready
                        else "override_required"
                        if results_status == "complete"
                        else "waiting_for_results"
                    ),
                    report_card_id=card.id if card else None,
                    report_card_status=card.status.value if card else None,
                    report_card_version=card.version if card else None,
                    is_outdated=card.is_outdated if card else False,
                    missing_subject_names=list(readiness.missing_subject_names),
                )
            )

        return ReportCardClassOverviewResponse(
            class_id=class_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            expected_subject_count=max(expected_counts, default=0),
            items=rows,
            total=total,
            offset=page_offset,
            limit=page_limit,
        )

    @staticmethod
    async def publish(
        db: AsyncSession,
        actor: TenantAdmin,
        report_card_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> ReportCardResponse:
        card = await ReportCardRepository.get_by_id(db, actor.tenant_id, report_card_id)
        if card is None:
            raise NotFoundException("Report card not found.")
        if card.status != ReportCardStatus.DRAFT or card.superseded_at is not None:
            raise BadRequestException("Only the current draft can be published.")
        if card.is_outdated:
            raise BadRequestException(
                "Outdated report cards must be regenerated before publication."
            )

        expected, ready_results, _ = await ReportCardService._ready_results(
            db,
            tenant_id=actor.tenant_id,
            student_id=card.student_id,
            academic_session_id=card.academic_session_id,
            academic_term_id=card.academic_term_id,
        )
        expected_ids = {item.curriculum_subject_id for item in expected}
        lines = await ReportCardRepository.list_lines(db, actor.tenant_id, card.id)
        line_curriculum_ids: set[uuid.UUID] = set()
        for line in lines:
            result = await StudentAcademicRepository.get_result_by_id(
                db,
                actor.tenant_id,
                line.student_subject_result_id,
            )
            if result is None or result.status != AcademicResultStatus.LOCKED:
                raise BadRequestException("Report source results must remain locked.")
            if result.total_score != line.total_score:
                raise BadRequestException("Report results changed; regenerate this draft.")
            line_curriculum_ids.add(result.curriculum_subject_id)
        if line_curriculum_ids != expected_ids:
            raise BadRequestException("Report curriculum changed; regenerate this draft.")

        component_scores = await StudentAcademicRepository.list_result_component_scores_batch(
            db,
            actor.tenant_id,
            ready_results,
        )
        performance = calculate_report_performance(ready_results, component_scores)
        if (
            performance is None
            or performance.earned_score != card.total_score
            or performance.percentage != card.average_score
        ):
            raise BadRequestException("Report performance changed; regenerate this draft.")

        (
            teacher_text,
            teacher_source,
            teacher_source_id,
            _,
            _,
            _,
        ) = await ReportCommentService.effective_teacher_comment(
            db,
            tenant_id=actor.tenant_id,
            student_id=card.student_id,
            academic_session_id=card.academic_session_id,
            academic_term_id=card.academic_term_id,
        )
        if (
            card.class_teacher_comment != teacher_text
            or card.teacher_comment_source != teacher_source.value
            or card.teacher_comment_source_id != teacher_source_id
        ):
            raise BadRequestException("Teacher comment changed; regenerate this draft.")

        previous = await ReportCardRepository.get_current_published(
            db,
            actor.tenant_id,
            card.student_id,
            card.academic_session_id,
            card.academic_term_id,
        )
        now = datetime.now(timezone.utc)
        if previous is not None and previous.id != card.id:
            previous.is_outdated = True
            previous.superseded_at = now
            await ReportCardRepository.save(db, previous)
        card.status = ReportCardStatus.PUBLISHED
        card.published_at = now
        card.published_by = actor.id
        await ReportCardRepository.save(db, card)
        if commit:
            await db.commit()
        return await ReportCardService.get(db, actor, card.id)

    @staticmethod
    async def _ensure_parent_can_view(
        db: AsyncSession,
        parent: Parent,
        student_id: uuid.UUID,
    ) -> None:
        link = await StudentParentLinkRepository.get_by_student_and_membership(
            db=db,
            tenant_id=parent.tenant_id,
            student_id=student_id,
            membership_id=parent.id,
        )
        if link is None:
            raise ForbiddenException("You cannot view report cards for this student.")

    @staticmethod
    async def _response(db: AsyncSession, card: ReportCard) -> ReportCardResponse:
        student = await StudentRepository.get_student_by_id(
            db,
            card.tenant_id,
            card.student_id,
        )
        session = await StudentAcademicRepository.get_academic_session_by_id(
            db,
            card.tenant_id,
            card.academic_session_id,
        )
        term = await StudentAcademicRepository.get_term_by_id(
            db,
            card.tenant_id,
            card.academic_term_id,
        )
        lines = await ReportCardRepository.list_lines(db, card.tenant_id, card.id)
        components = await ReportCardRepository.list_line_components_batch(
            db,
            card.tenant_id,
            [line.id for line in lines],
        )
        response_lines = [
            ReportCardSubjectLineResponse(
                id=line.id,
                subject_id=line.subject_id,
                subject_name=line.subject_name,
                subject_code=line.subject_code,
                teacher_name=line.teacher_name,
                components=[
                    ReportCardSubjectComponentResponse.model_validate(item)
                    for item in components.get(line.id, [])
                ],
                total_score=line.total_score,
                grade=line.grade,
                remark=line.remark,
            )
            for line in lines
        ]
        return ReportCardResponse(
            id=card.id,
            tenant_id=card.tenant_id,
            student_id=card.student_id,
            student_name=(
                " ".join(part for part in [student.first_name, student.last_name] if part).strip()
                if student
                else None
            ),
            admission_number=student.admission_number if student else None,
            student_passport_photo_url=student.passport_photo_url if student else None,
            class_id=card.class_id,
            academic_level_id=card.academic_level_id,
            academic_level_department_id=card.academic_level_department_id,
            class_name=card.class_name_snapshot,
            class_arm=card.class_arm_snapshot,
            department_name=card.department_name_snapshot,
            class_teacher_name=card.teacher_name_snapshot,
            academic_session_id=card.academic_session_id,
            academic_session_name=session.name if session else None,
            academic_term_id=card.academic_term_id,
            academic_term_name=term.name.value if term else None,
            total_score=card.total_score,
            average_score=card.average_score,
            position=card.position,
            position_out_of=card.position_out_of,
            class_teacher_comment=card.class_teacher_comment,
            teacher_comment_source=card.teacher_comment_source,
            teacher_comment_source_id=card.teacher_comment_source_id,
            principal_comment=card.principal_comment,
            principal_comment_source_template_id=card.principal_comment_source_template_id,
            version=card.version,
            replaces_report_card_id=card.replaces_report_card_id,
            published_at=card.published_at,
            published_by=card.published_by,
            is_outdated=card.is_outdated,
            superseded_at=card.superseded_at,
            status=card.status,
            lines=response_lines,
            created_at=card.created_at,
            updated_at=card.updated_at,
        )

    @staticmethod
    async def get(
        db: AsyncSession,
        actor: TenantAdmin | Parent | Student,
        report_card_id: uuid.UUID,
    ) -> ReportCardResponse:
        card = await ReportCardRepository.get_by_id(db, actor.tenant_id, report_card_id)
        if card is None:
            raise NotFoundException("Report card not found.")
        if isinstance(actor, Parent):
            await ReportCardService._ensure_parent_can_view(db, actor, card.student_id)
            if card.status != ReportCardStatus.PUBLISHED:
                raise NotFoundException("Report card not found.")
        if isinstance(actor, Student):
            if card.student_id != actor.id or card.status != ReportCardStatus.PUBLISHED:
                raise NotFoundException("Report card not found.")
        return await ReportCardService._response(db, card)

    @staticmethod
    async def list_cards(
        db: AsyncSession,
        actor: TenantAdmin | Parent | Student,
        *,
        student_id: uuid.UUID | None = None,
        class_id: uuid.UUID | None = None,
        academic_session_id: uuid.UUID | None = None,
        academic_term_id: uuid.UUID | None = None,
        status: ReportCardStatus | None = None,
        is_outdated: bool | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ReportCardResponse], int]:
        published_only = False
        if isinstance(actor, Parent):
            if student_id is None:
                raise BadRequestException("student_id is required.")
            await ReportCardService._ensure_parent_can_view(db, actor, student_id)
            published_only = True
        elif isinstance(actor, Student):
            student_id = actor.id
            published_only = True

        cards, total = await ReportCardRepository.list_cards(
            db,
            actor.tenant_id,
            skip=max(0, skip),
            limit=max(1, min(limit, 100)),
            student_id=student_id,
            class_id=class_id,
            academic_session_id=academic_session_id,
            academic_term_id=academic_term_id,
            status=status,
            is_outdated=is_outdated,
            published_only=published_only,
            search=search,
        )
        return [await ReportCardService._response(db, card) for card in cards], total
