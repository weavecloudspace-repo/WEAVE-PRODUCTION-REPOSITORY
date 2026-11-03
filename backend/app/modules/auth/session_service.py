"""Persistent login sessions and rotating refresh-token families."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.security import (
    create_access_token,
    generate_refresh_token,
    generate_token_jti,
    hash_refresh_token,
)
from app.config.settings import settings
from app.config.logging import get_logger
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.modules.auth.models import AuthRefreshToken, AuthSession, AuthSessionActorType
from app.modules.auth.repository import (
    AuthRefreshTokenRepository,
    AuthSessionRepository,
)
from app.modules.auth.schemas import LoginSessionUser
from app.modules.parents.models import (
    ParentAccountStatus,
    ParentMembershipStatus,
)
from app.modules.parents.repository import (
    ParentAccountRepository,
    ParentMembershipRepository,
)
from app.modules.students.models import StudentAccountStatus
from app.modules.students.repository import StudentRepository
from app.modules.superadmin.platform_control_service import PlatformControlService
from app.modules.superadmin.repository import SuperAdminRepository
from app.modules.superadmin.security_alert_service import SecurityAlertService
from app.modules.superadmin.security_response_service import SecurityResponseService
from app.modules.teachers.models import TeacherAccountStatus, TeacherMembershipStatus
from app.modules.teachers.repository import (
    TeacherAccountRepository,
    TeacherMembershipRepository,
)
from app.modules.tenant_admins.models import TenantAdminStatus
from app.modules.tenant_admins.repository import TenantAdminRepository
from app.tenant_management.models import TenantStatus, TenantVerificationStatus
from app.tenant_management.repository import TenantRepository


logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class AuthenticatedActor:
    actor_type: str
    account_type: str
    actor_id: uuid.UUID
    email: str
    role: str | None = None
    tenant_id: uuid.UUID | None = None
    password_reset_required: bool | None = None
    user: LoginSessionUser | None = None


@dataclass
class AuthSessionTokenPair:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    session_jti: str
    refresh_token_expires_at: datetime


class AuthSessionService:
    """Issue, rotate, reconstruct, and revoke persistent sessions."""

    @staticmethod
    async def _announce_revocation(session: AuthSession) -> None:
        """Best-effort immediate invalidation; WebSockets also revalidate periodically."""
        try:
            from app.modules.realtime.publisher import RealtimePublisher

            await RealtimePublisher.to_actor(
                event_type="auth.session.revoked",
                actor_type=session.actor_type.value,
                actor_id=session.actor_id,
                tenant_id=session.tenant_id,
                data={"session_jti": session.session_jti},
            )
        except Exception:
            logger.exception("Failed to notify realtime clients of a revoked auth session.")

    @staticmethod
    def _session_lifetime(*, remember_me: bool) -> timedelta:
        return timedelta(
            days=(
                settings.REMEMBER_ME_SESSION_DAYS if remember_me else settings.DEFAULT_SESSION_DAYS
            )
        )

    @staticmethod
    def _claims_from_actor(actor: AuthenticatedActor) -> dict[str, str]:
        claims = {
            "sub": str(actor.actor_id),
            "email": actor.email,
            "actor_type": actor.actor_type,
            "account_type": actor.account_type,
            "role": actor.role or "",
        }
        if actor.tenant_id is not None:
            claims["tenant_id"] = str(actor.tenant_id)
        return claims

    @staticmethod
    async def create_login_session(
        db: AsyncSession,
        *,
        actor: AuthenticatedActor,
        user_agent: str | None = None,
        ip_address: str | None = None,
        remember_me: bool = False,
    ) -> AuthSessionTokenPair:
        try:
            actor_type = AuthSessionActorType(actor.actor_type)
        except ValueError as exc:
            raise BadRequestException("Unsupported authenticated actor type.") from exc

        now = _utc_now()
        expires_at = now + AuthSessionService._session_lifetime(remember_me=remember_me)
        session = AuthSession(
            tenant_id=actor.tenant_id,
            actor_type=actor_type,
            actor_id=actor.actor_id,
            session_jti=generate_token_jti(),
            user_agent=user_agent,
            ip_address=ip_address,
            remember_me=remember_me,
            last_used_at=now,
            expires_at=expires_at,
        )
        session = await AuthSessionRepository.create_session(db, session)

        raw_refresh_token = generate_refresh_token()
        refresh_token = AuthRefreshToken(
            session_id=session.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            token_jti=generate_token_jti(),
            issued_ip_address=ip_address,
            issued_user_agent=user_agent,
            expires_at=expires_at,
        )
        await AuthRefreshTokenRepository.create_refresh_token(db, refresh_token)
        access_token = create_access_token(
            AuthSessionService._claims_from_actor(actor),
            session_jti=session.session_jti,
        )
        await db.commit()
        return AuthSessionTokenPair(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            session_id=session.id,
            session_jti=session.session_jti,
            refresh_token_expires_at=expires_at,
        )

    @staticmethod
    async def _ensure_tenant_active(
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> None:
        tenant = await TenantRepository.get_by_id(db, tenant_id)
        if (
            tenant is None
            or tenant.is_deleted
            or tenant.verification_status != TenantVerificationStatus.ACTIVE
            or tenant.status not in {TenantStatus.ACTIVE, TenantStatus.TRIAL}
        ):
            raise UnauthorizedException("Tenant is not active.")

    @staticmethod
    async def _claims_from_session(
        db: AsyncSession,
        session: AuthSession,
    ) -> dict[str, str]:
        if session.actor_type == AuthSessionActorType.SUPERADMIN:
            actor = await SuperAdminRepository.get_by_id(db, session.actor_id)
            if actor is None or not actor.is_active:
                raise UnauthorizedException("Account is not active.")
            return {
                "sub": str(actor.id),
                "email": actor.email,
                "actor_type": AuthSessionActorType.SUPERADMIN.value,
                "account_type": AuthSessionActorType.SUPERADMIN.value,
                "role": "superadmin",
            }

        if session.actor_type == AuthSessionActorType.PARENT_ACCOUNT:
            account = await ParentAccountRepository.get_by_id(db, session.actor_id)
            if (
                account is None
                or not account.is_active
                or not account.is_verified
                or account.account_status != ParentAccountStatus.ACTIVE
            ):
                raise UnauthorizedException("Parent account is not active.")
            return {
                "sub": str(account.id),
                "email": account.email,
                "actor_type": AuthSessionActorType.PARENT_ACCOUNT.value,
                "account_type": AuthSessionActorType.PARENT_ACCOUNT.value,
                "role": "parent",
            }

        if session.actor_type == AuthSessionActorType.TEACHER_ACCOUNT:
            account = await TeacherAccountRepository.get_by_id(db, session.actor_id)
            if (
                account is None
                or not account.is_active
                or not account.is_verified
                or account.account_status != TeacherAccountStatus.ACTIVE
            ):
                raise UnauthorizedException("Teacher account is not active.")
            return {
                "sub": str(account.id),
                "email": account.email,
                "actor_type": AuthSessionActorType.TEACHER_ACCOUNT.value,
                "account_type": AuthSessionActorType.TEACHER_ACCOUNT.value,
                "role": "teacher",
            }

        if session.tenant_id is None:
            raise UnauthorizedException("Invalid tenant session.")
        await AuthSessionService._ensure_tenant_active(db, session.tenant_id)

        if session.actor_type == AuthSessionActorType.TENANT_ADMIN:
            admin = await TenantAdminRepository.get_by_id(db, session.actor_id)
            if (
                admin is None
                or admin.tenant_id != session.tenant_id
                or not admin.is_active
                or not admin.is_verified
                or admin.account_status != TenantAdminStatus.ACTIVE
            ):
                raise UnauthorizedException("Tenant administrator is not active.")
            return {
                "sub": str(admin.id),
                "email": admin.email,
                "actor_type": AuthSessionActorType.TENANT_ADMIN.value,
                "account_type": AuthSessionActorType.TENANT_ADMIN.value,
                "role": "admin",
                "tenant_id": str(admin.tenant_id),
            }

        if session.actor_type == AuthSessionActorType.PARENT:
            membership = await ParentMembershipRepository.get_by_id(
                db,
                session.actor_id,
                tenant_id=session.tenant_id,
                load_account=True,
            )
            if (
                membership is None
                or membership.status
                not in {
                    ParentMembershipStatus.ACTIVE,
                    ParentMembershipStatus.READ_ONLY,
                }
                or not membership.parent_account.is_active
                or not membership.parent_account.is_verified
                or membership.parent_account.account_status != ParentAccountStatus.ACTIVE
            ):
                raise UnauthorizedException("Parent membership is not active.")
            return {
                "sub": str(membership.id),
                "email": membership.parent_account.email,
                "actor_type": AuthSessionActorType.PARENT.value,
                "account_type": AuthSessionActorType.PARENT_ACCOUNT.value,
                "role": "parent",
                "tenant_id": str(membership.tenant_id),
            }

        if session.actor_type == AuthSessionActorType.TEACHER:
            membership = await TeacherMembershipRepository.get_by_id(
                db,
                session.actor_id,
                tenant_id=session.tenant_id,
                load_account=True,
            )
            if (
                membership is None
                or membership.status != TeacherMembershipStatus.ACTIVE
                or not membership.teacher_account.is_active
                or not membership.teacher_account.is_verified
                or membership.teacher_account.account_status != TeacherAccountStatus.ACTIVE
            ):
                raise UnauthorizedException("Teacher membership is not active.")
            return {
                "sub": str(membership.id),
                "email": membership.teacher_account.email,
                "actor_type": AuthSessionActorType.TEACHER.value,
                "account_type": AuthSessionActorType.TEACHER_ACCOUNT.value,
                "role": "teacher",
                "tenant_id": str(membership.tenant_id),
            }

        if session.actor_type == AuthSessionActorType.STUDENT:
            student = await StudentRepository.get_by_id(
                db,
                session.tenant_id,
                session.actor_id,
            )
            if student is not None:
                from app.modules.students.lifecycle_service import StudentLifecycleService

                await StudentLifecycleService.activate_due_return(db, student=student)
            if (
                student is None
                or not student.is_active
                or not student.is_verified
                or student.account_status != StudentAccountStatus.ACTIVE
                or student.is_archived
            ):
                raise UnauthorizedException("Student is not active.")
            return {
                "sub": str(student.id),
                "email": student.admission_number,
                "actor_type": AuthSessionActorType.STUDENT.value,
                "account_type": AuthSessionActorType.STUDENT.value,
                "role": "student",
                "tenant_id": str(student.tenant_id),
            }

        raise UnauthorizedException("Invalid session actor type.")

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession,
        *,
        background_tasks: BackgroundTasks,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthSessionTokenPair:
        now = _utc_now()
        stored_token = await AuthRefreshTokenRepository.get_by_hash(
            db,
            hash_refresh_token(refresh_token),
            lock=True,
        )
        if stored_token is None:
            raise UnauthorizedException("Invalid session.")
        session = await AuthSessionRepository.get_session_by_id(
            db,
            stored_token.session_id,
            lock=True,
        )
        if session is None:
            raise UnauthorizedException("Invalid session.")

        if stored_token.used_at is not None or stored_token.revoked_at is not None:
            await AuthRefreshTokenRepository.mark_reuse_detected(
                db,
                stored_token,
                detected_at=now,
            )
            await AuthSessionRepository.mark_session_compromised(
                db,
                session,
                background_tasks=background_tasks,
                compromised_at=now,
            )
            await AuthRefreshTokenRepository.revoke_tokens_for_session(
                db,
                session_id=session.id,
                revoked_at=now,
                reason="refresh_reuse_detected",
            )
            await db.commit()
            await AuthSessionService._announce_revocation(session)
            SecurityAlertService.notify_refresh_token_reuse(
                background_tasks=background_tasks,
                actor_type=session.actor_type.value,
                actor_id=session.actor_id,
                tenant_id=session.tenant_id,
                session_jti=session.session_jti,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise UnauthorizedException("Session expired. Please log in again.")

        if (
            _aware(stored_token.expires_at) <= now
            or _aware(session.expires_at) <= now
            or session.revoked_at is not None
            or session.compromised_at is not None
        ):
            raise UnauthorizedException("Session expired.")

        await SecurityResponseService.enforce_actor_ip_allowed(
            db=db,
            ip_address=ip_address,
            actor_type=session.actor_type,
        )
        await PlatformControlService.enforce_actor_allowed(
            db=db,
            actor_type=session.actor_type,
        )
        claims = await AuthSessionService._claims_from_session(db, session)

        raw_replacement = generate_refresh_token()
        replacement = AuthRefreshToken(
            session_id=session.id,
            token_hash=hash_refresh_token(raw_replacement),
            token_jti=generate_token_jti(),
            issued_ip_address=ip_address,
            issued_user_agent=user_agent,
            expires_at=session.expires_at,
        )
        replacement = await AuthRefreshTokenRepository.create_refresh_token(
            db,
            replacement,
        )
        await AuthRefreshTokenRepository.mark_used(
            db,
            stored_token,
            used_at=now,
            replaced_by_token_id=replacement.id,
        )
        await AuthSessionRepository.touch_session(db, session, last_used_at=now)
        access_token = create_access_token(claims, session_jti=session.session_jti)
        await db.commit()
        return AuthSessionTokenPair(
            access_token=access_token,
            refresh_token=raw_replacement,
            session_id=session.id,
            session_jti=session.session_jti,
            refresh_token_expires_at=session.expires_at,
        )

    @staticmethod
    async def logout_by_refresh_token(
        db: AsyncSession,
        *,
        refresh_token: str,
    ) -> None:
        stored_token = await AuthRefreshTokenRepository.get_by_hash(
            db,
            hash_refresh_token(refresh_token),
            lock=True,
        )
        if stored_token is None:
            return
        session = await AuthSessionRepository.get_session_by_id(
            db,
            stored_token.session_id,
            lock=True,
        )
        if session is None:
            return
        now = _utc_now()
        await AuthSessionRepository.revoke_session(
            db,
            session,
            revoked_at=now,
            reason="logout",
        )
        await AuthRefreshTokenRepository.revoke_tokens_for_session(
            db,
            session_id=session.id,
            revoked_at=now,
            reason="logout",
        )
        await db.commit()
        await AuthSessionService._announce_revocation(session)
