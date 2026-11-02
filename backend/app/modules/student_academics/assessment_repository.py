import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.student_academics.models import (
    AcademicTerm,
    AcademicTermStatus,
    AssessmentComponent,
    AssessmentScheme,
    AssessmentSchemeStatus,
    StudentSubjectResult,
)


class AssessmentRepository:
    @staticmethod
    async def get_scheme(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID, *, lock: bool = False
    ) -> AssessmentScheme | None:
        query = select(AssessmentScheme).where(
            AssessmentScheme.tenant_id == tenant_id, AssessmentScheme.id == scheme_id
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_active_scheme(
        db: AsyncSession, tenant_id: uuid.UUID, *, lock: bool = False
    ) -> AssessmentScheme | None:
        query = select(AssessmentScheme).where(
            AssessmentScheme.tenant_id == tenant_id,
            AssessmentScheme.status == AssessmentSchemeStatus.ACTIVE,
        )
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_schemes(db: AsyncSession, tenant_id: uuid.UUID) -> list[AssessmentScheme]:
        return list(
            (
                await db.execute(
                    select(AssessmentScheme)
                    .where(AssessmentScheme.tenant_id == tenant_id)
                    .order_by(AssessmentScheme.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def get_schemes_by_id(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, AssessmentScheme]:
        if not scheme_ids:
            return {}
        rows = list(
            (
                await db.execute(
                    select(AssessmentScheme).where(
                        AssessmentScheme.tenant_id == tenant_id,
                        AssessmentScheme.id.in_(scheme_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    @staticmethod
    async def list_components(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID
    ) -> list[AssessmentComponent]:
        return list(
            (
                await db.execute(
                    select(AssessmentComponent)
                    .where(
                        AssessmentComponent.tenant_id == tenant_id,
                        AssessmentComponent.assessment_scheme_id == scheme_id,
                        AssessmentComponent.is_active.is_(True),
                    )
                    .order_by(AssessmentComponent.position.asc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def list_components_for_schemes(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scheme_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, list[AssessmentComponent]]:
        """Load active components for many schemes in one tenant-scoped query."""
        if not scheme_ids:
            return {}

        rows = list(
            (
                await db.execute(
                    select(AssessmentComponent)
                    .where(
                        AssessmentComponent.tenant_id == tenant_id,
                        AssessmentComponent.assessment_scheme_id.in_(scheme_ids),
                        AssessmentComponent.is_active.is_(True),
                    )
                    .order_by(
                        AssessmentComponent.assessment_scheme_id,
                        AssessmentComponent.position.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[uuid.UUID, list[AssessmentComponent]] = defaultdict(list)
        for row in rows:
            grouped[row.assessment_scheme_id].append(row)
        return dict(grouped)

    @staticmethod
    async def get_components_by_ids(
        db: AsyncSession, tenant_id: uuid.UUID, component_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, AssessmentComponent]:
        if not component_ids:
            return {}
        rows = (await db.execute(select(AssessmentComponent).where(
            AssessmentComponent.tenant_id == tenant_id,
            AssessmentComponent.id.in_(component_ids),
        ))).scalars().all()
        return {row.id: row for row in rows}

    @staticmethod
    async def get_component(
        db: AsyncSession, tenant_id: uuid.UUID, component_id: uuid.UUID
    ) -> AssessmentComponent | None:
        return (
            await db.execute(
                select(AssessmentComponent).where(
                    AssessmentComponent.tenant_id == tenant_id,
                    AssessmentComponent.id == component_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def current_open_term_result_count(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID
    ) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(StudentSubjectResult)
                    .join(AcademicTerm, AcademicTerm.id == StudentSubjectResult.academic_term_id)
                    .where(
                        StudentSubjectResult.tenant_id == tenant_id,
                        StudentSubjectResult.assessment_scheme_id == scheme_id,
                        AcademicTerm.tenant_id == tenant_id,
                        AcademicTerm.is_current.is_(True),
                        AcademicTerm.status == AcademicTermStatus.OPEN,
                    )
                )
            ).scalar_one()
        )
