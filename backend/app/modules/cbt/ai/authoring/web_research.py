"""Bounded, provider-independent DDGS search/extraction for AI authoring.

The LLM may only read URLs returned by its own previous search. External
content is untrusted and never becomes an instruction. Disable WEB_RESEARCH
until network egress controls are configured for the deployment.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlparse
from typing import Any

from ddgs import DDGS

from app.config.settings import settings


class WebResearchError(ValueError):
    pass


def safe_public_https(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return False
        if parsed.hostname in ("localhost",) or parsed.hostname.endswith(".localhost"):
            return False
        try:
            addresses = [ipaddress.ip_address(parsed.hostname)]
        except ValueError:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
            ]
        return bool(addresses) and all(address.is_global for address in addresses)
    except (ValueError, OSError):
        return False


class DDGSWebResearch:
    def __init__(self) -> None:
        self.allowed_urls: set[str] = set()
        self.search_calls = 0
        self.read_calls = 0

    async def search_web(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query or len(query) > 250:
            raise WebResearchError("Search query must contain 1-250 characters.")
        if self.search_calls >= settings.WEB_RESEARCH_MAX_SEARCHES:
            raise WebResearchError("Search budget exhausted.")
        self.search_calls += 1

        def run():
            return list(
                DDGS(timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS).text(
                    query, safesearch="on", max_results=5
                )
            )
        rows = await asyncio.wait_for(
            asyncio.to_thread(run), timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS + 3
        )
        results: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = row.get("href")
            if not isinstance(url, str) or not safe_public_https(url):
                continue
            self.allowed_urls.add(url)
            results.append(
                {
                    "title": str(row.get("title") or "")[:200],
                    "url": url,
                    "snippet": str(row.get("body") or "")[:750],
                }
            )
            if len(results) >= 5:
                break
        return {"results": results, "unverified_sources": True}

    async def read_webpage(self, url: str) -> dict[str, Any]:
        if url not in self.allowed_urls:
            raise WebResearchError("Only links from this request's search results can be read.")
        if self.read_calls >= settings.WEB_RESEARCH_MAX_READS:
            raise WebResearchError("Page-read budget exhausted.")
        if not safe_public_https(url):
            raise WebResearchError("Unsafe destination.")
        self.read_calls += 1
        def run():
            return DDGS(timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS).extract(
                url, fmt="text_markdown"
            )
        result = await asyncio.wait_for(
            asyncio.to_thread(run), timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS + 3
        )
        final_url = result.get("url") if isinstance(result, dict) else None
        if final_url != url:
            # Never trust post-redirect content. Network egress must ALSO block
            # internal destinations because DDGS may have followed a redirect.
            raise WebResearchError("Redirected extraction is not permitted.")
        content = result.get("content") if isinstance(result, dict) else None
        if not isinstance(content, str):
            raise WebResearchError("No readable webpage text.")
        return {"url": url, "content": content[:12000], "unverified_source": True}


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search public web sources when authentic exam-year documents, "
                "recent or time-sensitive facts, or source citations are needed. "
                "Do not use for routine syllabus-based questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "Read a relevant web search result URL, never an arbitrary URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
]


async def execute_web_tool(agent: DDGSWebResearch, name: str, argument_text: str) -> str:
    try:
        arguments = json.loads(argument_text)
        if not isinstance(arguments, dict):
            raise WebResearchError("Tool arguments must be an object.")
        if name == "search_web" and isinstance(arguments.get("query"), str):
            result = await agent.search_web(arguments["query"])
        elif name == "read_webpage" and isinstance(arguments.get("url"), str):
            result = await agent.read_webpage(arguments["url"])
        else:
            raise WebResearchError("Unknown tool or invalid parameters.")
        return json.dumps(result)
    except (WebResearchError, ValueError, asyncio.TimeoutError, OSError) as exc:
        return json.dumps({"error": type(exc).__name__, "message": str(exc)[:250]})
