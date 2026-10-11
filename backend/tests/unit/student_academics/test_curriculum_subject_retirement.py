from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictException
from app.modules.student_academics.curriculum_models import (
    CurriculumSubject,
    CurriculumSubjectDepartment,
)
from app.modules.student_academics.curriculum_v2_repository import CurriculumSubjectRepository
from app.modules.student_academics.curriculum_v2_schemas import (
    CurriculumSubjectResponse,
    CurriculumSubjectUpdate,
)
from app.modules.student_academics.curriculum_v2_service import AcademicCurriculumService
from app.modules.student_academics.models import (
    StudentSubjectResult,
    TeacherAssignment,
    TeacherAssignmentLifecycleAudit,
)


def _row(*, active: bool = True, elective: bool = False):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        curriculum_id=uuid4(),
        subject_id=uuid4(),
        is_elective=elective,
        is_active=active,
        created_at=now,
        updated_at=now,
    )


def _context(row):
    curriculum = SimpleNamespace(id=row.curriculum_id, academic_level_id=uuid4())
    subject = SimpleNamespace(
        id=row.subject_id,
        name="Physics",
        code="PHY",
        is_active=True,
        archived_at=None,
    )
    return row, curriculum, subject


def _response(row):
    return CurriculumSubjectResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        curriculum_id=row.curriculum_id,
        subject_id=row.subject_id,
        subject_name="Physics",
        subject_code="PHY",
        is_elective=row.is_elective,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _dependencies(**overrides):
    values = {
        "department_links_total": 0,
        "teacher_assignments_total": 0,
        "teacher_assignments_active": 0,
        "teacher_assignment_audits_total": 0,
        "results_total": 0,
        "results_live": 0,
    }
    values.update(overrides)
    return values


def test_curriculum_subject_patch_rejects_direct_lifecycle_changes() -> None:
    with pytest.raises(ValidationError):
        CurriculumSubjectUpdate(is_active=False)


def test_curriculum_subject_history_fks_are_restrict() -> None:
    assert (
        next(iter(CurriculumSubject.__table__.columns.curriculum_id.foreign_keys)).ondelete
        == "RESTRICT"
    )
    assert (
        next(
            iter(CurriculumSubjectDepartment.__table__.columns.curriculum_subject_id.foreign_keys)
        ).ondelete
        == "CASCADE"
    )
    assert (
        next(iter(TeacherAssignment.__table__.columns.curriculum_subject_id.foreign_keys)).ondelete
        == "RESTRICT"
    )
    assert (
        next(
            iter(
                TeacherAssignmentLifecycleAudit.__table__.columns.curriculum_subject_id.foreign_keys
            )
        ).ondelete
        == "RESTRICT"
    )
    assert (
        next(
            iter(StudentSubjectResult.__table__.columns.curriculum_subject_id.foreign_keys)
        ).ondelete
        == "RESTRICT"
    )


@pytest.mark.asyncio
async def test_live_dependencies_block_curriculum_subject_deactivation() -> None:
    row = _row()
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(
                return_value=_dependencies(
                    teacher_assignments_active=2,
                    results_live=3,
                )
            ),
        ),
        patch.object(CurriculumSubjectRepository, "save", new=AsyncMock()) as save,
    ):
        with pytest.raises(ConflictException) as exc_info:
            await AcademicCurriculumService.deactivate_subject(db, row.tenant_id, row.id)

    assert exc_info.value.payload == {
        "dependency_counts": {
            "teacher_assignments_active": 2,
            "results_live": 3,
        }
    }
    assert row.is_active is True
    save.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_only_dependencies_allow_curriculum_subject_deactivation() -> None:
    row = _row()
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ) as write_guard,
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(
                return_value=_dependencies(
                    teacher_assignments_total=1,
                    teacher_assignment_audits_total=3,
                    results_total=5,
                )
            ),
        ),
        patch.object(CurriculumSubjectRepository, "save", new=AsyncMock()) as save,
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_response",
            new=AsyncMock(side_effect=lambda _db, value, _subject=None: _response(value)),
        ),
    ):
        response = await AcademicCurriculumService.deactivate_subject(db, row.tenant_id, row.id)

    assert response.is_active is False
    assert row.is_active is False
    write_guard.assert_awaited_once_with(db, tenant_id=row.tenant_id)
    save.assert_awaited_once_with(db, row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_curriculum_subject_revalidates_parent_and_subject() -> None:
    row = _row(active=False)
    db = AsyncMock()
    context = AsyncMock(return_value=_context(row))
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=context,
        ),
        patch.object(CurriculumSubjectRepository, "save", new=AsyncMock()),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_response",
            new=AsyncMock(side_effect=lambda _db, value, _subject=None: _response(value)),
        ),
    ):
        response = await AcademicCurriculumService.activate_subject(db, row.tenant_id, row.id)

    assert response.is_active is True
    assert context.await_args.kwargs["lock"] is True
    assert context.await_args.kwargs["require_active_level"] is True
    assert context.await_args.kwargs["require_active_subject"] is True


