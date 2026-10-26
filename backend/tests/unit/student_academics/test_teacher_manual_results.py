from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.curriculum_service import CurriculumResolutionService
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicSessionStatus,
    AcademicTermStatus,
    AssessmentSchemeStatus,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.student_academics.schemas import StudentSubjectResultUpsert
from app.modules.student_academics.service import StudentAcademicService
from app.modules.student_academics.teacher_result_service import TeacherResultService
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.teachers.models import TeacherMembership


@pytest.fixture
def context(monkeypatch):
    tenant_id = uuid4()
    teacher = TeacherMembership(id=uuid4(), tenant_id=tenant_id)
    session = SimpleNamespace(
        id=uuid4(),
        is_current=True,
        status=AcademicSessionStatus.OPEN,
    )
    term = SimpleNamespace(
        id=uuid4(),
        academic_session_id=session.id,
        is_current=True,
        status=AcademicTermStatus.OPEN,
        start_date=None,
        end_date=None,
    )
    assignment = SimpleNamespace(
        id=uuid4(),
        teacher_membership_id=teacher.id,
        class_id=uuid4(),
        effective_from=None,
        effective_to=None,
    )
    curriculum_subject = SimpleNamespace(id=uuid4(), subject_id=uuid4())
    student = SimpleNamespace(id=uuid4())
    enrollment = SimpleNamespace(id=uuid4(), class_id=assignment.class_id)
    scheme = SimpleNamespace(id=uuid4(), status=AssessmentSchemeStatus.ACTIVE)
    exam_component = SimpleNamespace(
        id=uuid4(),
        name="Exam",
        maximum_score=Decimal("60"),
        is_examinable=True,
    )
    manual_component = SimpleNamespace(
        id=uuid4(),
        name="Notes",
        maximum_score=Decimal("40"),
        is_examinable=False,
    )

    monkeypatch.setattr(
        "app.modules.student_academics.teacher_result_service.ensure_academic_write_window",
        AsyncMock(),
    )
    monkeypatch.setattr(
        StudentAcademicService,
        "_resolve_assignment_context",
        AsyncMock(return_value=(assignment, curriculum_subject)),
    )
    monkeypatch.setattr(StudentRepository, "get_by_id", AsyncMock(return_value=student))
    monkeypatch.setattr(
        StudentAcademicRepository,
        "get_academic_session_by_id",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "get_term_by_id",
        AsyncMock(return_value=term),
    )
    monkeypatch.setattr(
        StudentEnrollmentRepository,
        "get_authoritative_for_session",
        AsyncMock(return_value=enrollment),
    )
    monkeypatch.setattr(
        CurriculumResolutionService,
        "resolve_student_subjects",
        AsyncMock(return_value=[SimpleNamespace(curriculum_subject_id=curriculum_subject.id)]),
    )
    monkeypatch.setattr(
        AssessmentRepository,
        "get_active_scheme",
        AsyncMock(return_value=scheme),
    )
    monkeypatch.setattr(
        AssessmentRepository,
        "list_components",
        AsyncMock(return_value=[exam_component, manual_component]),
    )

    return SimpleNamespace(
        tenant_id=tenant_id,
        teacher=teacher,
        session=session,
        term=term,
        assignment=assignment,
        curriculum_subject=curriculum_subject,
        student=student,
        enrollment=enrollment,
        scheme=scheme,
        exam_component=exam_component,
        manual_component=manual_component,
    )


@pytest.mark.asyncio
async def test_teacher_cannot_write_examinable_component(monkeypatch, context) -> None:
    monkeypatch.setattr(
        StudentAcademicRepository,
        "get_result_by_scope",
        AsyncMock(return_value=None),
    )
    payload = StudentSubjectResultUpsert(
        student_id=context.student.id,
        teacher_assignment_id=context.assignment.id,
        academic_session_id=context.session.id,
        academic_term_id=context.term.id,
        component_scores=[
            {
                "assessment_component_id": context.exam_component.id,
                "score": Decimal("45"),
            }
        ],
        status=AcademicResultStatus.DRAFT,
    )

    with pytest.raises(ForbiddenException, match="cannot change examinable"):
        await TeacherResultService.upsert_manual_scores(
            AsyncMock(),
            teacher=context.teacher,
            payload=payload,
        )


