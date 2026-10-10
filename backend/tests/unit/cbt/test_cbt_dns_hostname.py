"""Immutable school identity and server-name-based CBT hostname semantics."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.cbt.dns.hostname import (
    challenge_record_name,
    hostname_for_server,
    hostname_prefix,
)
from app.modules.cbt.dns.schemas import CreateDNSChallengeRequest


def test_staging_and_production_hostname_are_isolated() -> None:
    server_id = UUID("00000000-0000-4000-8000-000000000123")
    tenant_id = UUID("00000000-0000-4000-8000-000000000456")
    prefix = hostname_prefix(" Main CBT Server ", server_id)

    assert prefix == "main-cbt-server-000000000000"
    staging = hostname_for_server(prefix=prefix, tenant_id=tenant_id, environment="staging")
    production = hostname_for_server(prefix=prefix, tenant_id=tenant_id, environment="production")
    assert staging == (
        "main-cbt-server-000000000000.school-00000000000040008000000000000456."
        "cbt-staging.weavecloudspace.com"
    )
    assert production.endswith(".cbt.weavecloudspace.com")
    assert production != staging
    assert challenge_record_name(staging) == (
        "_acme-challenge.main-cbt-server-000000000000."
        "school-00000000000040008000000000000456.cbt-staging"
    )


def test_same_server_name_in_different_schools_cannot_collide() -> None:
    prefix = hostname_prefix("Computer Lab", uuid4())
    assert hostname_for_server(
        prefix=prefix, tenant_id=uuid4(), environment="staging"
    ) != hostname_for_server(prefix=prefix, tenant_id=uuid4(), environment="staging")


def test_dns_labels_are_bounded_and_punctuation_is_normalized() -> None:
    prefix = hostname_prefix("Å " + "@@@ long SERVER " * 100, uuid4())
    assert len(prefix) <= 63
    assert prefix.startswith("a-long-server")
    assert all(c.islower() or c.isdigit() or c == "-" for c in prefix)


@pytest.mark.parametrize("name", ["bad.example.com", "-bad", "bad-"])
def test_reject_invalid_persisted_label(name: str) -> None:
    with pytest.raises(ValueError):
        hostname_for_server(prefix=name, tenant_id=uuid4(), environment="staging")


def test_challenge_payload_rejects_unexpected_dns_record_or_value() -> None:
    with pytest.raises(ValidationError):
        CreateDNSChallengeRequest(
            request_id=uuid4(),
            value="not-a-dns01-digest",
            hostname="api.weavecloudspace.com",
        )


def test_challenge_payload_accepts_acme_sha256_base64url() -> None:
    payload = CreateDNSChallengeRequest(request_id=uuid4(), value="A" * 43)
    assert len(payload.value) == 43