@pytest.mark.asyncio
async def test_elective_setting_is_locked_after_results_exist() -> None:
    row = _row(elective=False)
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(return_value=_dependencies(results_total=1)),
        ),
    ):
        with pytest.raises(ConflictException, match="elective meaning is locked"):
            await AcademicCurriculumService.update_subject(
                db,
                row.tenant_id,
                row.id,
                CurriculumSubjectUpdate(is_elective=True),
            )

    assert row.is_elective is False
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_elective_setting_can_change_while_usage_is_draft_only() -> None:
    row = _row(elective=False)
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(return_value=_dependencies()),
        ),
        patch.object(CurriculumSubjectRepository, "save", new=AsyncMock()),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_response",
            new=AsyncMock(side_effect=lambda _db, value, _subject=None: _response(value)),
        ),
    ):
        response = await AcademicCurriculumService.update_subject(
            db,
            row.tenant_id,
            row.id,
            CurriculumSubjectUpdate(is_elective=True),
        )

    assert response.is_elective is True
    assert row.is_elective is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unused_curriculum_subject_can_be_hard_deleted() -> None:
    row = _row()
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(return_value=_dependencies()),
        ),
        patch.object(CurriculumSubjectRepository, "delete", new=AsyncMock()) as delete,
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_response",
            new=AsyncMock(side_effect=lambda _db, value, _subject=None: _response(value)),
        ),
    ):
        response = await AcademicCurriculumService.hard_delete_subject(db, row.tenant_id, row.id)

    assert response.id == row.id
    delete.assert_awaited_once_with(db, row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_department_scopes_do_not_block_unused_curriculum_subject_hard_delete() -> None:
    row = _row()
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(return_value=_dependencies(department_links_total=2)),
        ),
        patch.object(CurriculumSubjectRepository, "delete", new=AsyncMock()) as delete,
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_response",
            new=AsyncMock(side_effect=lambda _db, value, _subject=None: _response(value)),
        ),
    ):
        response = await AcademicCurriculumService.hard_delete_subject(db, row.tenant_id, row.id)

    assert response.id == row.id
    delete.assert_awaited_once_with(db, row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_used_curriculum_subject_can_never_be_hard_deleted() -> None:
    row = _row(active=False)
    db = AsyncMock()
    with (
        patch(
            "app.modules.student_academics.curriculum_v2_service.ensure_academic_write_window",
            new=AsyncMock(),
        ),
        patch.object(
            AcademicCurriculumService,
            "_curriculum_subject_context",
            new=AsyncMock(return_value=_context(row)),
        ),
        patch.object(
            CurriculumSubjectRepository,
            "count_dependencies",
            new=AsyncMock(
                return_value=_dependencies(
                    teacher_assignment_audits_total=1,
                )
            ),
        ),
        patch.object(CurriculumSubjectRepository, "delete", new=AsyncMock()) as delete,
    ):
        with pytest.raises(ConflictException) as exc_info:
            await AcademicCurriculumService.hard_delete_subject(db, row.tenant_id, row.id)

    assert exc_info.value.payload == {"dependency_counts": {"teacher_assignment_audits_total": 1}}
    delete.assert_not_awaited()
    db.commit.assert_not_awaited()
