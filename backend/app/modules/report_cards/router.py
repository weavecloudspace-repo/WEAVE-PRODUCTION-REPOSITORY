from typing import Annotated, TypeAlias
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    get_current_onboarded_student,
    get_current_parent,
    get_current_tenant_admin,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.parents.models import Parent
from app.modules.report_cards.models import ReportCardStatus
from app.modules.report_cards.principal_comment_policy import (
    require_admin_template_for_performance,
)
from app.modules.report_cards.print_service import ReportCardPrintService
from app.modules.report_cards.repository import ReportCardRepository
from app.modules.report_cards.schemas import (
    ReportCardListResponse,
    ReportCardPrincipalCommentUpdate,
    ReportCardResponse,
)
from app.modules.report_cards.service import ReportCardService
from app.modules.students.models import Student
from app.modules.subscriptions.service import SubscriptionFeatureService
from app.modules.subscriptions.subscription_enums import FeatureCode
from app.modules.tenant_admins.models import TenantAdmin
from app.tenant_management.repository import TenantRepository

REPORT_CARD_HTML_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "img-src 'self' data: https:; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'none'"
    ),
}
REPORT_CARD_DATA_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _prevent_report_card_cache(response: Response) -> None:
    for key, value in REPORT_CARD_DATA_HEADERS.items():
        response.headers[key] = value


async def _apply_school_branding(
    db: DbSession,
    *,
    tenant_id: UUID,
    cards: list[ReportCardResponse],
) -> list[ReportCardResponse]:
    tenant = await TenantRepository.get_by_id(db, tenant_id)
    for card in cards:
        card.school_name = tenant.school_name if tenant else "Weave School"
        card.school_logo_url = tenant.logo_url if tenant else None
        card.school_address = tenant.address if tenant else None
        card.school_phone = tenant.phone if tenant else None
        card.school_email = tenant.email if tenant else None
    return cards


async def _brand_card(
    db: DbSession,
    *,
    tenant_id: UUID,
    card: ReportCardResponse,
) -> ReportCardResponse:
    await _apply_school_branding(db, tenant_id=tenant_id, cards=[card])
    return card


tenant_admin_router = APIRouter(
    prefix="/tenant-admin/academic/report-cards",
    tags=["Tenant Admin Report Cards"],
)
parent_router = APIRouter(
    prefix="/parents/me/children/{student_id}/academic/report-cards",
    tags=["Parent Report Cards"],
)
student_router = APIRouter(
    prefix="/students/me/academic/report-cards",
    tags=["Student Report Cards"],
)

CurrentTenantAdmin: TypeAlias = Annotated[TenantAdmin, Depends(get_current_tenant_admin)]
CurrentParent: TypeAlias = Annotated[Parent, Depends(get_current_parent)]
CurrentStudent: TypeAlias = Annotated[Student, Depends(get_current_onboarded_student)]


@tenant_admin_router.get("", response_model=ReportCardListResponse)
async def list_report_cards(
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
    student_id: UUID | None = Query(default=None),
    class_id: UUID | None = Query(default=None),
    academic_session_id: UUID | None = Query(default=None),
    academic_term_id: UUID | None = Query(default=None),
    status: ReportCardStatus | None = Query(default=None),
    is_outdated: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> ReportCardListResponse:
    _prevent_report_card_cache(response)
    items, total = await ReportCardService.list_cards(
        db,
        current_admin,
        student_id=student_id,
        class_id=class_id,
        academic_session_id=academic_session_id,
        academic_term_id=academic_term_id,
        status=status,
        is_outdated=is_outdated,
        search=search,
        skip=skip,
        limit=limit,
    )
    await _apply_school_branding(db, tenant_id=current_admin.tenant_id, cards=items)
    return ReportCardListResponse(items=items, total=total)


@tenant_admin_router.get("/{report_card_id}", response_model=ReportCardResponse)
async def get_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
    response: Response,
) -> ReportCardResponse:
    _prevent_report_card_cache(response)
    card = await ReportCardService.get(db, current_admin, report_card_id)
    return await _brand_card(db, tenant_id=current_admin.tenant_id, card=card)


@tenant_admin_router.post("/{report_card_id}/regenerate", response_model=ReportCardResponse)
async def regenerate_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> ReportCardResponse:
    await SubscriptionFeatureService.ensure_feature_enabled(
        db=db,
        tenant_id=current_admin.tenant_id,
        feature=FeatureCode.REPORT_CARDS,
    )
    card = await ReportCardService.regenerate(db, current_admin, report_card_id)
    return await _brand_card(db, tenant_id=current_admin.tenant_id, card=card)


