"""Provider-agnostic image resolution engine for CBT AI authoring."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping, Sequence

import httpx

from app.modules.cbt.ai.authoring.flow_logging import get_question_generation_logger
from app.modules.cbt.ai.authoring.image_materializer import (
    ImageMaterializationError,
    ImageMaterializer,
)
from app.modules.cbt.ai.authoring.providers.base import (
    BaseImageEvaluationProvider,
    BaseImageGenerationProvider,
    BaseImageSearchProvider,
    ImageCandidate,
    ImageResolutionResult,
    ProviderImageEvaluationResult,
    ProviderImageGenerationResult,
    ProviderImageInput,
)

logger = get_question_generation_logger("image_resolver")


class ImageResolverError(RuntimeError):
    """Raised when providers return an invalid image-resolution decision."""


_GENERIC_SEARCH_TERMS = frozenset(
    {
        "anatomy",
        "biology",
        "clear",
        "diagram",
        "diagrams",
        "educational",
        "figure",
        "figures",
        "image",
        "images",
        "illustration",
        "illustrations",
        "labelled",
        "labeled",
        "photo",
        "photograph",
        "picture",
        "pictures",
        "science",
        "showing",
        "study",
        "structure",
        "system",
        "visual",
    }
)

_SEARCH_STOP_TERMS = _GENERIC_SEARCH_TERMS | frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "central",
        "containing",
        "directed",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "major",
        "of",
        "on",
        "or",
        "pointer",
        "show",
        "shown",
        "shows",
        "specifically",
        "surrounded",
        "the",
        "to",
        "various",
        "where",
        "which",
        "with",
    }
)


def _provider_name(provider: object) -> str:
    """Return a stable provider label for diagnostic logs."""

    provider_name = getattr(provider, "provider_name", None)
    if isinstance(provider_name, str) and provider_name.strip():
        return provider_name.strip()
    return type(provider).__name__


def _exception_chain(exc: BaseException, *, limit: int = 5) -> list[str]:
    """Render a bounded exception chain without changing exception handling."""

    chain: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < limit:
        seen.add(id(current))
        chain.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return chain


def _normalize_search_token(token: str) -> str:
    """Apply tiny plural normalization for cheap title/query matching."""

    normalized = token.casefold()
    if len(normalized) > 4 and normalized.endswith("ies"):
        return f"{normalized[:-3]}y"
    if (
        len(normalized) > 3
        and normalized.endswith("s")
        and not normalized.endswith(("ss", "us", "is"))
    ):
        return normalized[:-1]
    return normalized


def _search_terms(value: str) -> list[str]:
    return [
        _normalize_search_token(term)
        for term in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)?", value.casefold())
    ]


def _significant_search_terms(value: str) -> list[str]:
    terms: list[str] = []
    # Treat hyphenated compounds like their space-separated search equivalents.
    for term in _search_terms(value.replace("-", " ")):
        if term in _SEARCH_STOP_TERMS or term in terms:
            continue
        terms.append(term)
    return terms


def _build_broader_search_query(query: str) -> str | None:
    """Build a deliberately broader query for strict AND-style search."""

    significant = _significant_search_terms(query)
    if len(significant) <= 2:
        return None

    broader = f"{significant[0]} {significant[-1]}"
    if broader.casefold() == query.strip().casefold():
        return None
    return broader


def _build_secondary_search_query(requirement: str, primary_query: str) -> str | None:
    """Build one semantic alternate without another AI/provider call.

    Some search backends use strict AND-style keyword matching. The primary authoring query
    remains the first retrieval path. The alternate keeps the subject anchor from
    the primary query but replaces generic phrasing with concrete requirement
    terms that the authoring model may have omitted.
    """

    primary_terms = _significant_search_terms(primary_query)
    requirement_terms = _significant_search_terms(requirement)
    primary_set = set(primary_terms)
    novel_terms = [term for term in requirement_terms if term not in primary_set]

    if novel_terms:
        secondary_terms = list(primary_terms[:2])
        for term in novel_terms[-2:]:
            if term not in secondary_terms:
                secondary_terms.append(term)
        secondary = " ".join(secondary_terms[:4]).strip()
        if secondary and secondary.casefold() != primary_query.strip().casefold():
            return secondary

    return _build_broader_search_query(primary_query)


def _build_parallel_search_queries(requirement: str, primary_query: str) -> list[str]:
    queries = [primary_query.strip()]
    alternate = _build_secondary_search_query(requirement, primary_query)
    if alternate and alternate.casefold() != queries[0].casefold():
        queries.append(alternate)
    return queries[:2]


def _candidate_identity(candidate: ImageCandidate) -> tuple[str, ...]:
    """Return a stable dedupe key for candidates merged from parallel searches."""

    source = candidate.source.casefold()
    if candidate.external_id:
        return ("external_id", source, candidate.external_id.casefold())
    if candidate.image_url:
        return ("image_url", candidate.image_url.strip().casefold())
    if candidate.source_url:
        return ("source_url", candidate.source_url.strip().casefold())
    return ("fallback", source, (candidate.title or "").strip().casefold())


def _dedupe_candidates(
    candidate_groups: Sequence[Sequence[ImageCandidate]],
) -> list[ImageCandidate]:
    merged: list[ImageCandidate] = []
    seen: set[tuple[str, ...]] = set()
    for group in candidate_groups:
        for candidate in group:
            identity = _candidate_identity(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(candidate)
    return merged


def _rank_search_candidates(
    queries: Sequence[str],
    candidates: Sequence[ImageCandidate],
) -> list[tuple[int, ImageCandidate, int]]:
    """Prioritize metadata relevance while preserving every candidate.

    The first concrete primary-query term is treated as the strongest subject
    anchor. Other primary terms and alternate-query terms add weaker evidence.
    Provider order remains the final tie-breaker. Vision evaluation is still the
    semantic authority and can reject every ranked candidate.
    """

    term_weights: dict[str, int] = {}
    for query_index, query in enumerate(queries):
        terms = _significant_search_terms(query)
        for term_index, term in enumerate(terms):
            if query_index == 0 and term_index == 0:
                weight = 4
            elif query_index == 0:
                weight = 2
            else:
                weight = 1
            term_weights[term] = max(term_weights.get(term, 0), weight)

    ranked: list[tuple[int, ImageCandidate, int]] = []
    for original_index, candidate in enumerate(candidates):
        title_terms = set(_search_terms(candidate.title or ""))
        score = sum(weight for term, weight in term_weights.items() if term in title_terms)
        ranked.append((original_index, candidate, score))

    ranked.sort(key=lambda item: (-item[2], item[0]))
    return ranked


def _is_transient_provider_error(exc: BaseException) -> bool:
    """Identify retryable provider/network failures without retrying quota 429s."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))

        status_code = getattr(current, "status_code", None)
        if type(status_code) is int and (status_code == 408 or 500 <= status_code < 600):
            return True
        if isinstance(current, httpx.RequestError):
            return True

        current = current.__cause__ or current.__context__
    return False


