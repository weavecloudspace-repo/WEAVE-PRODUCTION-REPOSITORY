"""Minimal, fail-closed Bunny DNS client. No secrets or provider error bodies in logs."""

from __future__ import annotations

import httpx


class BunnyDNSUnavailable(Exception):
    """A provider request failed or returned an unexpected response."""


class BunnyDNSClient:
    def __init__(
        self,
        *,
        api_key: str,
        zone_id: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or zone_id <= 0:
            raise ValueError("Bunny DNS credentials not configured")
        self._key = api_key
        self._zone_id = zone_id
        self._transport = transport

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url="https://api.bunny.net",
                timeout=httpx.Timeout(8.0),
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers={"AccessKey": self._key},
                    json=json,
                )
        except httpx.HTTPError:
            raise BunnyDNSUnavailable("Bunny DNS request unavailable") from None
        return response

    async def create_txt(self, *, name: str, value: str, request_id: str) -> int:
        response = await self._request(
            "PUT",
            f"/dnszone/{self._zone_id}/records",
            json={
                "Type": 3,
                "Ttl": 300,
                "Name": name,
                "Value": value,
                "Comment": f"weave-cbt-dns01:{request_id}",
            },
        )
        if response.status_code != 201:
            raise BunnyDNSUnavailable("Bunny DNS record creation failed")
        try:
            record_id = int(response.json()["Id"])
            if record_id <= 0:
                raise ValueError("invalid record ID")
        except (ValueError, TypeError, KeyError, AttributeError):
            raise BunnyDNSUnavailable("Bunny DNS returned an invalid record ID") from None
        return record_id

    async def delete_txt(self, *, record_id: int) -> None:
        response = await self._request(
            "DELETE",
            f"/dnszone/{self._zone_id}/records/{record_id}",
        )
        # The provider may have already removed the owned record.
        if response.status_code not in (200, 204, 404):
            raise BunnyDNSUnavailable("Bunny DNS record cleanup failed")
