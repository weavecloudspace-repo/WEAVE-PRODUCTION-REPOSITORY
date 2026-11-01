"""Lead teacher assignment, delegation permissions, and tenant-safe persistence."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.core.exceptions import BadRequestException, ForbiddenException
from app.modules.teachers.models import TeacherMembership, TeacherMembershipStatus
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.authorization import TMAAuthorizationService
from app.modules.tma.models import TMAActorType, TMAAssignment, TMAAssignmentStatus
from app.modules.tma.schemas import TMAAssignmentCreate, TMAAssignmentUpdate


def uid() -> uuid.UUID:
    return uuid.uuid4()


def admin(tenant_id: uuid.UUID | None = None) -> TenantAdmin:
    return TenantAdmin(id=uid(), tenant_id=tenant_id or uid())


def teacher(tenant_id: uuid.UUID, teacher_id: uuid.UUID | None = None) -> TeacherMembership:
    return TeacherMembership(id=teacher_id or uid(), tenant_id=tenant_id)


def assignment(actor, *, lead=None, creator_type=TMAActorType.TENANT_ADMIN):
    return SimpleNamespace(
        id=uid(),
        tenant_id=actor.tenant_id,
        status=TMAAssignmentStatus.DRAFT,
        created_by_actor_type=creator_type,
        created_by_actor_id=actor.id,
        lead_teacher_membership_id=lead,
        academic_level_id=uid(),
        curriculum_subject_id=uid(),
        academic_session_id=uid(),
        academic_term_id=uid(),
        assessment_component_id=uid(),
    )


def scope_payload(*, lead=None) -> TMAAssignmentCreate:
    return TMAAssignmentCreate(
        academic_level_id=uid(),
        curriculum_subject_id=uid(),
        academic_session_id=uid(),
        academic_term_id=uid(),
        assessment_component_id=uid(),
        lead_teacher_membership_id=lead,
    )


def test_admin_remains_manager_and_only_selected_teacher_manages() -> None:
    owner = admin()
    lead = teacher(owner.tenant_id)
    collaborator = teacher(owner.tenant_id)
    row = assignment(owner, lead=lead.id)
    TMAAuthorizationService.require_assignment_management(owner, row)
    TMAAuthorizationService.require_assignment_management(lead, row)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_assignment_management(collaborator, row)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_assignment_management(teacher(uid(), lead.id), row)


def test_admin_created_without_lead_remains_under_admin_control() -> None:
    owner = admin()
    row = assignment(owner)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_assignment_management(teacher(owner.tenant_id), row)
    TMAAuthorizationService.require_assignment_management(owner, row)


def test_legacy_teacher_creator_remains_lead_until_admin_reassignment() -> None:
    creator = teacher(uid())
    row = assignment(creator, creator_type=TMAActorType.TEACHER)
    TMAAuthorizationService.require_assignment_management(creator, row)
    new_lead = teacher(creator.tenant_id)
    row.lead_teacher_membership_id = new_lead.id
    TMAAuthorizationService.require_assignment_management(new_lead, row)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_assignment_management(creator, row)


def test_lead_can_edit_admin_authored_question_and_collaborator_only_own() -> None:
    owner = admin()
    lead, collaborator = teacher(owner.tenant_id), teacher(owner.tenant_id)
    row = assignment(owner, lead=lead.id)
    question = SimpleNamespace(
        tenant_id=owner.tenant_id,
        assignment_id=row.id,
        author_actor_type=TMAActorType.TENANT_ADMIN,
        author_actor_id=owner.id,
    )
    TMAAuthorizationService.require_question_edit_access(lead, row, question)
    with pytest.raises(ForbiddenException):
        TMAAuthorizationService.require_question_edit_access(collaborator, row, question)
    question.author_actor_type = TMAActorType.TEACHER
    question.author_actor_id = collaborator.id
    TMAAuthorizationService.require_question_edit_access(collaborator, row, question)


@pytest.mark.asyncio
async def test_admin_can_create_assignment_and_delegate_to_eligible_lead(monkeypatch):
    from app.modules.tma import assignment_service as mod

    owner = admin()
    chosen = uid()
    payload = scope_payload(lead=chosen)
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    check = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_lead_teacher", check)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_component_scope", lookup)

    async def create(db, record):
        record.id = uid()
        return record

    monkeypatch.setattr(mod.TMAAssignmentRepository, "add", create)
    monkeypatch.setattr(mod.TMARevisionRepository, "add", AsyncMock())
    db = AsyncMock()
    record = await mod.TMAAssignmentService.create_assignment(db, actor=owner, payload=payload)
    assert record.lead_teacher_membership_id == chosen
    check.assert_awaited_once_with(
        db,
        tenant_id=owner.tenant_id,
        teacher_id=chosen,
        academic_level_id=payload.academic_level_id,
        curriculum_subject_id=payload.curriculum_subject_id,
        academic_term_id=payload.academic_term_id,
    )
    assert "lead_teacher_membership_id" not in lookup.await_args.kwargs
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_teacher_created_assignment_automatically_delegates_to_creator(monkeypatch):
    from app.modules.tma import assignment_service as mod

    creator = teacher(uid())
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    validate = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_lead_teacher", validate)
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_component_scope", AsyncMock(return_value=None)
    )

    async def create(db, record):
        record.id = uid()
        return record

    monkeypatch.setattr(mod.TMAAssignmentRepository, "add", create)
    monkeypatch.setattr(mod.TMARevisionRepository, "add", AsyncMock())
    record = await mod.TMAAssignmentService.create_assignment(
        AsyncMock(), actor=creator, payload=scope_payload()
    )
    assert record.lead_teacher_membership_id == creator.id
    validate.assert_not_awaited()


@pytest.mark.asyncio
async def test_teacher_cannot_choose_lead_during_creation(monkeypatch):
    from app.modules.tma import assignment_service as mod

    creator = teacher(uid())
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    added = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "add", added)
    with pytest.raises(ForbiddenException, match="administrator"):
        await mod.TMAAssignmentService.create_assignment(
            AsyncMock(), actor=creator, payload=scope_payload(lead=uid())
        )
    added.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_change_lead_after_questions_exist_and_when_active(monkeypatch):
    from app.modules.tma import assignment_service as mod

    owner = admin()
    row = assignment(owner, lead=uid())
    row.status = TMAAssignmentStatus.ACTIVE
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    check = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_lead_teacher", check)
    save = AsyncMock()
    questions = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "save", save)
    monkeypatch.setattr(mod.TMAQuestionRepository, "list_for_revision_with_options", questions)
    next_lead = uid()
    db = AsyncMock()
    updated = await mod.TMAAssignmentService.update_draft_assignment(
        db,
        actor=owner,
        assignment_id=row.id,
        payload=TMAAssignmentUpdate(lead_teacher_membership_id=next_lead),
    )
    assert updated.lead_teacher_membership_id == next_lead
    check.assert_awaited_once()
    questions.assert_not_awaited()
    save.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_collaborator_cannot_change_deadline_and_lead_cannot_delegate(monkeypatch):
    from app.modules.tma import assignment_service as mod

    owner = admin()
    lead = teacher(owner.tenant_id)
    collaborator = teacher(owner.tenant_id)
    row = assignment(owner, lead=lead.id)
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    save = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "save", save)
    with pytest.raises(ForbiddenException):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=collaborator,
            assignment_id=row.id,
            payload=TMAAssignmentUpdate(closes_at=None),
        )
    with pytest.raises(ForbiddenException, match="administrator"):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=lead,
            assignment_id=row.id,
            payload=TMAAssignmentUpdate(lead_teacher_membership_id=uid()),
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_lead_is_rejected_by_scope_validation(monkeypatch):
    from app.modules.tma import assignment_service as mod

    owner = admin()
    assigned = teacher(owner.tenant_id)
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = assigned
    access = AsyncMock(side_effect=ForbiddenException("not assigned to this subject"))
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", access)
    with pytest.raises(ForbiddenException):
        await mod.TMAAssignmentService._validate_lead_teacher(
            db,
            tenant_id=owner.tenant_id,
            teacher_id=assigned.id,
            academic_level_id=uid(),
            curriculum_subject_id=uid(),
            academic_term_id=uid(),
        )
    access.assert_awaited_once()
    db.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(BadRequestException, match="active teacher"):
        await mod.TMAAssignmentService._validate_lead_teacher(
            db,
            tenant_id=owner.tenant_id,
            teacher_id=uid(),
            academic_level_id=uid(),
            curriculum_subject_id=uid(),
            academic_term_id=uid(),
        )


def test_lead_teacher_uses_composite_tenant_foreign_key() -> None:
    table = TMAAssignment.__table__
    assert table.c.lead_teacher_membership_id.nullable
    foreign = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_tma_assignment_tenant_lead_teacher"
    )
    assert tuple(column.name for column in foreign.columns) == (
        "tenant_id",
        "lead_teacher_membership_id",
    )
    membership = TeacherMembership.__table__
    assert any(
        isinstance(c, UniqueConstraint) and c.name == "uq_teacher_memberships_tenant_id"
        for c in membership.constraints
    )
