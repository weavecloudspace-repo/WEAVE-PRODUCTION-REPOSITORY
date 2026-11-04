"""Canonical teacher account, membership, invitation, and capability routes."""

from __future__ import annotations

from typing import Annotated, TypeAlias
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    get_current_teacher,
    get_current_teacher_account,
    get_current_tenant_admin,
)
from app.modules.auth.membership_summary_service import (
    AccountMembershipSummaryList,
    AccountMembershipSummaryService,
)
from app.modules.teachers.capability_service import (
    TeacherSubjectCapabilityListResponse,
    TeacherSubjectCapabilityService,
)
from app.modules.teachers.invitation_workflow_service import (
    TeacherInvitationWorkflowService,
)
from app.modules.teachers.models import (
    Teacher,
    TeacherAccount,
    TeacherInvitationStatus,
    TeacherMembershipStatus,
)
from app.modules.teachers.offboarding_service import (
    TeacherOffboardingImpactResponse,
    TeacherOffboardingRequest,
    TeacherOffboardingService,
)
from app.modules.teachers.patch_service import TeacherPatchService
from app.modules.teachers.registration_service import (
    TeacherRegistrationService,
)
from app.modules.teachers.schemas import (
    TeacherAccountOnboardingRequest,
    TeacherAccountProfileUpdateRequest,
    TeacherAccountRegisterRequest,
    TeacherAccountResponse,
    TeacherInvitationAcceptanceRequest,
    TeacherInvitationCreateRequest,
    TeacherInvitationPublicContextResponse,
    TeacherInvitationResponse,
    TeacherMembershipListResponse,
    TeacherMembershipReactivateRequest,
    TeacherMembershipResponse,
    TeacherMembershipSubjectUpdateRequest,
    TeacherMembershipSuspendRequest,
    TeacherMembershipUpdateRequest,
    TeacherMembershipWithAccountResponse,
    TeacherPasswordChangeRequest,
)
from app.modules.teachers.service import (
    TeacherAccountService,
    TeacherInvitationService,
    TeacherMembershipService,
)
from app.modules.tenant_admins.models import TenantAdmin

router = APIRouter(tags=["Teachers"])

CurrentTeacherAccount: TypeAlias = Annotated[
    TeacherAccount,
    Depends(get_current_teacher_account),
]
CurrentTeacherMembership: TypeAlias = Annotated[
    Teacher,
    Depends(get_current_teacher),
]
CurrentTenantAdmin: TypeAlias = Annotated[
    TenantAdmin,
    Depends(get_current_tenant_admin),
]


@router.post(
    "/accounts/register",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
)
async def register_teacher_account(
    payload: TeacherAccountRegisterRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> dict[str, object] | JSONResponse:
    result = await TeacherRegistrationService.register_account(
        db,
        payload,
        background_tasks,
    )
    if result.get("created") is False:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(result),
            background=background_tasks,
        )
    return result


