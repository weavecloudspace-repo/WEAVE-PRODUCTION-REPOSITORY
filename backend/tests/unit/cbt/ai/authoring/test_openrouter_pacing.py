"""Qwen Vision pacing contract: bound bursts across workers and locally."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.modules.cbt.ai.authoring.providers import request_pacing


@pytest.mark.asyncio
async def test_local_pacer_queues_burst_instead_of_sending_together(monkeypatch):
    monkeypatch.setattr(request_pacing, "get_runtime_redis", lambda: None)
    pacer = request_pacing.VisionRequestPacer()

    async def send():
        await pacer.wait_for_slot(
            api_key="test", model="qwen/vision", interval=0.035, max_wait=0.5
        )
        return time.monotonic()

    times = await asyncio.gather(send(), send(), send())
    assert times[-1] - times[0] >= 0.05
    assert times[-1] - times[0] < 0.5


@pytest.mark.asyncio
async def test_local_pacer_enforces_queue_maximum(monkeypatch):
    monkeypatch.setattr(request_pacing, "get_runtime_redis", lambda: None)
    pacer = request_pacing.VisionRequestPacer()
    await pacer.wait_for_slot(api_key="test", model="vision", interval=30, max_wait=0.01)
    with pytest.raises(request_pacing.OpenRouterPacingError, match="capacity"):
        await pacer.wait_for_slot(
            api_key="test", model="vision", interval=30, max_wait=0.01
        )


@pytest.mark.asyncio
async def test_distributed_pacing_uses_atomic_redis_eval_and_shared_model_key(monkeypatch):
    class Redis:
        def __init__(self):
            self.calls = []

        async def eval(self, script, count, *args):
            self.calls.append((script, count, args))
            return 0

    redis = Redis()
    monkeypatch.setattr(request_pacing, "get_runtime_redis", lambda: redis)
    first = request_pacing.VisionRequestPacer()
    second = request_pacing.VisionRequestPacer()
    await first.wait_for_slot(
        api_key="same-secret", model="qwen/vision", interval=4, max_wait=90
    )
    await second.wait_for_slot(
        api_key="same-secret", model="qwen/vision", interval=4, max_wait=90
    )
    assert redis.calls[0][2][0] == redis.calls[1][2][0]
    assert "same-secret" not in redis.calls[0][2][0]
    assert redis.calls[0][2][1:] == (4000, 90000)


@pytest.mark.asyncio
async def test_distributed_redis_pacing_fail_closed(monkeypatch):
    class BrokenRedis:
        async def eval(self, *args):
            raise ConnectionError("redis not reachable")

    monkeypatch.setattr(request_pacing, "get_runtime_redis", lambda: BrokenRedis())
    pacer = request_pacing.VisionRequestPacer()
    with pytest.raises(request_pacing.OpenRouterPacingError, match="unavailable"):
        await pacer.wait_for_slot(
            api_key="test", model="qwen/vision", interval=4, max_wait=90
        )


@pytest.mark.asyncio
async def test_distributed_queue_saturation_rejected_without_http_request(monkeypatch):
    class SaturatedRedis:
        async def eval(self, *args):
            return -1

    monkeypatch.setattr(request_pacing, "get_runtime_redis", lambda: SaturatedRedis())
    with pytest.raises(request_pacing.OpenRouterPacingError, match="capacity"):
        await request_pacing.VisionRequestPacer().wait_for_slot(
            api_key="test", model="qwen/vision", interval=4, max_wait=90
        )
