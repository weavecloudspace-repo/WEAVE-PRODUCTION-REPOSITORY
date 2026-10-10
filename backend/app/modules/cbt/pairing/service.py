# ==========================#
# cbt/pairing/service
# ==========================#

"""
Business logic for pairing local CBT servers with Weave tenants
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)

from app.modules.cbt.models import CBTPairingCode, CBTServer, CBTServerCredential
from app.modules.cbt.dns.hostname import collision_label, hostname_prefix, school_label

from app.modules.cbt.enums import CBTServerStatus
from app.modules.cbt.pairing.schemas import (
    CBT_SERVER_REVOKE_CONFIRMATION_LITERAL,
    CBTServerCredentialRotationResponse,
    CBTServerListResponse,
    CBTServerResponse,
    PairingCode,
    PairingRequest,
    PairingResult,
    PairingStatusResponse,
    TenantInfo,
)

from app.modules.cbt.pairing.repository import (
    CBTPairingCodeRepository,
    CBTServerRepository,
    CBTServerCredentialRepository,
)
from app.modules.cbt.security import (
    generate_pairing_code,
    hash_pairing_code,
    hash_server_token,
    generate_server_token,
)
from app.modules.realtime.publisher import RealtimePublisher


from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import FeatureCode, ResourceLimitCode
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.models import Tenant, TenantStatus, TenantVerificationStatus
from app.tenant_management.repository import TenantRepository

PAIRING_CODE_TTL_MINUTES = 10


class CBTPairingService:
    """Coordinate the lifecycle of CBT server pairing"""

    @staticmethod
    def normalize_server_name(name: str) -> str:
        """Trim and collapse server-name whitespace without changing casing."""

        normalized = re.sub(r"\s+", " ", name.strip())
        if not normalized:
            raise BadRequestException(detail="CBT server name cannot be blank.")
        return normalized

    @staticmethod
    def _ensure_admin_has_tenant(admin: TenantAdmin) -> UUID:
        """Return the current admin tenant ID or raise if unattached."""

        if admin.tenant_id is None:
            raise ForbiddenException(detail="Tenant admin is not attached to a tenant")

        return admin.tenant_id

    @staticmethod
    async def _get_server_for_admin(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
        lock: bool = False,
    ) -> CBTServer:
        """Return one CBT server scoped to the current tenant admin."""

        tenant_id = CBTPairingService._ensure_admin_has_tenant(admin)
        server = await CBTServerRepository.get_by_tenant_and_id(
            db,
            tenant_id=tenant_id,
            server_id=server_id,
            lock=lock,
        )

        if server is None:
            raise NotFoundException(detail="CBT server not found.")

        return server

    @staticmethod
    def _ensure_not_revoked(server: CBTServer) -> None:
        """Reject state transitions that cannot operate on revoked servers."""

        if server.status == CBTServerStatus.REVOKED:
            raise BadRequestException(detail="Revoked CBT servers cannot be modified.")

    @staticmethod
    def _validate_revocation_request(*, reason: str, confirmation_literal: str) -> str:
        """Reject accidental or incomplete server revocation requests."""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BadRequestException(detail="A revocation reason is required.")
        if confirmation_literal != CBT_SERVER_REVOKE_CONFIRMATION_LITERAL:
            raise BadRequestException(
                detail=f"Type {CBT_SERVER_REVOKE_CONFIRMATION_LITERAL} to revoke this CBT server.",
            )
        return normalized_reason

    @staticmethod
    async def _get_pairable_tenant(db: AsyncSession, *, tenant_id, lock: bool = False) -> Tenant:
        """
        Return a tenant that is currently allowed to pair a CBT server

        Pairing is restricted to verified , non-deleted tenants whose
        lifecycle status currently permits normal platform access
        """

        tenant = await TenantRepository.get_by_id(db, tenant_id=tenant_id, lock=lock)

        if tenant is None:
            raise ForbiddenException(detail="Tenant is not eligible for CBT server pairing")

        if tenant.verification_status != TenantVerificationStatus.ACTIVE:
            raise ForbiddenException(detail="Tenant is not eligible for CBT server pairing")

        if tenant.status not in {TenantStatus.ACTIVE, TenantStatus.TRIAL}:
            raise ForbiddenException(detail="Tenant is not eligible for CBT server pairing")

        return tenant

    @staticmethod
    async def _ensure_server_name_available(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        normalized_name: str,
    ) -> None:
        """Reject duplicate normalized server names within one tenant."""

        existing = await CBTServerRepository.get_by_tenant_and_normalized_name(
            db,
            tenant_id=tenant_id,
            normalized_name=normalized_name,
            lock=True,
        )
        if existing is not None:
            raise ConflictException(
                detail="A CBT server with this name already exists for this tenant.",
            )

    @staticmethod
    async def _ensure_cbt_pairing_allowed(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        increment: int = 1,
    ) -> None:
        """Ensure the tenant plan includes CBT pairing and available server capacity."""

        await SubscriptionFeatureService.ensure_feature_enabled(
            db,
            tenant_id,
            FeatureCode.CBT_PAIRING,
        )
        await SubscriptionFeatureService.ensure_resource_limit_available(
            db,
            tenant_id,
            ResourceLimitCode.CBT_SERVERS,
            increment=increment,
        )

    @staticmethod
    async def create_pairing_code(db: AsyncSession, *, admin: TenantAdmin) -> PairingCode:
        """
        Generate a new short-lived pairing code for a tenant


        The tenant is derived exclusively from the authenticated tenant administrator
        Any previously unused pairing code for the same tenant is invalidated before
        the new code is created


        Only the cryptographic digest of the pairing code is persisted
        The raw code is returned to the administrator once
        """

        now = datetime.now(timezone.utc)
        tenant_id = CBTPairingService._ensure_admin_has_tenant(admin)

        await CBTPairingService._get_pairable_tenant(db, tenant_id=tenant_id, lock=True)
        await CBTPairingService._ensure_cbt_pairing_allowed(db, tenant_id=tenant_id)
        await CBTPairingCodeRepository.invalidate_unused_for_tenant(
            db, tenant_id=tenant_id, invalidated_at=now
        )

        raw_code = generate_pairing_code()
        code_hash = hash_pairing_code(raw_code)

        expires_at = now + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)

        pairing_record = CBTPairingCode(
            tenant_id=tenant_id,
            code_hash=code_hash,
            created_by_admin_id=admin.id,
            expires_at=expires_at,
        )

        await CBTPairingCodeRepository.create(db, pairing_record)

        return PairingCode(
            pairing_request_id=pairing_record.id,
            pairing_code=raw_code,
            expires_at=expires_at,
        )

    @staticmethod
    def _ensure_pairing_code_usable(pairing_code: CBTPairingCode, *, now: datetime):
        """
        Ensure a pairing code can still be exchanged

        All unusable pairing-code states intentionally produce the same
        external error so callers cannot determine whether a code existed,
        expired, was already used , or was invalidated
        """

        if pairing_code.used_at is not None:
            raise UnauthorizedException(detail="Invalid or expired pairing code")

        if pairing_code.invalidated_at is not None:
            raise UnauthorizedException(detail="Invalid or expired pairing code")

        if pairing_code.expires_at <= now:
            raise UnauthorizedException(detail="Invalid or expired pairing code")

    @staticmethod
    async def pair_server(db: AsyncSession, *, payload: PairingRequest) -> PairingResult:
        """
        Exchange a valid one-time pairing code for CBT server credentials

        The tenant is derived exclusively from the stored pairing-code
        record. The local CBT server cannot select or claim a tenant

        On success, a CBT server identity and high-entropy server credential
        are issued. Only the credential hash is persisted by Weave; the raw
        credential is returned to the local server once
        """

        now = datetime.now(timezone.utc)

        try:
            code_hash = hash_pairing_code(payload.pairing_code)

        except ValueError as exc:
            raise UnauthorizedException(detail="Invalid or expired pairing code") from exc

        candidate = await CBTPairingCodeRepository.get_by_hash(db, code_hash)

        if candidate is None:
            raise UnauthorizedException(detail="Invalid or expired pairing code")

        try:
            tenant = await CBTPairingService._get_pairable_tenant(
                db, tenant_id=candidate.tenant_id, lock=True
            )

        except ForbiddenException as exc:
            raise UnauthorizedException(detail="Invalid or expired pairing code") from exc

        pairing_code = await CBTPairingCodeRepository.get_by_hash(db, code_hash, lock=True)

        if pairing_code is None:
            raise UnauthorizedException(detail="Invalid or expired pairing code")

        CBTPairingService._ensure_pairing_code_usable(pairing_code, now=now)
        await CBTPairingService._ensure_cbt_pairing_allowed(
            db,
            tenant_id=pairing_code.tenant_id,
        )
        normalized_server_name = CBTPairingService.normalize_server_name(payload.server_name)
        await CBTPairingService._ensure_server_name_available(
            db,
            tenant_id=pairing_code.tenant_id,
            normalized_name=normalized_server_name,
        )

        server_id = uuid4()
        # Freeze the school's DNS namespace on first pairing, even if its
        # display name or tenant slug changes later.
        dns_school_slug = await CBTServerRepository.get_school_dns_slug(
            db, tenant_id=pairing_code.tenant_id
        )
        if dns_school_slug is None:
            dns_school_slug = school_label(tenant.slug)
            if await CBTServerRepository.dns_school_slug_owned_by_other(
                db, school_slug=dns_school_slug, tenant_id=pairing_code.tenant_id
            ):
                dns_school_slug = f"{school_label(tenant.slug)[:54].strip('-')}-{tenant.id.hex[:8]}"
        dns_prefix = hostname_prefix(normalized_server_name)
        if await CBTServerRepository.dns_name_exists(
            db, school_slug=dns_school_slug, server_label=dns_prefix
        ):
            dns_prefix = collision_label(normalized_server_name, server_id)
        server_record = CBTServer(
            id=server_id,
            tenant_id=pairing_code.tenant_id,
            name=normalized_server_name,
            hostname_prefix=dns_prefix,
            dns_school_slug=dns_school_slug,
            paired_at=now,
            paired_by_admin_id=pairing_code.created_by_admin_id,
            client_version=payload.client_version,
        )

        server = await CBTServerRepository.create(db, server_record)

        raw_server_credential = generate_server_token()

        credential = CBTServerCredential(
            server_id=server.id, credential_hash=hash_server_token(raw_server_credential)
        )
        await CBTServerCredentialRepository.create(db, credential)

        await CBTPairingCodeRepository.consume(db, pairing_code, used_at=now, server_id=server.id)

        if pairing_code.created_by_admin_id is not None:
            RealtimePublisher.defer_to_actor(
                db,
                event_type="cbt.pairing.completed",
                actor_type="tenant_admin",
                actor_id=pairing_code.created_by_admin_id,
                tenant_id=pairing_code.tenant_id,
                data={
                    "pairing_request_id": str(pairing_code.id),
                    "server_id": str(server.id),
                    "server_name": server.name,
                },
            )

        return PairingResult(
            server_id=server.id,
            server_credential=raw_server_credential,
            server_name=server.name,
            hostname=server.hostname,
            tenant=TenantInfo(id=tenant.id, name=tenant.school_name),
            paired_at=server.paired_at,
        )

    @staticmethod
    async def list_servers(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
    ) -> CBTServerListResponse:
        """List all CBT servers that belong to the current tenant."""

        tenant_id = CBTPairingService._ensure_admin_has_tenant(admin)
        await SubscriptionFeatureService.ensure_feature_enabled(
            db,
            tenant_id,
            FeatureCode.CBT_PAIRING,
        )
        servers = await CBTServerRepository.list_for_tenant(db, tenant_id)
        items = [CBTServerResponse.model_validate(server) for server in servers]
        return CBTServerListResponse(items=items, total=len(items))

    @staticmethod
    async def get_server(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
    ) -> CBTServerResponse:
        """Return one CBT server belonging to the current tenant."""

        server = await CBTPairingService._get_server_for_admin(
            db,
            admin=admin,
            server_id=server_id,
        )
        return CBTServerResponse.model_validate(server)

    @staticmethod
    async def suspend_server(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
    ) -> CBTServerResponse:
        """Suspend a paired CBT server."""

        now = datetime.now(timezone.utc)
        server = await CBTPairingService._get_server_for_admin(
            db,
            admin=admin,
            server_id=server_id,
            lock=True,
        )
        CBTPairingService._ensure_not_revoked(server)

        if server.status == CBTServerStatus.SUSPENDED:
            return CBTServerResponse.model_validate(server)

        await CBTServerRepository.suspend(db, server, suspended_at=now)
        return CBTServerResponse.model_validate(server)

    @staticmethod
    async def reactivate_server(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
    ) -> CBTServerResponse:
        """Reactivate a suspended CBT server."""

        server = await CBTPairingService._get_server_for_admin(
            db,
            admin=admin,
            server_id=server_id,
            lock=True,
        )
        CBTPairingService._ensure_not_revoked(server)

        if server.status == CBTServerStatus.ACTIVE:
            return CBTServerResponse.model_validate(server)

        await CBTServerRepository.reactivate(db, server)
        return CBTServerResponse.model_validate(server)

    @staticmethod
    async def revoke_server(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
        reason: str,
        confirmation_literal: str,
    ) -> CBTServerResponse:
        """Revoke a CBT server and invalidate any active credential."""

        now = datetime.now(timezone.utc)
        normalized_reason = CBTPairingService._validate_revocation_request(
            reason=reason,
            confirmation_literal=confirmation_literal,
        )
        server = await CBTPairingService._get_server_for_admin(
            db,
            admin=admin,
            server_id=server_id,
            lock=True,
        )

        if server.status == CBTServerStatus.REVOKED:
            return CBTServerResponse.model_validate(server)

        await CBTServerCredentialRepository.revoke_active_for_server(
            db,
            tenant_id=server.tenant_id,
            server_id=server.id,
            revoked_at=now,
            reason="Server revoked by tenant administrator.",
        )
        await CBTServerRepository.revoke(
            db,
            server,
            revoked_at=now,
            revoked_by_admin_id=admin.id,
            reason=normalized_reason,
        )
        return CBTServerResponse.model_validate(server)

    @staticmethod
    async def rotate_server_credential(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        server_id: UUID,
    ) -> CBTServerCredentialRotationResponse:
        """Rotate and return a new one-time CBT server credential."""

        now = datetime.now(timezone.utc)
        server = await CBTPairingService._get_server_for_admin(
            db,
            admin=admin,
            server_id=server_id,
            lock=True,
        )
        CBTPairingService._ensure_not_revoked(server)

        await CBTServerCredentialRepository.revoke_active_for_server(
            db,
            tenant_id=server.tenant_id,
            server_id=server.id,
            revoked_at=now,
            reason="Credential rotated by tenant administrator.",
        )

        raw_server_credential = generate_server_token()
        credential = CBTServerCredential(
            server_id=server.id,
            credential_hash=hash_server_token(raw_server_credential),
        )
        await CBTServerCredentialRepository.create(db, credential)

        return CBTServerCredentialRotationResponse(
            server_id=server.id,
            server_credential=raw_server_credential,
            rotated_at=now,
        )


class CBTPairingStatusService:
    """Resolve the status of the exact pairing code displayed to an admin."""

    @staticmethod
    async def get_status(
        db: AsyncSession,
        *,
        admin: TenantAdmin,
        pairing_code: str,
    ) -> PairingStatusResponse:
        tenant_id = admin.tenant_id
        if tenant_id is None:
            raise NotFoundException(detail="Pairing code not found.")

        try:
            code_hash = hash_pairing_code(pairing_code)
        except ValueError as exc:
            raise NotFoundException(detail="Pairing code not found.") from exc

        record = await CBTPairingCodeRepository.get_by_hash(db, code_hash)
        if record is None or record.tenant_id != tenant_id:
            raise NotFoundException(detail="Pairing code not found.")

        if record.used_at is not None:
            status = "paired"
        elif record.invalidated_at is not None:
            status = "invalidated"
        elif record.expires_at <= datetime.now(timezone.utc):
            status = "expired"
        else:
            status = "pending"

        return PairingStatusResponse(
            status=status,
            expires_at=record.expires_at,
            server_id=record.used_by_server_id if status == "paired" else None,
        )
