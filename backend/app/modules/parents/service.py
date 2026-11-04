"""Global parent account, tenant membership, and invitation services."""

from __future__ import annotations

import secrets
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
from app.core.utils.email_templates import get_parent_invitation_email_html
from app.modules.auth.account_email_guard import AccountEmailGuard
from app.modules.auth.models import AuthPurpose, AuthSession, AuthSessionActorType
from app.modules.auth.schemas import RequestOTP
from app.modules.auth.service import OTPService
from app.modules.auth_identity.models import ActorType, IdentifierType
from app.modules.auth_identity.repository import AuthIdentityRepository
from app.modules.auth_identity.schemas import AuthIdentityCreate
from app.modules.auth_identity.service import AuthIdentityService
from app.modules.parents.models import (
    ParentAccount,
    ParentAccountStatus,
    ParentInvitation,
    ParentInvitationStatus,
    ParentMembership,
    ParentMembershipStatus,
)
from app.modules.parents.repository import (
    ParentAccountRepository,
    ParentInvitationRepository,
    ParentMembershipRepository,
)
from app.modules.parents.schemas import (
    ParentAccountOnboardingRequest,
    ParentAccountPasswordChangeRequest,
    ParentAccountProfileUpdateRequest,
    ParentAccountRegisterRequest,
    ParentAccountResponse,
    ParentInvitationAcceptanceRequest,
    ParentInvitationCreateRequest,
    ParentInvitationPublicContextResponse,
    ParentInvitationResponse,
    ParentMembershipEndRequest,
    ParentMembershipListResponse,
    ParentMembershipNotificationUpdateRequest,
    ParentMembershipReactivateRequest,
    ParentMembershipResponse,
    ParentMembershipWithAccountResponse,
)
from app.modules.students.models import (
    StudentParentLinkRequest,
    StudentParentLinkRequestStatus,
    StudentParentLinkStatus,
)
from app.modules.students.repository import (
    StudentParentLinkRepository,
    StudentParentLinkRequestRepository,
    StudentRepository,
)
from app.modules.students.schemas import (
    StudentDetailResponse,
    StudentParentLinkRequestResponse,
)
from app.modules.students.service import StudentService
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import ResourceLimitCode
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParentAccountService:
    """Global parent credential and profile lifecycle."""

    @staticmethod
    def _require_account(account: ParentAccount | None) -> ParentAccount:
        if account is None:
            raise NotFoundException("Parent account not found.")
        return account

    @staticmethod
    def _require_active_account(account: ParentAccount) -> None:
        if (
            not account.is_active
            or not account.is_verified
            or account.account_status != ParentAccountStatus.ACTIVE
        ):
            raise ForbiddenException("Parent account is not active.")

    @staticmethod
    async def register_account(
        db: AsyncSession,
        payload: ParentAccountRegisterRequest,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, object]:
        normalized_email = payload.email.strip().casefold()
        normalized_email = await AccountEmailGuard.ensure_not_superadmin_email(
            db=db,
            email=normalized_email,
            message="This email cannot be used for parent registration.",
        )

        identity = await AuthIdentityRepository.get_by_identifier(
            db,
            normalized_email,
            IdentifierType.EMAIL,
        )
        account: ParentAccount | None = None
        created = False

        if identity is not None:
            if identity.actor_type not in {
                ActorType.PARENT_ACCOUNT,
                ActorType.PARENT,
            }:
                raise ConflictException("This email is already registered to another account.")
            account = await ParentAccountRepository.get_by_id(
                db,
                identity.actor_id,
                lock=True,
            )
            if account is None:
                raise ConflictException("The existing parent identity is invalid.")
            if (
                account.account_status == ParentAccountStatus.ACTIVE
                and account.is_verified
                and account.is_active
            ):
                raise ConflictException("This parent account already exists. Please log in.")
            if account.account_status == ParentAccountStatus.LOCKED or not account.is_active:
                raise ForbiddenException("This parent account cannot be registered again.")
            account.password_hash = hash_password(payload.password)
            account.account_status = ParentAccountStatus.PENDING
            account.is_verified = False
            account.is_active = True
            await ParentAccountRepository.save(db, account)
            if identity.actor_type != ActorType.PARENT_ACCOUNT:
                identity.actor_type = ActorType.PARENT_ACCOUNT
                identity.tenant_id = None
                identity.is_active = True
                await AuthIdentityRepository.save(db, identity)
        else:
            account = ParentAccount(
                email=normalized_email,
                password_hash=hash_password(payload.password),
                account_status=ParentAccountStatus.PENDING,
                is_verified=False,
                is_active=True,
            )
            account = await ParentAccountRepository.add(db, account)
            await AuthIdentityService.create_for_actor(
                db,
                payload=AuthIdentityCreate(
                    identifier=normalized_email,
                    identifier_type=IdentifierType.EMAIL,
                    actor_type=ActorType.PARENT_ACCOUNT,
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
    ) -> ParentAccountResponse:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(db, account_id)
        )
        return ParentAccountResponse.model_validate(account)

    @staticmethod
    async def get_onboarding_status(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> dict[str, object]:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(db, account_id)
        )
        return {
            "actor_type": "parent_account",
            "parent_account_id": account.id,
            "onboarding_required": not account.profile_completed,
            "profile_completed": account.profile_completed,
            "completion_target": "parent_account",
            "required_fields": ["first_name", "last_name"],
            "current_values": {
                "email": account.email,
                "first_name": account.first_name,
                "last_name": account.last_name,
                "phone_number": account.phone_number,
                "occupation": account.occupation,
                "address": account.address,
                "emergency_phone": account.emergency_phone,
            },
        }

    @staticmethod
    async def complete_onboarding(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: ParentAccountOnboardingRequest,
    ) -> ParentAccountResponse:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        ParentAccountService._require_active_account(account)
        for field, value in payload.model_dump().items():
            setattr(account, field, value)
        await ParentAccountRepository.save(db, account)
        await db.commit()
        await db.refresh(account)
        return ParentAccountResponse.model_validate(account)

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: ParentAccountProfileUpdateRequest,
    ) -> ParentAccountResponse:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        ParentAccountService._require_active_account(account)
        for field, value in payload.model_dump(
            exclude_unset=True,
            exclude_none=True,
        ).items():
            setattr(account, field, value)
        await ParentAccountRepository.save(db, account)
        await db.commit()
        await db.refresh(account)
        return ParentAccountResponse.model_validate(account)

    @staticmethod
    async def change_password(
        db: AsyncSession,
        *,
        account_id: UUID,
        payload: ParentAccountPasswordChangeRequest,
    ) -> None:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(
                db,
                account_id,
                lock=True,
            )
        )
        ParentAccountService._require_active_account(account)
        if not verify_password(
            payload.current_password,
            account.password_hash,
        ):
            raise BadRequestException("Current password is incorrect.")
        if verify_password(payload.new_password, account.password_hash):
            raise BadRequestException("New password must differ from the current password.")

        account.password_hash = hash_password(payload.new_password)
        await ParentAccountRepository.save(db, account)
        memberships = await ParentAccountRepository.list_memberships(
            db,
            account.id,
        )
        membership_ids = [membership.id for membership in memberships]
        session_filter = [
            (AuthSession.actor_type == AuthSessionActorType.PARENT_ACCOUNT)
            & (AuthSession.actor_id == account.id)
        ]
        if membership_ids:
            session_filter.append(
                (AuthSession.actor_type == AuthSessionActorType.PARENT)
                & AuthSession.actor_id.in_(membership_ids)
            )
        await db.execute(
            update(AuthSession)
            .where(
                or_(*session_filter),
                AuthSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=_utc_now(),
                revoked_reason="password_changed",
            )
        )
        await db.commit()

    @staticmethod
    async def list_memberships(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> ParentMembershipListResponse:
        account = ParentAccountService._require_account(
            await ParentAccountRepository.get_by_id(db, account_id)
        )
        memberships = await ParentAccountRepository.list_memberships(
            db,
            account.id,
        )
        return ParentMembershipListResponse(
            items=[
                ParentMembershipWithAccountResponse.model_validate(membership)
                for membership in memberships
            ],
            total=len(memberships),
        )


class ParentMembershipService:
    """Tenant-specific parent access and membership lifecycle."""

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
            ResourceLimitCode.PARENTS,
        )

    @staticmethod
    async def get_membership(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        membership_id: UUID,
    ) -> ParentMembershipWithAccountResponse:
        membership = await ParentMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=tenant_id,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Parent membership not found.")
        return ParentMembershipWithAccountResponse.model_validate(membership)

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        status: ParentMembershipStatus | None = None,
    ) -> ParentMembershipListResponse:
        memberships, total = await ParentMembershipRepository.list_for_tenant(
            db,
            tenant_id,
            status=status,
            search=search,
            offset=skip,
            limit=min(limit, 100),
        )
        return ParentMembershipListResponse(
            items=[
                ParentMembershipWithAccountResponse.model_validate(membership)
                for membership in memberships
            ],
            total=total,
        )

    @staticmethod
    async def update_notifications(
        db: AsyncSession,
        *,
        membership: ParentMembership,
        payload: ParentMembershipNotificationUpdateRequest,
    ) -> ParentMembershipResponse:
        for field, value in payload.model_dump(
            exclude_unset=True,
            exclude_none=True,
        ).items():
            setattr(membership, field, value)
        await ParentMembershipRepository.save(db, membership)
        await db.commit()
        await db.refresh(membership)
        return ParentMembershipResponse.model_validate(membership)

    @staticmethod
    async def end_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: ParentMembershipEndRequest,
    ) -> ParentMembershipResponse:
        membership = await ParentMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Parent membership not found.")
        if membership.status == ParentMembershipStatus.INACTIVE:
            raise ConflictException("Parent membership is already inactive.")

        links = await StudentParentLinkRepository.list_for_membership(
            db,
            actor.tenant_id,
            membership.id,
            lock=True,
        )
        now = _utc_now()
        for link in links:
            link.status = StudentParentLinkStatus.ENDED
            link.ended_at = now
            link.end_reason = payload.reason
            await StudentParentLinkRepository.save(db, link)

        membership.status = ParentMembershipStatus.INACTIVE
        membership.ended_at = now
        membership.end_reason = payload.reason
        await ParentMembershipRepository.save(db, membership)
        await db.execute(
            update(AuthSession)
            .where(
                AuthSession.actor_type == AuthSessionActorType.PARENT,
                AuthSession.actor_id == membership.id,
                AuthSession.tenant_id == membership.tenant_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=now,
                revoked_reason="membership_ended",
            )
        )
        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(actor.tenant_id)
        await db.refresh(membership)
        return ParentMembershipResponse.model_validate(membership)

    @staticmethod
    async def reactivate_membership(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        membership_id: UUID,
        payload: ParentMembershipReactivateRequest,
    ) -> ParentMembershipResponse:
        membership = await ParentMembershipRepository.get_by_id(
            db,
            membership_id,
            tenant_id=actor.tenant_id,
            lock=True,
            load_account=True,
        )
        if membership is None:
            raise NotFoundException("Parent membership not found.")
        if membership.status != ParentMembershipStatus.INACTIVE:
            raise ConflictException("Parent membership is already usable.")

        await ParentMembershipService._lock_tenant_and_enforce_limit(
            db,
            tenant_id=actor.tenant_id,
        )
        membership.status = ParentMembershipStatus.ACTIVE
        membership.ended_at = None
        membership.end_reason = None
        await ParentMembershipRepository.save(db, membership)
        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(actor.tenant_id)
        await db.refresh(membership)
        return ParentMembershipResponse.model_validate(membership)

    @staticmethod
    async def list_children(
        db: AsyncSession,
        *,
        membership: ParentMembership,
    ) -> list[StudentDetailResponse]:
        links = await StudentParentLinkRepository.list_for_membership(
            db,
            membership.tenant_id,
            membership.id,
            statuses=[
                StudentParentLinkStatus.ACTIVE,
                StudentParentLinkStatus.READ_ONLY,
                StudentParentLinkStatus.ALUMNI_READ_ONLY,
            ],
        )
        output: list[StudentDetailResponse] = []
        for link in links:
            if link.student is not None:
                output.append(
                    await StudentService._build_detail_response(
                        db,
                        link.student,
                    )
                )
        return output


