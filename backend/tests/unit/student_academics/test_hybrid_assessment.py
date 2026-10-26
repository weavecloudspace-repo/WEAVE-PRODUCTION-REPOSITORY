from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.cbt.results.schemas import CBTResultBulkRequest, CBTResultBulkScoreItem
from app.modules.cbt.results.service import CBTResultIngestionService
from app.modules.student_academics.assessment_schemas import (
    AssessmentComponentCreate,
    AssessmentComponentUpdate,
)
from app.modules.student_academics.hybrid_scores import (
    component_is_complete,
    component_score_response,
    has_recorded_component_scores,
)


def _component(*, hybrid=True):
    return SimpleNamespace(
        id=uuid4(),
        name="Examination",
        code="EXAM",
        position=2,
        maximum_score=Decimal("50"),
        is_hybrid=hybrid,
    )


def _record(*, cbt="16", allocation="20", theory=None):
    return SimpleNamespace(
        score=Decimal(cbt) + (Decimal(theory) if theory is not None else Decimal("0")),
        cbt_score=Decimal(cbt),
        cbt_maximum_score=Decimal(allocation),
        theory_score=Decimal(theory) if theory is not None else None,
        source_exam_id=uuid4(),
    )


def test_hybrid_is_opt_in_and_requires_examinability():
    baseline = dict(name="Examination", maximum_score=Decimal("50"), position=2)
    assert AssessmentComponentCreate(**baseline).is_hybrid is False
    assert AssessmentComponentCreate(**baseline, is_hybrid=True).is_hybrid
    with pytest.raises(ValidationError, match="Hybrid components must be examinable"):
        AssessmentComponentCreate(**baseline, is_examinable=False, is_hybrid=True)
    with pytest.raises(ValidationError, match="Hybrid components must be examinable"):
        AssessmentComponentUpdate(is_examinable=False, is_hybrid=True)
    with pytest.raises(ValidationError, match="is_hybrid cannot be null"):
        AssessmentComponentUpdate(is_hybrid=None)


def test_hybrid_completion_requires_cbt_before_theory_and_recognizes_zero():
    component = _component()
    assert not component_is_complete(component, None)
    partial = _record(theory=None)
    assert not component_is_complete(component, partial)
    assert component_score_response(component, partial).theory_maximum_score == Decimal("30")
    partial.theory_score = Decimal("0")
    partial.score = Decimal("16")
    assert component_is_complete(component, partial)
    assert component_score_response(component, partial).is_complete
    full = _record(cbt="0", allocation="50", theory=None)
    assert component_is_complete(component, full)
    assert component_score_response(component, full).score == Decimal("0")


def test_legacy_components_remain_complete_with_existing_canonical_score():
    component = _component(hybrid=False)
    assert component_is_complete(component, SimpleNamespace(score=Decimal("0")))


def test_sync_hash_tracks_allocation_without_changing_legacy_payload_shape():
    ids = dict(
        batch_id=uuid4(),
        source_exam_id=uuid4(),
        academic_session_id=uuid4(),
        academic_term_id=uuid4(),
        academic_level_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_component_id=uuid4(),
        exam_date=date(2026, 10, 10),
        scores=[CBTResultBulkScoreItem(student_id=uuid4(), score=Decimal("16"))],
    )
    legacy = CBTResultBulkRequest(**ids)
    partial = CBTResultBulkRequest(**ids, cbt_maximum_score=Decimal("20"))
    full = CBTResultBulkRequest(**ids, cbt_maximum_score=Decimal("50"))
    assert legacy.cbt_maximum_score is None
    assert CBTResultIngestionService._request_hash(
        legacy
    ) != CBTResultIngestionService._request_hash(partial)
    assert CBTResultIngestionService._request_hash(
        partial
    ) != CBTResultIngestionService._request_hash(full)


def test_recorded_component_visibility_accepts_draft_zero_and_hybrid_partial():
    component = _component()
    assert not has_recorded_component_scores([(component, None)])
    assert not has_recorded_component_scores(
        [(component, SimpleNamespace(score=None, cbt_score=None, theory_score=None))]
    )
    assert has_recorded_component_scores(
        [(component, SimpleNamespace(score=Decimal("0"), cbt_score=None, theory_score=None))]
    )
    assert has_recorded_component_scores(
        [(component, SimpleNamespace(score=None, cbt_score=Decimal("0"), theory_score=None))]
    )
    assert has_recorded_component_scores([(component, _record(theory=None))])
