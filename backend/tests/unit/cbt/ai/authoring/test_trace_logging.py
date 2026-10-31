"""Safe per-request diagnostics for synchronous CBT AI question generation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

import pytest

from app.modules.cbt.ai.authoring import trace_logging


def test_trace_file_is_separate_from_application_and_existing_ai_logs() -> None:
    assert trace_logging.TRACE_LOG_FILE.name == "cbt_ai_hybrid_trace.jsonl"
    assert trace_logging.TRACE_LOG_FILE.name != "app.log"
    assert trace_logging.TRACE_LOG_FILE.name != "cbt_ai_question_generation.log"


def test_trace_events_share_operation_id_but_not_http_request_id(monkeypatch) -> None:
    sink = Mock()
    monkeypatch.setattr(trace_logging, "_trace_logger", lambda: sink)
    monkeypatch.setattr(trace_logging, "_ENABLED", True)

    with trace_logging.trace_request(
        idempotency_key="same-operation", operation="generate", request_id="request-one"
    ):
        trace_logging.trace_event(
            "request.accepted",
            question_count=20,
            visual_mode="auto",
            generation_prompt="CONFIDENTIAL-TEACHER-PROMPT",
            access_token="SECRET-TOKEN",
            image_base64="SECRET-IMAGE-DATA",
            error_message="private error payload",
        )

    with trace_logging.trace_request(
        idempotency_key="same-operation", operation="generate", request_id="request-two"
    ):
        trace_logging.trace_event("idempotency.in_progress")

    assert sink.info.call_count == 2
    first = json.loads(sink.info.call_args_list[0].args[0])
    second = json.loads(sink.info.call_args_list[1].args[0])
    assert first["operation_id"] == second["operation_id"]
    assert first["request_id"] == "request-one"
    assert second["request_id"] == "request-two"
    assert first["question_count"] == 20
    assert first["visual_mode"] == "auto"
    assert first["operation"] == "generate"
    assert "same-operation" not in str(first)
    assert "CONFIDENTIAL" not in str(first)
    assert "SECRET" not in str(first)
    assert "private error" not in str(first)


@pytest.mark.asyncio
async def test_concurrent_images_have_independent_context(monkeypatch) -> None:
    events: list[dict] = []
    sink = Mock()
    sink.info.side_effect = lambda text: events.append(json.loads(text))
    monkeypatch.setattr(trace_logging, "_trace_logger", lambda: sink)
    monkeypatch.setattr(trace_logging, "_ENABLED", True)

    async def trace_one(ref: str) -> None:
        with trace_logging.trace_image(ref):
            trace_logging.trace_event("image.attempt_started", attempt=1)
            await asyncio.sleep(0)
            trace_logging.trace_event("image.materialized", image_bytes=12)

    with trace_logging.trace_request(idempotency_key="operation", operation="generate"):
        await asyncio.gather(trace_one("q1:stem"), trace_one("q2:option1"))

    assert [(item["image_ref"], item["event"]) for item in events] == [
        ("q1:stem", "image.attempt_started"),
        ("q2:option1", "image.attempt_started"),
        ("q1:stem", "image.materialized"),
        ("q2:option1", "image.materialized"),
    ]
    assert len({event["operation_id"] for event in events}) == 1


def test_trace_without_active_request_is_silent(monkeypatch) -> None:
    sink = Mock()
    monkeypatch.setattr(trace_logging, "_trace_logger", lambda: sink)
    monkeypatch.setattr(trace_logging, "_ENABLED", True)
    trace_logging.trace_event("request.accepted", question_count=20)
    sink.info.assert_not_called()


def test_trace_can_be_disabled(monkeypatch) -> None:
    sink = Mock()
    monkeypatch.setattr(trace_logging, "_trace_logger", lambda: sink)
    monkeypatch.setattr(trace_logging, "_ENABLED", False)
    with trace_logging.trace_request(idempotency_key="operation", operation="generate"):
        trace_logging.trace_event("request.accepted", question_count=20)
    sink.info.assert_not_called()
