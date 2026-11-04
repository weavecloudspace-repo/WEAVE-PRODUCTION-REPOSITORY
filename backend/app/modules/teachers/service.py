"""Global teacher account, membership, invitation, and capability services."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.security import hash_auth_secret, hash_password, verify_password
from app.config.settings import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.utils.email import send_email
from app.core.utils.email_templates import get_teacher_invitation_email_html
from app.core.utils.normalization import normalize_staff_id
from app.modules.auth.account_email_guard import AccountEmailGuard
from app.modules.auth.models import AuthPurpose, AuthSession, AuthSessionActorType
from app.modules.auth.schemas import RequestOTP
from app.modules.auth.service import OTPService
from app.modules.auth_identity.models import ActorType, IdentifierType
from app.modules.auth_identity.repository import AuthIdentityRepository
from app.modules.auth_identity.schemas import AuthIdentityCreate
from app.modules.auth_identity.service import AuthIdentityService
from app.modules.cbt.auth.service import CBTActorAuthorizationService
from app.modules.subjects.repository import SubjectRepository
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import ResourceLimitCode
from app.modules.teachers.models import (
    TeacherAccount,
    TeacherAccountStatus,
    TeacherInvitation,
    TeacherInvitationStatus,
    TeacherMembership,
    TeacherMembershipStatus,
)
from app.modules.teachers.repository import (
    TeacherAccountRepository,
    TeacherInvitationRepository,
    TeacherMembershipRepository,
    TeacherMembershipSubjectRepository,
)
from app.modules.teachers.schemas import (
    TeacherAccountOnboardingRequest,
    TeacherAccountProfileUpdateRequest,
    TeacherAccountRegisterRequest,
    TeacherAccountResponse,
    TeacherInvitationAcceptanceRequest,
    TeacherInvitationPublicContextResponse,
    TeacherInvitationResponse,
    TeacherMembershipEndRequest,
    TeacherMembershipListResponse,
    TeacherMembershipReactivateRequest,
    TeacherMembershipResponse,
    TeacherMembershipSubjectUpdateRequest,
    TeacherMembershipSuspendRequest,
    TeacherMembershipUpdateRequest,
    TeacherMembershipWithAccountResponse,
    TeacherPasswordChangeRequest,
)
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TeacherInvitationCreateCommand:
    """Internal command carrying backend-owned invitation fields."""

    email: str
    staff_id: str
    job_title: str | None
    department: str | None
    employment_type: str | None


class TeacherAccountService:
    """Global teacher credential and profile lifecycle."""

    @staticmethod
    def _require_account(account: TeacherAccount | None) -> TeacherAccount:
        if account is None:
            raise NotFoundException("Teacher account not found.")
        return account

    @staticmethod
    def _require_active_account(account: TeacherAccount) -> None:
        if (
            not account.is_active
            or not account.is_verified
            or account.account_status != TeacherAccountStatus.ACTIVE
        ):
            raise ForbiddenException("Teacher account is not active.")

    @staticmethod
    async def register_account(
        db: AsyncSession,
        payload: TeacherAccountRegisterRequest,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, object]:
        normalized_email = payload.email.strip().casefold()
        normalized_email = await AccountEmailGuard.ensure_not_superadmin_email(
            db=db,
            email=normalized_email,
            message="This email cannot be used for teacher registration.",
        )
        identity = await AuthIdentityRepository.get_by_identifier(
            db,
            normalized_email,
            IdentifierType.EMAIL,
        )
        account: TeacherAccount | None = None
        created = False

        if identity is not None:
            if identity.actor_type not in {
                ActorType.TEACHER_ACCOUNT,
                ActorType.TEACHER,
            }:
                raise ConflictException("This email is already registered to another account.")
            account = await TeacherAccountRepository.get_by_id(
                db,
                identity.actor_id,
                lock=True,
            )
            if account is None:
                raise ConflictException("The existing teacher identity is invalid.")
            if (
                account.account_status == TeacherAccountStatus.ACTIVE
                and account.is_verified
                and account.is_active
            ):
                raise ConflictException("This teacher account already exists. Please log in.")
            if account.account_status == TeacherAccountStatus.LOCKED or not account.is_active:
                raise ForbiddenException("This teacher account cannot be registered again.")
            account.password_hash = hash_password(payload.password)
            account.account_status = TeacherAccountStatus.PENDING
            account.is_verified = False
            account.is_active = True
            await TeacherAccountRepository.save(db, account)
            if identity.actor_type != ActorType.TEACHER_ACCOUNT:
                identity.actor_type = ActorType.TEACHER_ACCOUNT
                identity.tenant_id = None
                identity.is_active = True
                await AuthIdentityRepository.save(db, identity)
        else:
            account = TeacherAccount(
                email=normalized_email,
                password_hash=hash_password(payload.password),
                account_status=TeacherAccountStatus.PENDING,
                is_verified=False,
                is_active=True,
            )
            account = await TeacherAccountRepository.add(db, account)
            await AuthIdentityService.create_for_actor(
                db,
                payload=AuthIdentityCreate(
                    identifier=normalized_email,
                    identifier_type=IdentifierType.EMAIL,
                    actor_type=ActorType.TEACHER_ACCOUNT,
                    actor_id=account.id,
                    is_active=True,
                ),
            )
            created = True

        await db.commit()
        await AuthIdentityService.invalidate_after_commit(db)
        await OTPService.generate_otp(
            db,
            RequestOTP(
                email=normalized_email,
                purpose=AuthPurpose.VERIFICATION.value,
            ),
            background_tasks=background_tasks,
        )
        return {
            "created": created,
            "email": normalized_email,
            "verification_required": True,
            "purpose": AuthPurpose.VERIFICATION.value,
            "redirect_to": "/verify-otp",
            "resend_otp_available": True,
            "detail": "Check your email for the verification code.",
            "message": "Check your email for the verification code.",
        }

    @staticmethod
    async def get_account(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> TeacherAccountResponse:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(db, account_id)
        )
        return TeacherAccountResponse.model_validate(account)

    @staticmethod
    async def get_onboarding_status(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> dict[str, object]:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(db, account_id)
        )
        return {
            "actor_type": "teacher_account",
            "teacher_account_id": account.id,
            "onboarding_required": not account.profile_completed,
            "profile_completed": account.profile_completed,
            "completion_target": "teacher_account",
            "required_fields": ["first_name", "last_name"],
            "current_values": {
                "email": account.email,
                "first_name": account.first_name,
                "last_name": account.last_name,
                "phone_number": account.phone_number,
                "qualification": account.qualification,
                "specialization": account.specialization,
            },
        }

    @staticmethod
    async def complete_onboarding(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: TeacherAccountOnboardingRequest,
    ) -> TeacherAccountResponse:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        TeacherAccountService._require_active_account(account)
        for field, value in payload.model_dump().items():
            setattr(account, field, value)
        await TeacherAccountRepository.save(db, account)
        await db.commit()
        await db.refresh(account)
        return TeacherAccountResponse.model_validate(account)

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: TeacherAccountProfileUpdateRequest,
    ) -> TeacherAccountResponse:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        TeacherAccountService._require_active_account(account)
        for field, value in payload.model_dump(
            exclude_unset=True,
            exclude_none=True,
        ).items():
            setattr(account, field, value)
        await TeacherAccountRepository.save(db, account)
        await db.commit()
        await db.refresh(account)
        return TeacherAccountResponse.model_validate(account)

    @staticmethod
    async def change_password(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: TeacherPasswordChangeRequest,
    ) -> None:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        TeacherAccountService._require_active_account(account)
        if not verify_password(
            payload.current_password,
            account.password_hash,
        ):
            raise BadRequestException("Current password is incorrect.")
        if verify_password(payload.new_password, account.password_hash):
            raise BadRequestException("New password must differ from the current password.")

        account.password_hash = hash_password(payload.new_password)
        await TeacherAccountRepository.save(db, account)
        memberships = await TeacherAccountRepository.list_memberships(
            db,
            account.id,
        )
        membership_ids = [membership.id for membership in memberships]
        session_filters = [
            (AuthSession.actor_type == AuthSessionActorType.TEACHER_ACCOUNT)
            & (AuthSession.actor_id == account.id)
        ]
        if membership_ids:
            session_filters.append(
                (AuthSession.actor_type == AuthSessionActorType.TEACHER)
                & AuthSession.actor_id.in_(membership_ids)
            )
        await db.execute(
            update(AuthSession)
            .where(
                or_(*session_filters),
                AuthSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=_utc_now(),
                revoked_reason="password_changed",
            )
        )
        await CBTActorAuthorizationService.revoke_for_teacher_account(
            db,
            teacher_account_id=account.id,
            reason="password_changed",
        )
        await db.commit()

    @staticmethod
    async def list_memberships(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> TeacherMembershipListResponse:
        account = TeacherAccountService._require_account(
            await TeacherAccountRepository.get_by_id(db, account_id)
        )
        memberships = await TeacherAccountRepository.list_memberships(
            db,
            account.id,
        )
        return TeacherMembershipListResponse(
            items=[
                TeacherMembershipWithAccountResponse.model_validate(membership)
                for membership in memberships
            ],
            total=len(memberships),
        )


class TeacherMembershipService:
    """Tenant employment, authorization, and capability lifecycle."""

    @staticmethod
    async def _lock_tenant_and_enforce_limit(
        db: AsyncSession,
        *,
        tenant_id: UUID,
    ) -> None:
        tenant = await TenantRepository.get_by_id(
            db,
            tenant_id,
            lock=True,
        )
        if tenant is None:
            raise NotFoundException("Tenant not found.")
        await SubscriptionFeatureService.ensure_resource_limit_available(
            db,
            tenant_id,
            ResourceLimitCode.TEACHERS,
        )

    @staticmethod
    async def get_membership(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        membership_id: UUID,
    ) -> TeacherMembershipWithAccountResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=tenant_id,
            load_account=True,
            load_subjects=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")
        return TeacherMembershipWithAccountResponse.model_validate(membership)

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        status: TeacherMembershipStatus | None = None,
    ) -> TeacherMembershipListResponse:
        rows, total = await TeacherMembershipRepository.list_for_tenant(
            db,
            tenant_id,
            status=status,
            search=search,
            offset=skip,
            limit=min(limit, 100),
        )
        return TeacherMembershipListResponse(
            items=[TeacherMembershipWithAccountResponse.model_validate(row) for row in rows],
            total=total,
        )

    @staticmethod
    async def update_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin | TeacherMembership,
        membership_id: UUID,
        payload: TeacherMembershipUpdateRequest,
    ) -> TeacherMembershipResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")
        if isinstance(actor, TeacherMembership):
            if actor.id != membership.id:
                raise ForbiddenException(
                    "Teachers can update only their own membership preferences."
                )
            allowed = {
                "receive_email_notifications",
                "receive_push_notifications",
            }
            if not set(payload.model_fields_set).issubset(allowed):
                raise ForbiddenException("Employment fields are controlled by the school.")

        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "staff_id" in update_data:
            normalized_staff_id = normalize_staff_id(update_data["staff_id"])
            if normalized_staff_id and await TeacherMembershipRepository.staff_id_exists(
                db,
                actor.tenant_id,
                normalized_staff_id,
                exclude_membership_id=membership.id,
            ):
                raise ConflictException("This staff ID is already assigned.")
            update_data["staff_id"] = normalized_staff_id

        for field, value in update_data.items():
            setattr(membership, field, value)
        await TeacherMembershipRepository.save(db, membership)
        await db.commit()
        await db.refresh(membership)
        return TeacherMembershipResponse.model_validate(membership)

    @staticmethod
    async def _revoke_membership_sessions(
        db: AsyncSession,
        *,
        membership: TeacherMembership,
        reason: str,
    ) -> None:
        await db.execute(
            update(AuthSession)
            .where(
                AuthSession.actor_type == AuthSessionActorType.TEACHER,
                AuthSession.actor_id == membership.id,
                AuthSession.tenant_id == membership.tenant_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=_utc_now(),
                revoked_reason=reason[:100],
            )
        )

    @staticmethod
    async def suspend_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: TeacherMembershipSuspendRequest,
    ) -> TeacherMembershipResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")
        if membership.status != TeacherMembershipStatus.ACTIVE:
            raise ConflictException("Only active teacher memberships can be suspended.")
        membership.status = TeacherMembershipStatus.SUSPENDED
        membership.end_reason = payload.reason
        await TeacherMembershipRepository.save(db, membership)
        await TeacherMembershipService._revoke_membership_sessions(
            db,
            membership=membership,
            reason="membership_suspended",
        )
        await CBTActorAuthorizationService.revoke_for_teacher_membership(
            db,
            tenant_id=membership.tenant_id,
            membership_id=membership.id,
            reason="membership_suspended",
        )
        await db.commit()
        await db.refresh(membership)
        return TeacherMembershipResponse.model_validate(membership)

    @staticmethod
    async def end_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: TeacherMembershipEndRequest,
    ) -> TeacherMembershipResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")
        if membership.status == TeacherMembershipStatus.INACTIVE:
            raise ConflictException("Teacher membership is already inactive.")

        membership.status = TeacherMembershipStatus.INACTIVE
        membership.ended_at = _utc_now()
        membership.end_reason = payload.reason
        await TeacherMembershipRepository.save(db, membership)
        await TeacherMembershipService._revoke_membership_sessions(
            db,
            membership=membership,
            reason="membership_ended",
        )
        await CBTActorAuthorizationService.revoke_for_teacher_membership(
            db,
            tenant_id=membership.tenant_id,
            membership_id=membership.id,
            reason="membership_ended",
        )
        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(actor.tenant_id)
        await db.refresh(membership)
        return TeacherMembershipResponse.model_validate(membership)

    @staticmethod
    async def reactivate_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: TeacherMembershipReactivateRequest,
    ) -> TeacherMembershipResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")
        if membership.status == TeacherMembershipStatus.ACTIVE:
            raise ConflictException("Teacher membership is already active.")
        if membership.status == TeacherMembershipStatus.INACTIVE:
            await TeacherMembershipService._lock_tenant_and_enforce_limit(
                db,
                tenant_id=actor.tenant_id,
            )

        membership.status = TeacherMembershipStatus.ACTIVE
        membership.ended_at = None
        membership.end_reason = None
        await TeacherMembershipRepository.save(db, membership)
        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(actor.tenant_id)
        await db.refresh(membership)
        return TeacherMembershipResponse.model_validate(membership)

    @staticmethod
    async def replace_subject_capabilities(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: TeacherMembershipSubjectUpdateRequest,
    ) -> TeacherMembershipResponse:
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
            load_subjects=True,
        )
        if membership is None:
            raise NotFoundException("Teacher membership not found.")

        requested = set(payload.subject_ids)
        subjects = await SubjectRepository.get_subjects_by_id(
            db,
            actor.tenant_id,
            list(requested),
        )
        active_subject_ids = {
            subject.id for subject in subjects if subject.is_active and subject.archived_at is None
        }
        unavailable = requested - active_subject_ids
        if unavailable:
            subject_id = sorted(unavailable, key=str)[0]
            raise NotFoundException(f"Subject {subject_id} was not found or is inactive.")

        existing = {
            link.subject_id: link
            for link in await TeacherMembershipSubjectRepository.list_for_membership(
                db,
                actor.tenant_id,
                membership.id,
            )
        }
        for subject_id, link in existing.items():
            link.is_active = subject_id in requested
            db.add(link)
        await db.flush()

        missing = [subject_id for subject_id in requested if subject_id not in existing]
        if missing:
            await TeacherMembershipSubjectRepository.add_many(
                db,
                actor.tenant_id,
                membership.id,
                missing,
            )
        await db.commit()
        return TeacherMembershipResponse.model_validate(membership)


class TeacherInvitationService:
    """School invitation and teacher membership acceptance workflow."""

    INVITATION_DAYS = 7

    @staticmethod
    def _membership_is_usable(membership: TeacherMembership | None) -> bool:
        """Match the acceptance contract: only inactive memberships are reusable."""

        return membership is not None and membership.status != TeacherMembershipStatus.INACTIVE

    @staticmethod
    async def _recommended_action_for_email(
        db: AsyncSession,
        normalized_email: str,
    ) -> str:
        identity = await AuthIdentityRepository.get_by_identifier(
            db,
            normalized_email,
            IdentifierType.EMAIL,
        )
        if identity is None:
            return "register"
        if identity.actor_type == ActorType.TEACHER_ACCOUNT:
            return "login"
        return "contact_school"

    @staticmethod
    async def get_public_context(
        db: AsyncSession,
        *,
        invitation_token: str,
    ) -> TeacherInvitationPublicContextResponse:
        invitation = await TeacherInvitationRepository.get_by_token_digest(
            db,
            hash_auth_secret(invitation_token),
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if (
            invitation.status == TeacherInvitationStatus.PENDING
            and invitation.expires_at <= _utc_now()
        ):
            invitation.status = TeacherInvitationStatus.EXPIRED
            await TeacherInvitationRepository.save(db, invitation)
            await db.commit()

        tenant = await TenantRepository.get_by_id(db, invitation.tenant_id)
        if tenant is None:
            raise NotFoundException("Invitation context is unavailable.")

        return TeacherInvitationPublicContextResponse(
            invitation_id=invitation.id,
            tenant_name=tenant.school_name,
            tenant_logo_url=tenant.logo_url,
            invited_email=invitation.invited_email,
            staff_id=invitation.staff_id,
            job_title=invitation.job_title,
            department=invitation.department,
            employment_type=invitation.employment_type,
            expires_at=invitation.expires_at,
            status=invitation.status,
            recommended_action=await TeacherInvitationService._recommended_action_for_email(
                db,
                invitation.invited_email,
            ),
        )

    @staticmethod
    async def create_invitation(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        payload: TeacherInvitationCreateCommand,
        background_tasks: BackgroundTasks | None = None,
    ) -> TeacherInvitationResponse:
        normalized_email = await AccountEmailGuard.ensure_available_for_invitation_role(
            db=db,
            email=str(payload.email),
            invited_actor_type=ActorType.TEACHER_ACCOUNT,
        )
        account = await TeacherAccountRepository.get_by_email(
            db,
            normalized_email,
            lock=True,
        )
        if account is not None:
            existing_membership = await TeacherMembershipRepository.get_by_account_and_tenant(
                db,
                account.id,
                actor.tenant_id,
                lock=True,
            )
            if TeacherInvitationService._membership_is_usable(existing_membership):
                raise ConflictException(
                    "This teacher is already an active member of this school.",
                    payload={"code": "TEACHER_ALREADY_ACTIVE_MEMBER"},
                )
        pending = await TeacherInvitationRepository.get_pending_for_email(
            db,
            actor.tenant_id,
            normalized_email,
            lock=True,
        )
        if pending is not None:
            raise ConflictException("A pending invitation already exists for this teacher.")

        normalized_staff_id = normalize_staff_id(payload.staff_id)
        if normalized_staff_id and await TeacherMembershipRepository.staff_id_exists(
            db,
            actor.tenant_id,
            normalized_staff_id,
        ):
            raise ConflictException("This staff ID is already assigned.")

        raw_token = secrets.token_urlsafe(48)
        invitation = TeacherInvitation(
            tenant_id=actor.tenant_id,
            invited_email=normalized_email,
            token_digest=hash_auth_secret(raw_token),
            staff_id=normalized_staff_id,
            job_title=payload.job_title,
            department=payload.department,
            employment_type=payload.employment_type,
            status=TeacherInvitationStatus.PENDING,
            expires_at=_utc_now() + timedelta(days=TeacherInvitationService.INVITATION_DAYS),
            created_by_admin_id=actor.id,
        )
        invitation = await TeacherInvitationRepository.add(db, invitation)
        tenant = await TenantRepository.get_by_id(db, actor.tenant_id)
        await db.commit()

        invite_url = f"{settings.FRONTEND_APP_URL.rstrip('/')}/teacher-invitations/{raw_token}"
        if background_tasks is not None:
            school_name = tenant.school_name if tenant else "your school"
            background_tasks.add_task(
                send_email,
                normalized_email,
                f"Join {school_name} on Weave",
                get_teacher_invitation_email_html(
                    school_name=school_name,
                    invite_link=invite_url,
                ),
                True,
            )
        return TeacherInvitationResponse.model_validate(invitation)

    @staticmethod
    async def accept_invitation(
        db: AsyncSession,
        *,
        account: TeacherAccount,
        payload: TeacherInvitationAcceptanceRequest,
    ) -> TeacherMembershipWithAccountResponse:
        TeacherAccountService._require_active_account(account)
        invitation = await TeacherInvitationRepository.get_by_token_digest(
            db,
            hash_auth_secret(payload.invitation_token),
            lock=True,
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if invitation.status != TeacherInvitationStatus.PENDING:
            raise ConflictException("Invitation is no longer pending.")
        if invitation.expires_at <= _utc_now():
            invitation.status = TeacherInvitationStatus.EXPIRED
            await TeacherInvitationRepository.save(db, invitation)
            await db.commit()
            raise BadRequestException("Invitation has expired.")
        if account.email.casefold() != invitation.invited_email.casefold():
            raise ForbiddenException("This invitation belongs to another email address.")

        membership = await TeacherMembershipRepository.get_by_account_and_tenant(
            db,
            account.id,
            invitation.tenant_id,
            lock=True,
        )
        if membership is None:
            await TeacherMembershipService._lock_tenant_and_enforce_limit(
                db,
                tenant_id=invitation.tenant_id,
            )
            if invitation.staff_id and await TeacherMembershipRepository.staff_id_exists(
                db,
                invitation.tenant_id,
                invitation.staff_id,
            ):
                raise ConflictException("The invitation staff ID is already assigned.")
            membership = await TeacherMembershipRepository.add(
                db,
                TeacherMembership(
                    tenant_id=invitation.tenant_id,
                    teacher_account_id=account.id,
                    staff_id=invitation.staff_id,
                    job_title=invitation.job_title,
                    department=invitation.department,
                    employment_type=invitation.employment_type,
                    status=TeacherMembershipStatus.ACTIVE,
                    joined_at=_utc_now(),
                ),
            )
        elif membership.status == TeacherMembershipStatus.INACTIVE:
            await TeacherMembershipService._lock_tenant_and_enforce_limit(
                db,
                tenant_id=invitation.tenant_id,
            )
            membership.status = TeacherMembershipStatus.ACTIVE
            membership.joined_at = membership.joined_at or _utc_now()
            membership.ended_at = None
            membership.end_reason = None
            membership.staff_id = invitation.staff_id or membership.staff_id
            membership.job_title = invitation.job_title or membership.job_title
            membership.department = invitation.department or membership.department
            membership.employment_type = invitation.employment_type or membership.employment_type
            await TeacherMembershipRepository.save(db, membership)
        elif TeacherInvitationService._membership_is_usable(membership):
            raise ConflictException("This teacher already has a usable membership in the school.")

        invitation.status = TeacherInvitationStatus.ACCEPTED
        invitation.accepted_at = _utc_now()
        invitation.accepted_by_teacher_account_id = account.id
        await TeacherInvitationRepository.save(db, invitation)
        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(invitation.tenant_id)
        membership = await TeacherMembershipRepository.get_by_id(
            db,
            membership.id,
            tenant_id=invitation.tenant_id,
            load_account=True,
            load_subjects=True,
        )
        return TeacherMembershipWithAccountResponse.model_validate(membership)

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        status: TeacherInvitationStatus | None = None,
        search: str | None = None,
    ) -> tuple[list[TeacherInvitationResponse], int]:
        rows, total = await TeacherInvitationRepository.list_for_tenant(
            db,
            tenant_id,
            status=status,
            search=search,
            offset=skip,
            limit=min(limit, 100),
        )
        return [TeacherInvitationResponse.model_validate(row) for row in rows], total

    @staticmethod
    async def revoke_invitation(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        invitation_id: UUID,
    ) -> TeacherInvitationResponse:
        invitation = await TeacherInvitationRepository.get_by_id(
            db,
            actor.tenant_id,
            invitation_id,
            lock=True,
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if invitation.status != TeacherInvitationStatus.PENDING:
            raise ConflictException("Only pending invitations can be revoked.")
        invitation.status = TeacherInvitationStatus.REVOKED
        invitation.revoked_at = _utc_now()
        await TeacherInvitationRepository.save(db, invitation)
        await db.commit()
        await db.refresh(invitation)
        return TeacherInvitationResponse.model_validate(invitation)
