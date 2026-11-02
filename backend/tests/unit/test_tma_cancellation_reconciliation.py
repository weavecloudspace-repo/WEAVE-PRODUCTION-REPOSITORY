"""Read-only TMA cancellation reconciliation must never mutate academic marks."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundException
from app.modules.student_academics.models import AcademicResultStatus
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma import cancellation_reconciliation_service as mod


def uid():
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_admin_receives_exact_conflict_reasons_without_score_mutation(monkeypatch):
    actor = TenantAdmin(id=uid(), tenant_id=uid())
    assignment = SimpleNamespace(
        id=uid(), tenant_id=actor.tenant_id, academic_term_id=uid(),
        academic_session_id=uid(), curriculum_subject_id=uid(),
        assessment_component_id=uid(), current_revision_number=1,
    )
    revision = SimpleNamespace(id=uid())
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        mod.TMARevisionRepository, "get_by_number",
        AsyncMock(return_value=revision),
    )
    guard = AsyncMock()
    monkeypatch.setattr(mod.TMAAuthorizationService, "require_assignment_access", guard)
    participant1 = SimpleNamespace(student_id=uid())
    attempt1 = SimpleNamespace(
        id=uid(), score_id=uid(), score_snapshot=Decimal("6.00")
    )
    score1 = SimpleNamespace(
        id=attempt1.score_id, assessment_component_id=assignment.assessment_component_id,
        score=Decimal("7.00"), cbt_score=None, theory_score=None, source_exam_id=None,
    )
    result1 = SimpleNamespace(
        student_id=participant1.student_id,
        academic_session_id=assignment.academic_session_id,
        academic_term_id=assignment.academic_term_id,
        curriculum_subject_id=assignment.curriculum_subject_id,
        status=AcademicResultStatus.DRAFT,
    )
    participant2 = SimpleNamespace(student_id=uid())
    attempt2 = SimpleNamespace(
        id=uid(), score_id=uid(), score_snapshot=Decimal("0")
    )
    score2 = SimpleNamespace(
        assessment_component_id=assignment.assessment_component_id,
        score=Decimal("0"), cbt_score=None, theory_score=None, source_exam_id=None,
    )
    result2 = SimpleNamespace(
        student_id=participant2.student_id,
        academic_session_id=assignment.academic_session_id,
        academic_term_id=assignment.academic_term_id,
        curriculum_subject_id=assignment.curriculum_subject_id,
        status=AcademicResultStatus.APPROVED,
    )
    participant3 = SimpleNamespace(student_id=uid())
    attempt3 = SimpleNamespace(id=uid(), score_id=None, score_snapshot=None)
    result = MagicMock()
    result.all.return_value = [
        (attempt1, participant1, score1, result1),
        (attempt2, participant2, score2, result2),
        (attempt3, participant3, None, None),
    ]
    db = AsyncMock()
    db.execute.return_value = result
    conflicts = await mod.TMACancellationReconciliationService.conflicts(
        db, actor=actor, assignment_id=assignment.id
    )
    assert len(conflicts) == 3
    assert conflicts[0]["student_id"] == participant1.student_id
    assert "edited" in conflicts[0]["reason"]
    assert "approved" in conflicts[1]["reason"]
    assert "linked TMA score" in conflicts[2]["reason"]
    db.commit.assert_not_awaited()
    db.delete.assert_not_awaited()
    guard.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_tenant_cannot_query_reconciliation(monkeypatch):
    actor = TenantAdmin(id=uid(), tenant_id=uid())
    monkeypatch.setattr(
        mod.TMAAssignmentRepository, "get_by_id", AsyncMock(return_value=None)
    )
    db = AsyncMock()
    with pytest.raises(NotFoundException):
        await mod.TMACancellationReconciliationService.conflicts(
            db, actor=actor, assignment_id=uid()
        )
    db.execute.assert_not_awaited()
