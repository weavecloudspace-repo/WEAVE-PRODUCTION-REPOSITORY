"""DDGS web research never accepts arbitrary model-supplied read URLs."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.modules.cbt.ai.authoring import web_research


class FakeDDGS:
    def __init__(self, *, timeout):
        self.timeout = timeout

    def text(self, *args, **kwargs):
        return [
            {"title": "Sample exam", "href": "https://example.com/exam", "body": "Some questions"},
            {"title": "Local address", "href": "http://127.0.0.1/private"},
        ]

    def extract(self, url, fmt):
        return {"url": url, "content": "# Example Exam\nQ1: Which is correct?"}


@pytest.mark.asyncio
async def test_search_and_read_are_bounded_to_discovered_urls(monkeypatch):
    monkeypatch.setattr(web_research, "DDGS", FakeDDGS)
    monkeypatch.setattr(web_research, "safe_public_https", lambda url: url.startswith("https://example.com/"))
    agent = web_research.DDGSWebResearch()
    results = await agent.search_web("WAEC Mathematics 2022")
    assert results["results"][0]["url"] == "https://example.com/exam"
    assert len(results["results"]) == 1
    result = await agent.read_webpage("https://example.com/exam")
    assert "Q1" in result["content"]
    with pytest.raises(web_research.WebResearchError, match="Only links"):
        await agent.read_webpage("https://example.com/unlisted")


@pytest.mark.asyncio
async def test_unknown_function_does_not_execute_search():
    agent = web_research.DDGSWebResearch()
    result = await web_research.execute_web_tool(agent, "delete_database", "{}")
    assert "error" in json.loads(result)
    assert agent.search_calls == 0


@pytest.mark.parametrize("url", [
    "http://example.com",
    "https://127.0.0.1/",
    "https://localhost/",
    "file:///etc/passwd",
    "https://user:pass@example.com/",
    "https://192.168.1.1/",
])
def test_obvious_unsafe_url_rejected(url):
    assert not web_research.safe_public_https(url)
