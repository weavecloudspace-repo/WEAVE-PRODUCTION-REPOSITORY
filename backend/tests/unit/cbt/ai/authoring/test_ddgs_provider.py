"""DDGS image discovery contract; never calls external search engines."""
from __future__ import annotations

import pytest

from app.modules.cbt.ai.authoring.providers import ddgs as adapter


class FakeDDGS:
    calls = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    def images(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {"title": "Heart", "image": "https://cdn.example.org/heart.png",
             "thumbnail": "https://cdn.example.org/thumb.png",
             "url": "https://example.org/heart", "width": 1000, "height": 800},
            {"title": "Login", "image": "https://example.org/signin",
             "url": "http://invalid", "width": 600},
            {"title": "Bad scheme", "image": "file:///etc/passwd",
             "url": "https://example.org/bad"},
        ]


@pytest.mark.asyncio
async def test_ddgs_provides_original_image_and_source_page(monkeypatch):
    monkeypatch.setattr(adapter, "DDGS", FakeDDGS)
    provider = adapter.DDGSImageSearchProvider()
    images = await provider.search(query="labelled human heart", limit=5)
    assert len(images) == 1
    assert images[0].source == "ddgs"
    assert images[0].source_url == "https://example.org/heart"
    assert images[0].image_url == "https://cdn.example.org/heart.png"
    assert images[0].thumbnail_url == "https://cdn.example.org/thumb.png"
    assert images[0].license_name is None  # A search filter is not license verification.
    assert FakeDDGS.calls[-1]["license_image"] == "ModifyCommercially"
    assert FakeDDGS.calls[-1]["safesearch"] == "on"


@pytest.mark.asyncio
@pytest.mark.parametrize("query,limit", [("", 5), ("x", 0), ("x", 50)])
async def test_invalid_requests_rejected_before_search(query, limit):
    with pytest.raises(ValueError):
        await adapter.DDGSImageSearchProvider().search(query=query, limit=limit)


@pytest.mark.asyncio
async def test_search_errors_are_not_silently_treated_as_empty_results(monkeypatch):
    class Offline(FakeDDGS):
        def images(self, **kwargs):
            raise ConnectionError("search unavailable")

    monkeypatch.setattr(adapter, "DDGS", Offline)
    with pytest.raises(ConnectionError):
        await adapter.DDGSImageSearchProvider().search(query="heart")
