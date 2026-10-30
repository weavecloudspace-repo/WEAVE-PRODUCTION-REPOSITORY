"""Contact-sheet optimized image resolution for CBT AI authoring."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from app.modules.cbt.ai.authoring.assessment_integrity import (
    assessment_review_requirement,
    assessment_safe_generation_prompt,
)
from app.modules.cbt.ai.authoring.flow_logging import get_question_generation_logger
from app.modules.cbt.ai.authoring.image_contact_sheet import build_candidate_contact_sheet
from app.modules.cbt.ai.authoring.image_materializer import (
    ImageMaterializationError,
    ImageMaterializer,
)
from app.modules.cbt.ai.authoring.image_resolver import (
    ImageResolver,
    ImageResolverError,
    _build_parallel_search_queries,
    _dedupe_candidates,
    _exception_chain,
    _is_transient_provider_error,
    _provider_name,
)
from app.modules.cbt.ai.authoring.providers.base import (
    BaseImageEvaluationProvider,
    BaseImageGenerationProvider,
    BaseImageSearchProvider,
    ImageCandidate,
    ImageResolutionResult,
    ProviderImageEvaluationResult,
    ProviderImageInput,
    ProviderUsage,
)

logger = get_question_generation_logger("contact_sheet_resolver")


class ContactSheetImageResolver(ImageResolver):
    """Review a broad thumbnail pool through one numbered composite image."""

    DEFAULT_SEARCH_LIMIT = 12
    DEFAULT_REVIEW_LIMIT = 12
    MATERIALIZATION_CONCURRENCY = 6
    MAX_MATERIALIZATION_ATTEMPTS = 16

    def __init__(
        self,
        *,
        search_provider: BaseImageSearchProvider,
        evaluation_provider: BaseImageEvaluationProvider,
        generation_provider: BaseImageGenerationProvider,
        materializer: ImageMaterializer,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        review_limit: int = DEFAULT_REVIEW_LIMIT,
    ) -> None:
        super().__init__(
            search_provider=search_provider,
            evaluation_provider=evaluation_provider,
            generation_provider=generation_provider,
            materializer=materializer,
            search_limit=search_limit,
            review_limit=review_limit,
        )

    async def resolve(
        self,
        *,
        requirement: str,
        search_query: str,
        generation_prompt: str | None = None,
        search_metadata: Mapping[str, Any] | None = None,
        generation_metadata: Mapping[str, Any] | None = None,
        reference_images: Sequence[ProviderImageInput] | None = None,
        assessment_context: str | None = None,
    ) -> ImageResolutionResult:
        normalized_requirement = requirement.strip()
        normalized_search_query = search_query.strip()
        if not normalized_requirement:
            raise ValueError("Image requirement cannot be empty.")
        if not normalized_search_query:
            raise ValueError("Image search query cannot be empty.")

        normalized_generation_prompt = assessment_safe_generation_prompt(
            (
                generation_prompt.strip()
                if isinstance(generation_prompt, str) and generation_prompt.strip()
                else normalized_requirement
            ),
            assessment_context,
        )
        search_queries = _build_parallel_search_queries(
            normalized_requirement,
            normalized_search_query,
        )

        logger.info(
            "cbt.ai.image_resolution.started",
            extra={
                "image_search_provider": _provider_name(self.search_provider),
                "image_evaluation_provider": _provider_name(self.evaluation_provider),
                "image_generation_provider": _provider_name(self.generation_provider),
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_parallel_search_query_count": len(search_queries),
                "image_requirement": normalized_requirement,
                "image_search_limit_per_query": self.search_limit,
                "image_review_limit": self.review_limit,
                "image_materialization_concurrency": self.MATERIALIZATION_CONCURRENCY,
                "image_materialization_attempt_limit": self.MAX_MATERIALIZATION_ATTEMPTS,
                "image_evaluation_strategy": "contact_sheet",
            },
        )

        search_results = await asyncio.gather(
            *(
                self._search_one(
                    query=query,
                    search_index=index,
                    metadata=search_metadata,
                )
                for index, query in enumerate(search_queries)
            ),
            return_exceptions=True,
        )

        candidate_groups: list[list[ImageCandidate]] = []
        search_failures: list[BaseException] = []
        raw_candidate_count = 0
        for result in search_results:
            if isinstance(result, BaseException):
                search_failures.append(result)
                continue
            raw_candidate_count += len(result)
            candidate_groups.append(result)

        if not candidate_groups and search_failures:
            logger.warning(
                "cbt.ai.image_resolution.search_unavailable_fallback_to_generation",
                extra={"image_error_type": type(search_failures[0]).__name__},
            )
            return await self._generate(
                prompt=normalized_generation_prompt,
                metadata=generation_metadata,
                reference_images=reference_images,
                evaluation=None,
                assessment_context=assessment_context,
            )

        candidates = _dedupe_candidates(candidate_groups)
        logger.info(
            "cbt.ai.image_resolution.parallel_search.completed",
            extra={
                "image_search_provider": _provider_name(self.search_provider),
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_parallel_search_query_count": len(search_queries),
                "image_search_failure_count": len(search_failures),
                "image_raw_candidate_count": raw_candidate_count,
                "image_candidate_count": len(candidates),
                "image_deduplicated_candidate_count": raw_candidate_count - len(candidates),
            },
        )

        (
            materialized_candidates,
            attempted_candidate_count,
            failed_candidate_count,
        ) = await self._materialize_review_candidates(
            candidates,
            search_queries=search_queries,
        )

        logger.info(
            "cbt.ai.image_resolution.materialization.completed",
            extra={
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_candidate_count": len(candidates),
                "image_attempted_candidate_count": attempted_candidate_count,
                "image_failed_candidate_count": failed_candidate_count,
                "image_skipped_candidate_count": max(
                    0, len(candidates) - attempted_candidate_count
                ),
                "image_materialized_candidate_count": len(materialized_candidates),
                "image_materialization_concurrency": self.MATERIALIZATION_CONCURRENCY,
                "image_materialization_attempt_limit": self.MAX_MATERIALIZATION_ATTEMPTS,
                "image_materialization_mode": "preview",
            },
        )

        if not materialized_candidates:
            fallback_reason = (
                "parallel_search_returned_no_candidates"
                if not candidates
                else "all_attempted_search_candidates_failed_preview_materialization"
            )
            logger.warning(
                "cbt.ai.image_resolution.fallback_to_generation",
                extra={
                    "image_fallback_reason": fallback_reason,
                    "image_search_query": normalized_search_query,
                    "image_search_queries": search_queries,
                    "image_candidate_count": len(candidates),
                    "image_generation_provider": _provider_name(self.generation_provider),
                },
            )
            return await self._generate(
                prompt=normalized_generation_prompt,
                metadata=generation_metadata,
                reference_images=reference_images,
                evaluation=None,
                assessment_context=assessment_context,
            )

        preview_images = [image for _, image in materialized_candidates]
        supports_contact_sheet = bool(
            getattr(self.evaluation_provider, "supports_contact_sheet_selection", False)
        )
        evaluation_mode = "separate_images"
        evaluation_images = preview_images

        if supports_contact_sheet and len(preview_images) > 1:
            contact_sheet = await asyncio.to_thread(
                build_candidate_contact_sheet,
                preview_images,
            )
            evaluation_images = [contact_sheet]
            evaluation_mode = "contact_sheet"
            logger.info(
                "cbt.ai.image_resolution.contact_sheet.created",
                extra={
                    "image_contact_sheet_candidate_count": len(preview_images),
                    "image_contact_sheet_width": contact_sheet.width,
                    "image_contact_sheet_height": contact_sheet.height,
                    "image_contact_sheet_bytes": len(contact_sheet.data),
                    "image_contact_sheet_content_type": contact_sheet.content_type,
                },
            )

        evaluation: ProviderImageEvaluationResult | None = None
        for evaluation_attempt in range(1, self.MAX_EVALUATION_ATTEMPTS + 1):
            logger.info(
                "cbt.ai.image_resolution.evaluation.started",
                extra={
                    "image_evaluation_provider": _provider_name(self.evaluation_provider),
                    "image_search_query": normalized_search_query,
                    "image_search_queries": search_queries,
                    "image_review_candidate_count": len(materialized_candidates),
                    "image_evaluation_input_image_count": len(evaluation_images),
                    "image_evaluation_mode": evaluation_mode,
                    "image_evaluation_attempt": evaluation_attempt,
                    "image_evaluation_max_attempts": self.MAX_EVALUATION_ATTEMPTS,
                },
            )
            try:
                evaluation = await self.evaluation_provider.evaluate_images(
                    requirement=assessment_review_requirement(
                        normalized_requirement, assessment_context
                    ),
                    images=evaluation_images,
                )
                break
            except Exception as exc:
                if (
                    evaluation_attempt < self.MAX_EVALUATION_ATTEMPTS
                    and _is_transient_provider_error(exc)
                ):
                    logger.warning(
                        "cbt.ai.image_resolution.evaluation.retrying",
                        extra={
                            "image_evaluation_provider": _provider_name(self.evaluation_provider),
                            "image_search_query": normalized_search_query,
                            "image_evaluation_mode": evaluation_mode,
                            "image_evaluation_attempt": evaluation_attempt,
                            "image_error_type": type(exc).__name__,
                            "image_error_message": str(exc),
                            "image_error_chain": _exception_chain(exc),
                        },
                    )
                    await asyncio.sleep(self.EVALUATION_RETRY_DELAY_SECONDS)
                    continue

                logger.exception(
                    "cbt.ai.image_resolution.evaluation.failed",
                    extra={
                        "image_evaluation_provider": _provider_name(self.evaluation_provider),
                        "image_search_query": normalized_search_query,
                        "image_search_queries": search_queries,
                        "image_review_candidate_count": len(materialized_candidates),
                        "image_evaluation_mode": evaluation_mode,
                        "image_evaluation_attempt": evaluation_attempt,
                        "image_error_type": type(exc).__name__,
                        "image_error_message": str(exc),
                    },
                )
                raise

        if evaluation is None:
            raise ImageResolverError("Image evaluation provider returned no decision.")

        logger.info(
            "cbt.ai.image_resolution.evaluation.completed",
            extra={
                "image_evaluation_provider": _provider_name(self.evaluation_provider),
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_evaluation_mode": evaluation_mode,
                "image_evaluation_decision": evaluation.decision,
                "image_selected_index": evaluation.selected_index,
                "image_evaluation_reason": evaluation.reason,
            },
        )

        if evaluation.decision == "generate_image":
            logger.warning(
                "cbt.ai.image_resolution.fallback_to_generation",
                extra={
                    "image_fallback_reason": "evaluation_requested_generation",
                    "image_search_query": normalized_search_query,
                    "image_search_queries": search_queries,
                    "image_evaluation_mode": evaluation_mode,
                    "image_evaluation_reason": evaluation.reason,
                    "image_generation_provider": _provider_name(self.generation_provider),
                },
            )
            return await self._generate(
                prompt=normalized_generation_prompt,
                metadata=generation_metadata,
                reference_images=reference_images,
                evaluation=evaluation,
                assessment_context=assessment_context,
            )

        if evaluation.decision != "use_candidate":
            raise ImageResolverError(
                f"Unsupported image evaluation decision: {evaluation.decision!r}."
            )

        selected_index = evaluation.selected_index
        if (
            type(selected_index) is not int
            or selected_index < 0
            or selected_index >= len(materialized_candidates)
        ):
            raise ImageResolverError(
                "Image evaluation provider selected an invalid candidate index."
            )

        selected_candidate, selected_preview = materialized_candidates[selected_index]
        selected_image = selected_preview
        final_materialization_used_preview = False
        try:
            selected_image = await self.materializer.materialize_candidate(
                selected_candidate,
                label=f"selected_search_candidate_{selected_index}",
            )
        except ImageMaterializationError as exc:
            final_materialization_used_preview = True
            logger.warning(
                "cbt.ai.image_resolution.selected_candidate.full_materialization_failed",
                extra={
                    "image_selected_index": selected_index,
                    "image_candidate_source": selected_candidate.source,
                    "image_candidate_external_id": selected_candidate.external_id,
                    "image_candidate_title": selected_candidate.title,
                    "image_error_type": type(exc).__name__,
                    "image_error_message": str(exc),
                    "image_error_chain": _exception_chain(exc),
                    "image_preview_fallback_used": True,
                },
            )

        integrity_review_usages: list[ProviderUsage] = []
        if assessment_context:
            # Contact-sheet thumbnails can hide tiny titles, and full-size
            # materialization may produce different bytes. Reinspect exactly
            # what will be returned to the candidate.
            integrity_review = await self.evaluation_provider.evaluate_images(
                requirement=assessment_review_requirement(
                    normalized_requirement, assessment_context
                ),
                images=[selected_image],
            )
            integrity_review_usages.append(integrity_review.usage)
            if integrity_review.decision != "use_candidate" or integrity_review.selected_index != 0:
                logger.warning(
                    "cbt.ai.image_resolution.search_candidate.answer_leakage_rejected",
                    extra={
                        "image_selected_index": selected_index,
                        "image_integrity_reason": integrity_review.reason,
                    },
                )
                fallback = await self._generate(
                    prompt=normalized_generation_prompt,
                    metadata=generation_metadata,
                    reference_images=reference_images,
                    evaluation=evaluation,
                    assessment_context=assessment_context,
                )
                fallback.integrity_review_usages.extend(integrity_review_usages)
                return fallback

        logger.info(
            "cbt.ai.image_resolution.search_candidate.selected",
            extra={
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_evaluation_mode": evaluation_mode,
                "image_selected_index": selected_index,
                "image_candidate_source": selected_candidate.source,
                "image_candidate_external_id": selected_candidate.external_id,
                "image_candidate_title": selected_candidate.title,
                "image_width": selected_image.width,
                "image_height": selected_image.height,
                "image_content_type": selected_image.content_type,
                "image_bytes": len(selected_image.data),
                "image_preview_fallback_used": final_materialization_used_preview,
            },
        )
        return ImageResolutionResult(
            source="search",
            image=selected_image,
            candidate=selected_candidate,
            evaluation=evaluation,
            integrity_review_usages=integrity_review_usages,
        )

    async def _materialize_one_candidate(
        self,
        *,
        original_index: int,
        rank_index: int,
        relevance_score: int,
        candidate: ImageCandidate,
    ) -> tuple[ImageCandidate, ProviderImageInput] | None:
        preview_materializer = getattr(
            self.materializer,
            "materialize_candidate_preview",
            None,
        )
        if not callable(preview_materializer):
            return await super()._materialize_one_candidate(
                original_index=original_index,
                rank_index=rank_index,
                relevance_score=relevance_score,
                candidate=candidate,
            )

        logger.debug(
            "cbt.ai.image_resolution.candidate_preview.started",
            extra={
                "image_candidate_index": original_index,
                "image_candidate_rank": rank_index,
                "image_candidate_relevance_score": relevance_score,
                "image_candidate_source": candidate.source,
                "image_candidate_external_id": candidate.external_id,
                "image_candidate_title": candidate.title,
            },
        )
        try:
            image = await preview_materializer(
                candidate,
                label=f"search_preview_{rank_index}",
            )
        except ImageMaterializationError as exc:
            logger.debug(
                "cbt.ai.image_resolution.candidate_preview.failed",
                extra={
                    "image_candidate_index": original_index,
                    "image_candidate_rank": rank_index,
                    "image_candidate_relevance_score": relevance_score,
                    "image_candidate_source": candidate.source,
                    "image_candidate_external_id": candidate.external_id,
                    "image_candidate_title": candidate.title,
                    "image_error_type": type(exc).__name__,
                    "image_error_message": str(exc),
                    "image_error_chain": _exception_chain(exc),
                },
            )
            return None

        logger.debug(
            "cbt.ai.image_resolution.candidate_preview.succeeded",
            extra={
                "image_candidate_index": original_index,
                "image_candidate_rank": rank_index,
                "image_candidate_relevance_score": relevance_score,
                "image_candidate_source": candidate.source,
                "image_candidate_external_id": candidate.external_id,
                "image_candidate_title": candidate.title,
                "image_content_type": image.content_type,
                "image_width": image.width,
                "image_height": image.height,
                "image_bytes": len(image.data),
            },
        )
        return candidate, image
