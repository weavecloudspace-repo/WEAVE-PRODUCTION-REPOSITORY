"""Validation tests for the independent TMA image upload pipeline."""

from __future__ import annotations

import hashlib
import io

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.core.exceptions import BadRequestException
from app.modules.tma.media_validators import (
    MAX_TMA_IMAGE_BYTES,
    validate_tma_image,
)


def _file(data: bytes, *, name: str = "figure.png", mime: str = "image/png") -> UploadFile:
    return UploadFile(
        filename=name,
        file=io.BytesIO(data),
        headers=Headers({"content-type": mime}),
    )


def _image(format_name: str, *, width: int = 64, height: int = 32) -> bytes:
    file = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 30, 10)).save(file, format=format_name)
    return file.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("format_name", "filename", "mime", "extension"),
    [
        ("PNG", "diagram.png", "image/png", "png"),
        ("JPEG", "diagram.jpeg", "image/jpeg", "jpg"),
        ("WEBP", "diagram.webp", "image/webp", "webp"),
    ],
)
async def test_accepts_real_images_and_hashes_original_bytes(
    format_name: str,
    filename: str,
    mime: str,
    extension: str,
) -> None:
    data = _image(format_name)
    actual = await validate_tma_image(_file(data, name=filename, mime=mime))
    assert actual.content_type == mime
    assert actual.extension == extension
    assert actual.data == data
    assert actual.size_bytes == len(data)
    assert actual.checksum_sha256 == hashlib.sha256(data).hexdigest()
    assert (actual.width_px, actual.height_px) == (64, 32)


@pytest.mark.asyncio
async def test_accepts_generic_octet_stream_but_uses_detected_mime() -> None:
    validated = await validate_tma_image(
        _file(_image("PNG"), name="diagram.png", mime="application/octet-stream")
    )
    assert validated.content_type == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "filename", "mime"),
    [
        (b"", "figure.png", "image/png"),
        (b"not an image", "figure.png", "image/png"),
        (_image("PNG"), "figure.jpg", "image/png"),
        (_image("PNG"), "figure.png", "image/jpeg"),
        (_image("PNG"), "figure.png.exe", "image/png"),
    ],
)
async def test_rejects_empty_corrupt_and_spoofed_images(
    data: bytes,
    filename: str,
    mime: str,
) -> None:
    with pytest.raises(BadRequestException):
        await validate_tma_image(_file(data, name=filename, mime=mime))


@pytest.mark.asyncio
async def test_rejects_oversized_file_without_reading_unbounded_input() -> None:
    with pytest.raises(BadRequestException, match="5 MB"):
        await validate_tma_image(_file(b"x" * (MAX_TMA_IMAGE_BYTES + 1)))


@pytest.mark.asyncio
async def test_rejects_oversized_pixel_dimensions() -> None:
    data = _image("PNG", width=4097, height=1)
    with pytest.raises(BadRequestException, match="dimensions"):
        await validate_tma_image(_file(data))


@pytest.mark.asyncio
async def test_rejects_animated_images() -> None:
    file = io.BytesIO()
    frames = [Image.new("RGB", (20, 20), color=(n * 50, 0, 0)) for n in (1, 2)]
    frames[0].save(file, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(BadRequestException):
        await validate_tma_image(_file(file.getvalue(), name="animated.gif", mime="image/gif"))


@pytest.mark.asyncio
async def test_rejects_truncated_image() -> None:
    with pytest.raises(BadRequestException):
        await validate_tma_image(_file(_image("PNG")[:-18]))
