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
        data=b"test-image", content_type="image/png",
        sha256="0" * 64, width=80, height=80,
    )
    result = await OpenRouterQuestionGenerationProvider(api_key="test").regenerate_question(
        request={"existing_question": {"stem": "Old"}}, reference_images=[image],
    )
    assert len(calls) == 2
    assert result.question["stem"] == "Which triangle?"
    assert result.usage.input_tokens == 85
    assert result.usage.output_tokens == 28
    assert result.usage.provider_cost == pytest.approx(0.005)
