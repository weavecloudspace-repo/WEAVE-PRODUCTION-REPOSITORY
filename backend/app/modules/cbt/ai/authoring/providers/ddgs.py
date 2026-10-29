"""DDGS search adapter for existing CBT image candidate resolution."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping
from urllib.parse import urlparse

from ddgs import DDGS

from app.config.settings import settings
from app.modules.cbt.ai.authoring.providers.base import BaseImageSearchProvider, ImageCandidate


class DDGSImageSearchProvider(BaseImageSearchProvider):
    provider_name = "ddgs"

    def is_configured(self) -> bool:
        return True

    async def search(
        self, *, query: str, limit: int = 10, metadata: Mapping[str, Any] | None = None
    ) -> list[ImageCandidate]:
        if not query.strip():
            raise ValueError("Image search query cannot be blank.")
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError("Image search limit must be between 1 and 30.")

        # Restrict discovery to commercial-modification candidates. This is a
        # search filter, NOT proof of a license; independent verification is required.
        def _search() -> list[dict[str, Any]]:
            return list(
                DDGS(timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS).images(
                    query=query.strip(),
                    safesearch="on",
                    license_image="ModifyCommercially",
                    max_results=limit,
                )
            )

        rows = await asyncio.wait_for(
            asyncio.to_thread(_search),
            timeout=settings.DDGS_REQUEST_TIMEOUT_SECONDS + 3,
        )
        candidates: list[ImageCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            direct = row.get("image")
            source = row.get("url")
            if not isinstance(direct, str) or urlparse(direct).scheme != "https":
                continue
            if not isinstance(source, str) or urlparse(source).scheme not in ("http", "https"):
                continue
            thumb = row.get("thumbnail")
            candidates.append(
                ImageCandidate(
                    source="ddgs",
                    source_url=source,
                    image_url=direct,
                    thumbnail_url=thumb
                    if isinstance(thumb, str) and urlparse(thumb).scheme == "https"
                    else None,
                    title=str(row.get("title") or "")[:500],
                    width=row.get("width") if type(row.get("width")) is int else None,
                    height=row.get("height") if type(row.get("height")) is int else None,
                    # Never assert a verified license on the basis of DDGS results.
                    license_name=None,
                )
            )
        return candidates
