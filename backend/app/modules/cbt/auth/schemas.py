# ==========================#
# cbt/auth/schemas.py
# ==========================#

"""Schema definitions for CBT machine and staff authentication."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.cbt.enums import CBTServerStatus


class AuthenticatedCBTServer(BaseModel):
    """Trusted machine context produced after machine credential authentication.

    ``credential_id`` deliberately travels with the socket/session context so long-lived
    transports can prove that the *same* credential which opened the connection is still
    authorized after server revocation or credential rotation.
    """

    model_config = ConfigDict(frozen=True)

    server_id: UUID
    credential_id: UUID
    tenant_id: UUID
    server_name: str
    status: CBTServerStatus


class CBTServerHostnameResponse(BaseModel):
    """Public DNS hostname belonging to the authenticated CBT machine."""

    model_config = ConfigDict(frozen=True)

    server_id: UUID
    hostname: str


class CBTStaffLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class CBTStaffIdentity(BaseModel):
    """Trusted staff identity resolved from a successful Weave authentication."""

    model_config = ConfigDict(frozen=True)

    actor_id: UUID
    membership_id: UUID | None = None
    tenant_id: UUID
    role: Literal["admin", "teacher"]
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None


class CBTActorTokenPair(BaseModel):
    """Opaque cloud credentials attached to one local CBT staff session."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class CBTStaffAuthResponse(CBTStaffIdentity):
    """Staff identity plus the cloud actor credentials issued for this login."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class CBTActorRefreshRequest(BaseModel):
    """Payload required to rotate one CBT actor cloud authorization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    refresh_token: str = Field(..., min_length=32, max_length=512)


class AuthenticatedCBTActor(BaseModel):
    """Trusted human-actor context produced from an opaque CBT actor access token."""

    model_config = ConfigDict(frozen=True)

    authorization_id: UUID
    tenant_id: UUID
    actor_id: UUID
    membership_id: UUID | None = None
    role: Literal["admin", "teacher"]
