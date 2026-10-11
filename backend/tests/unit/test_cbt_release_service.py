"""Release catalogue validation against the actual WEAVE CBT versioned artifact contract."""

from types import SimpleNamespace

import pytest

from app.config.settings import EnvironmentType
from app.modules.cbt.releases.service import (
    CBTReleaseService,
    CBTReleaseUnavailableError,
    _PACKAGE_NAMES,
    _RELEASE_REPOSITORY,
)
import app.modules.cbt.releases.service as release_service_module


DIGEST = "a" * 64
COMMIT = "b" * 40
IMAGE = "ghcr.io/weavecloudspace-repo/weave-cbt-production-repository@sha256:" + DIGEST


def release_metadata(channel="staging"):
    tag = "staging-1.0.1512" if channel == "staging" else "v1.0.1512"
    assets = []
    for _, _, name in _PACKAGE_NAMES[channel]:
        assets.append(
            {
                "name": name,
                "state": "uploaded",
                "size": 1024,
                "browser_download_url": CBTReleaseService._asset_url(tag, name),
            }
        )
    assets.append(
        {
            "name": "SHA256SUMS",
            "state": "uploaded",
            "size": 512,
            "browser_download_url": CBTReleaseService._asset_url(tag, "SHA256SUMS"),
        }
    )
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": channel == "staging",
        "target_commitish": COMMIT,
        "body": f"GUI and CLI from commit {COMMIT}; application image {IMAGE}.",
        "assets": assets,
    }


def checksums(channel="staging"):
    return {name: DIGEST for _, _, name in _PACKAGE_NAMES[channel]}


@pytest.mark.parametrize("channel", ["staging", "production"])
def test_published_release_builds_four_packages(channel):
    metadata = release_metadata(channel)
    release = CBTReleaseService._build_release(channel, metadata, checksums(channel))
    assert release.channel == channel
    assert release.image == IMAGE
    assert release.source_commit == COMMIT
    assert release.installer_url == release.packages[0].url
    assert {(p.platform, p.kind) for p in release.packages} == {
        ("windows", "desktop"),
        ("windows", "cli"),
        ("linux", "desktop"),
        ("linux", "cli"),
    }
    assert release.release_url.host == "github.com"
    assert _RELEASE_REPOSITORY in str(release.release_url)


def test_release_channel_matches_weave_environment(monkeypatch):
    for env, expected in [
        (EnvironmentType.PRODUCTION, "production"),
        (EnvironmentType.STAGING, "staging"),
        (EnvironmentType.DEVELOPMENT, "staging"),
    ]:
        monkeypatch.setattr(
            release_service_module,
            "settings",
            SimpleNamespace(ENV=env),
        )
        assert CBTReleaseService.channel_for_environment() == expected


def test_wrong_repository_or_channel_asset_url_is_rejected():
    metadata = release_metadata()
    metadata["assets"][0]["browser_download_url"] = (
        "https://github.com/untrusted/repository/releases/download/"
        + metadata["tag_name"]
        + "/"
        + metadata["assets"][0]["name"]
    )
    with pytest.raises(CBTReleaseUnavailableError, match="URL"):
        CBTReleaseService._build_release("staging", metadata, checksums())


def test_incomplete_or_unuploaded_installers_are_rejected():
    metadata = release_metadata()
    metadata["assets"].pop()
    with pytest.raises(CBTReleaseUnavailableError, match="missing"):
        CBTReleaseService._build_release("staging", metadata, checksums())
    metadata = release_metadata()
    metadata["assets"][0]["state"] = "starter"
    with pytest.raises(CBTReleaseUnavailableError, match="not ready"):
        CBTReleaseService._build_release("staging", metadata, checksums())


def test_missing_or_extra_checksums_are_rejected():
    metadata = release_metadata()
    with pytest.raises(CBTReleaseUnavailableError, match="missing checksums"):
        CBTReleaseService._build_release("staging", metadata, {})
    invalid = checksums()
    invalid["rogue.exe"] = DIGEST
    with pytest.raises(CBTReleaseUnavailableError, match="unexpected entries"):
        CBTReleaseService._build_release("staging", metadata, invalid)


def test_wrong_image_digest_repository_or_source_commit_is_rejected():
    metadata = release_metadata()
    metadata["body"] = "application image ghcr.io/attacker/image@sha256:" + DIGEST
    with pytest.raises(CBTReleaseUnavailableError, match="image"):
        CBTReleaseService._build_release("staging", metadata, checksums())
    metadata = release_metadata()
    metadata["target_commitish"] = "staging"
    with pytest.raises(CBTReleaseUnavailableError, match="source commit"):
        CBTReleaseService._build_release("staging", metadata, checksums())


def test_channel_selection_skips_wrong_channel_drafts_and_previews():
    prod = release_metadata("production")
    staging = release_metadata("staging")
    draft = release_metadata("staging")
    draft["draft"] = True
    selected = CBTReleaseService._select_release("staging", [prod, draft, staging])
    assert selected is staging
    with pytest.raises(CBTReleaseUnavailableError, match="No verified"):
        CBTReleaseService._select_release("production", [staging, draft])


def test_checksum_parser_rejects_malformed_duplicate_and_empty_data():
    assert CBTReleaseService._parse_checksums(
        DIGEST + "  WEAVE-CBT-Staging-Desktop-Setup.exe\n"
    )["WEAVE-CBT-Staging-Desktop-Setup.exe"] == DIGEST
    for bad in (
        "",
        "not-a-checksum",
        DIGEST + "  ../traversal.exe",
        DIGEST + "  file.exe\n" + DIGEST + "  file.exe",
    ):
        with pytest.raises(CBTReleaseUnavailableError):
            CBTReleaseService._parse_checksums(bad)
