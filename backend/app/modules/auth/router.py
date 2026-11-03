"""Authentication, membership selection, refresh, logout, OTP, and recovery routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Request,
    Response,
    status,
)

from app.config.settings import settings
from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import get_current_actor
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.rate_limits.auth_rate_limits import AuthRateLimitService
from app.modules.auth.schemas import (
    LoginRequest,
    LoginSessionUser,
    MembershipSelectionRequest,
    RequestOTP,
    SessionBootstrapResponse,
    TenantActivationRequest,
    Token,
    UpdatePassword,
    VerifyOTP,
)
from app.modules.auth.service import (
    AuthenticatedActor,
    AuthService,
    AuthSessionService,
    OTPService,
    TenantActivationService,
)
from app.modules.auth.student_authentication import authenticate_student_actor
from app.modules.legal_compliance.service import LegalComplianceService
from app.modules.parents.models import Parent, ParentAccount
from app.modules.students.models import Student
from app.modules.superadmin.models import SuperAdmin
from app.modules.superadmin.platform_control_service import PlatformControlService
from app.modules.superadmin.security_response_service import SecurityResponseService
from app.modules.teachers.models import Teacher, TeacherAccount
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository

router = APIRouter()
REFRESH_TOKEN_COOKIE_NAME = "weave_refresh_token"
REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"

CurrentActorDependency = Annotated[
    SuperAdmin | TenantAdmin | Teacher | Parent | Student | TeacherAccount | ParentAccount,
    Depends(get_current_actor),
]


def _refresh_cookie_secure() -> bool:
    return not settings.is_development


def _refresh_cookie_samesite() -> str:
    if (settings.ALLOW_CROSS_SITE_REFRESH_COOKIE and settings.ENV.value == "prod"
            and datetime.now(timezone.utc) < datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc)):
        return "none"
    return "none" if settings.ENV.value == "stg" else "lax"


def _refresh_cookie_max_age(expires_at: datetime) -> int:
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return max(int((expires_at - now).total_seconds()), 0)


def _set_refresh_token_cookie(
    response: Response,
    *,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        max_age=_refresh_cookie_max_age(expires_at),
        path=REFRESH_COOKIE_PATH,
        secure=_refresh_cookie_secure(),
        httponly=True,
        samesite=_refresh_cookie_samesite(),
    )


def _delete_refresh_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=_refresh_cookie_secure(),
        httponly=True,
        samesite=_refresh_cookie_samesite(),
    )


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return request.client.host if request.client else None


def _actor_type_and_role(actor: CurrentActorDependency) -> tuple[str, str, str]:
    if isinstance(actor, SuperAdmin):
        return "superadmin", "superadmin", "superadmin"
    if isinstance(actor, TenantAdmin):
        return "tenant_admin", "tenant_admin", "admin"
    if isinstance(actor, Teacher):
        return "teacher", "teacher_account", "teacher"
    if isinstance(actor, TeacherAccount):
        return "teacher_account", "teacher_account", "teacher"
    if isinstance(actor, Parent):
        return "parent", "parent_account", "parent"
    if isinstance(actor, ParentAccount):
        return "parent_account", "parent_account", "parent"
    if isinstance(actor, Student):
        return "student", "student", "student"
    raise UnauthorizedException("Invalid session actor.")


async def _build_session_bootstrap_response(
    db: DbSession,
    actor: CurrentActorDependency,
) -> SessionBootstrapResponse:
    actor_type, account_type, role = _actor_type_and_role(actor)
    tenant_id = getattr(actor, "tenant_id", None)
    tenant = await TenantRepository.get_by_id(db, tenant_id) if tenant_id else None

    if isinstance(actor, Student):
        email = actor.admission_number
        admission_number = actor.admission_number
        first_name = actor.first_name
        last_name = actor.last_name
        passport_photo_url = actor.passport_photo_url
        meta = None
    elif isinstance(actor, Parent):
        account = actor.parent_account
        email = account.email
        admission_number = None
        first_name = account.first_name
        last_name = account.last_name
        passport_photo_url = None
        meta = {
            "parent_account_id": str(account.id),
            "membership_status": actor.status.value,
        }
    elif isinstance(actor, Teacher):
        account = actor.teacher_account
        email = account.email
        admission_number = None
        first_name = account.first_name
        last_name = account.last_name
        passport_photo_url = account.passport_photo_url
        meta = {
            "teacher_account_id": str(account.id),
            "membership_status": actor.status.value,
        }
    else:
        email = getattr(actor, "email", None)
        admission_number = None
        first_name = getattr(actor, "first_name", None)
        last_name = getattr(actor, "last_name", None)
        passport_photo_url = getattr(actor, "passport_photo_url", None)
        meta = None
        if isinstance(actor, (ParentAccount, TeacherAccount)):
            meta = {
                "profile_completed": actor.profile_completed,
                "onboarding_required": not actor.profile_completed,
            }

    user = LoginSessionUser(
        id=str(actor.id),
        tenant_id=str(tenant_id) if tenant_id else None,
        school_name=tenant.school_name if tenant else None,
        email=email,
        admission_number=admission_number,
        first_name=first_name,
        last_name=last_name,
        actor_type=actor_type,
        account_type=account_type,
        role=role,
        password_reset_required=getattr(actor, "password_reset_required", None),
        profile_status=(getattr(getattr(actor, "profile_status", None), "value", None)),
        meta=meta,
        passport_photo_url=passport_photo_url,
        tenant_logo_url=tenant.logo_url if tenant else None,
    )
    legal_status = await LegalComplianceService.get_status(db, actor)
    legal_accepted_at = legal_status["accepted_at"]
    legal_accepted_at_value = (
        legal_accepted_at.isoformat() if legal_accepted_at is not None else None
    )
    user.legal_compliance_required = not bool(legal_status["accepted"])
    user.legal_compliance_policy_version = str(legal_status["policy_version"])
    user.legal_compliance_accepted_at = legal_accepted_at_value
    return SessionBootstrapResponse(
        authenticated=True,
        actor_type=actor_type,
        account_type=account_type,
        role=role,
        tenant_id=str(tenant_id) if tenant_id else None,
        email=email,
        password_reset_required=getattr(actor, "password_reset_required", None),
        user=user,
        legal_compliance_required=not bool(legal_status["accepted"]),
        legal_compliance_policy_version=str(legal_status["policy_version"]),
        legal_compliance_accepted_at=legal_accepted_at_value,
    )


class LoginResponse(Token):
    detail: str | None = None
    resend_otp_available: bool = False
    email: str | None = None
    actor_type: str | None = None
    role: str | None = None
    account_type: str | None = None
    password_reset_required: bool | None = None
    user: LoginSessionUser | None = None
    legal_compliance_required: bool = True
    legal_compliance_policy_version: str | None = None
    legal_compliance_accepted_at: str | None = None


def _legal_identity_from_authenticated_actor(
    actor: AuthenticatedActor,
) -> tuple[str, str]:
    actor_type = str(actor.actor_type)
    account_type = str(actor.account_type)
    user_meta = actor.user.meta if actor.user and actor.user.meta else {}
    if actor_type == "teacher" and user_meta.get("teacher_account_id"):
        return "teacher_account", str(user_meta["teacher_account_id"])
    if actor_type == "parent" and user_meta.get("parent_account_id"):
        return "parent_account", str(user_meta["parent_account_id"])
    if actor_type in {"teacher_account", "parent_account"}:
        return actor_type, str(actor.actor_id)
    if account_type in {"teacher_account", "parent_account"} and actor.user and actor.user.id:
        return account_type, str(actor.user.id)
    return actor_type, str(actor.actor_id)


async def _legal_status_for_authenticated_actor(
    db: DbSession,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    actor_type, actor_id = _legal_identity_from_authenticated_actor(actor)
    return await LegalComplianceService.get_status_for_identity(
        db,
        actor_type=actor_type,
        actor_id=UUID(actor_id),
    )


def _apply_legal_status_to_login_response(
    response: LoginResponse,
    legal_status: dict[str, object],
) -> LoginResponse:
    accepted_at = legal_status["accepted_at"]
    accepted_at_value = accepted_at.isoformat() if accepted_at is not None else None
    response.legal_compliance_required = not bool(legal_status["accepted"])
    response.legal_compliance_policy_version = str(legal_status["policy_version"])
    response.legal_compliance_accepted_at = accepted_at_value
    if response.user is not None:
        response.user.legal_compliance_required = response.legal_compliance_required
        response.user.legal_compliance_policy_version = response.legal_compliance_policy_version
        response.user.legal_compliance_accepted_at = accepted_at_value
    return response


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
) -> LoginResponse:
    client_ip = _client_ip(request)
    await AuthRateLimitService.check_login_allowed(
        identifier=payload.identifier,
        ip_address=client_ip,
    )
    try:
        actor = (
            await AuthService.authenticate_actor(
                db,
                payload,
                background_tasks=background_tasks,
            )
            if "@" in payload.identifier
            else await authenticate_student_actor(
                db,
                admission_number=payload.identifier,
                credential=payload.password,
            )
        )
    except UnauthorizedException:
        await AuthRateLimitService.record_failed_login(
            identifier=payload.identifier,
            ip_address=client_ip,
        )
        raise

    await SecurityResponseService.enforce_actor_ip_allowed(
        db=db,
        ip_address=client_ip,
        actor_type=actor.actor_type,
    )
    await PlatformControlService.enforce_actor_allowed(
        db=db,
        actor_type=actor.actor_type,
    )
    await AuthRateLimitService.clear_login_failures(
        identifier=payload.identifier,
        ip_address=client_ip,
    )
    token_pair = await AuthSessionService.create_login_session(
        db,
        actor=actor,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip,
        remember_me=payload.remember_me,
    )
    _set_refresh_token_cookie(
        response,
        refresh_token=token_pair.refresh_token,
        expires_at=token_pair.refresh_token_expires_at,
    )
    login_response = LoginResponse(
        access_token=token_pair.access_token,
        email=actor.email,
        actor_type=actor.actor_type,
        role=actor.role,
        account_type=actor.account_type,
        password_reset_required=actor.password_reset_required,
        user=actor.user,
    )
    legal_status = await _legal_status_for_authenticated_actor(db, actor)
    return _apply_legal_status_to_login_response(login_response, legal_status)


@router.post("/select-membership", response_model=LoginResponse)
async def select_membership(
    payload: MembershipSelectionRequest,
    db: DbSession,
    current_actor: CurrentActorDependency,
    request: Request,
    response: Response,
    existing_refresh_token: str | None = Cookie(
        default=None,
        alias=REFRESH_TOKEN_COOKIE_NAME,
    ),
) -> LoginResponse:
    if isinstance(current_actor, ParentAccount):
        account = current_actor
    elif isinstance(current_actor, Parent):
        account = current_actor.parent_account
    elif isinstance(current_actor, TeacherAccount):
        account = current_actor
    elif isinstance(current_actor, Teacher):
        account = current_actor.teacher_account
    else:
        raise ForbiddenException("This account cannot switch school memberships.")

    selected_actor = await AuthService.select_membership(
        db,
        account=account,
        membership_id=payload.membership_id,
    )
    if existing_refresh_token:
        await AuthSessionService.logout_by_refresh_token(
            db,
            refresh_token=existing_refresh_token,
        )
    token_pair = await AuthSessionService.create_login_session(
        db,
        actor=selected_actor,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        remember_me=payload.remember_me,
    )
    _set_refresh_token_cookie(
        response,
        refresh_token=token_pair.refresh_token,
        expires_at=token_pair.refresh_token_expires_at,
    )
    login_response = LoginResponse(
        access_token=token_pair.access_token,
        email=selected_actor.email,
        actor_type=selected_actor.actor_type,
        role=selected_actor.role,
        account_type=selected_actor.account_type,
        user=selected_actor.user,
    )
    legal_status = await _legal_status_for_authenticated_actor(db, selected_actor)
    return _apply_legal_status_to_login_response(login_response, legal_status)


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    db: DbSession,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    refresh_token: str | None = Cookie(
        default=None,
        alias=REFRESH_TOKEN_COOKIE_NAME,
    ),
) -> Token:
    if refresh_token is None:
        raise UnauthorizedException("Invalid session.")
    token_pair = await AuthSessionService.rotate_refresh_token(
        db,
        background_tasks=background_tasks,
        refresh_token=refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    _set_refresh_token_cookie(
        response,
        refresh_token=token_pair.refresh_token,
        expires_at=token_pair.refresh_token_expires_at,
    )
    return Token(access_token=token_pair.access_token)


@router.post("/logout")
async def logout(
    db: DbSession,
    response: Response,
    refresh_token: str | None = Cookie(
        default=None,
        alias=REFRESH_TOKEN_COOKIE_NAME,
    ),
) -> dict[str, str]:
    if refresh_token:
        await AuthSessionService.logout_by_refresh_token(
            db,
            refresh_token=refresh_token,
        )
    _delete_refresh_token_cookie(response)
    return {"detail": "Logged out successfully."}


@router.get("/me/session", response_model=SessionBootstrapResponse)
async def get_current_session(
    db: DbSession,
    current_actor: CurrentActorDependency,
) -> SessionBootstrapResponse:
    return await _build_session_bootstrap_response(db, current_actor)


@router.post("/request-otp")
async def request_otp(
    payload: RequestOTP,
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    await AuthRateLimitService.check_otp_request_ip_allowed(
        purpose=payload.purpose,
        ip_address=_client_ip(request),
    )
    return await OTPService.generate_otp(
        db,
        payload,
        background_tasks=background_tasks,
    )


@router.post("/verify-otp")
async def verify_otp(
    payload: VerifyOTP,
    db: DbSession,
    request: Request,
) -> dict[str, str]:
    client_ip = _client_ip(request)
    await AuthRateLimitService.check_otp_verify_allowed(
        email=str(payload.email),
        purpose=payload.purpose,
        ip_address=client_ip,
    )
    result = await OTPService.verify_otp(db, payload)
    await AuthRateLimitService.clear_otp_verification_failures(
        email=str(payload.email),
        purpose=payload.purpose,
        ip_address=client_ip,
    )
    return result


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(payload: UpdatePassword, db: DbSession) -> None:
    await AuthService.reset_password(db, payload)


@router.post("/activate-tenant")
async def activate_tenant(
    payload: TenantActivationRequest,
    db: DbSession,
) -> dict[str, str]:
    return await TenantActivationService.activate_tenant(db, payload)
