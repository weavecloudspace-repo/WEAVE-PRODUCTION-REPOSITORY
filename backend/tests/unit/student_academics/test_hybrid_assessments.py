"""Focused regression tests for WEAVE hybrid CBT/theory assessment contracts."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.student_academics.assessment_schemas import (
    AssessmentComponentCreate,
    AssessmentComponentUpdate,
)
from app.modules.student_academics.hybrid_scores import (
    component_is_complete,
    component_score_response,
)


def _component(hybrid=True, maximum="50"):
    return SimpleNamespace(
        id=uuid4(), name="Examination", code="EX",
        position=0, maximum_score=Decimal(maximum), is_hybrid=hybrid,
    )


def _score(cbt="16", cbt_max="20", theory=None):
    cbt_score = Decimal(cbt) if cbt is not None else None
    theory_score = Decimal(theory) if theory is not None else None
    return SimpleNamespace(
        score=cbt_score + (theory_score or Decimal("0")) if cbt_score is not None else Decimal("0"),
        cbt_score=cbt_score,
        cbt_maximum_score=Decimal(cbt_max) if cbt_max is not None else None,
        theory_score=theory_score,
        source_exam_id=uuid4(),
    )


def test_hybrid_configuration_is_opt_in_and_requires_examinable():
    base = dict(name="Examination", position=0, maximum_score=Decimal("50"))
    assert AssessmentComponentCreate(**base).is_hybrid is False
    assert AssessmentComponentCreate(**base, is_hybrid=True).is_hybrid is True
    with pytest.raises(ValidationError, match="must be examinable"):
        AssessmentComponentCreate(**base, is_examinable=False, is_hybrid=True)
    with pytest.raises(ValidationError, match="must be examinable"):
        AssessmentComponentUpdate(is_examinable=False, is_hybrid=True)


def test_hybrid_partial_cbt_requires_theory_and_zero_is_valid():
    component = _component()
    assert component_is_complete(component, None) is False
    assert component_is_complete(component, _score(cbt=None)) is False
    assert component_is_complete(component, _score()) is False
    assert component_is_complete(component, _score(cbt="0", theory="0")) is True

    record = _score(cbt="16", theory="25")
    response = component_score_response(component, record)
    assert response.cbt_score == Decimal("16")
    assert response.theory_score == Decimal("25")
    assert response.theory_maximum_score == Decimal("30")
    assert response.score == Decimal("41")
    assert response.is_complete is True


def test_full_hybrid_cbt_requires_no_theory():
    component = _component()
    record = _score(cbt="40", cbt_max="50")
    assert component_is_complete(component, record) is True
    response = component_score_response(component, record)
    assert response.theory_maximum_score == Decimal("0")
    assert response.is_complete is True


def test_legacy_nonhybrid_score_is_complete_without_new_fields():
    component = _component(hybrid=False)
    legacy = SimpleNamespace(score=Decimal("0"))
    assert component_is_complete(component, legacy)
    response = component_score_response(component, legacy)
    assert response.is_complete
    assert response.is_hybrid is False
    assert response.cbt_score is None
