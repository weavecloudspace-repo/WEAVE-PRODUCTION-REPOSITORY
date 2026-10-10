# ==========================#
# cbt/pairing/schema.py
# ==========================#

"""
Schemas for pairing local CBT servers with Weave tenants.

Pairing is the bootstrap process that establishes trust between a local
CBT installation and a Weave tenant.

A tenant admin does not submit tenant or admin identifiers when requesting
a pairing code because those values are derived from the authenticated
tenant-admin session.

The local CBT server later exchanges the one-time pairing code for a
long-lived server identity and credential.
"""

from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.modules.cbt.enums import CBTServerStatus

CBT_SERVER_REVOKE_CONFIRMATION_LITERAL = "REVOKE SERVER"


class PairingCode(BaseModel):
    """
    Pairing challenge issued to an authenticated tenant admin.

    The raw pairing code is returned to the admin so it can be entered
    manually on the local CBT server.

    Weave must never persist the raw code. Only its cryptographic digest
    is stored together with its expiration and lifecycle metadata.
    """

    pairing_request_id: UUID
    pairing_code: str
    expires_at: datetime


class PairingRequest(BaseModel):
    """
    Request sent by a local CBT server when exchanging a pairing code
    for permanent machine credentials.

    The server supplies only installation-specific metadata and the
    pairing code.

    Tenant information is intentionally excluded from this request.
    Weave derives the tenant from the pairing-code record, preventing
    the local server from claiming or selecting an arbitrary tenant.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    pairing_code: str = Field(..., min_length=8, max_length=20)
    server_name: str = Field(..., min_length=2, max_length=150)
    client_version: str | None = Field(default=None, max_length=50)


class TenantInfo(BaseModel):
    """
    Minimal tenant identity returned to the local CBT server after
    successful pairing.

    This information allows the local installation to persist which
    Weave tenant it has been paired with.
    """

    id: UUID
    name: str


class PairingResult(BaseModel):
    """
    Result returned after a pairing code has been successfully exchanged.

    `server_id` is the persistent identifier assigned to the CBT
    installation by Weave.

    `server_credential` is the long-lived secret used by the local server
    to authenticate future requests to Weave. The raw credential is
    returned only during this pairing exchange; Weave stores only its
    cryptographic hash.

    The local CBT server must persist both the server identifier and
    credential securely because they establish its machine identity on
    subsequent requests.
    """

    server_id: UUID
    server_credential: str
    server_name: str
    hostname: str
    tenant: TenantInfo
    paired_at: datetime


class CBTServerResponse(BaseModel):
    """Tenant-admin view of one paired CBT server."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    hostname: str
    status: CBTServerStatus
    paired_at: datetime
    paired_by_admin_id: UUID | None
    client_version: str | None
    last_seen_at: datetime | None
    last_ip_address: str | None
    suspended_at: datetime | None
    revoked_at: datetime | None
    revoked_by_admin_id: UUID | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime


class CBTServerListResponse(BaseModel):
    """List response for tenant CBT servers."""

    items: list[CBTServerResponse]
    total: int


class CBTServerRevokeRequest(BaseModel):
    """Required, intentional revocation details for a CBT server."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=3, max_length=1000)
    confirmation_literal: str = Field(..., min_length=1, max_length=40)


class CBTServerCredentialRotationResponse(BaseModel):
    """One-time raw credential returned after rotation."""

    server_id: UUID
    server_credential: str
    rotated_at: datetime


class PairingStatusRequest(BaseModel):
    """Identify the exact pairing challenge being monitored by the admin UI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    pairing_code: str = Field(..., min_length=8, max_length=20)


class PairingStatusResponse(BaseModel):
    """Current lifecycle state of one tenant-owned pairing challenge."""

    status: Literal["pending", "paired", "expired", "invalidated"]
    expires_at: datetime
    server_id: UUID | None = None
