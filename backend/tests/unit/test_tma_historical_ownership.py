"""Historic TMA closure grading cannot cross tenant, level or session ownership."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AssessmentSchemeStatus,
)
from app.modules.tma.grading_service import TMAGradingService


def _fixtures():
    tenant, student, session, component_id = (uuid4() for _ in range(4))
    scheme = SimpleNamespace(id=uuid4(), status=AssessmentSchemeStatus.ACTIVE)
    component = SimpleNamespace(
        id=component_id,
        assessment_scheme_id=scheme.id,
        is_active=True,
        is_hybrid=False,
        is_examinable=False,
        maximum_score=Decimal("20"),
    )
    cutoff = date.today() - timedelta(days=3)
    prior = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        student_id=student,
        academic_session_id=session,
        academic_level_id=uuid4(),
        class_id=uuid4(),
        started_on=cutoff - timedelta(days=20),
        ended_on=cutoff + timedelta(days=1),
    )
    destination = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        student_id=student,
        academic_session_id=session,
        academic_level_id=prior.academic_level_id,
        class_id=uuid4(),
        started_on=cutoff + timedelta(days=2),
    )
    result = SimpleNamespace(
        id=uuid4(),
        student_enrollment_id=destination.id,
        class_id=destination.class_id,
        status=AcademicResultStatus.DRAFT,
        assessment_scheme_id=scheme.id,
        total_score=Decimal("0"),
        grade=None,
        remark=None,
        grading_scale_id=None,
    )
    assignment = SimpleNamespace(
        assessment_component_id=component.id,
        curriculum_subject_id=uuid4(),
        academic_session_id=session,
        academic_term_id=uuid4(),
    )
    return SimpleNamespace(
        tenant=tenant,
        student=student,
        cutoff=cutoff,
        prior=prior,
        destination=destination,
        result=result,
        assignment=assignment,
        scheme=scheme,
        component=component,
    )


def _mocks(monkeypatch, ctx):
    from app.modules.tma import grading_service as mod

    monkeypatch.setattr(mod, "ensure_academic_write_window", AsyncMock())
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_active_scheme",
        AsyncMock(return_value=ctx.scheme),
    )
    monkeypatch.setattr(
        mod.AssessmentRepository, "get_component",
        AsyncMock(return_value=ctx.component),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_results_by_scope_batch",
        AsyncMock(return_value={ctx.student: ctx.result}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "get_component_scores_batch",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "add_component_scores_batch", AsyncMock()
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "list_result_component_scores",
        AsyncMock(return_value=[(ctx.component, SimpleNamespace(score=Decimal("0")))]),
    )
    monkeypatch.setattr(
        mod.StudentAcademicRepository, "find_grade_for_score",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(mod.StudentAcademicRepository, "upsert_result", AsyncMock())
    lookup = AsyncMock(return_value=ctx.destination)
    monkeypatch.setattr(mod.StudentEnrollmentRepository, "get_by_id", lookup)
    return lookup


@pytest.mark.asyncio
async def test_immutable_closure_zero_can_follow_valid_same_level_transfer(monkeypatch):
    ctx = _fixtures()
    lookup = _mocks(monkeypatch, ctx)
    db = AsyncMock()
    score = await TMAGradingService.persist_component_score(
        db,
        tenant_id=ctx.tenant,
        student_id=ctx.student,
        enrollment=ctx.prior,
        assignment=ctx.assignment,
        correct=0,
        total=10,
        scoring_date=ctx.cutoff,
        deadline_subject_id=uuid4(),
    )
    assert score == Decimal("0.00")
    lookup.assert_awaited_once_with(
        db, ctx.tenant, ctx.destination.id
    )


@pytest.mark.asyncio
async def test_ordinary_tma_submission_cannot_grade_different_class(monkeypatch):
    ctx = _fixtures()
    lookup = _mocks(monkeypatch, ctx)
    with pytest.raises(ConflictException, match="enrollment/class"):
        await TMAGradingService.persist_component_score(
            AsyncMock(),
            tenant_id=ctx.tenant,
            student_id=ctx.student,
            enrollment=ctx.prior,
            assignment=ctx.assignment,
            correct=0,
            total=10,
        )
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_deadline_cannot_cross_academic_levels(monkeypatch):
    ctx = _fixtures()
    ctx.destination.academic_level_id = uuid4()
    _mocks(monkeypatch, ctx)
    with pytest.raises(ConflictException, match="enrollment/class"):
        await TMAGradingService.persist_component_score(
            AsyncMock(),
            tenant_id=ctx.tenant,
            student_id=ctx.student,
            enrollment=ctx.prior,
            assignment=ctx.assignment,
            correct=0,
            total=10,
            scoring_date=ctx.cutoff,
            deadline_subject_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_historical_deadline_cannot_cross_tenants(monkeypatch):
    ctx = _fixtures()
    ctx.destination.tenant_id = uuid4()
    _mocks(monkeypatch, ctx)
    with pytest.raises(ConflictException, match="enrollment/class"):
        await TMAGradingService.persist_component_score(
            AsyncMock(),
            tenant_id=ctx.tenant,
            student_id=ctx.student,
            enrollment=ctx.prior,
            assignment=ctx.assignment,
            correct=0,
            total=10,
            scoring_date=ctx.cutoff,
            deadline_subject_id=uuid4(),
        )
