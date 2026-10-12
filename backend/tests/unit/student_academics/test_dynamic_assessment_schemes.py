from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestException, ConflictException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.assessment_schemas import AssessmentSchemeCreate
from app.modules.student_academics.assessment_service import AssessmentService
from app.modules.student_academics.models import AssessmentSchemeStatus
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.service import StudentAcademicService


def component(name: str, maximum: str, position: int):
    return SimpleNamespace(
        id=uuid4(),
        assessment_scheme_id=uuid4(),
        name=name,
        code=None,
        maximum_score=Decimal(maximum),
        position=position,
        is_active=True,
    )


def scheme(status=AssessmentSchemeStatus.DRAFT):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Standard",
        status=status,
        activated_at=now if status == AssessmentSchemeStatus.ACTIVE else None,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )


def test_scheme_payload_rejects_duplicate_component_names_and_positions():
    with pytest.raises(ValidationError, match="unique"):
        AssessmentSchemeCreate(
            name="Duplicate",
            components=[
                {"name": "CA", "maximum_score": 50, "position": 0},
                {"name": "ca", "maximum_score": 50, "position": 0},
            ],
        )


@pytest.mark.asyncio
async def test_active_scheme_response_preserves_tenant_specific_order(monkeypatch):
    item = scheme(AssessmentSchemeStatus.ACTIVE)
    configured = [component("Assignment", "20", 0), component("Final", "80", 1)]
    for entry in configured:
        entry.assessment_scheme_id = item.id
    monkeypatch.setattr(AssessmentRepository, "list_components", AsyncMock(return_value=configured))

    response = await AssessmentService.response(SimpleNamespace(), item)

    assert [entry.name for entry in response.components] == ["Assignment", "Final"]
    assert response.total_maximum_score == Decimal("100")
    assert response.is_configured is True


@pytest.mark.asyncio
async def test_activation_rejects_component_total_below_100(monkeypatch):
    item = scheme()
    monkeypatch.setattr(AssessmentService, "_draft", AsyncMock(return_value=item))
    monkeypatch.setattr(
        AssessmentRepository,
        "list_components",
        AsyncMock(return_value=[component("Coursework", "40", 0), component("Final", "50", 1)]),
    )

    with pytest.raises(BadRequestException, match="totaling 100"):
        await AssessmentService.activate(SimpleNamespace(), item.tenant_id, item.id)


@pytest.mark.asyncio
async def test_activation_cannot_replace_scheme_used_in_current_open_term(monkeypatch):
    item = scheme()
    current = scheme(AssessmentSchemeStatus.ACTIVE)
    configured = [component("Coursework", "40", 0), component("Final", "60", 1)]
    monkeypatch.setattr(AssessmentService, "_draft", AsyncMock(return_value=item))
    monkeypatch.setattr(AssessmentRepository, "list_components", AsyncMock(return_value=configured))
    monkeypatch.setattr(AssessmentRepository, "get_active_scheme", AsyncMock(return_value=current))
    monkeypatch.setattr(
        AssessmentRepository, "current_open_term_result_count", AsyncMock(return_value=1)
    )

    with pytest.raises(ConflictException, match="current open term"):
        await AssessmentService.activate(SimpleNamespace(), item.tenant_id, item.id)


@pytest.mark.asyncio
async def test_zero_score_is_complete_but_missing_score_is_not(monkeypatch):
    result = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        total_score=Decimal("99"),
        grade=None,
        remark=None,
        grading_scale_id=None,
    )
    configured = component("CA 1", "10", 0)
    zero_score = SimpleNamespace(score=Decimal("0"))
    scale = SimpleNamespace(id=uuid4(), grade="A", remark="Excellent")
    monkeypatch.setattr(
        StudentAcademicRepository,
        "list_result_component_scores",
        AsyncMock(return_value=[(configured, zero_score)]),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "find_grade_for_score",
        AsyncMock(return_value=scale),
    )

    await StudentAcademicService._ensure_result_complete(SimpleNamespace(), result)

    assert result.total_score == Decimal("0")
    assert result.grade == "A"
    assert result.remark == "Excellent"
    assert result.grading_scale_id == scale.id

    monkeypatch.setattr(
        StudentAcademicRepository,
        "list_result_component_scores",
        AsyncMock(return_value=[(configured, None)]),
    )
    with pytest.raises(BadRequestException, match="Every configured"):
        await StudentAcademicService._ensure_result_complete(SimpleNamespace(), result)


@pytest.mark.asyncio
async def test_complete_result_requires_grading_scale(monkeypatch):
    result = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        total_score=Decimal("0"),
        grade=None,
        remark=None,
        grading_scale_id=None,
    )
    configured = component("Exam", "100", 0)
    score = SimpleNamespace(score=Decimal("66"))
    monkeypatch.setattr(
        StudentAcademicRepository,
        "list_result_component_scores",
        AsyncMock(return_value=[(configured, score)]),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "find_grade_for_score",
        AsyncMock(return_value=None),
    )

    with pytest.raises(ConflictException, match="grading scale"):
        await StudentAcademicService._ensure_result_complete(SimpleNamespace(), result)
