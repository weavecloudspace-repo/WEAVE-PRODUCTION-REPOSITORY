"""Authenticated admin/teacher TMA authoring and student attempt endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies.db import DbSession
from app.core.dependencies.route_guards import (
    get_current_onboarded_student,
    get_current_tenant_member,
)
from app.core.exceptions import ForbiddenException
from app.modules.students.models import Student
from app.modules.teachers.models import TeacherMembership
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.tma.assignment_service import TMAAssignmentService
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.lifecycle_service import TMALifecycleService
from app.modules.tma.question_service import TMAQuestionService
from app.modules.tma.schemas import (
    TMAAnswerSaveRequest,
    TMAAnswerSaveResponse,
    TMAAssignmentCreate,
    TMAAssignmentListResponse,
    TMAAssignmentResponse,
    TMAAssignmentStatusResponse,
    TMAAssignmentUpdate,
    TMAQuestionAdminResponse,
    TMAQuestionCreate,
    TMAQuestionUpdate,
    TMAStartResponse,
    TMAStudentAssignmentResponse,
    TMASubmitResponse,
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


def _admin_question(question, options) -> TMAQuestionAdminResponse:
    return TMAQuestionAdminResponse(
        id=question.id, assignment_id=question.assignment_id,
        revision_id=question.revision_id,
        position=question.position, version=question.version,
        question_text=question.question_text,
        image_asset_id=question.image_asset_id,
        author_actor_type=question.author_actor_type,
        author_actor_id=question.author_actor_id,
        options=[
            {
                "id": option.id, "question_id": question.id,
                "position": option.position, "option_text": option.option_text,
                "image_asset_id": option.image_asset_id,
                "is_correct": option.is_correct,
            }
            for option in options
        ],
    )


@author_router.post("/assignments", response_model=TMAAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: TMAAssignmentCreate, db: DbSession, actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.create_assignment(db, actor=actor, payload=payload)
    return TMAAssignmentResponse.model_validate(item)


@author_router.get("/assignments", response_model=TMAAssignmentListResponse)
async def list_assignments(
    db: DbSession, actor: Author,
    academic_term_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> TMAAssignmentListResponse:
    items, total = await TMAAssignmentService.list_assignments(
        db, actor=actor, academic_term_id=academic_term_id, offset=offset, limit=limit,
    )
    return TMAAssignmentListResponse(
        items=[TMAAssignmentResponse.model_validate(item) for item in items],
        total=total, offset=offset, limit=limit,
    )


@author_router.get("/assignments/{assignment_id}", response_model=TMAAssignmentResponse)
async def get_assignment(
    assignment_id: uuid.UUID, db: DbSession, actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.get_assignment(
        db, actor=actor, assignment_id=assignment_id,
    )
    return TMAAssignmentResponse.model_validate(item)


@author_router.patch("/assignments/{assignment_id}", response_model=TMAAssignmentResponse)
async def update_assignment(
    assignment_id: uuid.UUID, payload: TMAAssignmentUpdate, db: DbSession, actor: Author,
) -> TMAAssignmentResponse:
    item = await TMAAssignmentService.update_draft_assignment(
        db, actor=actor, assignment_id=assignment_id, payload=payload,
    )
    return TMAAssignmentResponse.model_validate(item)


@author_router.get("/assignments/{assignment_id}/readiness", response_model=list[str])
async def assignment_readiness(
    assignment_id: uuid.UUID, db: DbSession, actor: Author,
) -> list[str]:
    return await TMALifecycleService.get_assignment_readiness(
        db, actor=actor, assignment_id=assignment_id,
    )


@author_router.post("/assignments/{assignment_id}/activate", response_model=TMAAssignmentStatusResponse)
async def activate_assignment(
    assignment_id: uuid.UUID, db: DbSession, actor: Author,
) -> TMAAssignmentStatusResponse:
    item = await TMALifecycleService.activate_assignment(
        db, actor=actor, assignment_id=assignment_id,
    )
    return TMAAssignmentStatusResponse.model_validate(item)


@author_router.get("/assignments/{assignment_id}/questions", response_model=list[TMAQuestionAdminResponse])
async def list_questions(
    assignment_id: uuid.UUID, db: DbSession, actor: Author,
) -> list[TMAQuestionAdminResponse]:
    rows = await TMAQuestionService.list_questions(
        db, actor=actor, assignment_id=assignment_id,
    )
    return [_admin_question(question, options) for question, options in rows]


@author_router.post(
    "/assignments/{assignment_id}/questions",
    response_model=TMAQuestionAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    assignment_id: uuid.UUID, payload: TMAQuestionCreate, db: DbSession, actor: Author,
) -> TMAQuestionAdminResponse:
    question = await TMAQuestionService.add_question(
        db, actor=actor, assignment_id=assignment_id, payload=payload,
    )
    row, options = await TMAQuestionService.get_question(
        db, actor=actor, assignment_id=assignment_id, question_id=question.id,
    )
    return _admin_question(row, options)


@author_router.patch(
    "/assignments/{assignment_id}/questions/{question_id}",
    response_model=TMAQuestionAdminResponse,
)
async def update_question(
    assignment_id: uuid.UUID, question_id: uuid.UUID,
    payload: TMAQuestionUpdate, db: DbSession, actor: Author,
) -> TMAQuestionAdminResponse:
    await TMAQuestionService.update_question(
        db, actor=actor, assignment_id=assignment_id,
        question_id=question_id, payload=payload,
    )
    row, options = await TMAQuestionService.get_question(
        db, actor=actor, assignment_id=assignment_id, question_id=question_id,
    )
    return _admin_question(row, options)


@author_router.delete(
    "/assignments/{assignment_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    assignment_id: uuid.UUID, question_id: uuid.UUID, db: DbSession, actor: Author,
) -> None:
    await TMAQuestionService.delete_question(
        db, actor=actor, assignment_id=assignment_id, question_id=question_id,
    )


@student_router.get("/assignments", response_model=list[TMAStudentAssignmentResponse])
async def list_my_assignments(
    db: DbSession, student: CurrentStudent,
) -> list[TMAStudentAssignmentResponse]:
    return await TMAAttemptService.list_available_assignments(db, student=student)


@student_router.post("/assignments/{assignment_id}/start", response_model=TMAStartResponse)
async def start_assignment(
    assignment_id: uuid.UUID, db: DbSession, student: CurrentStudent,
) -> TMAStartResponse:
    return await TMAAttemptService.start_or_resume_attempt(
        db, student=student, assignment_id=assignment_id,
    )


@student_router.get("/attempts/{attempt_id}", response_model=TMAStartResponse)
async def resume_assignment(
    attempt_id: uuid.UUID, db: DbSession, student: CurrentStudent,
) -> TMAStartResponse:
    return await TMAAttemptService.get_attempt(
        db, student=student, attempt_id=attempt_id,
    )


@student_router.put("/attempts/{attempt_id}/answer", response_model=TMAAnswerSaveResponse)
async def save_my_answer(
    attempt_id: uuid.UUID, payload: TMAAnswerSaveRequest,
    db: DbSession, student: CurrentStudent,
) -> TMAAnswerSaveResponse:
    return await TMAAttemptService.save_answer(
        db, student=student, attempt_id=attempt_id, payload=payload,
    )


@student_router.post("/attempts/{attempt_id}/submit", response_model=TMASubmitResponse)
async def submit_assignment(
    attempt_id: uuid.UUID, db: DbSession, student: CurrentStudent,
) -> TMASubmitResponse:
    return await TMAAttemptService.submit_attempt(
        db, student=student, attempt_id=attempt_id,
    )


@student_router.get("/attempts/{attempt_id}/result", response_model=TMASubmitResponse)
async def get_my_score(
    attempt_id: uuid.UUID, db: DbSession, student: CurrentStudent,
) -> TMASubmitResponse:
    return await TMAAttemptService.get_submission_result(
        db, student=student, attempt_id=attempt_id,
    )
