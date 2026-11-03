# ====================================== #
#   modules/realtime/authentication.py   #
# ====================================== #

"""Authentication contracts for realtime WebSocket connections."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID


from app.modules.parents.models import Parent, ParentAccount
from app.modules.students.models import Student
from app.modules.superadmin.models import SuperAdmin
from app.modules.teachers.models import Teacher, TeacherAccount
from app.modules.tenant_admins.models import TenantAdmin

from datetime import datetime, timezone

from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.dependencies.route_guards import (
    get_current_actor,
    get_current_parent,
    get_current_parent_account,
    get_current_student,
    get_current_superadmin,
    get_current_teacher,
    get_current_teacher_account,
    get_current_tenant_admin,
)
from app.core.exceptions import UnauthorizedException
from app.modules.auth.repository import AuthSessionRepository


@dataclass(frozen=True)
class RealtimeIdentity:
    """
    Authenticated identity attached to one realtime connection.
    """

    actor_type: str
    actor_id: UUID
    tenant_id: UUID | None
    token_expires_at: datetime
    session_jti: str | None = None


def build_realtime_identity(
    actor,
    *,
    token_expires_at: datetime,
) -> RealtimeIdentity:
    """
    Convert an authenticated Weave actor into
    a realtime connection identity.
    """

    if isinstance(actor, SuperAdmin):
        return RealtimeIdentity(
            actor_type="superadmin",
            actor_id=actor.id,
            tenant_id=None,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, TenantAdmin):
        return RealtimeIdentity(
            actor_type="tenant_admin",
            actor_id=actor.id,
            tenant_id=actor.tenant_id,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, Teacher):
        return RealtimeIdentity(
            actor_type="teacher",
            actor_id=actor.id,
            tenant_id=actor.tenant_id,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, Parent):
        return RealtimeIdentity(
            actor_type="parent",
            actor_id=actor.id,
            tenant_id=actor.tenant_id,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, Student):
        return RealtimeIdentity(
            actor_type="student",
            actor_id=actor.id,
            tenant_id=actor.tenant_id,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, TeacherAccount):
        return RealtimeIdentity(
            actor_type="teacher_account",
            actor_id=actor.id,
            tenant_id=None,
            token_expires_at=token_expires_at,
        )

    if isinstance(actor, ParentAccount):
        return RealtimeIdentity(
            actor_type="parent_account",
            actor_id=actor.id,
            tenant_id=None,
            token_expires_at=token_expires_at,
        )

    raise ValueError(f"Unsupported realtime actor: {type(actor).__name__}")


async def authenticate_realtime_access_token(
    db: AsyncSession,
    *,
    access_token: str,
) -> RealtimeIdentity:
    """
    Authenticate a WebSocket access token using Weave's
    existing HTTP authentication/session infrastructure.
    """

    actor = await get_current_actor(
        access_token,
        db,
    )

    # Apply the same active-account and tenant checks
    # used by protected HTTP routes.
    if isinstance(actor, SuperAdmin):
        actor = await get_current_superadmin(actor)

    elif isinstance(actor, TenantAdmin):
        actor = await get_current_tenant_admin(
            actor,
            db,
        )

    elif isinstance(actor, Teacher):
        actor = await get_current_teacher(
            actor,
            db,
        )

    elif isinstance(actor, Parent):
        actor = await get_current_parent(
            actor,
            db,
        )

    elif isinstance(actor, Student):
        actor = await get_current_student(
            actor,
            db,
        )

    elif isinstance(actor, TeacherAccount):
        actor = await get_current_teacher_account(
            actor,
        )

    elif isinstance(actor, ParentAccount):
        actor = await get_current_parent_account(
            actor,
        )

    else:
        raise UnauthorizedException("Unsupported realtime identity.")

    payload = jwt.decode(
        access_token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    expires_at = payload.get("exp")

    if expires_at is None:
        raise UnauthorizedException("Access token is missing an expiration.")

    token_expires_at = datetime.fromtimestamp(
        expires_at,
        tz=timezone.utc,
    )

    return replace(
        build_realtime_identity(actor, token_expires_at=token_expires_at),
        session_jti=payload.get("sid"),
    )


async def validate_realtime_session(db: AsyncSession, *, identity: RealtimeIdentity) -> None:
    """Cheap periodic revocation check; full actor checks occur on auth/refresh."""
    if not identity.session_jti:
        raise UnauthorizedException("Realtime session has no persistent session identifier.")
    session = await AuthSessionRepository.get_session_by_jti(db, identity.session_jti)
    if session is None:
        raise UnauthorizedException("Realtime session is no longer valid.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        session.revoked_at is not None
        or session.compromised_at is not None
        or expires_at <= datetime.now(timezone.utc)
        or session.actor_id != identity.actor_id
        or session.actor_type.value != identity.actor_type
        or session.tenant_id != identity.tenant_id
    ):
        raise UnauthorizedException("Realtime session is no longer valid.")
