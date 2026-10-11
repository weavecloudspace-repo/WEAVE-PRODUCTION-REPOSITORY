"""Application service for persistent level curricula and term class specialization."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.classes.category_catalog import category_supports_departments
from app.modules.classes.department_repository import AcademicLevelDepartmentRepository
from app.modules.classes.models import (
    AcademicCategory,
    AcademicLevel,
    AcademicLevelDepartment,
    AcademicLevelStatus,
    ArmLabel,
    ClassRoom,
    Department,
)
from app.modules.classes.repository import AcademicLevelRepository, ClassRoomRepository
from app.modules.student_academics.curriculum_models import (
    ClassTermDepartmentAssignment,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
)
from app.modules.student_academics.academic_evidence import AcademicEvidenceProtection
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.curriculum_v2_repository import CurriculumSubjectRepository
from app.modules.student_academics.curriculum_v2_schemas import (
    AcademicLevelSpecializationResponse,
    AcademicLevelSpecializationUpdate,
    ClassTermDepartmentCopyResponse,
    ClassTermDepartmentResponse,
    CurriculumResponse,
    CurriculumSubjectCreate,
    CurriculumSubjectDepartmentResponse,
    CurriculumSubjectResponse,
    CurriculumSubjectUpdate,
    EligibleTeacherAssignmentClassResponse,
    ResolvedClassSubjectResponse,
    TeacherAssignmentSubjectAvailabilityResponse,
)
from app.modules.student_academics.models import (
    AcademicLifecycleAudit,
    AcademicTerm,
    AcademicTermStatus,
    TeacherAssignment,
    TeacherAssignmentLifecycleAudit,
)
from app.modules.student_academics.write_guard import ensure_academic_write_window
from app.modules.subjects.models import Subject
from app.tenant_management.repository import TenantRepository


class AcademicCurriculumService:
    """Canonical curriculum/specialization service.

    Curriculum subject scope is persistent. Terms never own subject applicability.
    Terms only activate specialization filtering and store the exact department of
    each class through ClassTermDepartmentAssignment.
    """

    @staticmethod
    async def _curriculum(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        level_id: uuid.UUID,
        *,
        require_active_level: bool = False,
    ) -> Curriculum:
        level = await AcademicLevelRepository.get_by_id(db, tenant_id, level_id)
        if level is None:
            raise NotFoundException("Academic level not found.")
        if require_active_level and level.status != AcademicLevelStatus.ACTIVE:
            raise ConflictException(
                "Academic level must be active before curriculum is configured."
            )
        row = (
            await db.execute(
                select(Curriculum).where(
                    Curriculum.tenant_id == tenant_id,
                    Curriculum.academic_level_id == level_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException(
                "Curriculum not found. Activate the academic level before configuring curriculum."
            )
        return row

    @staticmethod
    async def _term(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> AcademicTerm:
        query = select(AcademicTerm).where(
            AcademicTerm.tenant_id == tenant_id,
            AcademicTerm.id == term_id,
        )
        if lock:
            query = query.with_for_update()
        term = (await db.execute(query)).scalar_one_or_none()
        if term is None:
            raise NotFoundException("Academic term not found.")
        return term

    @staticmethod
    async def _curriculum_subject_context(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        *,
        lock: bool = False,
        require_active_level: bool = False,
        require_active_subject: bool = False,
    ) -> tuple[CurriculumSubject, Curriculum, Subject]:
        context = await CurriculumSubjectRepository.get_context(
            db,
            tenant_id,
            curriculum_subject_id,
            lock=lock,
        )
        if context is None:
            raise NotFoundException("Curriculum subject not found.")
        row, curriculum = context
        level = await AcademicLevelRepository.get_by_id(db, tenant_id, curriculum.academic_level_id)
        if level is None:
            raise NotFoundException("Academic level not found.")
        if require_active_level and level.status != AcademicLevelStatus.ACTIVE:
            raise ConflictException("Academic level must be active.")
        subject = (
            await db.execute(
                select(Subject).where(
                    Subject.tenant_id == tenant_id,
                    Subject.id == row.subject_id,
                )
            )
        ).scalar_one_or_none()
        if subject is None:
            raise NotFoundException("Subject not found.")
        if require_active_subject and (not subject.is_active or subject.archived_at is not None):
            raise ConflictException("Subject must be active.")
        return row, curriculum, subject

    @staticmethod
    async def _subject_department_scope_map(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        curriculum_subject_ids: list[uuid.UUID] | set[uuid.UUID],
    ) -> dict[uuid.UUID, list[CurriculumSubjectDepartmentResponse]]:
        subject_ids = list(dict.fromkeys(curriculum_subject_ids))
        if not subject_ids:
            return {}
        rows = (
            await db.execute(
                select(
                    CurriculumSubjectDepartment.curriculum_subject_id,
                    AcademicLevelDepartment.id,
                    Department.id,
                    Department.name,
                )
                .join(
                    AcademicLevelDepartment,
                    AcademicLevelDepartment.id
                    == CurriculumSubjectDepartment.academic_level_department_id,
                )
                .join(Department, Department.id == AcademicLevelDepartment.department_id)
                .where(
                    CurriculumSubjectDepartment.tenant_id == tenant_id,
                    CurriculumSubjectDepartment.curriculum_subject_id.in_(subject_ids),
                    AcademicLevelDepartment.tenant_id == tenant_id,
                    Department.tenant_id == tenant_id,
                )
                .order_by(CurriculumSubjectDepartment.curriculum_subject_id, Department.name)
            )
        ).all()
        result: dict[uuid.UUID, list[CurriculumSubjectDepartmentResponse]] = {
            subject_id: [] for subject_id in subject_ids
        }
        for curriculum_subject_id, link_id, department_id, department_name in rows:
            result.setdefault(curriculum_subject_id, []).append(
                CurriculumSubjectDepartmentResponse(
                    academic_level_department_id=link_id,
                    department_id=department_id,
                    department_name=department_name,
                )
            )
        return result

    @staticmethod
    async def _subject_department_scopes(
        db: AsyncSession,
        row: CurriculumSubject,
    ) -> list[CurriculumSubjectDepartmentResponse]:
        scopes = await AcademicCurriculumService._subject_department_scope_map(
            db,
            tenant_id=row.tenant_id,
            curriculum_subject_ids=[row.id],
        )
        return scopes.get(row.id, [])

    @staticmethod
    async def _curriculum_subject_response(
        db: AsyncSession,
        row: CurriculumSubject,
        subject: Subject | None = None,
        *,
        departments: list[CurriculumSubjectDepartmentResponse] | None = None,
    ) -> CurriculumSubjectResponse:
        if subject is None:
            subject = (
                await db.execute(
                    select(Subject).where(
                        Subject.tenant_id == row.tenant_id,
                        Subject.id == row.subject_id,
                    )
                )
            ).scalar_one_or_none()
        if subject is None:
            raise NotFoundException("Subject not found.")
        if departments is None:
            departments = await AcademicCurriculumService._subject_department_scopes(db, row)
        return CurriculumSubjectResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            curriculum_id=row.curriculum_id,
            subject_id=row.subject_id,
            subject_name=subject.name,
            subject_code=subject.code,
            is_elective=row.is_elective,
            is_active=row.is_active,
            departments=departments,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def _ensure_department_capability(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_level_id: uuid.UUID,
    ) -> AcademicLevel:
        level = await AcademicLevelRepository.get_by_id(db, tenant_id, academic_level_id, lock=True)
        tenant = await TenantRepository.get_by_id(db, tenant_id)
        if level is None:
            raise NotFoundException("Academic level not found.")
        if level.status != AcademicLevelStatus.ACTIVE:
            raise ConflictException("Academic level must be active.")
        if tenant is None or tenant.institution_type is None:
            raise ConflictException(
                "Institution type is required before specialization can be configured."
            )
        if not category_supports_departments(tenant.institution_type, level.category):
            raise ConflictException(
                "Departments are not supported by this academic level category."
            )
        return level

    @staticmethod
    async def _validated_level_department_ids(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_level_id: uuid.UUID,
        ids: list[uuid.UUID],
    ) -> list[AcademicLevelDepartment]:
        if not ids:
            return []
        await AcademicCurriculumService._ensure_department_capability(
            db,
            tenant_id=tenant_id,
            academic_level_id=academic_level_id,
        )
        requested_ids = list(dict.fromkeys(ids))
        rows = (
            await db.execute(
                select(AcademicLevelDepartment, Department)
                .join(Department, Department.id == AcademicLevelDepartment.department_id)
                .where(
                    AcademicLevelDepartment.tenant_id == tenant_id,
                    AcademicLevelDepartment.academic_level_id == academic_level_id,
                    AcademicLevelDepartment.id.in_(requested_ids),
                    Department.tenant_id == tenant_id,
                )
                .with_for_update()
            )
        ).all()
        by_id = {link.id: (link, department) for link, department in rows}
        if set(by_id) != set(requested_ids):
            raise ConflictException(
                "Every selected department must be enabled for this academic level."
            )
        for link, department in by_id.values():
            if (
                not link.is_active
                or link.archived_at is not None
                or not department.is_active
                or department.archived_at is not None
            ):
                raise ConflictException("Every selected level department must be active.")
        return [by_id[link_id][0] for link_id in requested_ids]

    @staticmethod
    async def _replace_department_scopes(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        curriculum_subject: CurriculumSubject,
        curriculum: Curriculum,
        academic_level_department_ids: list[uuid.UUID],
    ) -> bool:
        links = await AcademicCurriculumService._validated_level_department_ids(
            db,
            tenant_id=tenant_id,
            academic_level_id=curriculum.academic_level_id,
            ids=academic_level_department_ids,
        )
        existing = await CurriculumSubjectRepository.list_department_links(
            db, tenant_id, curriculum_subject.id, lock=True
        )
        old_ids = {row.academic_level_department_id for row in existing}
        new_ids = {row.id for row in links}
        if old_ids == new_ids:
            return False
        await db.execute(
            delete(CurriculumSubjectDepartment).where(
                CurriculumSubjectDepartment.tenant_id == tenant_id,
                CurriculumSubjectDepartment.curriculum_subject_id == curriculum_subject.id,
            )
        )
        for link in links:
            db.add(
                CurriculumSubjectDepartment(
                    tenant_id=tenant_id,
                    curriculum_subject_id=curriculum_subject.id,
                    academic_level_department_id=link.id,
                )
            )
        await db.flush()
        return True

    @staticmethod
    async def get_curriculum(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        level_id: uuid.UUID,
    ) -> CurriculumResponse:
        curriculum = await AcademicCurriculumService._curriculum(db, tenant_id, level_id)
        level = await AcademicLevelRepository.get_by_id(db, tenant_id, level_id)
        rows = (
            await db.execute(
                select(CurriculumSubject, Subject)
                .join(Subject, Subject.id == CurriculumSubject.subject_id)
                .where(
                    CurriculumSubject.tenant_id == tenant_id,
                    CurriculumSubject.curriculum_id == curriculum.id,
                    Subject.tenant_id == tenant_id,
                )
                .order_by(Subject.name)
            )
        ).all()
        scope_map = await AcademicCurriculumService._subject_department_scope_map(
            db,
            tenant_id=tenant_id,
            curriculum_subject_ids=[item.id for item, _subject in rows],
        )
        return CurriculumResponse(
            id=curriculum.id,
            tenant_id=tenant_id,
            academic_level_id=level_id,
            level_name=level.name if level else None,
            subjects=[
                await AcademicCurriculumService._curriculum_subject_response(
                    db,
                    item,
                    subject,
                    departments=scope_map.get(item.id, []),
                )
                for item, subject in rows
            ],
        )

    @staticmethod
    async def add_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        level_id: uuid.UUID,
        payload: CurriculumSubjectCreate,
    ) -> CurriculumSubjectResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        curriculum = await AcademicCurriculumService._curriculum(
            db, tenant_id, level_id, require_active_level=True
        )
        subject = (
            await db.execute(
                select(Subject).where(
                    Subject.tenant_id == tenant_id,
                    Subject.id == payload.subject_id,
                    Subject.is_active.is_(True),
                    Subject.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if subject is None:
            raise NotFoundException("Active subject not found.")
        existing = await CurriculumSubjectRepository.get_for_curriculum_subject(
            db, tenant_id, curriculum.id, subject.id
        )
        if existing:
            raise ConflictException("This subject is already in the level curriculum.")
        row = CurriculumSubject(
            tenant_id=tenant_id,
            curriculum_id=curriculum.id,
            subject_id=subject.id,
            is_elective=payload.is_elective,
            is_active=True,
        )
        try:
            await CurriculumSubjectRepository.add(db, row)
            await AcademicCurriculumService._replace_department_scopes(
                db,
                tenant_id=tenant_id,
                curriculum_subject=row,
                curriculum=curriculum,
                academic_level_department_ids=payload.academic_level_department_ids,
            )
            await db.commit()
            await db.refresh(row)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("This subject is already in the level curriculum.") from exc
        return await AcademicCurriculumService._curriculum_subject_response(db, row, subject)

    @staticmethod
    async def update_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        payload: CurriculumSubjectUpdate,
    ) -> CurriculumSubjectResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        row, curriculum, subject = await AcademicCurriculumService._curriculum_subject_context(
            db,
            tenant_id,
            curriculum_subject_id,
            lock=True,
            require_active_level=True,
        )
        if not row.is_active:
            raise ConflictException(
                "Inactive curriculum subjects cannot be edited. Activate the membership first."
            )
        dependencies = await CurriculumSubjectRepository.count_dependencies(db, tenant_id, row.id)
        if (
            "is_elective" in payload.model_fields_set
            and payload.is_elective != row.is_elective
            and dependencies["results_total"] > 0
        ):
            raise ConflictException(
                "Curriculum subject elective meaning is locked after academic results exist.",
                payload={"dependency_counts": {"results_total": dependencies["results_total"]}},
            )
        scope_changed = False
        if "academic_level_department_ids" in payload.model_fields_set:
            requested = payload.academic_level_department_ids or []
            existing_links = await CurriculumSubjectRepository.list_department_links(
                db, tenant_id, row.id, lock=True
            )
            old_ids = {link.academic_level_department_id for link in existing_links}
            if old_ids != set(requested) and dependencies["results_total"] > 0:
                raise ConflictException(
                    "Department applicability is locked after academic results exist for this curriculum subject.",
                    payload={"dependency_counts": {"results_total": dependencies["results_total"]}},
                )
            scope_changed = await AcademicCurriculumService._replace_department_scopes(
                db,
                tenant_id=tenant_id,
                curriculum_subject=row,
                curriculum=curriculum,
                academic_level_department_ids=requested,
            )
        if "is_elective" in payload.model_fields_set:
            row.is_elective = bool(payload.is_elective)
        await CurriculumSubjectRepository.save(db, row)
        if scope_changed:
            current_term = (
                await db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.tenant_id == tenant_id,
                        AcademicTerm.is_current.is_(True),
                        AcademicTerm.status == AcademicTermStatus.OPEN,
                    )
                )
            ).scalar_one_or_none()
            if current_term is not None:
                await AcademicCurriculumService.reconcile_teacher_assignments_for_term(
                    db,
                    tenant_id=tenant_id,
                    term=current_term,
                    acting_admin_id=None,
                    transition_boundary=date.today(),
                )
        await db.commit()
        await db.refresh(row)
        return await AcademicCurriculumService._curriculum_subject_response(db, row, subject)

    @staticmethod
    async def activate_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
    ) -> CurriculumSubjectResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        row, _curriculum, subject = await AcademicCurriculumService._curriculum_subject_context(
            db,
            tenant_id,
            curriculum_subject_id,
            lock=True,
            require_active_level=True,
            require_active_subject=True,
        )
        if not row.is_active:
            row.is_active = True
            await CurriculumSubjectRepository.save(db, row)
            await db.commit()
            await db.refresh(row)
        return await AcademicCurriculumService._curriculum_subject_response(db, row, subject)

    @staticmethod
    async def deactivate_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
    ) -> CurriculumSubjectResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        row, _curriculum, subject = await AcademicCurriculumService._curriculum_subject_context(
            db, tenant_id, curriculum_subject_id, lock=True, require_active_level=True
        )
        if not row.is_active:
            return await AcademicCurriculumService._curriculum_subject_response(db, row, subject)
        dependencies = await CurriculumSubjectRepository.count_dependencies(db, tenant_id, row.id)
        blockers = {
            key: dependencies[key]
            for key in ("teacher_assignments_active", "results_live")
            if dependencies[key] > 0
        }
        if blockers:
            raise ConflictException(
                "This curriculum subject still has live academic dependencies and cannot be deactivated.",
                payload={"dependency_counts": blockers},
            )
        row.is_active = False
        await CurriculumSubjectRepository.save(db, row)
        await db.commit()
        await db.refresh(row)
        return await AcademicCurriculumService._curriculum_subject_response(db, row, subject)

    @staticmethod
    async def hard_delete_subject(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
    ) -> CurriculumSubjectResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        row, _curriculum, subject = await AcademicCurriculumService._curriculum_subject_context(
            db, tenant_id, curriculum_subject_id, lock=True
        )
        dependencies = await CurriculumSubjectRepository.count_dependencies(db, tenant_id, row.id)
        historical = {
            key: dependencies[key]
            for key in (
                "teacher_assignments_total",
                "teacher_assignment_audits_total",
                "results_total",
            )
            if dependencies[key] > 0
        }
        if historical:
            raise ConflictException(
                "This curriculum subject has academic history and cannot be permanently deleted.",
                payload={"dependency_counts": historical},
            )
        response = await AcademicCurriculumService._curriculum_subject_response(db, row, subject)
        await CurriculumSubjectRepository.delete(db, row)
        await db.commit()
        return response

    @staticmethod
    async def _class_department_responses(
        db: AsyncSession,
        rows: list[ClassTermDepartmentAssignment],
    ) -> list[ClassTermDepartmentResponse]:
        if not rows:
            return []
        tenant_id = rows[0].tenant_id
        link_ids = {row.academic_level_department_id for row in rows}
        contexts = (
            await db.execute(
                select(
                    AcademicLevelDepartment.id,
                    AcademicLevelDepartment.department_id,
                    Department.name,
                )
                .join(Department, Department.id == AcademicLevelDepartment.department_id)
                .where(
                    AcademicLevelDepartment.tenant_id == tenant_id,
                    AcademicLevelDepartment.id.in_(link_ids),
                    Department.tenant_id == tenant_id,
                )
            )
        ).all()
        by_link_id = {
            link_id: (department_id, department_name)
            for link_id, department_id, department_name in contexts
        }
        responses: list[ClassTermDepartmentResponse] = []
        for row in rows:
            context = by_link_id.get(row.academic_level_department_id)
            if context is None:
                raise ConflictException(
                    "Class specialization references a missing level department."
                )
            department_id, department_name = context
            responses.append(
                ClassTermDepartmentResponse(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    class_id=row.class_id,
                    academic_term_id=row.academic_term_id,
                    academic_level_department_id=row.academic_level_department_id,
                    department_id=department_id,
                    department_name=department_name,
                    assigned_by_admin_id=row.assigned_by_admin_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return responses

    @staticmethod
    async def _class_department_response(
        db: AsyncSession,
        row: ClassTermDepartmentAssignment,
    ) -> ClassTermDepartmentResponse:
        return (await AcademicCurriculumService._class_department_responses(db, [row]))[0]

    @staticmethod
    async def get_class_department(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> ClassTermDepartmentResponse | None:
        classroom = await ClassRoomRepository.get_by_id(db, tenant_id, class_id)
        if classroom is None:
            raise NotFoundException("Class not found.")
        await AcademicCurriculumService._term(db, tenant_id, term_id)
        row = (
            await db.execute(
                select(ClassTermDepartmentAssignment).where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.class_id == class_id,
                    ClassTermDepartmentAssignment.academic_term_id == term_id,
                )
            )
        ).scalar_one_or_none()
        return await AcademicCurriculumService._class_department_response(db, row) if row else None

    @staticmethod
    async def list_class_departments(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> list[ClassTermDepartmentResponse]:
        await AcademicCurriculumService._term(db, tenant_id, term_id)
        rows = list(
            (
                await db.execute(
                    select(ClassTermDepartmentAssignment)
                    .where(
                        ClassTermDepartmentAssignment.tenant_id == tenant_id,
                        ClassTermDepartmentAssignment.academic_term_id == term_id,
                    )
                    .order_by(ClassTermDepartmentAssignment.class_id)
                )
            ).scalars()
        )
        return await AcademicCurriculumService._class_department_responses(db, rows)

    @staticmethod
    async def _class_department_name_map(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term_id: uuid.UUID,
        class_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, str | None]:
        if not class_ids:
            return {}
        rows = (
            await db.execute(
                select(ClassTermDepartmentAssignment.class_id, Department.name)
                .join(
                    AcademicLevelDepartment,
                    AcademicLevelDepartment.id
                    == ClassTermDepartmentAssignment.academic_level_department_id,
                )
                .join(Department, Department.id == AcademicLevelDepartment.department_id)
                .where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.academic_term_id == term_id,
                    ClassTermDepartmentAssignment.class_id.in_(class_ids),
                    AcademicLevelDepartment.tenant_id == tenant_id,
                    Department.tenant_id == tenant_id,
                )
            )
        ).all()
        return {class_id: department_name for class_id, department_name in rows}

    @staticmethod
    async def _subject_ids_for_level_department(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_level_id: uuid.UUID,
        academic_level_department_id: uuid.UUID | None,
    ) -> set[uuid.UUID]:
        rows = list(
            (
                await db.execute(
                    select(CurriculumSubject.id)
                    .join(Curriculum, Curriculum.id == CurriculumSubject.curriculum_id)
                    .join(Subject, Subject.id == CurriculumSubject.subject_id)
                    .where(
                        CurriculumSubject.tenant_id == tenant_id,
                        CurriculumSubject.is_active.is_(True),
                        Curriculum.tenant_id == tenant_id,
                        Curriculum.academic_level_id == academic_level_id,
                        Subject.tenant_id == tenant_id,
                        Subject.is_active.is_(True),
                        Subject.archived_at.is_(None),
                    )
                )
            ).scalars()
        )
        if not rows:
            return set()
        links = list(
            (
                await db.execute(
                    select(
                        CurriculumSubjectDepartment.curriculum_subject_id,
                        CurriculumSubjectDepartment.academic_level_department_id,
                    ).where(
                        CurriculumSubjectDepartment.tenant_id == tenant_id,
                        CurriculumSubjectDepartment.curriculum_subject_id.in_(rows),
                    )
                )
            ).all()
        )
        links_by_subject: dict[uuid.UUID, set[uuid.UUID]] = {}
        for curriculum_subject_id, level_department_id in links:
            links_by_subject.setdefault(curriculum_subject_id, set()).add(level_department_id)
        return {
            subject_id
            for subject_id in rows
            if not links_by_subject.get(subject_id)
            or academic_level_department_id in links_by_subject[subject_id]
        }

    @staticmethod
    async def set_class_department(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        admin_id: uuid.UUID,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
        academic_level_department_id: uuid.UUID,
    ) -> ClassTermDepartmentResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        term = await AcademicCurriculumService._term(db, tenant_id, term_id, lock=True)
        if term.status in {AcademicTermStatus.CLOSING, AcademicTermStatus.CLOSED}:
            raise ConflictException(
                "Class specialization cannot be changed after term closing begins."
            )
        classroom = await ClassRoomRepository.get_by_id(db, tenant_id, class_id, lock=True)
        if classroom is None or not classroom.is_active or classroom.archived_at is not None:
            raise ConflictException("Class must be active before specialization is assigned.")
        level = await AcademicCurriculumService._ensure_department_capability(
            db,
            tenant_id=tenant_id,
            academic_level_id=classroom.academic_level_id,
        )
        if not CurriculumResolutionService.specialization_is_active(level, term):
            raise ConflictException(
                "This level does not use department specialization in the selected term."
            )
        link = await AcademicLevelDepartmentRepository.get_by_id(
            db, tenant_id, academic_level_department_id, lock=True
        )
        if link is None or link.academic_level_id != classroom.academic_level_id:
            raise ConflictException("Selected department is not enabled for this academic level.")
        if (
            not link.is_active
            or link.archived_at is not None
            or not link.department.is_active
            or link.department.archived_at is not None
        ):
            raise ConflictException("Selected level department must be active.")
        row = (
            await db.execute(
                select(ClassTermDepartmentAssignment)
                .where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.class_id == class_id,
                    ClassTermDepartmentAssignment.academic_term_id == term_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        old_id = row.academic_level_department_id if row else None
        if old_id == link.id:
            return await AcademicCurriculumService._class_department_response(db, row)

        affected: set[uuid.UUID] = set()
        if term.status == AcademicTermStatus.OPEN:
            old_subjects = await AcademicCurriculumService._subject_ids_for_level_department(
                db,
                tenant_id=tenant_id,
                academic_level_id=classroom.academic_level_id,
                academic_level_department_id=old_id,
            )
            new_subjects = await AcademicCurriculumService._subject_ids_for_level_department(
                db,
                tenant_id=tenant_id,
                academic_level_id=classroom.academic_level_id,
                academic_level_department_id=link.id,
            )
            affected = old_subjects.symmetric_difference(new_subjects)
            evidence = await AcademicEvidenceProtection.counts_for_class_term(
                db,
                tenant_id=tenant_id,
                class_id=class_id,
                academic_term_id=term.id,
                affected_curriculum_subject_ids=affected,
            )
            AcademicEvidenceProtection.ensure_none(
                evidence,
                operation="Class specialization change",
            )

        if row is None:
            row = ClassTermDepartmentAssignment(
                tenant_id=tenant_id,
                class_id=class_id,
                academic_term_id=term_id,
                academic_level_department_id=link.id,
                assigned_by_admin_id=admin_id,
            )
            db.add(row)
        else:
            row.academic_level_department_id = link.id
            row.assigned_by_admin_id = admin_id
        await db.flush()
        if term.status == AcademicTermStatus.OPEN:
            db.add(
                AcademicLifecycleAudit(
                    tenant_id=tenant_id,
                    entity_type="specialization",
                    entity_id=row.id,
                    action="department_changed" if old_id else "department_assigned",
                    previous_status=None,
                    new_status=None,
                    acting_admin_id=admin_id,
                    reason="Open-term class specialization correction.",
                    metadata_json={
                        "class_id": str(class_id),
                        "academic_term_id": str(term.id),
                        "previous_academic_level_department_id": str(old_id) if old_id else None,
                        "new_academic_level_department_id": str(link.id),
                        "affected_curriculum_subject_ids": [
                            str(item) for item in sorted(affected, key=str)
                        ],
                    },
                )
            )
            await AcademicCurriculumService.reconcile_teacher_assignments_for_term(
                db,
                tenant_id=tenant_id,
                term=term,
                acting_admin_id=admin_id,
                class_ids={class_id},
                transition_boundary=date.today(),
            )
        await db.commit()
        await db.refresh(row)
        return await AcademicCurriculumService._class_department_response(db, row)

    @staticmethod
    async def clear_class_department(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
        admin_id: uuid.UUID | None = None,
    ) -> None:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        term = await AcademicCurriculumService._term(db, tenant_id, term_id, lock=True)
        if term.status in {AcademicTermStatus.CLOSING, AcademicTermStatus.CLOSED}:
            raise ConflictException(
                "Class specialization cannot be changed after term closing begins."
            )
        classroom = await ClassRoomRepository.get_by_id(db, tenant_id, class_id, lock=True)
        if classroom is None:
            raise NotFoundException("Class not found.")
        level = await AcademicCurriculumService._ensure_department_capability(
            db,
            tenant_id=tenant_id,
            academic_level_id=classroom.academic_level_id,
        )
        row = (
            await db.execute(
                select(ClassTermDepartmentAssignment)
                .where(
                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                    ClassTermDepartmentAssignment.class_id == class_id,
                    ClassTermDepartmentAssignment.academic_term_id == term_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return
        if CurriculumResolutionService.specialization_is_active(level, term):
            raise ConflictException(
                "This academic level requires specialization in the selected term, so the class department cannot be cleared."
            )
        await db.delete(row)
        await db.commit()

    @staticmethod
    async def copy_class_departments(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        admin_id: uuid.UUID,
        target_term_id: uuid.UUID,
        source_term_id: uuid.UUID,
    ) -> ClassTermDepartmentCopyResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        target = await AcademicCurriculumService._term(db, tenant_id, target_term_id, lock=True)
        source = await AcademicCurriculumService._term(db, tenant_id, source_term_id)
        if target.academic_session_id != source.academic_session_id:
            raise ConflictException(
                "Specializations can only be copied within one academic session."
            )
        if target.status != AcademicTermStatus.DRAFT:
            raise ConflictException(
                "Specializations can only be copied into a draft academic term."
            )
        source_rows = list(
            (
                await db.execute(
                    select(ClassTermDepartmentAssignment).where(
                        ClassTermDepartmentAssignment.tenant_id == tenant_id,
                        ClassTermDepartmentAssignment.academic_term_id == source.id,
                    )
                )
            ).scalars()
        )
        existing_class_ids = set(
            (
                await db.execute(
                    select(ClassTermDepartmentAssignment.class_id).where(
                        ClassTermDepartmentAssignment.tenant_id == tenant_id,
                        ClassTermDepartmentAssignment.academic_term_id == target.id,
                    )
                )
            ).scalars()
        )
        candidates = [row for row in source_rows if row.class_id not in existing_class_ids]
        candidate_class_ids = {row.class_id for row in candidates}
        candidate_link_ids = {row.academic_level_department_id for row in candidates}

        class_contexts: dict[uuid.UUID, tuple[ClassRoom, AcademicLevel]] = {}
        if candidate_class_ids:
            class_rows = (
                await db.execute(
                    select(ClassRoom, AcademicLevel)
                    .join(AcademicLevel, AcademicLevel.id == ClassRoom.academic_level_id)
                    .where(
                        ClassRoom.tenant_id == tenant_id,
                        ClassRoom.id.in_(candidate_class_ids),
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                        AcademicLevel.tenant_id == tenant_id,
                        AcademicLevel.status == AcademicLevelStatus.ACTIVE,
                    )
                )
            ).all()
            class_contexts = {classroom.id: (classroom, level) for classroom, level in class_rows}

        link_contexts: dict[uuid.UUID, tuple[AcademicLevelDepartment, Department]] = {}
        if candidate_link_ids:
            link_rows = (
                await db.execute(
                    select(AcademicLevelDepartment, Department)
                    .join(Department, Department.id == AcademicLevelDepartment.department_id)
                    .where(
                        AcademicLevelDepartment.tenant_id == tenant_id,
                        AcademicLevelDepartment.id.in_(candidate_link_ids),
                        AcademicLevelDepartment.is_active.is_(True),
                        AcademicLevelDepartment.archived_at.is_(None),
                        Department.tenant_id == tenant_id,
                        Department.is_active.is_(True),
                        Department.archived_at.is_(None),
                    )
                )
            ).all()
            link_contexts = {link.id: (link, department) for link, department in link_rows}

        copied_rows: list[ClassTermDepartmentAssignment] = []
        skipped = len(source_rows) - len(candidates)
        for source_row in candidates:
            class_context = class_contexts.get(source_row.class_id)
            link_context = link_contexts.get(source_row.academic_level_department_id)
            if class_context is None or link_context is None:
                skipped += 1
                continue
            classroom, level = class_context
            link, _department = link_context
            if link.academic_level_id != classroom.academic_level_id:
                skipped += 1
                continue
            if not CurriculumResolutionService.specialization_is_active(level, target):
                skipped += 1
                continue
            row = ClassTermDepartmentAssignment(
                tenant_id=tenant_id,
                class_id=source_row.class_id,
                academic_term_id=target.id,
                academic_level_department_id=source_row.academic_level_department_id,
                assigned_by_admin_id=admin_id,
            )
            db.add(row)
            copied_rows.append(row)
        await db.flush()
        responses = await AcademicCurriculumService._class_department_responses(db, copied_rows)
        await db.commit()
        return ClassTermDepartmentCopyResponse(
            copied=len(copied_rows), skipped=skipped, assignments=responses
        )

    @staticmethod
    async def specialization_readiness(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term: AcademicTerm,
    ) -> tuple[dict[str, int], list[str]]:
        """Validate minimum term structure and exact-term specialization in one contract."""

        levels = await AcademicLevelRepository.list_for_tenant(db, tenant_id, active_only=True)
        levels_by_id = {level.id: level for level in levels}
        classes = list(
            (
                await db.execute(
                    select(ClassRoom).where(
                        ClassRoom.tenant_id == tenant_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            ).scalars()
        )
        invalid_level_classes = [
            classroom for classroom in classes if classroom.academic_level_id not in levels_by_id
        ]
        counts = {
            "active_academic_levels": len(levels),
            "active_classes": len(classes),
            "classes_on_inactive_levels": len(invalid_level_classes),
            "classes_missing_department": 0,
        }
        blockers: list[str] = []
        if not levels:
            blockers.append("Activate at least one academic level before opening the term.")
        if not classes:
            blockers.append("Create at least one active class before opening the term.")
        if invalid_level_classes:
            blockers.append(
                f"{len(invalid_level_classes)} active classes belong to an inactive or missing academic level."
            )

        required = {
            level.id: level
            for level in levels
            if CurriculumResolutionService.specialization_is_active(level, term)
        }
        required_classes = [
            classroom for classroom in classes if classroom.academic_level_id in required
        ]
        class_ids = {row.id for row in required_classes}
        valid_assignments: set[uuid.UUID] = set()
        if class_ids:
            assignment_rows = (
                await db.execute(
                    select(
                        ClassTermDepartmentAssignment.class_id,
                        AcademicLevelDepartment.academic_level_id,
                    )
                    .join(
                        AcademicLevelDepartment,
                        AcademicLevelDepartment.id
                        == ClassTermDepartmentAssignment.academic_level_department_id,
                    )
                    .join(Department, Department.id == AcademicLevelDepartment.department_id)
                    .where(
                        ClassTermDepartmentAssignment.tenant_id == tenant_id,
                        ClassTermDepartmentAssignment.academic_term_id == term.id,
                        ClassTermDepartmentAssignment.class_id.in_(class_ids),
                        AcademicLevelDepartment.tenant_id == tenant_id,
                        AcademicLevelDepartment.is_active.is_(True),
                        AcademicLevelDepartment.archived_at.is_(None),
                        Department.tenant_id == tenant_id,
                        Department.is_active.is_(True),
                        Department.archived_at.is_(None),
                    )
                )
            ).all()
            level_by_class = {row.id: row.academic_level_id for row in required_classes}
            valid_assignments = {
                class_id
                for class_id, level_id in assignment_rows
                if level_by_class.get(class_id) == level_id
            }

        missing_by_level: dict[uuid.UUID, int] = {}
        for classroom in required_classes:
            if classroom.id not in valid_assignments:
                missing_by_level[classroom.academic_level_id] = (
                    missing_by_level.get(classroom.academic_level_id, 0) + 1
                )
        term_name = getattr(term.name, "value", str(term.name)).replace("_", " ").title()
        blockers.extend(
            f"{count} {required[level_id].name} classes need a valid active department specialization for {term_name}."
            for level_id, count in missing_by_level.items()
        )
        counts["classes_missing_department"] = sum(missing_by_level.values())
        return counts, blockers

    @staticmethod
    async def update_specialization_policy(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        admin_id: uuid.UUID,
        academic_level_id: uuid.UUID,
        payload: AcademicLevelSpecializationUpdate,
    ) -> AcademicLevelSpecializationResponse:
        await ensure_academic_write_window(db, tenant_id=tenant_id)
        level = await AcademicLevelRepository.get_by_id(db, tenant_id, academic_level_id, lock=True)
        if level is None:
            raise NotFoundException("Academic level not found.")
        await AcademicCurriculumService._ensure_department_capability(
            db,
            tenant_id=tenant_id,
            academic_level_id=academic_level_id,
        )
        requested = payload.specialization_required_from_term_position
        if level.category != AcademicCategory.SENIOR_SECONDARY:
            raise ConflictException(
                "Specialization timing is only configurable for senior-secondary levels."
            )
        configurable = level.position == 1
        if not configurable and requested != 1:
            raise ConflictException(
                "Senior-secondary levels after the first position must specialize from First Term."
            )
        old = level.specialization_required_from_term_position
        if old == requested:
            return AcademicLevelSpecializationResponse(
                academic_level_id=level.id,
                specialization_required_from_term_position=requested,
                is_configurable=configurable,
            )

        terms = list(
            (
                await db.execute(select(AcademicTerm).where(AcademicTerm.tenant_id == tenant_id))
            ).scalars()
        )
        affected_term_ids = {
            term.id
            for term in terms
            if (
                old is not None
                and CurriculumResolutionService.specialization_is_active(level, term)
            )
            != (AcademicCurriculumService._term_position(term) >= requested)
        }
        evidence = await AcademicEvidenceProtection.counts_for_level_terms(
            db,
            tenant_id=tenant_id,
            academic_level_id=level.id,
            academic_term_ids=affected_term_ids,
        )
        AcademicEvidenceProtection.ensure_none(
            evidence,
            operation="Specialization timing change",
        )

        current_term = (
            await db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.tenant_id == tenant_id,
                    AcademicTerm.is_current.is_(True),
                    AcademicTerm.status == AcademicTermStatus.OPEN,
                )
            )
        ).scalar_one_or_none()
        if current_term is not None:
            was_active = (
                old is not None and AcademicCurriculumService._term_position(current_term) >= old
            )
            will_be_active = AcademicCurriculumService._term_position(current_term) >= requested
            if not was_active and will_be_active:
                classes = set(
                    (
                        await db.execute(
                            select(ClassRoom.id).where(
                                ClassRoom.tenant_id == tenant_id,
                                ClassRoom.academic_level_id == level.id,
                                ClassRoom.is_active.is_(True),
                                ClassRoom.archived_at.is_(None),
                            )
                        )
                    ).scalars()
                )
                assigned = (
                    set(
                        (
                            await db.execute(
                                select(ClassTermDepartmentAssignment.class_id).where(
                                    ClassTermDepartmentAssignment.tenant_id == tenant_id,
                                    ClassTermDepartmentAssignment.academic_term_id
                                    == current_term.id,
                                    ClassTermDepartmentAssignment.class_id.in_(classes),
                                )
                            )
                        ).scalars()
                    )
                    if classes
                    else set()
                )
                if classes - assigned:
                    raise ConflictException(
                        "Configure every class specialization for the current term before moving specialization earlier.",
                        payload={
                            "dependency_counts": {
                                "classes_missing_department": len(classes - assigned)
                            }
                        },
                    )
        level.specialization_required_from_term_position = requested
        if current_term is not None and not was_active and will_be_active:
            await db.flush()
            await AcademicCurriculumService.reconcile_teacher_assignments_for_term(
                db,
                tenant_id=tenant_id,
                term=current_term,
                acting_admin_id=admin_id,
                transition_boundary=date.today(),
            )
        db.add(
            AcademicLifecycleAudit(
                tenant_id=tenant_id,
                entity_type="academic_level",
                entity_id=level.id,
                action="specialization_policy_changed",
                previous_status=str(old) if old is not None else None,
                new_status=str(requested),
                acting_admin_id=admin_id,
                reason="Academic specialization timing updated.",
                metadata_json={
                    "previous_term_position": old,
                    "new_term_position": requested,
                },
            )
        )
        db.add(level)
        await db.commit()
        return AcademicLevelSpecializationResponse(
            academic_level_id=level.id,
            specialization_required_from_term_position=requested,
            is_configurable=configurable,
        )

    @staticmethod
    def _term_position(term: AcademicTerm) -> int:
        return {
            "first_term": 1,
            "second_term": 2,
            "third_term": 3,
        }.get(getattr(term.name, "value", term.name), 0)

    @staticmethod
    async def eligible_classes_for_subject(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        curriculum_subject_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list[EligibleTeacherAssignmentClassResponse]:
        row, curriculum, _subject = await AcademicCurriculumService._curriculum_subject_context(
            db,
            tenant_id,
            curriculum_subject_id,
            require_active_level=True,
            require_active_subject=True,
        )
        if not row.is_active:
            raise ConflictException("Curriculum subject is inactive.")
        class_rows = (
            await db.execute(
                select(ClassRoom, AcademicLevel, ArmLabel)
                .join(AcademicLevel, AcademicLevel.id == ClassRoom.academic_level_id)
                .join(ArmLabel, ArmLabel.id == ClassRoom.arm_label_id)
                .where(
                    ClassRoom.tenant_id == tenant_id,
                    ClassRoom.academic_level_id == curriculum.academic_level_id,
                    ClassRoom.is_active.is_(True),
                    ClassRoom.archived_at.is_(None),
                    AcademicLevel.tenant_id == tenant_id,
                    AcademicLevel.status == AcademicLevelStatus.ACTIVE,
                    ArmLabel.tenant_id == tenant_id,
                )
            )
        ).all()
        class_ids = {classroom.id for classroom, _level, _arm in class_rows}
        resolved_by_class = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=tenant_id,
            class_ids=class_ids,
            academic_term_id=academic_term_id,
            skip_unresolvable=True,
        )
        protected_assignments = set(
            (
                await db.execute(
                    select(TeacherAssignment.class_id).where(
                        TeacherAssignment.tenant_id == tenant_id,
                        TeacherAssignment.curriculum_subject_id == row.id,
                        (TeacherAssignment.effective_to.is_(None))
                        | (TeacherAssignment.effective_to >= date.today()),
                    )
                )
            ).scalars()
        )
        department_names = await AcademicCurriculumService._class_department_name_map(
            db,
            tenant_id=tenant_id,
            term_id=academic_term_id,
            class_ids=class_ids,
        )
        result: list[EligibleTeacherAssignmentClassResponse] = []
        for classroom, level, arm in class_rows:
            subjects = resolved_by_class.get(classroom.id, [])
            if row.id not in {item.curriculum_subject_id for item in subjects}:
                continue
            result.append(
                EligibleTeacherAssignmentClassResponse(
                    class_id=classroom.id,
                    academic_level_id=classroom.academic_level_id,
                    academic_level_name=level.name,
                    arm_label=arm.label,
                    display_name=f"{level.name} {arm.label}".strip(),
                    department_name=department_names.get(classroom.id),
                    already_assigned=classroom.id in protected_assignments,
                )
            )
        return result

    @staticmethod
    async def teacher_assignment_subject_availability(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        academic_level_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list[TeacherAssignmentSubjectAvailabilityResponse]:
        curriculum = await AcademicCurriculumService._curriculum(
            db,
            tenant_id,
            academic_level_id,
            require_active_level=True,
        )
        curriculum_subject_ids = set(
            (
                await db.execute(
                    select(CurriculumSubject.id)
                    .join(Subject, Subject.id == CurriculumSubject.subject_id)
                    .where(
                        CurriculumSubject.tenant_id == tenant_id,
                        CurriculumSubject.curriculum_id == curriculum.id,
                        CurriculumSubject.is_active.is_(True),
                        Subject.tenant_id == tenant_id,
                        Subject.is_active.is_(True),
                        Subject.archived_at.is_(None),
                    )
                )
            ).scalars()
        )
        if not curriculum_subject_ids:
            return []

        classes = list(
            (
                await db.execute(
                    select(ClassRoom).where(
                        ClassRoom.tenant_id == tenant_id,
                        ClassRoom.academic_level_id == academic_level_id,
                        ClassRoom.is_active.is_(True),
                        ClassRoom.archived_at.is_(None),
                    )
                )
            ).scalars()
        )
        resolved_by_class = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=tenant_id,
            class_ids={classroom.id for classroom in classes},
            academic_term_id=academic_term_id,
            skip_unresolvable=True,
        )
        eligible_class_ids = {subject_id: set() for subject_id in curriculum_subject_ids}
        for classroom in classes:
            for resolved_subject in resolved_by_class.get(classroom.id, []):
                if resolved_subject.curriculum_subject_id in eligible_class_ids:
                    eligible_class_ids[resolved_subject.curriculum_subject_id].add(classroom.id)

        protected_rows = (
            await db.execute(
                select(
                    TeacherAssignment.curriculum_subject_id,
                    TeacherAssignment.class_id,
                ).where(
                    TeacherAssignment.tenant_id == tenant_id,
                    TeacherAssignment.curriculum_subject_id.in_(curriculum_subject_ids),
                    (TeacherAssignment.effective_to.is_(None))
                    | (TeacherAssignment.effective_to >= date.today()),
                )
            )
        ).all()
        protected_class_ids = {subject_id: set() for subject_id in curriculum_subject_ids}
        for subject_id, class_id in protected_rows:
            if subject_id in protected_class_ids:
                protected_class_ids[subject_id].add(class_id)

        result = []
        for subject_id in curriculum_subject_ids:
            eligible = eligible_class_ids[subject_id]
            assigned = eligible & protected_class_ids[subject_id]
            result.append(
                TeacherAssignmentSubjectAvailabilityResponse(
                    curriculum_subject_id=subject_id,
                    eligible_class_count=len(eligible),
                    assigned_class_count=len(assigned),
                    unassigned_class_count=len(eligible - assigned),
                )
            )
        return result

    @staticmethod
    async def resolved_class_subject_responses(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        class_id: uuid.UUID,
        academic_term_id: uuid.UUID,
    ) -> list[ResolvedClassSubjectResponse]:
        resolved = await CurriculumResolutionService.resolve_class_subjects(
            db,
            tenant_id=tenant_id,
            class_id=class_id,
            academic_term_id=academic_term_id,
        )
        subjects = (
            {
                row.id: row
                for row in (
                    await db.execute(
                        select(Subject).where(
                            Subject.tenant_id == tenant_id,
                            Subject.id.in_({item.subject_id for item in resolved}),
                        )
                    )
                ).scalars()
            }
            if resolved
            else {}
        )
        return [
            ResolvedClassSubjectResponse(
                curriculum_subject_id=item.curriculum_subject_id,
                subject_id=item.subject_id,
                subject_name=subjects[item.subject_id].name
                if item.subject_id in subjects
                else None,
                subject_code=subjects[item.subject_id].code
                if item.subject_id in subjects
                else None,
                is_elective=item.is_elective,
                is_general=item.is_general,
                matched_academic_level_department_id=item.academic_level_department_id,
            )
            for item in resolved
        ]

    @staticmethod
    async def reconcile_teacher_assignments_for_term(
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        term: AcademicTerm,
        acting_admin_id: uuid.UUID | None,
        class_ids: set[uuid.UUID] | None = None,
        transition_boundary: date | None = None,
    ) -> dict[str, int]:
        """End started assignments that lose eligibility without rewriting scheduled history."""

        query = select(TeacherAssignment).where(
            TeacherAssignment.tenant_id == tenant_id,
            TeacherAssignment.effective_to.is_(None),
        )
        if term.end_date is not None:
            query = query.where(TeacherAssignment.effective_from <= term.end_date)
        if class_ids:
            query = query.where(TeacherAssignment.class_id.in_(class_ids))
        assignments = list((await db.execute(query.with_for_update())).scalars())
        boundary = transition_boundary or term.start_date or date.today()
        if term.start_date is not None and boundary < term.start_date:
            boundary = term.start_date

        resolved_by_class = await CurriculumResolutionService.resolve_classes_subjects(
            db,
            tenant_id=tenant_id,
            class_ids={assignment.class_id for assignment in assignments},
            academic_term_id=term.id,
            skip_unresolvable=True,
        )
        eligible_by_class = {
            class_id: {item.curriculum_subject_id for item in subjects}
            for class_id, subjects in resolved_by_class.items()
        }
        ineligible = [
            assignment
            for assignment in assignments
            if assignment.curriculum_subject_id
            not in eligible_by_class.get(assignment.class_id, set())
        ]

        scheduled_conflicts = [
            assignment for assignment in ineligible if assignment.effective_from >= boundary
        ]
        if scheduled_conflicts:
            raise ConflictException(
                "A scheduled teacher assignment would become ineligible at this academic transition. "
                "Remove or reschedule it explicitly before changing the specialization context.",
                payload={
                    "code": "SCHEDULED_TEACHER_ASSIGNMENT_CONFLICT",
                    "transition_boundary": boundary.isoformat(),
                    "dependency_counts": {
                        "scheduled_teacher_assignments": len(scheduled_conflicts)
                    },
                    "teacher_assignment_ids": [
                        str(assignment.id) for assignment in scheduled_conflicts
                    ],
                },
            )

        ended = 0
        for assignment in ineligible:
            previous_state = assignment.state.value
            effective_to = boundary - timedelta(days=1)
            assignment.effective_to = effective_to
            db.add(assignment)
            db.add(
                TeacherAssignmentLifecycleAudit(
                    tenant_id=tenant_id,
                    assignment_id=assignment.id,
                    class_id=assignment.class_id,
                    curriculum_subject_id=assignment.curriculum_subject_id,
                    action="specialization_assignment_ended",
                    previous_teacher_membership_id=assignment.teacher_membership_id,
                    new_teacher_membership_id=assignment.teacher_membership_id,
                    previous_state=previous_state,
                    new_state="ended",
                    previous_effective_from=assignment.effective_from,
                    previous_effective_to=None,
                    new_effective_from=assignment.effective_from,
                    new_effective_to=effective_to,
                    acting_admin_id=acting_admin_id,
                    reason="Subject is no longer eligible for the class in the target specialization context.",
                )
            )
            ended += 1
        await db.flush()
        return {"ended": ended, "deleted_scheduled": 0}
