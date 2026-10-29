"""OpenRouter adapters with fake HTTP responses; CI never spends model credits."""

from __future__ import annotations

import base64

import httpx
import pytest

from app.modules.cbt.ai.authoring.providers.openrouter import (
    OpenRouterImageEvaluationProvider,
    OpenRouterImageGenerationProvider,
    OpenRouterProviderError,
    OpenRouterQuestionGenerationProvider,
)


def fake_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, json=payload, request=httpx.Request("POST", "https://openrouter.ai/api/v1/images")
    )


@pytest.mark.asyncio
async def test_no_api_key_rejects_without_network():
    provider = OpenRouterQuestionGenerationProvider(api_key=" ")
    with pytest.raises(OpenRouterProviderError, match="not configured"):
        await provider.generate_questions(request={"prompt": "Hi"})


@pytest.mark.asyncio
async def test_question_generation_normalizes_response(monkeypatch):
    async def post(self, url, *, headers, json):
        assert url.endswith("/chat/completions")
        assert json["model"] == "openai/gpt-oss-120b"
        return fake_response(
            {
                "choices": [{"message": {"content": '{"questions":[{"stem":"Which?"}]}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10, "cost": 0.001},
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    provider = OpenRouterQuestionGenerationProvider(api_key="test", timeout=10)
    result = await provider.generate_questions(request={"topic": "Biology"})
    assert result.questions == [{"stem": "Which?"}]
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 10
    assert result.usage.provider_cost == 0.001


@pytest.mark.asyncio
async def test_malformed_question_response_rejected(monkeypatch):
    async def post(self, url, *, headers, json):
        return fake_response({"choices": [{"message": {"content": '{"wrong": []}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(OpenRouterProviderError, match="questions array"):
        await OpenRouterQuestionGenerationProvider(api_key="test").generate_questions(request={})


@pytest.mark.asyncio
async def test_unauthorized_response_is_normalized(monkeypatch):
    async def post(self, url, *, headers, json):
        return fake_response({"error": "bad token"}, 401)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(OpenRouterProviderError) as caught:
        await OpenRouterQuestionGenerationProvider(api_key="test").generate_questions(request={})
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_image_generation_accepts_valid_png(monkeypatch):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"payload").decode()

    async def post(self, url, *, headers, json):
        assert url.endswith("/images")
        assert json["model"] == "qwen/qwen-image-2.1-turbo"
        return fake_response(
            {"data": [{"b64_json": png, "media_type": "image/png"}], "usage": {"cost": 0.0184}}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    generated = await OpenRouterImageGenerationProvider(api_key="test").generate_image(
        prompt="Human heart"
    )
    assert generated.image.content_type == "image/png"
    assert generated.image.data_base64 == png


@pytest.mark.asyncio
async def test_image_evaluation_validates_index(monkeypatch):
    async def post(self, url, *, headers, json):
        return fake_response(
            {
                "choices": [
                    {"message": {"content": '{"decision":"use_candidate","selected_index":99}'}}
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    from app.modules.cbt.ai.authoring.providers.base import ProviderImageInput

    image = ProviderImageInput(
        data=b"image", content_type="image/png", sha256="0" * 64, width=10, height=10
    )
    with pytest.raises(OpenRouterProviderError, match="index"):
        await OpenRouterImageEvaluationProvider(api_key="test").evaluate_images(
            requirement="Heart", images=[image]
        )


@pytest.mark.asyncio
async def test_reference_image_regeneration_uses_vision_before_text(monkeypatch):
    calls = []

    async def post(self, url, *, headers, json):
        calls.append(json)
        if json["model"] == "qwen/qwen3-vl-8b-instruct":
            assert any(part.get("type") == "image_url" for part in json["messages"][0]["content"])
            return fake_response(
                {
                    "choices": [{"message": {"content": "A labelled blue triangle."}}],
                    "usage": {"prompt_tokens": 25, "completion_tokens": 8, "cost": 0.002},
                }
            )
        assert json["model"] == "openai/gpt-oss-120b"
        assert isinstance(json["messages"][-1]["content"], str)
        assert "A labelled blue triangle." in json["messages"][-1]["content"]
        return fake_response(
            {
                "choices": [{"message": {"content": '{"question":{"stem":"Which triangle?"}}'}}],
                "usage": {"prompt_tokens": 60, "completion_tokens": 20, "cost": 0.003},
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    from app.modules.cbt.ai.authoring.providers.base import ProviderImageInput

    image = ProviderImageInput(
        data=b"test-image",
        content_type="image/png",
        sha256="0" * 64,
        width=80,
        height=80,
    )
    result = await OpenRouterQuestionGenerationProvider(api_key="test").regenerate_question(
        request={"existing_question": {"stem": "Old"}},
        reference_images=[image],
    )
    assert len(calls) == 2
    assert result.question["stem"] == "Which triangle?"
    assert result.usage.input_tokens == 85
    assert result.usage.output_tokens == 28
    assert result.usage.provider_cost == pytest.approx(0.005)


@pytest.mark.asyncio
async def test_vision_429_respects_retry_after_and_retries_without_spamming(monkeypatch):
    from unittest.mock import AsyncMock
    from app.modules.cbt.ai.authoring.providers import openrouter

    attempts = []
    waits = []
    cooldowns = []
    monkeypatch.setattr(openrouter.settings, "OPENROUTER_429_MAX_RETRIES", 2)
    monkeypatch.setattr(openrouter.settings, "OPENROUTER_VISION_MIN_INTERVAL_SECONDS", 4.0)
    monkeypatch.setattr(
        openrouter.vision_request_pacer,
        "wait_for_slot",
        AsyncMock(side_effect=lambda **kwargs: waits.append(kwargs)),
    )
    monkeypatch.setattr(
        openrouter.vision_request_pacer,
        "cooldown",
        AsyncMock(side_effect=lambda **kwargs: cooldowns.append(kwargs)),
    )

    async def post(self, url, *, headers, json):
        attempts.append(json["model"])
        if len(attempts) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "5"},
                json={"error": {"code": "rate_limit", "message": "Temporary capacity limit"}},
                request=httpx.Request("POST", url),
            )
        return fake_response(
            {"choices": [{"message": {"content": '{"decision":"generate_image"}'}}]}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    from app.modules.cbt.ai.authoring.providers.base import ProviderImageInput

    image = ProviderImageInput(
        data=b"image", content_type="image/png", sha256="0" * 64, width=10, height=10
    )
    result = await OpenRouterImageEvaluationProvider(api_key="fake-key").evaluate_images(
        requirement="An unlabeled organ", images=[image]
    )
    assert result.decision == "generate_image"
    assert attempts == ["qwen/qwen3-vl-8b-instruct"] * 2
    assert len(waits) == 2
    assert len(cooldowns) == 1
    assert cooldowns[0]["delay"] == 5


@pytest.mark.asyncio
async def test_daily_quota_429_fails_without_retrying(monkeypatch):
    from app.modules.cbt.ai.authoring.providers import openrouter
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        openrouter.vision_request_pacer, "wait_for_slot", AsyncMock()
    )
    attempts = []

    async def post(self, url, *, headers, json):
        attempts.append(True)
        return httpx.Response(
            429,
            headers={"Retry-After": "120"},
            json={"error": {"code": "insufficient_quota", "message": "Daily quota exhausted"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    provider = OpenRouterQuestionGenerationProvider(api_key="fake-key")
    with pytest.raises(OpenRouterProviderError) as caught:
        await provider.generate_questions(request={})
    assert caught.value.status_code == 429
    assert caught.value.quota_exhausted
    assert caught.value.error_code == "insufficient_quota"
    assert caught.value.retry_after_seconds == 120
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_excessive_retry_after_fails_fast_and_does_not_sleep(monkeypatch):
    from app.modules.cbt.ai.authoring.providers import openrouter

    attempts = []
    monkeypatch.setattr(openrouter.settings, "OPENROUTER_429_MAX_BACKOFF_SECONDS", 15.0)

    async def post(self, url, *, headers, json):
        attempts.append(True)
        return httpx.Response(
            429,
            headers={"Retry-After": "3600"},
            json={"error": {"code": 429, "message": "Provider temporarily rate limited"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(OpenRouterProviderError) as caught:
        await OpenRouterQuestionGenerationProvider(api_key="fake-key").generate_questions(
            request={}
        )
    assert not caught.value.quota_exhausted
    assert caught.value.retry_after_seconds == 3600
    assert len(attempts) == 1


def test_retry_after_parses_seconds_and_invalid_dates():
    from app.modules.cbt.ai.authoring.providers.openrouter import _parse_retry_after

    assert _parse_retry_after("2.5") == 2.5
    assert _parse_retry_after("-1") is None
    assert _parse_retry_after("nonsense") is None
