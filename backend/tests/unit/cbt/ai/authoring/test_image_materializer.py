from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, call

import pytest
from PIL import Image

from app.modules.cbt.ai.authoring.image_materializer import (
    ImageDownloadError,
    ImageMaterializer,
    InvalidImageError,
    _build_wikimedia_raster_url,
)
from app.modules.cbt.ai.authoring.providers.base import ImageCandidate, ProviderGeneratedImage


def _encoded_image(format_name: str = "PNG") -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", (32, 24), "white")
    image.save(buffer, format=format_name)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_transport_round_trip_preserves_encoded_file_bytes() -> None:
    raw = _encoded_image("PNG")
    digest = hashlib.sha256(raw).hexdigest()
    materializer = ImageMaterializer()

    image = await materializer.materialize_transport_base64(
        data_base64=base64.b64encode(raw).decode("ascii"),
        content_type="image/png",
        expected_sha256=digest,
        label="existing_question.image",
    )

    assert image.data == raw
    assert image.sha256 == digest
    assert image.content_type == "image/png"
    assert image.width == 32
    assert image.height == 24
    assert image.label == "existing_question.image"
    assert base64.b64decode(materializer.encode_transport_base64(image)) == raw


@pytest.mark.asyncio
async def test_transport_rejects_mime_type_that_does_not_match_bytes() -> None:
    raw = _encoded_image("PNG")
    with pytest.raises(InvalidImageError, match="content type"):
        await ImageMaterializer().materialize_transport_base64(
            data_base64=base64.b64encode(raw).decode("ascii"),
            content_type="image/jpeg",
            expected_sha256=hashlib.sha256(raw).hexdigest(),
        )


@pytest.mark.asyncio
async def test_transport_rejects_hash_mismatch() -> None:
    raw = _encoded_image("PNG")
    with pytest.raises(InvalidImageError, match="SHA-256"):
        await ImageMaterializer().materialize_transport_base64(
            data_base64=base64.b64encode(raw).decode("ascii"),
            content_type="image/png",
            expected_sha256="0" * 64,
        )


@pytest.mark.asyncio
async def test_generated_base64_is_materialized_to_real_image_file_bytes() -> None:
    raw = _encoded_image("PNG")
    image = await ImageMaterializer().materialize_generated(
        ProviderGeneratedImage(
            content_type="image/png",
            data_base64=base64.b64encode(raw).decode("ascii"),
        )
    )

    assert image.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.content_type == "image/png"
    assert hashlib.sha256(image.data).hexdigest() == image.sha256


@pytest.mark.asyncio
async def test_candidate_falls_back_to_thumbnail_when_original_url_is_unusable() -> None:
    raw = _encoded_image("PNG")
    materializer = ImageMaterializer()
    materializer._download = AsyncMock(
        side_effect=[
            ImageDownloadError("original unavailable"),
            raw,
        ]
    )
    candidate = ImageCandidate(
        source="ddgs",
        source_url="https://example.com/source",
        image_url="https://cdn.example.com/original.png",
        thumbnail_url="https://cdn.example.com/thumbnail.png",
        mime_type="image/png",
    )

    image = await materializer.materialize_candidate(candidate)

    assert image.content_type == "image/png"
    assert materializer._download.await_args_list == [
        call("https://cdn.example.com/original.png"),
        call("https://cdn.example.com/thumbnail.png"),
    ]


def test_wikimedia_svg_builds_raster_render_url() -> None:
    raster_url = _build_wikimedia_raster_url(
        "https://upload.wikimedia.org/wikipedia/commons/4/40/"
        "Simple_diagram_of_animal_cell_%28en%29.svg",
        width=1600,
    )

    assert raster_url is not None
    parsed = urlparse(raster_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "commons.wikimedia.org"
    assert parsed.path == "/w/index.php"
    assert query["title"] == ["Special:Redirect/file/Simple_diagram_of_animal_cell_(en).svg"]
    assert query["width"] == ["1600"]


def test_non_wikimedia_or_non_svg_urls_do_not_build_raster_render_url() -> None:
    assert (
        _build_wikimedia_raster_url(
            "https://upload.wikimedia.org/wikipedia/commons/a/a0/photo.jpg",
            width=1600,
        )
        is None
    )
    assert (
        _build_wikimedia_raster_url(
            "https://example.com/diagram.svg",
            width=1600,
        )
        is None
    )


@pytest.mark.asyncio
async def test_wikimedia_svg_uses_raster_render_before_openverse_thumbnail() -> None:
    raw = _encoded_image("PNG")
    materializer = ImageMaterializer()
    materializer._download = AsyncMock(return_value=raw)
    candidate = ImageCandidate(
        source="wikimedia",
        source_url="https://commons.wikimedia.org/wiki/File:Simple_diagram.svg",
        image_url=(
            "https://upload.wikimedia.org/wikipedia/commons/4/40/"
            "Simple_diagram_of_animal_cell_%28en%29.svg"
        ),
        thumbnail_url=(
            "https://api.openverse.org/v1/images/54719370-bce5-4f80-bcd9-8abbe3993bab/thumb/"
        ),
        mime_type="image/svg+xml",
    )

    image = await materializer.materialize_candidate(candidate)

    assert image.content_type == "image/png"
    assert materializer._download.await_count == 1
    requested_url = materializer._download.await_args.args[0]
    parsed = urlparse(requested_url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "commons.wikimedia.org"
    assert query["title"] == ["Special:Redirect/file/Simple_diagram_of_animal_cell_(en).svg"]
    assert query["width"] == ["1600"]


@pytest.mark.asyncio
async def test_wikimedia_svg_falls_back_to_openverse_thumbnail_if_raster_fails() -> None:
    raw = _encoded_image("PNG")
    materializer = ImageMaterializer()
    thumbnail_url = "https://api.openverse.org/v1/images/example/thumb/"
    materializer._download = AsyncMock(side_effect=[ImageDownloadError("raster unavailable"), raw])
    candidate = ImageCandidate(
        source="wikimedia",
        source_url="https://commons.wikimedia.org/wiki/File:Example.svg",
        image_url="https://upload.wikimedia.org/wikipedia/commons/a/ab/Example.svg",
        thumbnail_url=thumbnail_url,
        mime_type="image/svg+xml",
    )

    image = await materializer.materialize_candidate(candidate)

    assert image.content_type == "image/png"
    assert materializer._download.await_count == 2
    assert materializer._download.await_args_list[1] == call(thumbnail_url)


def test_image_download_user_agent_is_informative() -> None:
    assert ImageMaterializer.DOWNLOAD_USER_AGENT.startswith("WEAVE-CBT-Bot/")
    assert "weavecloudspace.com" in ImageMaterializer.DOWNLOAD_USER_AGENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/image.png",
        "http://localhost/image.png",
    ],
)
async def test_external_image_url_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(ImageDownloadError):
        await ImageMaterializer._validate_public_url(url)