class ImageResolver:
    """Resolve CBT visual requirements into fully materialized image bytes.

    URLs and provider Base64 are transient inputs only. If resolve() returns
    successfully, ImageResolutionResult.image contains validated encoded image
    file bytes that can be sent to CBT or another provider without performing
    another external download.
    """

    DEFAULT_SEARCH_LIMIT = 10
    DEFAULT_REVIEW_LIMIT = 4
    MATERIALIZATION_CONCURRENCY = 4
    MAX_MATERIALIZATION_ATTEMPTS = 8
    MAX_EVALUATION_ATTEMPTS = 2
    EVALUATION_RETRY_DELAY_SECONDS = 0.5
    MAX_GENERATION_MATERIALIZATION_ATTEMPTS = 2

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
        if type(search_limit) is not int or search_limit <= 0:
            raise ValueError("Image search limit must be a positive integer.")
        if type(review_limit) is not int or review_limit <= 0:
            raise ValueError("Image review limit must be a positive integer.")
        if review_limit > search_limit:
            raise ValueError("Image review limit cannot exceed the search limit.")

        self.search_provider = search_provider
        self.evaluation_provider = evaluation_provider
        self.generation_provider = generation_provider
        self.materializer = materializer
        self.search_limit = search_limit
        self.review_limit = review_limit

    async def _search_one(
        self,
        *,
        query: str,
        search_index: int,
        metadata: Mapping[str, Any] | None,
    ) -> list[ImageCandidate]:
        logger.debug(
            "cbt.ai.image_resolution.search.started",
            extra={
                "image_search_provider": _provider_name(self.search_provider),
                "image_search_query": query,
                "image_search_attempt": search_index + 1,
                "image_search_parallel": True,
            },
        )
        try:
            candidates = await self.search_provider.search(
                query=query,
                limit=self.search_limit,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception(
                "cbt.ai.image_resolution.search.failed",
                extra={
                    "image_search_provider": _provider_name(self.search_provider),
                    "image_search_query": query,
                    "image_search_attempt": search_index + 1,
                    "image_search_parallel": True,
                    "image_error_type": type(exc).__name__,
                    "image_error_message": str(exc),
                },
            )
            raise

        logger.info(
            "cbt.ai.image_resolution.search.completed",
            extra={
                "image_search_provider": _provider_name(self.search_provider),
                "image_search_query": query,
                "image_search_attempt": search_index + 1,
                "image_search_parallel": True,
                "image_candidate_count": len(candidates),
            },
        )
        return candidates

    async def resolve(
        self,
        *,
        requirement: str,
        search_query: str,
        generation_prompt: str | None = None,
        search_metadata: Mapping[str, Any] | None = None,
        generation_metadata: Mapping[str, Any] | None = None,
        reference_images: Sequence[ProviderImageInput] | None = None,
    ) -> ImageResolutionResult:
        """Resolve one requested visual into sourced or generated image bytes."""

        normalized_requirement = requirement.strip()
        normalized_search_query = search_query.strip()

        if not normalized_requirement:
            raise ValueError("Image requirement cannot be empty.")
        if not normalized_search_query:
            raise ValueError("Image search query cannot be empty.")

        normalized_generation_prompt = (
            generation_prompt.strip()
            if isinstance(generation_prompt, str) and generation_prompt.strip()
            else normalized_requirement
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
            },
        )

        if not materialized_candidates:
            fallback_reason = (
                "parallel_search_returned_no_candidates"
                if not candidates
                else "all_attempted_search_candidates_failed_materialization"
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
                    "image_evaluation_attempt": evaluation_attempt,
                    "image_evaluation_max_attempts": self.MAX_EVALUATION_ATTEMPTS,
                },
            )
            try:
                evaluation = await self.evaluation_provider.evaluate_images(
                    requirement=normalized_requirement,
                    images=[image for _, image in materialized_candidates],
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
                    "image_evaluation_reason": evaluation.reason,
                    "image_generation_provider": _provider_name(self.generation_provider),
                },
            )
            return await self._generate(
                prompt=normalized_generation_prompt,
                metadata=generation_metadata,
                reference_images=reference_images,
                evaluation=evaluation,
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

        selected_candidate, selected_image = materialized_candidates[selected_index]
        logger.info(
            "cbt.ai.image_resolution.search_candidate.selected",
            extra={
                "image_search_query": normalized_search_query,
                "image_search_queries": search_queries,
                "image_selected_index": selected_index,
                "image_candidate_source": selected_candidate.source,
                "image_candidate_external_id": selected_candidate.external_id,
                "image_candidate_title": selected_candidate.title,
                "image_width": selected_image.width,
                "image_height": selected_image.height,
                "image_content_type": selected_image.content_type,
                "image_bytes": len(selected_image.data),
            },
        )
        return ImageResolutionResult(
            source="search",
            image=selected_image,
            candidate=selected_candidate,
            evaluation=evaluation,
        )

    async def _materialize_one_candidate(
        self,
        *,
        original_index: int,
        rank_index: int,
        relevance_score: int,
        candidate: ImageCandidate,
    ) -> tuple[ImageCandidate, ProviderImageInput] | None:
        logger.debug(
            "cbt.ai.image_resolution.candidate_materialization.started",
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
            image = await self.materializer.materialize_candidate(
                candidate,
                label=f"search_candidate_{rank_index}",
            )
        except ImageMaterializationError as exc:
            logger.debug(
                "cbt.ai.image_resolution.candidate_materialization.failed",
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
            "cbt.ai.image_resolution.candidate_materialization.succeeded",
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

    async def _materialize_review_candidates(
        self,
        candidates: Sequence[ImageCandidate],
        *,
        search_queries: Sequence[str],
    ) -> tuple[list[tuple[ImageCandidate, ProviderImageInput]], int, int]:
        """Materialize likely candidates in bounded concurrent batches.

        The larger parallel-search pool improves recall, but download latency is
        bounded: at most MAX_MATERIALIZATION_ATTEMPTS candidates are attempted and
        no more than MATERIALIZATION_CONCURRENCY run at once.
        """

        ranked_candidates = _rank_search_candidates(search_queries, candidates)
        logger.debug(
            "cbt.ai.image_resolution.candidates.ranked",
            extra={
                "image_search_queries": list(search_queries),
                "image_ranked_candidates": [
                    {
                        "rank": rank_index,
                        "original_index": original_index,
                        "score": score,
                        "source": candidate.source,
                        "external_id": candidate.external_id,
                        "title": candidate.title,
                    }
                    for rank_index, (original_index, candidate, score) in enumerate(
                        ranked_candidates
                    )
                ],
            },
        )

        materialized: list[tuple[ImageCandidate, ProviderImageInput]] = []
        attempted_count = 0
        failed_count = 0
        cursor = 0
        attempt_limit = min(len(ranked_candidates), self.MAX_MATERIALIZATION_ATTEMPTS)

        while cursor < attempt_limit and len(materialized) < self.review_limit:
            remaining_slots = self.review_limit - len(materialized)
            batch_size = min(
                self.MATERIALIZATION_CONCURRENCY,
                remaining_slots,
                attempt_limit - cursor,
            )
            batch = ranked_candidates[cursor : cursor + batch_size]

            results = await asyncio.gather(
                *(
                    self._materialize_one_candidate(
                        original_index=original_index,
                        rank_index=cursor + offset,
                        relevance_score=score,
                        candidate=candidate,
                    )
                    for offset, (original_index, candidate, score) in enumerate(batch)
                )
            )

            attempted_count += len(batch)
            for result in results:
                if result is None:
                    failed_count += 1
                else:
                    materialized.append(result)

            cursor += len(batch)

        return materialized, attempted_count, failed_count

    async def _generate(
        self,
        *,
        prompt: str,
        metadata: Mapping[str, Any] | None,
        reference_images: Sequence[ProviderImageInput] | None,
        evaluation: ProviderImageEvaluationResult | None,
    ) -> ImageResolutionResult:
        """Generate a fallback visual and retry once if its payload is unusable."""

        generation_attempts: list[ProviderImageGenerationResult] = []
        last_error: ImageMaterializationError | None = None

        for attempt_index in range(1, self.MAX_GENERATION_MATERIALIZATION_ATTEMPTS + 1):
            logger.info(
                "cbt.ai.image_resolution.generation.started",
                extra={
                    "image_generation_provider": _provider_name(self.generation_provider),
                    "image_generation_attempt": attempt_index,
                    "image_generation_max_attempts": self.MAX_GENERATION_MATERIALIZATION_ATTEMPTS,
                },
            )
            try:
                generation = await self.generation_provider.generate_image(
                    prompt=prompt,
                    metadata=metadata,
                    reference_images=reference_images,
                )
            except Exception as exc:
                logger.exception(
                    "cbt.ai.image_resolution.generation_provider.failed",
                    extra={
                        "image_generation_provider": _provider_name(self.generation_provider),
                        "image_generation_attempt": attempt_index,
                        "image_error_type": type(exc).__name__,
                        "image_error_message": str(exc),
                    },
                )
                raise

            generation_attempts.append(generation)

            logger.debug(
                "cbt.ai.image_resolution.generation_provider.completed",
                extra={
                    "image_generation_provider": _provider_name(self.generation_provider),
                    "image_generation_attempt": attempt_index,
                    "image_generation_has_base64": bool(generation.image.data_base64),
                    "image_generation_has_url": bool(generation.image.url),
                    "image_generation_content_type": generation.image.content_type,
                },
            )

            try:
                image = await self.materializer.materialize_generated(
                    generation.image,
                    label="generated_image",
                )
            except ImageMaterializationError as exc:
                last_error = exc
                logger.warning(
                    "cbt.ai.image_resolution.generated_materialization.failed",
                    extra={
                        "image_generation_provider": _provider_name(self.generation_provider),
                        "image_generation_attempt": attempt_index,
                        "image_error_type": type(exc).__name__,
                        "image_error_message": str(exc),
                        "image_error_chain": _exception_chain(exc),
                    },
                )
                continue

            logger.info(
                "cbt.ai.image_resolution.generation.completed",
                extra={
                    "image_generation_provider": _provider_name(self.generation_provider),
                    "image_generation_attempt": attempt_index,
                    "image_content_type": image.content_type,
                    "image_width": image.width,
                    "image_height": image.height,
                    "image_bytes": len(image.data),
                },
            )
            return ImageResolutionResult(
                source="generated",
                image=image,
                generation=generation,
                generation_attempts=generation_attempts,
                evaluation=evaluation,
            )

        raise ImageResolverError(
            "Image generation provider returned unusable image data after retry."
        ) from last_error
