from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException
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