@tenant_admin_router.patch(
    "/{report_card_id}/principal-comment",
    response_model=ReportCardResponse,
)
async def update_principal_comment(
    report_card_id: UUID,
    payload: ReportCardPrincipalCommentUpdate,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> ReportCardResponse:
    if payload.principal_template_id is not None:
        card_model = await ReportCardRepository.get_by_id(
            db,
            current_admin.tenant_id,
            report_card_id,
        )
        if card_model is None:
            raise NotFoundException("Report card not found.")
        await require_admin_template_for_performance(
            db,
            admin=current_admin,
            template_id=payload.principal_template_id,
            performance_percentage=card_model.average_score,
        )
    card = await ReportCardService.update_principal_comment(
        db, current_admin, report_card_id, payload
    )
    return await _brand_card(db, tenant_id=current_admin.tenant_id, card=card)


@tenant_admin_router.post("/{report_card_id}/publish", response_model=ReportCardResponse)
async def publish_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> ReportCardResponse:
    card = await ReportCardService.publish(db, current_admin, report_card_id)
    return await _brand_card(db, tenant_id=current_admin.tenant_id, card=card)


@tenant_admin_router.get("/{report_card_id}/print", response_class=HTMLResponse)
async def print_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> HTMLResponse:
    return HTMLResponse(
        await ReportCardPrintService.render_html(db, current_admin, report_card_id),
        headers=REPORT_CARD_HTML_HEADERS,
    )


@tenant_admin_router.get("/{report_card_id}/download", response_class=HTMLResponse)
async def download_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_admin: CurrentTenantAdmin,
) -> HTMLResponse:
    return HTMLResponse(
        await ReportCardPrintService.render_html(db, current_admin, report_card_id),
        headers=REPORT_CARD_HTML_HEADERS,
    )


@parent_router.get("", response_model=ReportCardListResponse)
async def list_child_report_cards(
    student_id: UUID,
    db: DbSession,
    current_parent: CurrentParent,
    response: Response,
    academic_session_id: UUID | None = Query(default=None),
    academic_term_id: UUID | None = Query(default=None),
) -> ReportCardListResponse:
    _prevent_report_card_cache(response)
    items, total = await ReportCardService.list_cards(
        db,
        current_parent,
        student_id=student_id,
        academic_session_id=academic_session_id,
        academic_term_id=academic_term_id,
    )
    await _apply_school_branding(db, tenant_id=current_parent.tenant_id, cards=items)
    return ReportCardListResponse(items=items, total=total)


@student_router.get("", response_model=ReportCardListResponse)
async def list_my_report_cards(
    db: DbSession,
    current_student: CurrentStudent,
    response: Response,
    academic_session_id: UUID | None = Query(default=None),
    academic_term_id: UUID | None = Query(default=None),
) -> ReportCardListResponse:
    _prevent_report_card_cache(response)
    items, total = await ReportCardService.list_cards(
        db,
        current_student,
        academic_session_id=academic_session_id,
        academic_term_id=academic_term_id,
    )
    await _apply_school_branding(db, tenant_id=current_student.tenant_id, cards=items)
    return ReportCardListResponse(items=items, total=total)


@student_router.get("/{report_card_id}", response_model=ReportCardResponse)
async def get_my_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_student: CurrentStudent,
    response: Response,
) -> ReportCardResponse:
    _prevent_report_card_cache(response)
    card = await ReportCardService.get(db, current_student, report_card_id)
    return await _brand_card(db, tenant_id=current_student.tenant_id, card=card)


@student_router.get("/{report_card_id}/print", response_class=HTMLResponse)
async def print_my_report_card(
    report_card_id: UUID,
    db: DbSession,
    current_student: CurrentStudent,
) -> HTMLResponse:
    return HTMLResponse(
        await ReportCardPrintService.render_html(db, current_student, report_card_id),
        headers=REPORT_CARD_HTML_HEADERS,
    )


@parent_router.get("/{report_card_id}", response_model=ReportCardResponse)
async def get_child_report_card(
    student_id: UUID,
    report_card_id: UUID,
    db: DbSession,
    current_parent: CurrentParent,
    response: Response,
) -> ReportCardResponse:
    _prevent_report_card_cache(response)
    card = await ReportCardService.get(db, current_parent, report_card_id)
    if card.student_id != student_id:
        raise ForbiddenException("Report card does not belong to this child.")
    return await _brand_card(db, tenant_id=current_parent.tenant_id, card=card)


@parent_router.get("/{report_card_id}/print", response_class=HTMLResponse)
async def print_child_report_card(
    student_id: UUID,
    report_card_id: UUID,
    db: DbSession,
    current_parent: CurrentParent,
) -> HTMLResponse:
    card = await ReportCardService.get(db, current_parent, report_card_id)
    if card.student_id != student_id:
        raise ForbiddenException("Report card does not belong to this child.")
    return HTMLResponse(
        await ReportCardPrintService.render_html(db, current_parent, report_card_id),
        headers=REPORT_CARD_HTML_HEADERS,
    )
