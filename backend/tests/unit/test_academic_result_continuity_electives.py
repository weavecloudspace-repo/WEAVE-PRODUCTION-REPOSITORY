"""Student-specific elective eligibility in placement preview and reconciliation."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.classes.models import ClassRoom
from app.modules.student_academics.assessment_repository import AssessmentRepository
from app.modules.student_academics.curriculum_models import StudentElectiveSelection
from app.modules.student_academics.curriculum_service import (
    CurriculumResolutionService,
    ResolvedCurriculumSubject,
)
from app.modules.student_academics.models import (
    AcademicResultStatus,
    AcademicTerm,
    StudentSubjectResult,
)
from app.modules.student_academics.repository import StudentAcademicRepository
from app.modules.students.models import StudentEnrollment
from app.modules.students.result_continuity import AcademicResultContinuityService


def _context(monkeypatch, *, status=AcademicResultStatus.DRAFT, selected=True):
    tenant_id, student_id, session_id, level_id = (uuid4() for _ in range(4))
    source = SimpleNamespace(id=uuid4(), academic_level_id=level_id)
    destination = SimpleNamespace(id=uuid4(), class_id=uuid4())
    target = SimpleNamespace(id=destination.class_id, academic_level_id=level_id)
    original = SimpleNamespace(id=uuid4(), class_id=source.id, academic_level_id=level_id)
    term, scheme = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    group_id = uuid4()
    offerings = [
        ResolvedCurriculumSubject(
            curriculum_subject_id=uuid4(),
            subject_id=uuid4(),
            academic_level_department_id=None,
            is_elective=elective,
            elective_group_id=group_id if elective else None,
            is_general=True,
        )
        for elective in (True, True, False)
    ]
    results = [
        SimpleNamespace(
            id=uuid4(),
            student_id=student_id,
            class_id=source.id,
            student_enrollment_id=original.id,
            curriculum_subject_id=subject.curriculum_subject_id,
            assessment_scheme_id=scheme.id,
            teacher_assignment_id=uuid4(),
            teacher_membership_id=uuid4(),
            status=status,
            total_score=9,
            grade="F",
        )
        for subject in offerings
    ]
    teacher = SimpleNamespace(id=uuid4(), teacher_membership_id=uuid4())
    selections = [
        # These rows must not make the first elective eligible for this student.
        (uuid4(), student_id, offerings[0].curriculum_subject_id),
        (tenant_id, uuid4(), offerings[0].curriculum_subject_id),
    ]
    if selected:
        selections.append((tenant_id, student_id, offerings[1].curriculum_subject_id))

    async def execute(statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        if entity is ClassRoom:
            classroom = target if params["id_1"] == target.id else source
            return SimpleNamespace(scalar_one_or_none=lambda: classroom)
        if entity is AcademicTerm:
            return SimpleNamespace(scalar_one_or_none=lambda: term)
        if entity is StudentSubjectResult:
            return SimpleNamespace(scalars=lambda: results)
        if entity is StudentEnrollment:
            return SimpleNamespace(scalar_one_or_none=lambda: original)
        if entity is StudentElectiveSelection:
            # Emulate the tenant/student predicates against deliberately hostile
            # choices, rather than handing the service an already-filtered list.
            chosen = [
                subject_id
                for choice_tenant, choice_student, subject_id in selections
                if ("tenant_id_1" not in params or choice_tenant == params["tenant_id_1"])
                and ("student_id_1" not in params or choice_student == params["student_id_1"])
            ]
            return SimpleNamespace(scalars=lambda: chosen)
        raise AssertionError(f"Unexpected query entity: {entity}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    resolve = AsyncMock(return_value=offerings)
    monkeypatch.setattr(CurriculumResolutionService, "resolve_class_subjects", resolve)
    monkeypatch.setattr(AssessmentRepository, "get_active_scheme", AsyncMock(return_value=scheme))
    owners = AsyncMock(return_value={target.id: teacher})
    audit = AsyncMock()
    monkeypatch.setattr(
        StudentAcademicRepository, "get_teacher_assignments_for_classes_on_date", owners
    )
    monkeypatch.setattr(StudentAcademicRepository, "add_academic_lifecycle_audit", audit)
    return SimpleNamespace(
        db=db,
        results=results,
        offerings=offerings,
        destination=destination,
        teacher=teacher,
        audit=audit,
        resolve=resolve,
        owners=owners,
        args={
            "tenant_id": tenant_id,
            "student_id": student_id,
            "academic_session_id": session_id,
            "source_level_id": level_id,
            "target_class_id": target.id,
            "effective_date": date.today(),
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [True, False])
async def test_preview_uses_destination_offerings_and_only_this_students_choices(
    monkeypatch, selected
):
    ctx = _context(monkeypatch, selected=selected)
    decisions = await AcademicResultContinuityService.inspect(ctx.db, **ctx.args)
    assert [d.action for d in decisions] == [
        "historical_only",
        "automatic" if selected else "historical_only",
        "automatic",
    ]
    assert decisions[0].reason == "Elective subject is not selected by student"
    ctx.resolve.assert_awaited_once_with(
        ctx.db,
        tenant_id=ctx.args["tenant_id"],
        class_id=ctx.destination.class_id,
        academic_term_id=ctx.resolve.await_args.kwargs["academic_term_id"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(AcademicResultStatus))
async def test_unselected_elective_is_not_forwarded_even_with_finalized_consent(
    monkeypatch, status
):
    ctx = _context(monkeypatch, status=status)
    ctx.results[:] = ctx.results[:1]
    before = vars(ctx.results[0]).copy()
    args = {k: v for k, v in ctx.args.items() if k != "target_class_id"}
    decisions = await AcademicResultContinuityService.apply(
        ctx.db,
        **args,
        actor_id=uuid4(),
        destination_enrollment=ctx.destination,
        reason="Elective entitlement regression",
        carry_finalized_results=True,
    )
    assert decisions[0].action == "historical_only"
    assert vars(ctx.results[0]) == before
    ctx.db.add.assert_not_called()
    ctx.audit.assert_not_awaited()
    ctx.owners.assert_not_awaited()


@pytest.mark.asyncio
async def test_selected_elective_and_compulsory_marks_survive_ownership_transfer(monkeypatch):
    ctx = _context(monkeypatch)
    before = [vars(result).copy() for result in ctx.results]
    args = {k: v for k, v in ctx.args.items() if k != "target_class_id"}
    await AcademicResultContinuityService.apply(
        ctx.db,
        **args,
        actor_id=uuid4(),
        destination_enrollment=ctx.destination,
        reason="Selected elective continuity",
        carry_finalized_results=False,
    )
    assert vars(ctx.results[0]) == before[0]
    for result, initial in zip(ctx.results[1:], before[1:]):
        assert result.class_id == ctx.destination.class_id
        assert result.student_enrollment_id == ctx.destination.id
        assert result.teacher_assignment_id == ctx.teacher.id
        assert result.teacher_membership_id == ctx.teacher.teacher_membership_id
        for field in (
            "id",
            "student_id",
            "curriculum_subject_id",
            "total_score",
            "grade",
            "status",
        ):
            assert getattr(result, field) == initial[field]
    assert ctx.db.add.call_count == 2
    assert ctx.audit.await_count == 2
