"""Schemas for verified environment-specific WEAVE CBT installer releases."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class CBTReleasePackage(BaseModel):
    """Verified official package and published SHA-256 digest."""

    platform: Literal["windows", "linux"]
    kind: Literal["desktop", "cli"]
    asset: str = Field(min_length=1, max_length=255)
    url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CBTReleaseResponse(BaseModel):
    """Additive release metadata; legacy Windows installer fields stay intact."""

    channel: Literal["production", "staging"]
    manager_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    cbt_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    minimum_supported_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    image: str = Field(min_length=1, max_length=512)
    installer_asset: str = Field(min_length=1, max_length=255)
    installer_url: HttpUrl
    installer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_notes: str = Field(default="", max_length=4000)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    tag_name: str = Field(default="", max_length=100)
    release_url: HttpUrl | None = None
    checksums_url: HttpUrl | None = None
    packages: list[CBTReleasePackage] = Field(default_factory=list)
