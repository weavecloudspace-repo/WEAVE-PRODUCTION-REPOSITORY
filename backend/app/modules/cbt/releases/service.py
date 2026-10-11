"""Resolve official versioned WEAVE CBT releases for the current environment."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from time import monotonic
from urllib.parse import quote, urlparse

import httpx
from pydantic import ValidationError

from app.config.settings import EnvironmentType, settings
from app.modules.cbt.releases.schemas import CBTReleasePackage, CBTReleaseResponse

_RELEASE_REPOSITORY = "weavecloudspace-repo/WEAVE-CBT-PRODUCTION-REPOSITORY"
_RELEASE_API_URL = f"https://api.github.com/repos/{_RELEASE_REPOSITORY}/releases"
_RELEASE_BASE_URL = f"https://github.com/{_RELEASE_REPOSITORY}/releases/download"
_IMAGE_REPOSITORY = "ghcr.io/weavecloudspace-repo/weave-cbt-production-repository"
_IMAGE_REFERENCE_PATTERN = re.compile(
    rf"^{re.escape(_IMAGE_REPOSITORY)}@sha256:[0-9a-f]{{64}}$"
)
_RELEASE_TAGS = {
    "production": re.compile(r"^v1\.0\.\d+$"),
    "staging": re.compile(r"^staging-1\.0\.\d+$"),
}
_PACKAGE_NAMES = {
    "production": (
        ("windows", "desktop", "WEAVE-CBT-Desktop-Setup.exe"),
        ("windows", "cli", "WEAVE-CBT-Setup.exe"),
        ("linux", "desktop", "weave-cbt-desktop-production-linux-amd64.deb"),
        ("linux", "cli", "weave-cbt-production-linux-amd64.tar.gz"),
    ),
    "staging": (
        ("windows", "desktop", "WEAVE-CBT-Staging-Desktop-Setup.exe"),
        ("windows", "cli", "WEAVE-CBT-Staging-Setup.exe"),
        ("linux", "desktop", "weave-cbt-desktop-staging-linux-amd64.deb"),
        ("linux", "cli", "weave-cbt-staging-linux-amd64.tar.gz"),
    ),
}
_SHA256_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?([A-Za-z0-9._-]+)$")
_CACHE_TTL_SECONDS = 300.0


class CBTReleaseUnavailableError(RuntimeError):
    """Raised when the official installer metadata cannot be trusted."""


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    release: CBTReleaseResponse


class CBTReleaseService:
    """Read official public GitHub Releases; fail closed on incomplete artifacts."""

    _cache: dict[str, _CacheEntry] = {}
    _lock = asyncio.Lock()

    @staticmethod
    def channel_for_environment() -> str:
        if settings.ENV == EnvironmentType.PRODUCTION:
            return "production"
        return "staging"

    @classmethod
    async def get_latest(cls) -> CBTReleaseResponse:
        channel = cls.channel_for_environment()
        now = monotonic()
        cached = cls._cache.get(channel)
        if cached is not None and cached.expires_at > now:
            return cached.release

        async with cls._lock:
            now = monotonic()
            cached = cls._cache.get(channel)
            if cached is not None and cached.expires_at > now:
                return cached.release
            release = await cls._fetch_release(channel)
            cls._cache[channel] = _CacheEntry(
                expires_at=monotonic() + _CACHE_TTL_SECONDS, release=release
            )
            return release

    @classmethod
    async def _fetch_release(cls, channel: str) -> CBTReleaseResponse:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(12.0, connect=4.0),
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "WEAVE-API",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            ) as client:
                response = await client.get(_RELEASE_API_URL, params={"per_page": 100})
                response.raise_for_status()
                releases = response.json()
                selected = cls._select_release(channel, releases)
                tag = selected["tag_name"]
                checksums_url = cls._asset_url(tag, "SHA256SUMS")
                checksums_response = await client.get(checksums_url)
                checksums_response.raise_for_status()
                if len(checksums_response.content) > 65536:
                    raise CBTReleaseUnavailableError(
                        "The published WEAVE CBT checksum file is unexpectedly large."
                    )
                checksums = cls._parse_checksums(checksums_response.text)
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            raise CBTReleaseUnavailableError(
                "The official WEAVE CBT release could not be verified. Please try again shortly."
            ) from exc
        return cls._build_release(channel, selected, checksums)

    @staticmethod
    def _select_release(channel: str, releases: object) -> dict:
        if not isinstance(releases, list):
            raise CBTReleaseUnavailableError("GitHub returned invalid release metadata.")
        for release in releases:
            if not isinstance(release, dict):
                continue
            tag = release.get("tag_name")
            if (
                isinstance(tag, str)
                and _RELEASE_TAGS[channel].fullmatch(tag)
                and release.get("draft") is False
                and release.get("prerelease") is (channel == "staging")
            ):
                return release
        raise CBTReleaseUnavailableError(
            f"No verified {channel} WEAVE CBT installer release has been published."
        )

    @staticmethod
    def _asset_url(tag: str, filename: str) -> str:
        return f"{_RELEASE_BASE_URL}/{quote(tag, safe='')}/{quote(filename, safe='')}"

    @staticmethod
    def _parse_checksums(raw: str) -> dict[str, str]:
        checksums: dict[str, str] = {}
        for line in raw.splitlines():
            match = _SHA256_LINE.fullmatch(line.strip())
            if match is None:
                raise CBTReleaseUnavailableError("Invalid SHA256SUMS format.")
            digest, filename = match.groups()
            if filename in checksums:
                raise CBTReleaseUnavailableError("Duplicate installer checksum entry.")
            checksums[filename] = digest
        if not checksums:
            raise CBTReleaseUnavailableError("The installer checksum list is empty.")
        return checksums

    @classmethod
    def _build_release(
        cls, channel: str, metadata: dict, checksums: dict[str, str]
    ) -> CBTReleaseResponse:
        tag = metadata["tag_name"]
        names = _PACKAGE_NAMES[channel]
        expected_names = {name for _, _, name in names}
        assets = metadata.get("assets")
        if not isinstance(assets, list):
            raise CBTReleaseUnavailableError("The release asset list is missing.")
        published = {
            item.get("name"): item
            for item in assets
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if len(published) != len(assets) or not expected_names.issubset(published):
            raise CBTReleaseUnavailableError("Required platform installers are missing.")
        if "SHA256SUMS" not in published or not expected_names.issubset(checksums):
            raise CBTReleaseUnavailableError("The published release has missing checksums.")
        if set(checksums) != expected_names:
            raise CBTReleaseUnavailableError("The checksum manifest has unexpected entries.")

        for filename in expected_names | {"SHA256SUMS"}:
            asset = published[filename]
            if asset.get("state") != "uploaded" or asset.get("size", 0) <= 0:
                raise CBTReleaseUnavailableError("An official release asset is not ready.")
            if asset.get("browser_download_url") != cls._asset_url(tag, filename):
                raise CBTReleaseUnavailableError("A release asset URL failed validation.")

        body = metadata.get("body")
        if not isinstance(body, str):
            raise CBTReleaseUnavailableError("The pinned CBT image metadata is missing.")
        pinned = re.search(
            rf"\b(?:application|pinned application) image "
            rf"({re.escape(_IMAGE_REPOSITORY)}@sha256:[0-9a-f]{{64}})\b",
            body,
        )
        if pinned is None:
            raise CBTReleaseUnavailableError("The immutable CBT image is not identified.")
        image = pinned.group(1)
        source_commit = metadata.get("target_commitish")
        if not isinstance(source_commit, str) or not re.fullmatch(
            r"[0-9a-f]{40}", source_commit
        ):
            raise CBTReleaseUnavailableError("The release source commit is not pinned.")

        packages = [
            CBTReleasePackage(
                platform=platform,
                kind=kind,
                asset=filename,
                url=cls._asset_url(tag, filename),
                sha256=checksums[filename],
            )
            for platform, kind, filename in names
        ]
        desktop = packages[0]
        version = tag.removeprefix("staging-").removeprefix("v")
        try:
            release = CBTReleaseResponse(
                channel=channel,
                tag_name=tag,
                release_url=f"https://github.com/{_RELEASE_REPOSITORY}/releases/tag/{tag}",
                checksums_url=cls._asset_url(tag, "SHA256SUMS"),
                manager_version=version,
                cbt_version=version,
                minimum_supported_version=version,
                image=image,
                installer_asset=desktop.asset,
                installer_url=desktop.url,
                installer_sha256=desktop.sha256,
                packages=packages,
                release_notes=body[:4000],
                source_commit=source_commit,
            )
        except ValidationError as exc:
            raise CBTReleaseUnavailableError("The release metadata failed validation.") from exc
        cls._validate_release(channel=channel, tag=tag, release=release)
        return release

    @staticmethod
    def _validate_release(
        *, channel: str, tag: str, release: CBTReleaseResponse
    ) -> None:
        if release.channel != channel or not _RELEASE_TAGS[channel].fullmatch(tag):
            raise CBTReleaseUnavailableError(
                "The published WEAVE CBT installer does not match this environment."
            )
        if release.tag_name != tag:
            raise CBTReleaseUnavailableError("The release tag does not match.")
        if not _IMAGE_REFERENCE_PATTERN.fullmatch(release.image):
            raise CBTReleaseUnavailableError(
                "The WEAVE CBT release references an unexpected container image."
            )
        expected = {(p, k, n) for p, k, n in _PACKAGE_NAMES[channel]}
        observed = {(p.platform, p.kind, p.asset) for p in release.packages}
        if observed != expected:
            raise CBTReleaseUnavailableError("Installer platform assets do not match.")
        for package in release.packages:
            url = urlparse(str(package.url))
            if (
                url.scheme != "https"
                or url.netloc != "github.com"
                or url.query
                or url.fragment
                or url.path != f"/{_RELEASE_REPOSITORY}/releases/download/{tag}/{package.asset}"
            ):
                raise CBTReleaseUnavailableError("An installer URL failed channel validation.")
        desktop = release.packages[0]
        if (
            release.installer_asset != desktop.asset
            or str(release.installer_url) != str(desktop.url)
            or release.installer_sha256 != desktop.sha256
        ):
            raise CBTReleaseUnavailableError("The legacy installer fields do not match.")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear process-local release metadata cache (primarily for tests)."""
        cls._cache.clear()
