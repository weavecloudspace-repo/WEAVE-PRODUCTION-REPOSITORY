"""Only a validation value and idempotency key can be submitted by a CBT machine."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateDNSChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    # DNS-01 TXT values are base64url-encoded SHA-256 digests (43 characters).
    value: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")


class DNSChallengeResponse(BaseModel):
    id: UUID
    hostname: str
    fqdn: str
    status: str
    expires_at: datetime
    ttl: int = 300
