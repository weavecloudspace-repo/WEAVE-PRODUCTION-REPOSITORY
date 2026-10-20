import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.assessment_schemas import (
    AssessmentComponentCreate,
    AssessmentComponentOrder,
    AssessmentComponentResponse,
    AssessmentComponentUpdate,
    AssessmentSchemeCreate,
    AssessmentSchemeResponse,
    AssessmentSchemeUpdate,
)
from app.modules.student_academics.models import (
    AssessmentComponent,
    AssessmentScheme,
    AssessmentSchemeStatus,
)


class AssessmentService:
    @staticmethod
    async def response(
        db: AsyncSession,
        scheme: AssessmentScheme,
        *,
        components: list[AssessmentComponent] | None = None,
    ) -> AssessmentSchemeResponse:
        if components is None:
            components = await AssessmentRepository.list_components(db, scheme.tenant_id, scheme.id)
        total = sum((item.maximum_score for item in components), Decimal("0"))
        return AssessmentSchemeResponse(
            id=scheme.id,
            tenant_id=scheme.tenant_id,
            name=scheme.name,
            status=scheme.status,
            activated_at=scheme.activated_at,
            archived_at=scheme.archived_at,
            components=[AssessmentComponentResponse.model_validate(item) for item in components],
            total_maximum_score=total,
            is_configured=scheme.status == AssessmentSchemeStatus.ACTIVE
            and total == Decimal("100"),
            created_at=scheme.created_at,
            updated_at=scheme.updated_at,
        )

    @staticmethod
    async def active(db: AsyncSession, tenant_id: uuid.UUID) -> AssessmentSchemeResponse:
        scheme = await AssessmentRepository.get_active_scheme(db, tenant_id)
        if scheme is None:
            raise NotFoundException("No active assessment scheme is configured.")
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def create(
        db: AsyncSession, tenant_id: uuid.UUID, payload: AssessmentSchemeCreate
    ) -> AssessmentSchemeResponse:
        scheme = AssessmentScheme(tenant_id=tenant_id, name=payload.name)
        db.add(scheme)
        try:
            await db.flush()
            for item in payload.components:
                db.add(
                    AssessmentComponent(
                        tenant_id=tenant_id,
                        assessment_scheme_id=scheme.id,
                        **item.model_dump(),
                    )
                )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Scheme and component names and positions must be unique."
            ) from exc
        await db.refresh(scheme)
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def _draft(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID
    ) -> AssessmentScheme:
        scheme = await AssessmentRepository.get_scheme(db, tenant_id, scheme_id, lock=True)
        if scheme is None:
            raise NotFoundException("Assessment scheme not found.")
        if scheme.status != AssessmentSchemeStatus.DRAFT:
            raise ConflictException("Only draft assessment schemes can be changed.")
        return scheme

    @staticmethod
    async def rename(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scheme_id: uuid.UUID,
        payload: AssessmentSchemeUpdate,
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        scheme.name = payload.name
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Assessment scheme names must be unique.") from exc
        await db.refresh(scheme)
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def add_component(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scheme_id: uuid.UUID,
        payload: AssessmentComponentCreate,
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        db.add(
            AssessmentComponent(
                tenant_id=tenant_id, assessment_scheme_id=scheme.id, **payload.model_dump()
            )
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Component name and position must be unique in the scheme."
            ) from exc
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def update_component(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scheme_id: uuid.UUID,
        component_id: uuid.UUID,
        payload: AssessmentComponentUpdate,
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        component = await AssessmentRepository.get_component(db, tenant_id, component_id)
        if component is None or component.assessment_scheme_id != scheme.id:
            raise NotFoundException("Assessment component not found.")
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("is_hybrid", component.is_hybrid) and not changes.get("is_examinable", component.is_examinable):
            raise BadRequestException("Hybrid components must also be examinable.")
        for field, value in changes.items():
            setattr(component, field, value)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("Component names must be unique in the scheme.") from exc
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def remove_component(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID, component_id: uuid.UUID
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        component = await AssessmentRepository.get_component(db, tenant_id, component_id)
        if component is None or component.assessment_scheme_id != scheme.id:
            raise NotFoundException("Assessment component not found.")
        await db.delete(component)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException("The component is referenced and cannot be removed.") from exc
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def reorder(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        scheme_id: uuid.UUID,
        payload: AssessmentComponentOrder,
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        components = await AssessmentRepository.list_components(db, tenant_id, scheme.id)
        if set(payload.component_ids) != {item.id for item in components}:
            raise BadRequestException("Ordering must include every scheme component exactly once.")
        by_id = {item.id: item for item in components}
        temporary_offset = (
            max((item.position for item in components), default=0) + len(components) + 1
        )
        try:
            for index, component_id in enumerate(payload.component_ids):
                by_id[component_id].position = temporary_offset + index
            await db.flush()
            for index, component_id in enumerate(payload.component_ids):
                by_id[component_id].position = index
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "Component ordering could not be saved; refresh and try again."
            ) from exc
        return await AssessmentService.response(db, scheme)

    @staticmethod
    async def activate(
        db: AsyncSession, tenant_id: uuid.UUID, scheme_id: uuid.UUID
    ) -> AssessmentSchemeResponse:
        scheme = await AssessmentService._draft(db, tenant_id, scheme_id)
        components = await AssessmentRepository.list_components(db, tenant_id, scheme.id)
        if not components or sum((item.maximum_score for item in components), Decimal("0")) != 100:
            raise BadRequestException(
                "An active assessment scheme must contain components totaling 100."
            )
        current = await AssessmentRepository.get_active_scheme(db, tenant_id, lock=True)
        if current is not None:
            count = await AssessmentRepository.current_open_term_result_count(
                db, tenant_id, current.id
            )
            if count:
                raise ConflictException(
                    "The active scheme has results in the current open term and cannot be replaced."
                )
            current.status = AssessmentSchemeStatus.ARCHIVED
            current.archived_at = datetime.now(timezone.utc)
            await db.flush()
        scheme.status = AssessmentSchemeStatus.ACTIVE
        scheme.activated_at = datetime.now(timezone.utc)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(
                "The assessment scheme changed concurrently; refresh and try again."
            ) from exc
        await db.refresh(scheme)
        return await AssessmentService.response(db, scheme)
