"""Stable CBT projections for the tenant's active assessment configuration."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.cbt.academics.schemas import (
    CBTAssessmentComponentSnapshot,
    CBTAssessmentSchemeSnapshot,
)
from app.modules.student_academics.assessment_examinability import (
    is_assessment_component_examinable,
)
from app.modules.student_academics.models import (
    AssessmentComponent,
    AssessmentScheme,
    AssessmentSchemeStatus,
)


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def project_assessment_scheme(
    session: Session, tenant_id: uuid.UUID, entity_id: uuid.UUID
) -> dict[str, Any] | None:
    row = session.execute(
        select(AssessmentScheme).where(
            AssessmentScheme.tenant_id == tenant_id,
            AssessmentScheme.id == entity_id,
        )
    ).scalar_one_or_none()
    if row is None or row.status != AssessmentSchemeStatus.ACTIVE:
        return None
    return CBTAssessmentSchemeSnapshot(
        id=row.id,
        name=row.name,
        status=_value(row.status),
    ).model_dump(mode="json")


def project_assessment_component(
    session: Session, tenant_id: uuid.UUID, entity_id: uuid.UUID
) -> dict[str, Any] | None:
    joined = session.execute(
        select(AssessmentComponent, AssessmentScheme)
        .join(
            AssessmentScheme,
            AssessmentScheme.id == AssessmentComponent.assessment_scheme_id,
        )
        .where(
            AssessmentComponent.tenant_id == tenant_id,
            AssessmentComponent.id == entity_id,
            AssessmentScheme.tenant_id == tenant_id,
        )
    ).first()
    if joined is None:
        return None
    row, scheme = joined
    if (
        not row.is_active
        or not is_assessment_component_examinable(row)
        or scheme.status != AssessmentSchemeStatus.ACTIVE
    ):
        return None
    return CBTAssessmentComponentSnapshot(
        id=row.id,
        assessment_scheme_id=row.assessment_scheme_id,
        name=row.name,
        code=row.code,
        maximum_score=row.maximum_score,
        position=row.position,
        is_active=row.is_active,
        is_hybrid=row.is_hybrid,
    ).model_dump(mode="json")
