"""Application orchestration for CBT AI authoring and credit workflows."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.cbt.ai.authoring.image_materializer import (
    ImageMaterializationError,
    ImageMaterializer,
)
from app.modules.cbt.ai.authoring.providers.base import (
    ImageResolutionResult,
    ProviderImageInput,
)
from app.modules.cbt.ai.authoring.providers.factory import CBTProviderFactory
from app.modules.cbt.ai.authoring.service import (
    AuthoredQuestion,
    QuestionAuthoringService,
    QuestionGenerationResult,
    QuestionRegenerationResult,
)
from app.modules.cbt.ai.quota.cache import get_cached_quota
from app.modules.cbt.ai.quota.models import (
    AIQuotaActorType,
    AIQuotaPurchaseStatus,
    AIQuotaRequestStatus,
)
from app.modules.cbt.ai.quota.payment_schemas import (
    AIQuotaPurchaseCheckoutResponse,
    AIQuotaPurchaseQuote,
)
from app.modules.cbt.ai.quota.payment_service import AIQuotaPaymentService
from app.modules.cbt.ai.quota.schemas import (
    AIActorQuotaBalanceListResponse,
    AICreditAllocationListResponse,
    AICreditAllocationResponse,
    AICreditSettlementResponse,
    AIQuotaPurchaseListResponse,
    AIQuotaPurchaseResponse,
    AIQuotaRequestListResponse,
    AIQuotaRequestResponse,
    AIQuotaStatusResponse,
    AITenantQuotaSummaryResponse,
)
from app.modules.cbt.ai.quota.service import (
    AIInsufficientCreditsError,
    AIQuotaConflictError,
    AIQuotaError,
    AIQuotaNotFoundError,
    AIQuotaPermissionError,
    AIQuotaService,
)
from app.modules.cbt.ai.schemas import (
    AICreditChargeResponse,
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIQuestionOptionResponse,
    AIQuestionResponse,
    AIRegenerateQuestionRequest,
    AIRegenerateQuestionResponse,
    AIResolvedImageResponse,
)
from app.modules.cbt.auth.schemas import AuthenticatedCBTActor
from app.modules.tenant_admins.repository import TenantAdminRepository


logger = get_logger(__name__)
T = TypeVar("T")


class CBTAIService:
    """Coordinate authenticated CBT actors, AI authoring, quota, and purchases."""

    CREDITS_PER_GENERATED_QUESTION = 1
    CREDITS_PER_REGENERATED_QUESTION = 1

    @classmethod
    async def generate_questions(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIGenerateQuestionsRequest,
    ) -> AIGenerateQuestionsResponse:
        actor_type, quota_actor_id = cls._resolve_quota_actor(actor)
        credits_to_reserve = request.question_count * cls.CREDITS_PER_GENERATED_QUESTION

        reservation = await cls._run_quota(
            AIQuotaService.reserve_credits(
                db,
                tenant_id=actor.tenant_id,
                actor_type=actor_type,
                actor_id=quota_actor_id,
                credits=credits_to_reserve,
            )
        )

        authoring_service = cls._build_authoring_service()
        try:
            result = await authoring_service.generate_questions(
                request=request.model_dump(exclude_none=True),
                expected_count=request.question_count,
                expected_type_counts=request.question_type_counts,
            )
        except Exception:
            await cls._release_reservation_safely(
                db,
                tenant_id=actor.tenant_id,
                reservation_id=reservation.id,
            )
            raise

        actual_credits = len(result.questions) * cls.CREDITS_PER_GENERATED_QUESTION
        settlement = await cls._run_quota(
            AIQuotaService.settle_reservation(
                db,
                tenant_id=actor.tenant_id,
                reservation_id=reservation.id,
                actual_credits=actual_credits,
            )
        )
        return cls._build_generation_response(result=result, settlement=settlement)

    @classmethod
    async def regenerate_question(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request: AIRegenerateQuestionRequest,
    ) -> AIRegenerateQuestionResponse:
        request_payload, reference_images = await cls._prepare_regeneration_request(request)

        actor_type, quota_actor_id = cls._resolve_quota_actor(actor)
        reservation = await cls._run_quota(
            AIQuotaService.reserve_credits(
                db,
                tenant_id=actor.tenant_id,
                actor_type=actor_type,
                actor_id=quota_actor_id,
                credits=cls.CREDITS_PER_REGENERATED_QUESTION,
            )
        )

        authoring_service = cls._build_authoring_service()
        try:
            result = await authoring_service.regenerate_question(
                request=request_payload,
                expected_question_type=request.existing_question.question_type,
                reference_images=reference_images,
            )
        except Exception:
            await cls._release_reservation_safely(
                db,
                tenant_id=actor.tenant_id,
                reservation_id=reservation.id,
            )
            raise

        settlement = await cls._run_quota(
            AIQuotaService.settle_reservation(
                db,
                tenant_id=actor.tenant_id,
                reservation_id=reservation.id,
                actual_credits=cls.CREDITS_PER_REGENERATED_QUESTION,
            )
        )
        return cls._build_regeneration_response(result=result, settlement=settlement)

    @classmethod
    async def get_quota_status(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
    ) -> AIQuotaStatusResponse:
        actor_type, actor_id = cls._resolve_quota_actor(actor)

        async def fetch() -> AIQuotaStatusResponse:
            return await cls._run_quota(
                AIQuotaService.get_quota_status(
                    db,
                    tenant_id=actor.tenant_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            )

        return await get_cached_quota(
            tenant_id=actor.tenant_id,
            identity=f"actor:{actor_type.value}:{actor_id}",
            response_type=AIQuotaStatusResponse,
            fetcher=fetch,
        )

    @classmethod
    async def request_credits(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        credits: int,
    ) -> AIQuotaRequestResponse:
        membership_id = cls._require_teacher(actor)
        return await cls._run_quota(
            AIQuotaService.create_quota_request(
                db,
                tenant_id=actor.tenant_id,
                teacher_membership_id=membership_id,
                credits=credits,
            )
        )

    @classmethod
    async def list_my_credit_requests(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaRequestListResponse:
        membership_id = cls._require_teacher(actor)
        return await cls._run_quota(
            AIQuotaService.list_my_quota_requests(
                db,
                tenant_id=actor.tenant_id,
                teacher_membership_id=membership_id,
                offset=offset,
                limit=limit,
            )
        )

    @classmethod
    async def cancel_my_credit_request(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request_id: UUID,
    ) -> AIQuotaRequestResponse:
        membership_id = cls._require_teacher(actor)
        return await cls._run_quota(
            AIQuotaService.cancel_my_quota_request(
                db,
                tenant_id=actor.tenant_id,
                teacher_membership_id=membership_id,
                request_id=request_id,
            )
        )

    @classmethod
    async def get_tenant_quota_summary(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
    ) -> AITenantQuotaSummaryResponse:
        admin_id = cls._require_admin(actor)

        async def fetch() -> AITenantQuotaSummaryResponse:
            return await cls._run_quota(
                AIQuotaService.get_tenant_quota_summary(
                    db,
                    tenant_id=actor.tenant_id,
                    tenant_admin_id=admin_id,
                )
            )

        return await get_cached_quota(
            tenant_id=actor.tenant_id,
            identity=f"summary:admin:{admin_id}",
            response_type=AITenantQuotaSummaryResponse,
            fetcher=fetch,
        )

    @classmethod
    async def list_actor_quota_balances(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
    ) -> AIActorQuotaBalanceListResponse:
        admin_id = cls._require_admin(actor)

        async def fetch() -> AIActorQuotaBalanceListResponse:
            return await cls._run_quota(
                AIQuotaService.list_actor_quota_balances(
                    db,
                    tenant_id=actor.tenant_id,
                    tenant_admin_id=admin_id,
                )
            )

        return await get_cached_quota(
            tenant_id=actor.tenant_id,
            identity=f"actors:admin:{admin_id}",
            response_type=AIActorQuotaBalanceListResponse,
            fetcher=fetch,
        )

    @classmethod
    async def list_credit_requests(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        status: AIQuotaRequestStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaRequestListResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.list_quota_requests(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                status=status,
                offset=offset,
                limit=limit,
            )
        )

    @classmethod
    async def approve_credit_request(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request_id: UUID,
        approved_credits: int | None = None,
        note: str | None = None,
    ) -> AIQuotaRequestResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.approve_quota_request(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                request_id=request_id,
                approved_credits=approved_credits,
                note=note,
            )
        )

    @classmethod
    async def reject_credit_request(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        request_id: UUID,
        note: str | None = None,
    ) -> AIQuotaRequestResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.reject_quota_request(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                request_id=request_id,
                note=note,
            )
        )

    @classmethod
    async def allocate_credits(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        recipient_actor_type: AIQuotaActorType,
        recipient_actor_id: UUID,
        credits: int,
    ) -> AICreditAllocationResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.allocate_credits(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                recipient_actor_type=recipient_actor_type,
                recipient_actor_id=recipient_actor_id,
                credits=credits,
            )
        )

    @classmethod
    async def list_credit_allocations(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        offset: int = 0,
        limit: int = 50,
    ) -> AICreditAllocationListResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.list_credit_allocations(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                offset=offset,
                limit=limit,
            )
        )

    @classmethod
    def quote_credit_purchase(
        cls,
        *,
        actor: AuthenticatedCBTActor,
        credits: int,
    ) -> AIQuotaPurchaseQuote:
        cls._require_admin(actor)
        try:
            return AIQuotaPaymentService.quote_purchase(credits)
        except AIQuotaError as exc:
            cls._raise_quota_error(exc)
        raise AssertionError("unreachable")

    @classmethod
    async def initialize_credit_purchase(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        credits: int,
    ) -> AIQuotaPurchaseCheckoutResponse:
        admin_id = cls._require_admin(actor)
        admin = await TenantAdminRepository.get_by_tenant_and_id(
            db,
            tenant_id=actor.tenant_id,
            admin_id=admin_id,
        )
        if admin is None:
            raise ForbiddenException("Tenant administrator is no longer active")
        return await cls._run_quota(
            AIQuotaPaymentService.initialize_purchase_checkout(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                email=admin.email,
                credits=credits,
            )
        )

    @classmethod
    async def verify_credit_purchase(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        reference: str,
    ) -> AIQuotaPurchaseResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaPaymentService.verify_purchase_checkout(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                reference=reference,
            )
        )

    @classmethod
    async def list_credit_purchases(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        status: AIQuotaPurchaseStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> AIQuotaPurchaseListResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.list_tenant_quota_purchases(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                status=status,
                offset=offset,
                limit=limit,
            )
        )

    @classmethod
    async def get_credit_purchase(
        cls,
        db: AsyncSession,
        *,
        actor: AuthenticatedCBTActor,
        purchase_id: UUID,
    ) -> AIQuotaPurchaseResponse:
        admin_id = cls._require_admin(actor)
        return await cls._run_quota(
            AIQuotaService.get_quota_purchase(
                db,
                tenant_id=actor.tenant_id,
                tenant_admin_id=admin_id,
                purchase_id=purchase_id,
            )
        )

    @staticmethod
    def _resolve_quota_actor(actor: AuthenticatedCBTActor) -> tuple[AIQuotaActorType, UUID]:
        if actor.role == "teacher":
            if actor.membership_id is None:
                raise ForbiddenException("Teacher CBT authorization has no membership")
            return AIQuotaActorType.TEACHER, actor.membership_id
        if actor.role == "admin":
            return AIQuotaActorType.TENANT_ADMIN, actor.actor_id
        raise ForbiddenException("This CBT actor cannot use AI")

    @staticmethod
    def _require_teacher(actor: AuthenticatedCBTActor) -> UUID:
        if actor.role != "teacher" or actor.membership_id is None:
            raise ForbiddenException("This operation is available only to teachers")
        return actor.membership_id

    @staticmethod
    def _require_admin(actor: AuthenticatedCBTActor) -> UUID:
        if actor.role != "admin":
            raise ForbiddenException("This operation is available only to tenant administrators")
        return actor.actor_id

    @staticmethod
    def _build_authoring_service() -> QuestionAuthoringService:
        return QuestionAuthoringService(
            question_provider=CBTProviderFactory.get_question_provider(),
            image_resolver=CBTProviderFactory.get_image_resolver(),
        )

    @classmethod
    async def _prepare_regeneration_request(
        cls,
        request: AIRegenerateQuestionRequest,
    ) -> tuple[dict, list[ProviderImageInput]]:
        payload = request.model_dump(exclude_none=True)
        existing = payload["existing_question"]
        reference_images: list[ProviderImageInput] = []
        materializer = ImageMaterializer()

        async def consume_image(container: dict, key: str, label: str) -> None:
            raw_image = container.get(key)
            if not isinstance(raw_image, dict):
                return
            try:
                image = await materializer.materialize_transport_base64(
                    data_base64=raw_image["data_base64"],
                    content_type=raw_image["content_type"],
                    expected_sha256=raw_image["sha256"],
                    label=label,
                    alt_text=raw_image.get("alt_text"),
                )
            except ImageMaterializationError as exc:
                raise BadRequestException("Existing question contains an invalid image") from exc
            reference_images.append(image)
            container[key] = {
                "reference_image_label": label,
                "content_type": image.content_type,
                "width": image.width,
                "height": image.height,
            }

        await consume_image(existing, "image", "existing_question.image")
        for index, option in enumerate(existing.get("options", [])):
            if isinstance(option, dict):
                await consume_image(
                    option,
                    "image",
                    f"existing_question.options[{index}].image",
                )

        return payload, reference_images

    @classmethod
    async def _release_reservation_safely(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> None:
        try:
            await AIQuotaService.release_reservation(
                db,
                tenant_id=tenant_id,
                reservation_id=reservation_id,
            )
        except Exception:
            logger.exception(
                "Failed to release CBT AI credit reservation after authoring failure",
                extra={
                    "tenant_id": str(tenant_id),
                    "reservation_id": str(reservation_id),
                },
            )

    @staticmethod
    async def _run_quota(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except AIQuotaError as exc:
            CBTAIService._raise_quota_error(exc)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_quota_error(exc: AIQuotaError) -> None:
        if isinstance(exc, AIInsufficientCreditsError):
            raise ConflictException(
                str(exc),
                payload={
                    "code": "AI_INSUFFICIENT_CREDITS",
                    "requested_credits": exc.requested_credits,
                    "available_credits": exc.available_credits,
                },
            ) from exc
        if isinstance(exc, AIQuotaPermissionError):
            raise ForbiddenException(str(exc)) from exc
        if isinstance(exc, AIQuotaNotFoundError):
            raise NotFoundException(str(exc)) from exc
        if isinstance(exc, AIQuotaConflictError):
            raise ConflictException(str(exc)) from exc
        raise BadRequestException(str(exc)) from exc

    @classmethod
    def _build_generation_response(
        cls,
        *,
        result: QuestionGenerationResult,
        settlement: AICreditSettlementResponse,
    ) -> AIGenerateQuestionsResponse:
        return AIGenerateQuestionsResponse(
            questions=[cls._build_question_response(item) for item in result.questions],
            repaired=result.repaired,
            charge=cls._build_charge_response(settlement),
        )

    @classmethod
    def _build_regeneration_response(
        cls,
        *,
        result: QuestionRegenerationResult,
        settlement: AICreditSettlementResponse,
    ) -> AIRegenerateQuestionResponse:
        return AIRegenerateQuestionResponse(
            question=cls._build_question_response(result.question),
            repaired=result.repaired,
            charge=cls._build_charge_response(settlement),
        )

    @staticmethod
    def _build_charge_response(settlement: AICreditSettlementResponse) -> AICreditChargeResponse:
        return AICreditChargeResponse(
            reservation_id=settlement.reservation_id,
            credits_charged=settlement.total_settled_credits,
            credits_released=settlement.released_credits,
        )

    @classmethod
    def _build_question_response(cls, authored: AuthoredQuestion) -> AIQuestionResponse:
        question = authored.question
        return AIQuestionResponse(
            question_type=question.question_type,
            prompt=question.prompt,
            instruction=question.instruction,
            image=cls._build_image_response(authored.question_image),
            options=[
                AIQuestionOptionResponse(
                    text=option.text,
                    is_correct=option.is_correct,
                    image=cls._build_image_response(authored.option_images.get(index)),
                )
                for index, option in enumerate(question.options)
            ],
        )

    @staticmethod
    def _build_image_response(
        resolution: ImageResolutionResult | None,
    ) -> AIResolvedImageResponse | None:
        if resolution is None:
            return None

        image = resolution.image
        candidate = resolution.candidate
        return AIResolvedImageResponse(
            source=resolution.source,
            content_type=image.content_type,
            data_base64=ImageMaterializer.encode_transport_base64(image),
            sha256=image.sha256,
            width=image.width,
            height=image.height,
            alt_text=image.alt_text,
            source_url=candidate.source_url if candidate is not None else None,
            creator=candidate.creator if candidate is not None else None,
            attribution_text=candidate.attribution_text if candidate is not None else None,
            license_name=candidate.license_name if candidate is not None else None,
            license_url=candidate.license_url if candidate is not None else None,
        )
