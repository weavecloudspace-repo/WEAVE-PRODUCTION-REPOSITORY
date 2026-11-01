from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException, ConflictException
from app.modules.tma import configuration_service as mod


@pytest.mark.asyncio
async def test_configuration_excludes_scopes_denied_by_existing_authorization(monkeypatch):
    tenant_id, term_id, session_id = uuid4(), uuid4(), uuid4()
    term = SimpleNamespace(
        id=term_id,
        academic_session_id=session_id,
        name=SimpleNamespace(value="first_term"),
        status=SimpleNamespace(value="open"),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_current_term", AsyncMock(return_value=term)
    )
    monkeypatch.setattr(mod.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=None))
    allowed = (
        SimpleNamespace(id=uuid4(), name="SS1"),
        SimpleNamespace(id=uuid4()),
        SimpleNamespace(name="Maths"),
    )
    denied = (
        SimpleNamespace(id=uuid4(), name="SS2"),
        SimpleNamespace(id=uuid4()),
        SimpleNamespace(name="Physics"),
    )
    result = MagicMock()
    result.all.return_value = [allowed, denied]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    guard = AsyncMock(side_effect=[None, ForbiddenException("Not assigned")])
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_authoring_access", guard)
    config = await mod.get_authoring_configuration(db, SimpleNamespace(tenant_id=tenant_id))
    assert len(config["scopes"]) == 1
    assert config["scopes"][0]["curriculum_subject_id"] == allowed[1].id
    assert config["academic_term_id"] == term_id
    assert config["term_open"] is True
    assert guard.call_args_list[0].kwargs["academic_term_id"] == term_id
    statement = db.execute.call_args_list[0].args[0].compile()
    assert set(statement.params.values()) == {tenant_id}


@pytest.mark.asyncio
async def test_configuration_without_term_or_scheme_does_not_offer_creation(monkeypatch):
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_current_term", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(mod.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=None))
    config = await mod.get_authoring_configuration(
        SimpleNamespace(), SimpleNamespace(tenant_id=uuid4())
    )
    assert config["term_open"] is False
    assert config["scopes"] == []
    assert config["components"] == []


@pytest.mark.asyncio
async def test_component_choices_require_non_examinable_and_non_hybrid(monkeypatch):
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_current_term", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        mod.AssessmentRepository,
        "get_active_scheme",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    await mod.get_authoring_configuration(db, SimpleNamespace(tenant_id=uuid4()))
    query = str(db.execute.call_args.args[0])
    assert "is_examinable IS false" in query
    assert "is_hybrid IS false" in query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "examinable,hybrid,valid",
    [(False, False, True), (True, False, False), (True, True, False), (False, True, False)],
)
async def test_assignment_scope_enforces_component_eligibility(
    monkeypatch, examinable, hybrid, valid
):
    from app.modules.tma import assignment_service as service
    from app.modules.tma.schemas import TMAAssignmentCreate
    from app.modules.student_academics.models import AcademicSessionStatus, AssessmentSchemeStatus

    payload = TMAAssignmentCreate(
        academic_level_id=uuid4(),
        curriculum_subject_id=uuid4(),
        academic_session_id=uuid4(),
        academic_term_id=uuid4(),
        assessment_component_id=uuid4(),
    )
    scheme = SimpleNamespace(id=uuid4(), status=AssessmentSchemeStatus.ACTIVE)
    monkeypatch.setattr(
        service.StudentAcademicRepository,
        "get_academic_session_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=payload.academic_session_id, status=AcademicSessionStatus.OPEN, is_current=True
            )
        ),
    )
    monkeypatch.setattr(
        service.StudentAcademicRepository,
        "get_term_by_id",
        AsyncMock(return_value=SimpleNamespace(academic_session_id=payload.academic_session_id)),
    )
    monkeypatch.setattr(
        service.AssessmentRepository, "get_active_scheme", AsyncMock(return_value=scheme)
    )
    monkeypatch.setattr(
        service.AssessmentRepository,
        "get_component",
        AsyncMock(
            return_value=SimpleNamespace(
                is_active=True,
                assessment_scheme_id=scheme.id,
                is_hybrid=hybrid,
                is_examinable=examinable,
            )
        ),
    )
    if valid:
        await service.TMAAssignmentService._validate_scope(None, tenant_id=uuid4(), payload=payload)
    else:
        with pytest.raises(ConflictException, match="non-examinable"):
            await service.TMAAssignmentService._validate_scope(
                None, tenant_id=uuid4(), payload=payload
            )