@router.get(
    "/accounts/me",
    response_model=TeacherAccountResponse,
)
async def get_my_teacher_account(
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> TeacherAccountResponse:
    return await TeacherAccountService.get_account(
        db,
        account_id=current_account.id,
    )


@router.get("/accounts/me/onboarding-status")
async def get_my_teacher_account_onboarding_status(
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> dict[str, object]:
    return await TeacherAccountService.get_onboarding_status(
        db,
        account_id=current_account.id,
    )


@router.post(
    "/accounts/me/onboarding",
    response_model=TeacherAccountResponse,
)
async def complete_my_teacher_account_onboarding(
    payload: TeacherAccountOnboardingRequest,
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> TeacherAccountResponse:
    return await TeacherAccountService.complete_onboarding(
        db,
        account_id=current_account.id,
        payload=payload,
    )


@router.patch(
    "/accounts/me/profile",
    response_model=TeacherAccountResponse,
)
async def update_my_teacher_account_profile(
    payload: TeacherAccountProfileUpdateRequest,
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> TeacherAccountResponse:
    return await TeacherPatchService.update_account_profile(
        db,
        account_id=current_account.id,
        payload=payload,
    )


@router.post(
    "/accounts/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_my_teacher_account_password(
    payload: TeacherPasswordChangeRequest,
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> None:
    await TeacherAccountService.change_password(
        db,
        account_id=current_account.id,
        payload=payload,
    )


@router.get(
    "/accounts/me/memberships",
    response_model=AccountMembershipSummaryList,
)
async def list_my_teacher_memberships(
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> AccountMembershipSummaryList:
    return await AccountMembershipSummaryService.list_teacher_memberships(
        db,
        account_id=current_account.id,
    )


@router.post(
    "/accounts/me/invitations/accept",
    response_model=TeacherMembershipWithAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_teacher_invitation(
    payload: TeacherInvitationAcceptanceRequest,
    db: DbSession,
    current_account: CurrentTeacherAccount,
) -> TeacherMembershipWithAccountResponse:
    return await TeacherInvitationWorkflowService.accept_invitation(
        db,
        account=current_account,
        payload=payload,
    )


@router.get(
    "/invitations/context",
    response_model=TeacherInvitationPublicContextResponse,
)
async def get_teacher_invitation_context(
    token: str = Query(min_length=20, max_length=500),
    db: DbSession = None,
) -> TeacherInvitationPublicContextResponse:
    return await TeacherInvitationService.get_public_context(
        db,
        invitation_token=token,
    )


@router.get(
    "/me",
    response_model=TeacherMembershipWithAccountResponse,
)
async def get_my_teacher_membership(
    db: DbSession,
    current_membership: CurrentTeacherMembership,
) -> TeacherMembershipWithAccountResponse:
    return await TeacherMembershipService.get_membership(
        db,
        tenant_id=current_membership.tenant_id,
        membership_id=current_membership.id,
    )


@router.patch(
    "/me/membership",
    response_model=TeacherMembershipResponse,
)
async def update_my_teacher_membership_preferences(
    payload: TeacherMembershipUpdateRequest,
    db: DbSession,
    current_membership: CurrentTeacherMembership,
) -> TeacherMembershipResponse:
    return await TeacherPatchService.update_membership(
        db,
        actor=current_membership,
        membership_id=current_membership.id,
        payload=payload,
    )


@router.post(
    "/invitations",
    response_model=TeacherInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_teacher_invitation(
    payload: TeacherInvitationCreateRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherInvitationResponse:
    return await TeacherInvitationWorkflowService.create_invitation(
        db,
        actor=current_admin,
        payload=payload,
        background_tasks=background_tasks,
    )


@router.get(
    "/invitations",
    response_model=list[TeacherInvitationResponse],
)
async def list_teacher_invitations(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    search: str | None = Query(default=None, max_length=100),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    invitation_status: TeacherInvitationStatus | None = Query(
        default=None,
        alias="status",
    ),
) -> list[TeacherInvitationResponse]:
    invitations, _ = await TeacherInvitationService.list_for_tenant(
        db,
        tenant_id=current_admin.tenant_id,
        skip=skip,
        limit=limit,
        status=invitation_status,
        search=search,
    )
    return invitations


@router.post(
    "/invitations/{invitation_id}/revoke",
    response_model=TeacherInvitationResponse,
)
async def revoke_teacher_invitation(
    invitation_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherInvitationResponse:
    return await TeacherInvitationService.revoke_invitation(
        db,
        actor=current_admin,
        invitation_id=invitation_id,
    )


@router.get(
    "/memberships",
    response_model=TeacherMembershipListResponse,
)
async def list_teacher_memberships(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    membership_status: TeacherMembershipStatus | None = Query(
        default=None,
        alias="status",
    ),
) -> TeacherMembershipListResponse:
    return await TeacherMembershipService.list_for_tenant(
        db,
        tenant_id=current_admin.tenant_id,
        skip=skip,
        limit=limit,
        search=search,
        status=membership_status,
    )


@router.get(
    "/memberships/{membership_id}",
    response_model=TeacherMembershipWithAccountResponse,
)
async def get_teacher_membership(
    membership_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipWithAccountResponse:
    return await TeacherMembershipService.get_membership(
        db,
        tenant_id=current_admin.tenant_id,
        membership_id=membership_id,
    )


@router.patch(
    "/memberships/{membership_id}",
    response_model=TeacherMembershipResponse,
)
async def update_teacher_membership(
    membership_id: UUID,
    payload: TeacherMembershipUpdateRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipResponse:
    return await TeacherPatchService.update_membership(
        db,
        actor=current_admin,
        membership_id=membership_id,
        payload=payload,
    )


@router.post(
    "/memberships/{membership_id}/suspend",
    response_model=TeacherMembershipResponse,
)
async def suspend_teacher_membership(
    membership_id: UUID,
    payload: TeacherMembershipSuspendRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipResponse:
    return await TeacherMembershipService.suspend_membership(
        db,
        actor=current_admin,
        membership_id=membership_id,
        payload=payload,
    )


@router.get(
    "/memberships/{membership_id}/offboarding-impact",
    response_model=TeacherOffboardingImpactResponse,
)
async def inspect_teacher_offboarding_impact(
    membership_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherOffboardingImpactResponse:
    return await TeacherOffboardingService.inspect(
        db,
        tenant_id=current_admin.tenant_id,
        membership_id=membership_id,
    )


@router.post(
    "/memberships/{membership_id}/end",
    response_model=TeacherMembershipResponse,
)
async def end_teacher_membership(
    membership_id: UUID,
    payload: TeacherOffboardingRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipResponse:
    return await TeacherOffboardingService.end_membership_and_release_responsibilities(
        db,
        actor=current_admin,
        membership_id=membership_id,
        payload=payload,
    )


@router.post(
    "/memberships/{membership_id}/reactivate",
    response_model=TeacherMembershipResponse,
)
async def reactivate_teacher_membership(
    membership_id: UUID,
    payload: TeacherMembershipReactivateRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipResponse:
    return await TeacherMembershipService.reactivate_membership(
        db,
        actor=current_admin,
        membership_id=membership_id,
        payload=payload,
    )


@router.get(
    "/memberships/{membership_id}/subject-capabilities",
    response_model=TeacherSubjectCapabilityListResponse,
)
async def list_teacher_subject_capabilities(
    membership_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherSubjectCapabilityListResponse:
    return await TeacherSubjectCapabilityService.list_capabilities(
        db,
        tenant_id=current_admin.tenant_id,
        membership_id=membership_id,
    )


@router.put(
    "/memberships/{membership_id}/subject-capabilities",
    response_model=TeacherMembershipResponse,
)
async def replace_teacher_subject_capabilities(
    membership_id: UUID,
    payload: TeacherMembershipSubjectUpdateRequest,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> TeacherMembershipResponse:
    return await TeacherSubjectCapabilityService.replace_capabilities(
        db,
        actor=current_admin,
        membership_id=membership_id,
        payload=payload,
    )
