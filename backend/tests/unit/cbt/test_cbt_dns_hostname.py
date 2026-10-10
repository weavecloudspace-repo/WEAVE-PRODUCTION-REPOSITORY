"""Readable, stable CBT DNS hostnames and isolated environment suffixes."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.cbt.dns.hostname import (
    challenge_record_name,
    collision_label,
    hostname_for_server,
    hostname_prefix,
    school_label,
)
from app.modules.cbt.dns.schemas import CreateDNSChallengeRequest


def test_readable_hostname_and_production_env_alias() -> None:
    prefix = hostname_prefix(" Main CBT Server ")
    school = school_label("Greenfield-Lagos")
    staging = hostname_for_server(prefix=prefix, school_slug=school, environment="stg")
    prod = hostname_for_server(prefix=prefix, school_slug=school, environment="prod")
    assert staging == "main-cbt-server.greenfield-lagos.cbt-staging.weavecloudspace.com"
    assert prod == "main-cbt-server.greenfield-lagos.cbt.weavecloudspace.com"
    assert prod == hostname_for_server(
        prefix=prefix, school_slug=school, environment="production"
    )
    assert challenge_record_name(staging) == (
        "_acme-challenge.main-cbt-server.greenfield-lagos.cbt-staging"
    )


def test_server_label_collisions_use_short_suffix_only_when_needed() -> None:
    server_id = UUID("12345678-0000-4000-8000-000000000123")
    assert hostname_prefix("Main CBT Server", server_id) == "main-cbt-server"
    assert collision_label("Main CBT Server", server_id) == "main-cbt-server-12345678"


def test_dns_labels_are_bounded_and_normalized() -> None:
    assert hostname_prefix("Å server") == "a-server"
    assert school_label("Kings College!") == "kings-college"
    assert len(hostname_prefix("Å " + "@@@ long SERVER " * 100, uuid4())) <= 63


@pytest.mark.parametrize("label", ["bad.example.com", "-bad", "bad-"])
def test_reject_invalid_persisted_label(label: str) -> None:
    with pytest.raises(ValueError):
        hostname_for_server(prefix=label, school_slug="greenfield", environment="stg")


def test_unknown_env_fails_closed() -> None:
    with pytest.raises(ValueError):
        hostname_for_server(prefix="main", school_slug="greenfield", environment="unknown")


def test_challenge_payload_rejects_arbitrary_dns_records() -> None:
    with pytest.raises(ValidationError):
        CreateDNSChallengeRequest(
            request_id=uuid4(), value="not-a-dns01-digest", hostname="api.weavecloudspace.com"
        )


def test_challenge_payload_accepts_acme_sha256_base64url() -> None:
    payload = CreateDNSChallengeRequest(request_id=uuid4(), value="A" * 43)
    assert len(payload.value) == 43