@pytest.mark.asyncio
async def test_teacher_manual_edit_preserves_existing_exam_score(monkeypatch, context) -> None:
    existing = SimpleNamespace(
        id=uuid4(),
        assessment_scheme_id=context.scheme.id,
        status=AcademicResultStatus.DRAFT,
        teacher_assignment_id=context.assignment.id,
        teacher_membership_id=context.teacher.id,
        total_score=Decimal("55"),
        grade=None,
        remark=None,
        grading_scale_id=None,
        recorded_by_actor_type="cbt_server",
        recorded_by_actor_id=uuid4(),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "get_result_by_scope",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "list_result_component_scores",
        AsyncMock(
            return_value=[
                (context.exam_component, SimpleNamespace(score=Decimal("50"))),
                (context.manual_component, SimpleNamespace(score=Decimal("5"))),
            ]
        ),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "find_grade_for_score",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        StudentAcademicRepository,
        "upsert_result",
        AsyncMock(return_value=existing),
    )
    replace_scores = AsyncMock()
    monkeypatch.setattr(
        StudentAcademicRepository,
        "replace_result_scores",
        replace_scores,
    )
    monkeypatch.setattr(
        StudentAcademicService,
        "_record_academic_lifecycle",
        AsyncMock(),
    )
    expected_response = SimpleNamespace(id=existing.id)
    monkeypatch.setattr(
        StudentAcademicService,
        "_build_result_response",
        AsyncMock(return_value=expected_response),
    )

    db = SimpleNamespace(
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        info={},
    )
    payload = StudentSubjectResultUpsert(
        student_id=context.student.id,
        teacher_assignment_id=context.assignment.id,
        academic_session_id=context.session.id,
        academic_term_id=context.term.id,
        component_scores=[
            {
                "assessment_component_id": context.manual_component.id,
                "score": Decimal("8"),
            }
        ],
        status=AcademicResultStatus.DRAFT,
    )

    response = await TeacherResultService.upsert_manual_scores(
        db,
        teacher=context.teacher,
        payload=payload,
    )

    assert response is expected_response
    replace_scores.assert_awaited_once()
    merged = replace_scores.await_args.args[2]
    assert merged[context.exam_component.id] == Decimal("50")
    assert merged[context.manual_component.id] == Decimal("8")
    assert existing.total_score == Decimal("58")
    assert existing.recorded_by_actor_type == "teacher"
    assert existing.recorded_by_actor_id == context.teacher.id
    queued = db.info["weave_pending_realtime_messages"]
    assert len(queued) == 1
    assert queued[0].event.type == "academic.component_score.updated"
    assert queued[0].audience.actor_id == context.student.id
    assert queued[0].audience.tenant_id == context.tenant_id


@pytest.mark.asyncio
async def test_teacher_cannot_edit_another_teachers_assignment(monkeypatch, context) -> None:
    context.assignment.teacher_membership_id = uuid4()
    payload = StudentSubjectResultUpsert(
        student_id=context.student.id,
        teacher_assignment_id=context.assignment.id,
        academic_session_id=context.session.id,
        academic_term_id=context.term.id,
        component_scores=[
            {
                "assessment_component_id": context.manual_component.id,
                "score": Decimal("8"),
            }
        ],
        status=AcademicResultStatus.DRAFT,
    )

    with pytest.raises(ForbiddenException, match="their own active subject assignments"):
        await TeacherResultService.upsert_manual_scores(
            AsyncMock(),
            teacher=context.teacher,
            payload=payload,
        )