class ParentInvitationService:
    """School invitation and parent acceptance workflow."""

    INVITATION_DAYS = 7

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
        if identity.actor_type == ActorType.PARENT_ACCOUNT:
            return "login"
        return "contact_school"

    @staticmethod
    async def create_invitation(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        payload: ParentInvitationCreateRequest,
        background_tasks: BackgroundTasks | None = None,
    ) -> ParentInvitationResponse:
        student = await StudentRepository.get_by_id(
            db,
            actor.tenant_id,
            payload.student_id,
            lock=True,
        )
        if student is None:
            raise NotFoundException("Student not found.")

        normalized_email = await AccountEmailGuard.ensure_available_for_invitation_role(
            db=db,
            email=str(payload.email),
            invited_actor_type=ActorType.PARENT_ACCOUNT,
        )
        pending = await ParentInvitationRepository.get_pending_for_student_email(
            db,
            actor.tenant_id,
            student.id,
            normalized_email,
            lock=True,
        )
        if pending is not None:
            raise ConflictException("A pending invitation already exists for this parent.")

        raw_token = secrets.token_urlsafe(48)
        invitation = ParentInvitation(
            tenant_id=actor.tenant_id,
            student_id=student.id,
            invited_email=normalized_email,
            relationship_type=payload.relationship_type,
            admission_number_snapshot=student.admission_number,
            token_digest=hash_auth_secret(raw_token),
            status=ParentInvitationStatus.PENDING,
            expires_at=_utc_now() + timedelta(days=ParentInvitationService.INVITATION_DAYS),
            created_by_admin_id=actor.id,
        )
        invitation = await ParentInvitationRepository.add(db, invitation)
        tenant = await TenantRepository.get_by_id(db, actor.tenant_id)
        await db.commit()

        invite_url = f"{settings.FRONTEND_APP_URL.rstrip('/')}/parent-invitations/{raw_token}"
        if background_tasks is not None:
            school_name = tenant.school_name if tenant else "your school"
            student_name = (
                " ".join(part for part in [student.first_name, student.last_name] if part)
                or "a student"
            )
            background_tasks.add_task(
                send_email,
                normalized_email,
                f"Join {school_name} on Weave",
                get_parent_invitation_email_html(
                    school_name=school_name,
                    student_name=student_name,
                    invite_link=invite_url,
                    admission_number=student.admission_number,
                ),
                True,
            )
        return ParentInvitationResponse.model_validate(invitation)

    @staticmethod
    async def get_public_context(
        db: AsyncSession,
        *,
        invitation_token: str,
    ) -> ParentInvitationPublicContextResponse:
        invitation = await ParentInvitationRepository.get_by_token_digest(
            db,
            hash_auth_secret(invitation_token),
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if (
            invitation.status == ParentInvitationStatus.PENDING
            and invitation.expires_at <= _utc_now()
        ):
            invitation.status = ParentInvitationStatus.EXPIRED
            await ParentInvitationRepository.save(db, invitation)
            await db.commit()

        student = await StudentRepository.get_by_id(
            db,
            invitation.tenant_id,
            invitation.student_id,
            include_archived=True,
        )
        tenant = await TenantRepository.get_by_id(db, invitation.tenant_id)
        if student is None or tenant is None:
            raise NotFoundException("Invitation context is unavailable.")
        display_name = (
            " ".join(part for part in [student.first_name, student.last_name] if part) or "Student"
        )
        admission = invitation.admission_number_snapshot
        hint = f"{admission[:3]}***{admission[-3:]}" if len(admission) > 6 else "***"
        return ParentInvitationPublicContextResponse(
            invitation_id=invitation.id,
            tenant_name=tenant.school_name,
            tenant_logo_url=tenant.logo_url,
            student_display_name=display_name,
            invited_email=invitation.invited_email,
            admission_number=admission,
            admission_number_hint=hint,
            relationship_type=invitation.relationship_type,
            expires_at=invitation.expires_at,
            status=invitation.status,
            recommended_action=await ParentInvitationService._recommended_action_for_email(
                db,
                invitation.invited_email,
            ),
        )

    @staticmethod
    async def accept_invitation(
        db: AsyncSession,
        *,
        account: ParentAccount,
        payload: ParentInvitationAcceptanceRequest,
    ) -> StudentParentLinkRequestResponse:
        ParentAccountService._require_active_account(account)
        invitation = await ParentInvitationRepository.get_by_token_digest(
            db,
            hash_auth_secret(payload.invitation_token),
            lock=True,
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if invitation.status != ParentInvitationStatus.PENDING:
            raise ConflictException("Invitation is no longer pending.")
        if invitation.expires_at <= _utc_now():
            invitation.status = ParentInvitationStatus.EXPIRED
            await ParentInvitationRepository.save(db, invitation)
            await db.commit()
            raise BadRequestException("Invitation has expired.")
        if account.email.casefold() != invitation.invited_email.casefold():
            raise ForbiddenException("This invitation belongs to another email address.")
        if payload.admission_number.strip().upper() != invitation.admission_number_snapshot.upper():
            raise BadRequestException("Admission number does not match.")

        membership = await ParentMembershipRepository.get_by_account_and_tenant(
            db,
            account.id,
            invitation.tenant_id,
            lock=True,
        )
        if membership is None:
            await ParentMembershipService._lock_tenant_and_enforce_limit(
                db,
                tenant_id=invitation.tenant_id,
            )
            membership = await ParentMembershipRepository.add(
                db,
                ParentMembership(
                    tenant_id=invitation.tenant_id,
                    parent_account_id=account.id,
                    status=ParentMembershipStatus.ACTIVE,
                    joined_at=_utc_now(),
                ),
            )
        elif membership.status == ParentMembershipStatus.INACTIVE:
            await ParentMembershipService._lock_tenant_and_enforce_limit(
                db,
                tenant_id=invitation.tenant_id,
            )
            membership.status = ParentMembershipStatus.ACTIVE
            membership.joined_at = membership.joined_at or _utc_now()
            membership.ended_at = None
            membership.end_reason = None
            await ParentMembershipRepository.save(db, membership)

        existing = await StudentParentLinkRequestRepository.get_by_invitation(
            db,
            invitation.id,
            lock=True,
        )
        if existing is None:
            existing = await StudentParentLinkRequestRepository.add(
                db,
                StudentParentLinkRequest(
                    tenant_id=invitation.tenant_id,
                    invitation_id=invitation.id,
                    student_id=invitation.student_id,
                    parent_account_id=account.id,
                    parent_membership_id=membership.id,
                    admission_number_snapshot=(invitation.admission_number_snapshot),
                    relationship_type=invitation.relationship_type,
                    status=StudentParentLinkRequestStatus.PENDING,
                    requested_at=_utc_now(),
                ),
            )

        await db.commit()
        await SubscriptionFeatureService.invalidate_tenant_subscription_state(invitation.tenant_id)
        return StudentParentLinkRequestResponse.model_validate(existing)

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        status: ParentInvitationStatus | None = None,
        search: str | None = None,
    ) -> tuple[list[ParentInvitationResponse], int]:
        rows, total = await ParentInvitationRepository.list_for_tenant(
            db,
            tenant_id,
            status=status,
            search=search,
            offset=skip,
            limit=min(limit, 100),
        )
        return [ParentInvitationResponse.model_validate(row) for row in rows], total

    @staticmethod
    async def revoke_invitation(
        db: AsyncSession,
        *,
        actor: TenantAdmin,
        invitation_id: UUID,
    ) -> ParentInvitationResponse:
        invitation = await ParentInvitationRepository.get_by_id(
            db,
            actor.tenant_id,
            invitation_id,
            lock=True,
        )
        if invitation is None:
            raise NotFoundException("Invitation not found.")
        if invitation.status != ParentInvitationStatus.PENDING:
            raise ConflictException("Only pending invitations can be revoked.")
        invitation.status = ParentInvitationStatus.REVOKED
        invitation.revoked_at = _utc_now()
        await ParentInvitationRepository.save(db, invitation)
        await db.commit()
        await db.refresh(invitation)
        return ParentInvitationResponse.model_validate(invitation)
