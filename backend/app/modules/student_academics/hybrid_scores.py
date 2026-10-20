"""Canonical CBT/theory score rules shared by academic results and ingestion."""

from __future__ import annotations

from decimal import Decimal

from app.modules.student_academics.models import AssessmentComponent, StudentAssessmentScore
from app.modules.student_academics.schemas import AssessmentComponentScoreResponse


def component_is_complete(
    component: AssessmentComponent, record: StudentAssessmentScore | None
) -> bool:
    if record is None:
        return False
    if not component.is_hybrid:
        return True
    if record.cbt_score is None or record.cbt_maximum_score is None:
        return False
    return (
        record.cbt_maximum_score == component.maximum_score
        or record.theory_score is not None
    )


def component_theory_maximum(
    component: AssessmentComponent, record: StudentAssessmentScore | None
) -> Decimal | None:
    if not component.is_hybrid or record is None or record.cbt_maximum_score is None:
        return None
    return component.maximum_score - record.cbt_maximum_score


def component_score_response(
    component: AssessmentComponent, record: StudentAssessmentScore | None
) -> AssessmentComponentScoreResponse:
    return AssessmentComponentScoreResponse(
        assessment_component_id=component.id,
        name=component.name,
        code=component.code,
        position=component.position,
        maximum_score=component.maximum_score,
        score=record.score if record is not None else None,
        is_hybrid=component.is_hybrid,
        cbt_score=record.cbt_score if record is not None and component.is_hybrid else None,
        cbt_maximum_score=record.cbt_maximum_score if record is not None and component.is_hybrid else None,
        theory_score=record.theory_score if record is not None and component.is_hybrid else None,
        theory_maximum_score=component_theory_maximum(component, record),
        source_exam_id=record.source_exam_id if record is not None and component.is_hybrid else None,
        is_complete=component_is_complete(component, record),
    )
