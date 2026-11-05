"""Authenticated admin/teacher TMA authoring and student attempt endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import TypeAdapter

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    get_current_onboarded_student,
    get_current_tenant_member,
)
from app.core.exceptions import ForbiddenException, ConflictException, NotFoundException
from app.modules.tma.cache import cached_staff_read
from app.modules.students.models import Student
from app.modules.teachers.models import TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.models import TMAAssignmentStatus
from app.modules.tma.assignment_service import TMAAssignmentService
from app.modules.tma.cancellation_service import TMACancellationService
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.lifecycle_service import TMALifecycleService
from app.modules.tma.media_service import TMAMediaService
from app.modules.tma.question_service import TMAQuestionService
from app.modules.tma.reporting_service import TMAReportingService
from app.modules.tma.authorization import TMAAuthorizationService
from app.modules.tma.repository import TMARevisionRepository
from app.modules.tma.schemas import (
    TMAAnswerSaveRequest,
    TMAAuthoringConfiguration,
    TMAAuthoringTerm,
    TMAAnswerSaveResponse,
    TMAAssignmentCreate,
    TMAAssignmentListResponse,
    TMAAssignmentResponse,
    TMAAssignmentStatusResponse,
    TMAReopenRequest,
    TMAAssignmentUpdate,
    TMACancellationRequest,
    TMACancellationConflictResponse,
    TMAZeroGradingConflictResponse,
    TMAZeroExemptionRequest,
    TMACancellationRunResponse,
    TMARevisionResponse,
    TMARevisionHistoryResponse,
    TMAQuestionAdminResponse,
    TMAQuestionCreate,
    TMAQuestionUpdate,
    TMAMediaAssetResponse,
    TMAMediaDeleteResponse,
    TMAMediaSignedUrlResponse,
    TMAStartResponse,
    TMAStudentAssignmentResponse,
    TMASubmitResponse,
    TMAParticipationStatus,
    TMASubmissionListResponse,
)


author_router = APIRouter(prefix="/tma", tags=["TMA Authoring"])
student_router = APIRouter(prefix="/students/tma", tags=["Student TMA"])


async def _current_author(
    actor: Annotated[object, Depends(get_current_tenant_member)],
) -> TenantAdmin | TeacherMembership:
    if not isinstance(actor, (TenantAdmin, TeacherMembership)):
        raise ForbiddenException("TMA authoring requires a teacher or administrator.")
    return actor


Author = Annotated[TenantAdmin | TeacherMembership, Depends(_current_author)]
CurrentStudent = Annotated[Student, Depends(get_current_onboarded_student)]


@author_router.get("/configuration", response_model=TMAAuthoringConfiguration)
async def authoring_configuration(db: DbSession, actor: Author):
    from app.modules.tma.configuration_service import get_authoring_configuration

    async def fetch():
        return TMAAuthoringConfiguration.model_validate(
            await get_authoring_configuration(db, actor)
        ).model_dump(mode="json")

    if isinstance(actor, TeacherMembership):
        # A fresh bulk query enforces current membership and teaching scope;
        # rechecking cached scopes individually caused an authorization N+1.
        return TMAAuthoringConfiguration.model_validate(await fetch())
    return TMAAuthoringConfiguration.model_validate(
        await cached_staff_read(actor, "configuration", fetch, ttl=60)
    )


def _admin_question(question, options) -> TMAQuestionAdminResponse:
    return TMAQuestionAdminResponse(
        id=question.id,
        assignment_id=question.assignment_id,
        revision_id=question.revision_id,
        position=question.position,
        version=question.version,
        question_text=question.question_text,
        image_asset_id=question.image_asset_id,
        author_actor_type=question.author_actor_type,
        author_actor_id=question.author_actor_id,
        options=[
            {
                "id": option.id,
                "question_id": question.id,
                "position": option.position,
                "option_text": option.option_text,
                "image_asset_id": option.image_asset_id,
                "is_correct": option.is_correct,
            }
            for option in options
        ],
    )


@author_router.get("/terms", response_model=list[TMAAuthoringTerm])
async def authoring_terms(db: DbSession, actor: Author) -> list[TMAAuthoringTerm]:
    from app.modules.tma.configuration_service import list_authoring_terms

    return [TMAAuthoringTerm.model_validate(row) for row in await list_authoring_terms(db, actor)]


@author_router.post(
    "/assignments", response_model=TMAAssignmentResponse, status_code=status.HTTP_201_CREATED
)
async def create_assignment(
    payload: TMAAssignmentCreate,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.create_assignment(db, actor=actor, payload=payload)
    return TMAAssignmentResponse.model_validate(item)


@author_router.get("/assignments", response_model=TMAAssignmentListResponse)
async def list_assignments(
    db: DbSession,
    actor: Author,
    academic_term_id: uuid.UUID | None = None,
    academic_level_id: uuid.UUID | None = None,
    status: TMAAssignmentStatus | None = None,
    search: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> TMAAssignmentListResponse:
    async def fetch():
        items, total = await TMAAssignmentService.list_assignments(
            db,
            actor=actor,
            academic_term_id=academic_term_id,
            academic_level_id=academic_level_id,
            status=status,
            search=search,
            offset=offset,
            limit=limit,
        )
        return TMAAssignmentListResponse(
            items=[TMAAssignmentResponse.model_validate(item) for item in items],
            total=total,
            offset=offset,
            limit=limit,
        ).model_dump(mode="json")

    # Teacher scope can be revoked without a TMA write. Query it fresh on every
    # request so a cached page cannot disclose revoked assignments or stale totals.
    if isinstance(actor, TeacherMembership):
        return TMAAssignmentListResponse.model_validate(await fetch())
    return TMAAssignmentListResponse.model_validate(
        await cached_staff_read(
            actor,
            "assignments",
            fetch,
            params={
                "term": academic_term_id,
                "level": academic_level_id,
                "status": status.value if status else None,
                "search": search,
                "offset": offset,
                "limit": limit,
            },
            ttl=15,
        )
    )


@author_router.get("/assignments/{assignment_id}", response_model=TMAAssignmentResponse)
async def get_assignment(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.get_assignment(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMAAssignmentResponse.model_validate(item)


@author_router.patch("/assignments/{assignment_id}", response_model=TMAAssignmentResponse)
async def update_assignment(
    assignment_id: uuid.UUID,
    payload: TMAAssignmentUpdate,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.update_draft_assignment(
        db,
        actor=actor,
        assignment_id=assignment_id,
        payload=payload,
    )
    return TMAAssignmentResponse.model_validate(item)


@author_router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_assignment(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> None:
    from app.modules.tma.draft_deletion_service import TMADraftDeletionService

    await TMADraftDeletionService.delete_draft(db, actor=actor, assignment_id=assignment_id)


@author_router.get("/assignments/{assignment_id}/readiness", response_model=list[str])
async def assignment_readiness(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> list[str]:
    return await TMALifecycleService.get_assignment_readiness(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )


@author_router.post(
    "/assignments/{assignment_id}/activate", response_model=TMAAssignmentStatusResponse
)
async def activate_assignment(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentStatusResponse:
    item = await TMALifecycleService.activate_assignment(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMAAssignmentStatusResponse.model_validate(item)


@author_router.post(
    "/assignments/{assignment_id}/reopen", response_model=TMAAssignmentStatusResponse
)
async def reopen_assignment(
    assignment_id: uuid.UUID,
    payload: TMAReopenRequest,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentStatusResponse:
    item = await TMALifecycleService.reopen_assignment(
        db, actor=actor, assignment_id=assignment_id, closes_at=payload.closes_at
    )
    return TMAAssignmentStatusResponse.model_validate(item)


@author_router.get(
    "/assignments/{assignment_id}/questions", response_model=list[TMAQuestionAdminResponse]
)
async def list_questions(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> list[TMAQuestionAdminResponse]:
    await TMAAssignmentService.get_assignment(db, actor=actor, assignment_id=assignment_id)
    adapter = TypeAdapter(list[TMAQuestionAdminResponse])

    async def fetch():
        rows = await TMAQuestionService.list_questions(db, actor=actor, assignment_id=assignment_id)
        return [
            _admin_question(question, options).model_dump(mode="json") for question, options in rows
        ]

    return adapter.validate_python(
        await cached_staff_read(
            actor, "questions", fetch, params={"assignment": assignment_id}, ttl=15
        )
    )


@author_router.post(
    "/assignments/{assignment_id}/questions",
    response_model=TMAQuestionAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    assignment_id: uuid.UUID,
    payload: TMAQuestionCreate,
    db: DbSession,
    actor: Author,
) -> TMAQuestionAdminResponse:
    question = await TMAQuestionService.add_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        payload=payload,
    )
    row, options = await TMAQuestionService.get_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question_id=question.id,
    )
    return _admin_question(row, options)


@author_router.patch(
    "/assignments/{assignment_id}/questions/{question_id}",
    response_model=TMAQuestionAdminResponse,
)
async def update_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: TMAQuestionUpdate,
    db: DbSession,
    actor: Author,
) -> TMAQuestionAdminResponse:
    await TMAQuestionService.update_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question_id=question_id,
        payload=payload,
    )
    row, options = await TMAQuestionService.get_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question_id=question_id,
    )
    return _admin_question(row, options)


@author_router.delete(
    "/assignments/{assignment_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> None:
    await TMAQuestionService.delete_question(
        db,
        actor=actor,
        assignment_id=assignment_id,
        question_id=question_id,
    )


@student_router.get("/assignments", response_model=list[TMAStudentAssignmentResponse])
async def list_my_assignments(
    db: DbSession,
    student: CurrentStudent,
) -> list[TMAStudentAssignmentResponse]:
    return await TMAAttemptService.list_available_assignments(db, student=student)


@student_router.post("/assignments/{assignment_id}/start", response_model=TMAStartResponse)
async def start_assignment(
    assignment_id: uuid.UUID,
    db: DbSession,
    student: CurrentStudent,
) -> TMAStartResponse:
    return await TMAAttemptService.start_or_resume_attempt(
        db,
        student=student,
        assignment_id=assignment_id,
    )


@student_router.get("/attempts/{attempt_id}", response_model=TMAStartResponse)
async def resume_assignment(
    attempt_id: uuid.UUID,
    db: DbSession,
    student: CurrentStudent,
) -> TMAStartResponse:
    return await TMAAttemptService.get_attempt(
        db,
        student=student,
        attempt_id=attempt_id,
    )


@student_router.put("/attempts/{attempt_id}/answer", response_model=TMAAnswerSaveResponse)
async def save_my_answer(
    attempt_id: uuid.UUID,
    payload: TMAAnswerSaveRequest,
    db: DbSession,
    student: CurrentStudent,
) -> TMAAnswerSaveResponse:
    return await TMAAttemptService.save_answer(
        db,
        student=student,
        attempt_id=attempt_id,
        payload=payload,
    )


@student_router.post("/attempts/{attempt_id}/submit", response_model=TMASubmitResponse)
async def submit_assignment(
    attempt_id: uuid.UUID,
    db: DbSession,
    student: CurrentStudent,
) -> TMASubmitResponse:
    return await TMAAttemptService.submit_attempt(
        db,
        student=student,
        attempt_id=attempt_id,
    )


@student_router.get("/attempts/{attempt_id}/result", response_model=TMASubmitResponse)
async def get_my_score(
    attempt_id: uuid.UUID,
    db: DbSession,
    student: CurrentStudent,
) -> TMASubmitResponse:
    return await TMAAttemptService.get_submission_result(
        db,
        student=student,
        attempt_id=attempt_id,
    )


@author_router.post(
    "/assignments/{assignment_id}/images",
    response_model=TMAMediaAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_tma_image(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
    file: Annotated[UploadFile, File()],
) -> TMAMediaAssetResponse:
    asset = await TMAMediaService.upload_image(
        db,
        actor=actor,
        assignment_id=assignment_id,
        file=file,
    )
    return TMAMediaAssetResponse.model_validate(asset)


@author_router.get(
    "/assignments/{assignment_id}/images",
    response_model=list[TMAMediaAssetResponse],
)
async def list_tma_images(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> list[TMAMediaAssetResponse]:
    await TMAAssignmentService.get_assignment(db, actor=actor, assignment_id=assignment_id)

    async def fetch():
        assets = await TMAMediaService.list_assignment_images(
            db, actor=actor, assignment_id=assignment_id
        )
        return [
            TMAMediaAssetResponse.model_validate(asset).model_dump(mode="json") for asset in assets
        ]

    return TypeAdapter(list[TMAMediaAssetResponse]).validate_python(
        await cached_staff_read(
            actor, "images", fetch, params={"assignment": assignment_id}, ttl=60
        )
    )


@author_router.get(
    "/assignments/{assignment_id}/images/{asset_id}/url",
    response_model=TMAMediaSignedUrlResponse,
)
async def get_tma_image_url(
    assignment_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMAMediaSignedUrlResponse:
    return await TMAMediaService.get_image_url(
        db,
        actor=actor,
        assignment_id=assignment_id,
        asset_id=asset_id,
    )


@author_router.delete(
    "/assignments/{assignment_id}/images/{asset_id}",
    response_model=TMAMediaDeleteResponse,
)
async def delete_unused_tma_image(
    assignment_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMAMediaDeleteResponse:
    return await TMAMediaService.delete_unused_image(
        db,
        actor=actor,
        assignment_id=assignment_id,
        asset_id=asset_id,
    )


@student_router.get(
    "/attempts/{attempt_id}/images/{asset_id}/url",
    response_model=TMAMediaSignedUrlResponse,
)
async def get_student_tma_image_url(
    attempt_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: DbSession,
    student: CurrentStudent,
) -> TMAMediaSignedUrlResponse:
    return await TMAMediaService.get_student_image_url(
        db,
        student=student,
        attempt_id=attempt_id,
        asset_id=asset_id,
    )


@author_router.get(
    "/assignments/{assignment_id}/submissions",
    response_model=TMASubmissionListResponse,
)
async def list_assignment_submissions(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
    search: str | None = Query(default=None, max_length=200),
    class_id: uuid.UUID | None = None,
    participation_status: TMAParticipationStatus | None = Query(
        default=None,
        alias="status",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> TMASubmissionListResponse:
    """List eligible and historically participating students, without analytics."""
    return await TMAReportingService.list_assignment_participation(
        db,
        actor=actor,
        assignment_id=assignment_id,
        search=search,
        class_id=class_id,
        participation_status=participation_status,
        offset=offset,
        limit=limit,
    )


@author_router.post(
    "/assignments/{assignment_id}/close",
    response_model=TMAAssignmentStatusResponse,
)
async def close_assignment(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMAAssignmentStatusResponse:
    assignment = await TMACancellationService.close(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMAAssignmentStatusResponse.model_validate(assignment)


@author_router.post(
    "/assignments/{assignment_id}/cancel",
    response_model=TMACancellationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_assignment(
    assignment_id: uuid.UUID,
    payload: TMACancellationRequest,
    db: DbSession,
    actor: Author,
) -> TMACancellationRunResponse:
    run = await TMACancellationService.cancel(
        db,
        actor=actor,
        assignment_id=assignment_id,
        reason=payload.reason,
    )
    return TMACancellationRunResponse.model_validate(run)


@author_router.get(
    "/assignments/{assignment_id}/cancellation",
    response_model=TMACancellationRunResponse,
)
async def get_cancellation(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMACancellationRunResponse:
    run = await TMACancellationService.get_status(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMACancellationRunResponse.model_validate(run)


@author_router.get(
    "/assignments/{assignment_id}/deadline-zeros/conflicts",
    response_model=list[TMAZeroGradingConflictResponse],
)
async def get_deadline_zero_conflicts(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> list[TMAZeroGradingConflictResponse]:
    from app.modules.tma.zero_reconciliation_service import TMAZeroReconciliationService

    rows = await TMAZeroReconciliationService.list_conflicts(
        db, actor=actor, assignment_id=assignment_id
    )
    return [TMAZeroGradingConflictResponse.model_validate(row) for row in rows]


@author_router.post(
    "/assignments/{assignment_id}/deadline-zeros/exempt/{student_id}",
    response_model=TMAZeroGradingConflictResponse,
)
async def exempt_deadline_zero(
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    payload: TMAZeroExemptionRequest,
    db: DbSession,
    actor: Author,
) -> TMAZeroGradingConflictResponse:
    from app.modules.tma.zero_reconciliation_service import TMAZeroReconciliationService

    row = await TMAZeroReconciliationService.exempt(
        db,
        actor=actor,
        assignment_id=assignment_id,
        student_id=student_id,
        reason=payload.reason,
    )
    return TMAZeroGradingConflictResponse.model_validate(row)


@author_router.get(
    "/assignments/{assignment_id}/cancellation/conflicts",
    response_model=list[TMACancellationConflictResponse],
)
async def get_cancellation_conflicts(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> list[TMACancellationConflictResponse]:
    from app.modules.tma.cancellation_reconciliation_service import (
        TMACancellationReconciliationService,
    )

    rows = await TMACancellationReconciliationService.conflicts(
        db, actor=actor, assignment_id=assignment_id
    )
    return [TMACancellationConflictResponse.model_validate(row) for row in rows]


@author_router.post(
    "/assignments/{assignment_id}/cancellation/retry",
    response_model=TMACancellationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_cancellation(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMACancellationRunResponse:
    run = await TMACancellationService.retry(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMACancellationRunResponse.model_validate(run)


@author_router.post(
    "/assignments/{assignment_id}/revisions",
    response_model=TMARevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_corrected_revision(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMARevisionResponse:
    revision = await TMACancellationService.create_revision(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )
    return TMARevisionResponse.model_validate(revision)


@author_router.get(
    "/assignments/{assignment_id}/revisions",
    response_model=TMARevisionHistoryResponse,
)
async def list_assignment_revisions(
    assignment_id: uuid.UUID,
    db: DbSession,
    actor: Author,
) -> TMARevisionHistoryResponse:
    assignment = await TMAAssignmentService.get_assignment(
        db,
        actor=actor,
        assignment_id=assignment_id,
    )

    async def fetch():
        revisions = await TMARevisionRepository.list_for_assignment(
            db, actor.tenant_id, assignment.id
        )
        return TMARevisionHistoryResponse(
            assignment_id=assignment.id,
            revisions=[TMARevisionResponse.model_validate(item) for item in revisions],
        ).model_dump(mode="json")

    return TMARevisionHistoryResponse.model_validate(
        await cached_staff_read(
            actor, "revisions", fetch, params={"assignment": assignment.id}, ttl=30
        )
    )
