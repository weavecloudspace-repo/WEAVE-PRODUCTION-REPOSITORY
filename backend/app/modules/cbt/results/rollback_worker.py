"""Bounded ARQ processing and PostgreSQL-ledger recovery of CBT rollbacks."""

from __future__ import annotations
from typing import Any
from uuid import UUID
from sqlalchemy import select
from app.config.database import AsyncSessionLocal
from app.core.queue.arq import HEAVY_QUEUE_NAME
from app.modules.cbt.results.rollback_models import CBTResultRollbackOperation
from app.modules.cbt.results.rollback_service import CBTResultRollbackService


async def process_cbt_result_rollback_job(ctx: dict[str, Any], operation_pk: str) -> int:
    processed = await CBTResultRollbackService.process_pending(
        AsyncSessionLocal, operation_pk=UUID(operation_pk)
    )
    if processed:
        redis = ctx.get("redis")
        if redis is not None:
            await redis.enqueue_job(
                "process_cbt_result_rollback_job",
                operation_pk,
                _queue_name=HEAVY_QUEUE_NAME,
                _defer_by=1,
            )
    return processed


async def recover_cbt_result_rollbacks(ctx: dict[str, Any]) -> int:
    async with AsyncSessionLocal() as db:
        pending = list(
            (
                await db.execute(
                    select(CBTResultRollbackOperation.id)
                    .where(CBTResultRollbackOperation.status.in_(("pending", "processing")))
                    .order_by(CBTResultRollbackOperation.created_at)
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
    redis = ctx.get("redis")
    if redis is not None:
        for operation_pk in pending:
            await redis.enqueue_job(
                "process_cbt_result_rollback_job",
                str(operation_pk),
                _queue_name=HEAVY_QUEUE_NAME,
            )
    return len(pending)
