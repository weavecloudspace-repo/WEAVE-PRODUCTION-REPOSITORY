"""Regression tests for enforced TMA deadlines and visible closed assignments."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException
from app.modules.student_academics.models import AcademicTermStatus
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.models import TMAAssignment, TMAAssignmentStatus, TMAAttemptStatus
from app.modules.tma.schemas import (
    TMAAssignmentCreate,
    TMAAssignmentUpdate,
    TMAStudentAssignmentResponse,
)


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _actor() -> TenantAdmin:
    return TenantAdmin(id=_id(), tenant_id=_id())


def _date(days: int = 3) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=days)


def _assignment(actor: TenantAdmin, status: TMAAssignmentStatus):
    return SimpleNamespace(
        id=_id(),
        tenant_id=actor.tenant_id,
        status=status,
        current_revision_number=1,
        academic_level_id=_id(),
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
        assessment_component_id=_id(),
        closes_at=None,
        closed_at=None,
    )


def _scope_payload(**extra) -> TMAAssignmentCreate:
    fields = dict(
        academic_level_id=_id(),
        curriculum_subject_id=_id(),
        academic_session_id=_id(),
        academic_term_id=_id(),
        assessment_component_id=_id(),
    )
    fields.update(closes_at=_date())
    fields.update(extra)
    return TMAAssignmentCreate(**fields)


def _setup(monkeypatch, assignment):
    from app.modules.tma import assignment_service as mod

    actor = TenantAdmin(id=_id(), tenant_id=assignment.tenant_id)
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "get_by_id",
        AsyncMock(return_value=assignment),
    )
    access = AsyncMock()
    management = lambda *args, **kwargs: None
    monkeypatch.setattr(
        mod.TMAAuthorizationService,
        "require_assignment_access",
        access,
    )
    monkeypatch.setattr(
        mod.TMAAuthorizationService,
        "require_assignment_management",
        management,
    )
    saved = AsyncMock()
    monkeypatch.setattr(mod.TMAAssignmentRepository, "save", saved)
    questions = AsyncMock()
    monkeypatch.setattr(
        mod.TMAQuestionRepository,
        "list_for_revision_with_options",
        questions,
    )
    return actor, saved, questions


def test_closes_at_is_nullable_and_timezone_aware_in_orm() -> None:
    col = TMAAssignment.__table__.c.closes_at
    assert col.nullable is True
    assert col.type.timezone is True
    assert TMAAssignment.__table__.c.closed_at is not col


def test_schemas_require_aware_deadline_and_reject_explicit_clear() -> None:
    when = _date()
    assert _scope_payload(closes_at=when).closes_at == when
    assert TMAAssignmentUpdate(closes_at=when).closes_at == when
    with pytest.raises(ValidationError):
        TMAAssignmentUpdate(closes_at=None)
    with pytest.raises(ValidationError):
        _scope_payload(closes_at=None)
    assert TMAAssignmentUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        TMAAssignmentCreate.model_validate(
            {
                field: getattr(_scope_payload(), field)
                for field in TMAAssignmentCreate.model_fields
                if field != "closes_at"
            }
        )


@pytest.mark.parametrize("klass", [TMAAssignmentCreate, TMAAssignmentUpdate])
def test_schema_rejects_naive_closing_date(klass) -> None:
    with pytest.raises(ValidationError):
        if klass is TMAAssignmentCreate:
            _scope_payload(closes_at=datetime(2026, 11, 15, 23, 0))
        else:
            klass(closes_at=datetime(2026, 11, 15, 23, 0))


@pytest.mark.asyncio
async def test_create_includes_closes_at_but_not_in_uniqueness_lookup(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    date = _date()
    payload = _scope_payload(closes_at=date)
    monkeypatch.setattr(mod.TMAAssignmentService, "_validate_scope", AsyncMock())
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", AsyncMock())
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(mod.TMAAssignmentRepository, "get_by_component_scope", lookup)

    async def add(db, assignment):
        assignment.id = _id()
        return assignment

    monkeypatch.setattr(mod.TMAAssignmentRepository, "add", add)
    monkeypatch.setattr(mod.TMARevisionRepository, "add", AsyncMock())
    db = AsyncMock()
    created = await mod.TMAAssignmentService.create_assignment(db, actor=actor, payload=payload)
    assert created.closes_at == date
    assert "closes_at" not in lookup.await_args.kwargs
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TMAAssignmentStatus.DRAFT, TMAAssignmentStatus.ACTIVE])
async def test_can_change_only_closing_estimate_without_touching_questions(
    monkeypatch,
    status,
) -> None:
    from app.modules.tma import assignment_service as mod

    author = _actor()
    assignment = _assignment(author, status)
    actor, save, questions = _setup(monkeypatch, assignment)
    db = AsyncMock()
    date = _date(5)
    updated = await mod.TMAAssignmentService.update_draft_assignment(
        db,
        actor=actor,
        assignment_id=assignment.id,
        payload=TMAAssignmentUpdate(closes_at=date),
    )
    assert updated.closes_at == date
    assert updated.status == status
    save.assert_awaited_once_with(db, assignment)
    questions.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_closing_estimate_cannot_be_cleared(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.ACTIVE)
    assignment.closes_at = _date()
    current, save, _ = _setup(monkeypatch, assignment)
    with pytest.raises(ValidationError):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(closes_at=None),
        )
    assert assignment.closes_at is not None
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_cannot_change_academic_scope_even_with_closes_at(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.ACTIVE)
    current, save, questions = _setup(monkeypatch, assignment)
    with pytest.raises(ConflictException):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(curriculum_subject_id=_id(), closes_at=_date()),
        )
    assert assignment.closes_at is None
    save.assert_not_awaited()
    questions.assert_not_awaited()


@pytest.mark.asyncio
async def test_closed_manager_can_extend_closing_deadline_before_reopen(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.CLOSED)
    current, save, _ = _setup(monkeypatch, assignment)
    deadline = _date()
    updated = await mod.TMAAssignmentService.update_draft_assignment(
        AsyncMock(),
        actor=current,
        assignment_id=assignment.id,
        payload=TMAAssignmentUpdate(closes_at=deadline),
    )
    assert updated.closes_at == deadline
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_scope_edit_still_requires_no_questions(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.DRAFT)
    current, save, questions = _setup(monkeypatch, assignment)
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_by_number",
        AsyncMock(return_value=SimpleNamespace(id=_id())),
    )
    questions.return_value = [(SimpleNamespace(), [])]
    with pytest.raises(ConflictException, match="after questions exist"):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(academic_level_id=_id(), closes_at=_date()),
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_null_academic_scope_remains_invalid(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.DRAFT)
    current, save, _ = _setup(monkeypatch, assignment)
    with pytest.raises(BadRequestException):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(academic_level_id=None, closes_at=_date()),
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_collaborator_cannot_change_closing_estimate(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    author = _actor()
    assignment = _assignment(author, TMAAssignmentStatus.ACTIVE)
    current, save, _ = _setup(monkeypatch, assignment)

    def deny_management(*args, **kwargs):
        raise ForbiddenException("Not lead")

    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_management", deny_management
    )
    date = _date()
    with pytest.raises(ForbiddenException, match="Not lead"):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(closes_at=date),
        )
    assert assignment.closes_at is None
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_academic_scope_edit_still_requires_lead_permission(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    author = _actor()
    assignment = _assignment(author, TMAAssignmentStatus.DRAFT)
    current, save, _ = _setup(monkeypatch, assignment)

    def deny_management(*args, **kwargs):
        raise ForbiddenException("Not lead")

    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_management", deny_management
    )
    with pytest.raises(ForbiddenException):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=current,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(academic_level_id=_id()),
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attempt_status", [None, TMAAttemptStatus.IN_PROGRESS, TMAAttemptStatus.SUBMITTED]
)
async def test_student_list_keeps_expired_tma_visible_but_disables_attempts(
    monkeypatch, attempt_status
) -> None:
    from app.modules.tma import attempt_service as mod

    student = SimpleNamespace(id=_id(), tenant_id=_id())
    term = SimpleNamespace(
        id=_id(),
        status=AcademicTermStatus.OPEN,
        is_current=True,
        academic_session_id=_id(),
    )
    enrollment = SimpleNamespace(academic_level_id=_id())
    assignment = SimpleNamespace(
        id=_id(),
        academic_term_id=term.id,
        curriculum_subject_id=_id(),
        assessment_component_id=_id(),
        current_revision_number=1,
        status=TMAAssignmentStatus.ACTIVE,
        closes_at=_date(-3),
    )
    revision = SimpleNamespace(id=_id(), published_at=_date(-10), invalidated_at=None)
    participant = SimpleNamespace(id=_id(), revision_id=revision.id)
    attempt = SimpleNamespace(id=_id(), status=attempt_status)
    scheme = SimpleNamespace(id=_id())
    component = SimpleNamespace(
        maximum_score=Decimal("20.00"),
        assessment_scheme_id=scheme.id,
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_current_term", AsyncMock(return_value=term)
    )
    monkeypatch.setattr(
        mod.StudentEnrollmentRepository,
        "get_authoritative_for_session",
        AsyncMock(return_value=enrollment),
    )
    monkeypatch.setattr(
        mod.CurriculumResolutionService,
        "resolve_student_subjects",
        AsyncMock(
            return_value=[SimpleNamespace(curriculum_subject_id=assignment.curriculum_subject_id)]
        ),
    )
    monkeypatch.setattr(
        mod.TMAAssignmentRepository,
        "list_for_scope",
        AsyncMock(return_value=([assignment], 1)),
    )
    monkeypatch.setattr(
        mod.TMAParticipantRepository,
        "list_for_student",
        AsyncMock(return_value=[participant] if attempt_status else []),
    )
    monkeypatch.setattr(
        mod.TMAAttemptRepository,
        "list_for_participants",
        AsyncMock(return_value={participant.id: attempt} if attempt_status else {}),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository,
        "get_many_by_number",
        AsyncMock(return_value={assignment.id: revision}),
    )
    monkeypatch.setattr(
        mod.AssessmentRepository,
        "get_active_scheme",
        AsyncMock(return_value=scheme),
    )
    monkeypatch.setattr(
        mod.AssessmentRepository,
        "get_components_by_ids",
        AsyncMock(return_value={assignment.assessment_component_id: component}),
    )
    items = await mod.TMAAttemptService.list_available_assignments(
        AsyncMock(),
        student=student,
    )
    assert len(items) == 1
    assert items[0].closes_at == assignment.closes_at
    assert items[0].can_start_or_resume is False
    assert items[0].status == TMAAssignmentStatus.CLOSED
    assert items[0].attempt_status == attempt_status
    assert items[0].attempt_id == (attempt.id if attempt_status else None)


def test_student_schema_exposes_optional_closes_at() -> None:
    item = TMAStudentAssignmentResponse(
        assignment_id=_id(),
        academic_term_id=_id(),
        curriculum_subject_id=_id(),
        assessment_component_id=_id(),
        status=TMAAssignmentStatus.ACTIVE,
        attempt_status=None,
        closes_at=None,
        can_start_or_resume=True,
        component_maximum_score=Decimal("20"),
    )
    assert item.model_dump()["closes_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("old_deadline,new_deadline", [(-1, 5), (5, -1)])
async def test_active_deadline_cannot_rewrite_historical_eligibility(
    monkeypatch, old_deadline, new_deadline
):
    from app.modules.tma import assignment_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.ACTIVE)
    assignment.closes_at = _date(old_deadline)
    actor, save, _ = _setup(monkeypatch, assignment)
    with pytest.raises(ConflictException):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=actor,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(closes_at=_date(new_deadline)),
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_rejects_legacy_draft_without_deadline(monkeypatch) -> None:
    from app.modules.tma import lifecycle_service as mod

    actor = _actor()
    assignment = _assignment(actor, TMAAssignmentStatus.DRAFT)
    assignment.closes_at = None
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", AsyncMock())
    monkeypatch.setattr(
        mod.TMAAuthorizationService, "require_assignment_management", lambda *_: None
    )
    readiness = AsyncMock(return_value=[])
    monkeypatch.setattr(mod.TMALifecycleService, "_readiness_errors", readiness)
    db = AsyncMock()
    with pytest.raises(ConflictException, match="future submission deadline"):
        await mod.TMALifecycleService.activate_assignment(
            db, actor=actor, assignment_id=assignment.id
        )
    readiness.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_deadline_that_already_passed(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    db = AsyncMock()
    with pytest.raises(BadRequestException, match="future"):
        await mod.TMAAssignmentService.create_assignment(
            db, actor=_actor(), payload=_scope_payload(closes_at=_date(-1))
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_update_rejects_past_deadline(monkeypatch) -> None:
    from app.modules.tma import assignment_service as mod

    author = _actor()
    assignment = _assignment(author, TMAAssignmentStatus.DRAFT)
    actor, save, _ = _setup(monkeypatch, assignment)
    with pytest.raises(ConflictException, match="future"):
        await mod.TMAAssignmentService.update_draft_assignment(
            AsyncMock(),
            actor=actor,
            assignment_id=assignment.id,
            payload=TMAAssignmentUpdate(closes_at=_date(-1)),
        )
    save.assert_not_awaited()
