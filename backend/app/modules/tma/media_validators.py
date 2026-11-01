"""Validate TMA question/option images independently of profile media rules."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import BadRequestException

MAX_TMA_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TMA_IMAGE_EDGE = 4096
MAX_TMA_IMAGE_PIXELS = 16_000_000

MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSION_BY_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@dataclass(frozen=True, slots=True)
class ValidatedTMAImage:
    data: bytes
    content_type: str
    extension: str
    size_bytes: int
    checksum_sha256: str
    width_px: int
    height_px: int


async def validate_tma_image(file: UploadFile) -> ValidatedTMAImage:
    """Bound memory and pixel decoding; never trust client-supplied MIME."""
    raw = await file.read(MAX_TMA_IMAGE_BYTES + 1)
    if not raw:
        raise BadRequestException("TMA image cannot be empty.")
    if len(raw) > MAX_TMA_IMAGE_BYTES:
        raise BadRequestException("TMA image exceeds the 5 MB upload limit.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                image_format = image.format
                width, height = image.size
                frames = getattr(image, "n_frames", 1)
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_TMA_IMAGE_EDGE
                    or height > MAX_TMA_IMAGE_EDGE
                    or width * height > MAX_TMA_IMAGE_PIXELS
                ):
                    raise BadRequestException("TMA image dimensions exceed allowed limits.")
                if frames != 1:
                    raise BadRequestException("Animated images are not supported for TMA.")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except BadRequestException:
        raise
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError,
            UnidentifiedImageError) as exc:
        raise BadRequestException("Invalid or corrupt TMA image.") from exc

    mime = MIME_BY_FORMAT.get((image_format or "").upper())
    if mime is None:
        raise BadRequestException("TMA images must be JPEG, PNG or WebP.")
    extension = EXTENSION_BY_MIME[mime]
    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    if suffix and (("jpg" if suffix == "jpeg" else suffix) != extension):
        raise BadRequestException("TMA image extension does not match the actual image.")
    declared = (file.content_type or "").strip().lower()
    if declared and declared not in {mime, "application/octet-stream"}:
        raise BadRequestException("TMA image MIME type does not match the actual image.")

    return ValidatedTMAImage(
        data=raw,
        content_type=mime,
        extension=extension,
        size_bytes=len(raw),
        checksum_sha256=hashlib.sha256(raw).hexdigest(),
        width_px=width,
        height_px=height,
    )
