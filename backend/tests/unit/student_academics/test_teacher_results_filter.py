from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies.db import get_db
from app.core.dependencies.route_guards import get_current_teacher
from app.core.exceptions import ForbiddenException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.router import teacher_router
from app.modules.student_academics.service import StudentAcademicService
from app.modules.teachers.models import TeacherMembership


@pytest.fixture
def workspace(monkeypatch):
    app = FastAPI()
    app.include_router(teacher_router)
    teacher = TeacherMembership(id=uuid4(), tenant_id=uuid4())
    db = SimpleNamespace()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    listing = AsyncMock(return_value=([], 225))
    monkeypatch.setattr(StudentAcademicService, "list_results", listing)
    with TestClient(app) as client:
        yield client, listing, db, teacher


def test_teacher_results_route_forwards_assignment_and_pagination(workspace):
    client, listing, db, teacher = workspace
    assignment_id, session_id, term_id = uuid4(), uuid4(), uuid4()
    response = client.get(
        "/teachers/academics/results",
        params={
            "teacher_assignment_id": str(assignment_id),
            "academic_session_id": str(session_id),
            "academic_term_id": str(term_id),
            "skip": 100,
            "limit": 25,
        },
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 225}
    listing.assert_awaited_once_with(
        db,
        teacher,
        class_id=None,
        teacher_assignment_id=assignment_id,
        academic_session_id=session_id,
        academic_term_id=term_id,
        skip=100,
        limit=25,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"teacher_assignment_id": "invalid"},
        {"skip": -1},
        {"limit": 0},
        {"limit": 101},
    ],
)
def test_teacher_results_route_rejects_invalid_filters(workspace, params):
    client, listing, _, _ = workspace
    assert client.get("/teachers/academics/results", params=params).status_code == 422
    listing.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_filter_preserves_tenant_and_teacher_scope(monkeypatch):
    teacher = TeacherMembership(id=uuid4(), tenant_id=uuid4())
    assignment_id = uuid4()
    listing = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(StudentAcademicRepository, "list_results", listing)
    monkeypatch.setattr(
        StudentAcademicRepository, "list_result_component_scores_batch", AsyncMock(return_value={})
    )
    monkeypatch.setattr(AssessmentRepository, "get_schemes_by_id", AsyncMock(return_value={}))
    await StudentAcademicService.list_results(
        SimpleNamespace(), teacher, teacher_assignment_id=assignment_id
    )
    args, kwargs = listing.await_args
    assert args[1] == teacher.tenant_id
    assert kwargs["teacher_id"] == teacher.id
    assert kwargs["teacher_assignment_id"] == assignment_id
    listing.reset_mock()
    with pytest.raises(ForbiddenException, match="own results"):
        await StudentAcademicService.list_results(
            SimpleNamespace(), teacher, teacher_id=uuid4(), teacher_assignment_id=assignment_id
        )
    listing.assert_not_awaited()
