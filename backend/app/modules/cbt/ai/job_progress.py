"""Minimal Redis progress metadata for an idempotent CBT AI generation job."""

from __future__ import annotations

from uuid import UUID

from app.core.cache.redis import get_runtime_redis

AI_JOB_PROGRESS_TTL_SECONDS = 24 * 60 * 60
AI_JOB_PROGRESS_STAGES = frozenset(
    {"queued", "generating_questions", "generating_images", "finalizing"}
)


class AIJobProgressCache:
    @staticmethod
    def _key(job_id: UUID) -> str:
        return f"cbt:ai:generation:progress:{job_id}"

    @classmethod
    async def set(cls, job_id: UUID, stage: str) -> None:
        if stage not in AI_JOB_PROGRESS_STAGES:
            raise ValueError("Unsupported generation progress stage")
        redis = get_runtime_redis()
        if redis is None:
            raise RuntimeError("Redis unavailable for CBT AI generation progress.")
        await redis.set(cls._key(job_id), stage, ex=AI_JOB_PROGRESS_TTL_SECONDS)

    @classmethod
    async def get(cls, job_id: UUID) -> str | None:
        redis = get_runtime_redis()
        if redis is None:
            return None
        try:
            value = await redis.get(cls._key(job_id))
        except Exception:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return value if value in AI_JOB_PROGRESS_STAGES else None
