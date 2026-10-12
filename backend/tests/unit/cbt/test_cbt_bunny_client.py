"""Transport-level tests: only our intended TXT name and record ID are modified."""

import httpx
import pytest

from app.modules.cbt.dns.bunny import BunnyDNSClient, BunnyDNSUnavailable


@pytest.mark.asyncio
async def test_bunny_uses_put_txt_record_with_exact_authorization() -> None:
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"Domain": "weavecloudspace.com"})
        return httpx.Response(201, json={"Id": 31415})

    client = BunnyDNSClient(
        api_key="not-a-real-key", zone_id=1234, transport=httpx.MockTransport(handle)
    )
    record_id = await client.create_txt(
        name="_acme-challenge.node.school-abc.cbt-staging",
        value="A" * 43,
        request_id="debug-request",
    )
    assert record_id == 31415
    assert seen[1].method == "PUT"
    assert seen[1].url.path == "/dnszone/1234/records"
    assert seen[1].headers["AccessKey"] == "not-a-real-key"
    assert b'"Type":3' in seen[1].content
    assert b'"Name":"_acme-challenge.node.school-abc.cbt-staging"' in seen[1].content


@pytest.mark.asyncio
async def test_bunny_delete_uses_only_owned_record_id() -> None:
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"Domain": "weavecloudspace.com"})
        return httpx.Response(204)

    client = BunnyDNSClient(api_key="fake", zone_id=1234, transport=httpx.MockTransport(handle))
    await client.delete_txt(record_id=31415)
    assert seen[1].method == "DELETE"
    assert seen[1].url.path == "/dnszone/1234/records/31415"


@pytest.mark.asyncio
async def test_bunny_failure_hides_provider_body() -> None:
    client = BunnyDNSClient(
        api_key="fake",
        zone_id=1234,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="PRIVATE PROVIDER DATA")
        ),
    )
    with pytest.raises(BunnyDNSUnavailable) as exc:
        await client.create_txt(name="_acme-challenge.foo", value="A" * 43, request_id="x")
    assert "PRIVATE PROVIDER DATA" not in str(exc.value)


@pytest.mark.asyncio
async def test_wrong_zone_is_rejected_before_record_creation() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"Domain": "some-other-domain.example"})

    client = BunnyDNSClient(api_key="fake", zone_id=1234, transport=httpx.MockTransport(handle))
    with pytest.raises(BunnyDNSUnavailable):
        await client.create_txt(name="_acme-challenge.foo", value="A" * 43, request_id="x")
    assert len(calls) == 1
    assert calls[0].method == "GET"
