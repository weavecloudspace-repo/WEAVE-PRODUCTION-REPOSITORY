"""PostgreSQL service regressions for revision, roster, authorization and batching."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.students.models import StudentEnrollmentOutcome
from app.modules.student_academics.models import AssessmentComponent, StudentAssessmentScore
from app.modules.student_academics.curriculum_models import (
    CurriculumElectiveGroup,
    StudentElectiveSelection,
)
from app.modules.teachers.models import TeacherMembershipStatus
from app.modules.tma.assignment_service import TMAAssignmentService
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.cancellation_service import TMACancellationService
from app.modules.tma.deadline_zero_service import TMADeadlineZeroService
from app.modules.tma.deadline_eligibility_repository import TMADeadlineEligibilityRepository
from app.modules.tma.reporting_service import TMAReportingService
from app.modules.tma.models import (
    TMAAssignmentStatus,
    TMAAssignmentRevision,
    TMAClosureEligibility,
    TMAClosureRun,
    TMAZeroGradingFailure,
    TMAAttempt,
    TMAAttemptStatus,
    TMAParticipant,
)
from app.modules.tma.repository import TMAQuestionRepository
from app.modules.tma.schemas import TMAAnswerSaveRequest


async def due(w, item, *, capture=True):
    # Simulate elapsed time without sleeping. Tracking is explicitly before the
    # synthetic deadline; enrollment was inserted before that deadline as well.
    now = datetime.now(timezone.utc)
    item.closes_at = now - timedelta(milliseconds=1)
    item.closed_at = now
    item.zero_grading_requested_at = now
    item.status = TMAAssignmentStatus.CLOSED
    revision = (
        await w.db.execute(
            select(TMAAssignmentRevision).where(
                TMAAssignmentRevision.assignment_id == item.id,
                TMAAssignmentRevision.tenant_id == w.tenant.id,
                TMAAssignmentRevision.revision_number == item.current_revision_number,
            )
        )
    ).scalar_one()
    revision.eligibility_tracking_started_at = now - timedelta(minutes=1)
    closure = TMAClosureRun(
        tenant_id=w.tenant.id,
        assignment_id=item.id,
        revision_id=revision.id,
        closed_at=now,
        cutoff_at=item.closes_at,
        original_deadline_at=item.closes_at,
        kind="automatic",
    )
    w.db.add(closure)
    await w.db.flush()
    if capture:
        await TMADeadlineEligibilityRepository.capture(
            w.db,
            tenant_id=w.tenant.id,
            assignment_id=item.id,
            closure_id=closure.id,
        )
    await w.db.commit()
    return revision


@pytest.mark.asyncio
async def test_normal_submission_scores_once_and_replays(tma_world):
    w = tma_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    available = await TMAAttemptService.list_available_assignments(w.db, student=student)
    assert [r.assignment_id for r in available] == [item.id]
    started = await TMAAttemptService.start_or_resume_attempt(
        w.db, student=student, assignment_id=item.id
    )
    attempt_id = started.attempt.id
    question, options = (
        await TMAQuestionRepository.list_for_revision_with_options(
            w.db, w.tenant.id, started.attempt.revision_id
        )
    )[0]
    correct = next(o for o in options if o.is_correct)
    await TMAAttemptService.save_answer(
        w.db,
        student=student,
        attempt_id=attempt_id,
        payload=TMAAnswerSaveRequest(question_id=question.id, selected_option_id=correct.id),
    )
    first = await TMAAttemptService.submit_attempt(w.db, student=student, attempt_id=attempt_id)
    second = await TMAAttemptService.submit_attempt(w.db, student=student, attempt_id=attempt_id)
    assert first.component_score == second.component_score == Decimal("20")
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1
    await due(w, item)
    assert (await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id}))[
        "zeroed"
    ] == 0
    result = await TMAAttemptService.get_submission_result(
        w.db, student=student, attempt_id=attempt_id
    )
    assert result.component_score == Decimal("20")


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [100, 1200])
async def test_large_assignment_bounded_batches_retry_and_completion(tma_world, monkeypatch, count):
    w = tma_world
    # Real ORM rows, constraints, score writes and worker transactions.
    for _ in range(count):
        await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    monkeypatch.setattr(TMADeadlineZeroService, "MAX_WRITES", 200)
    batches = []
    for _ in range(10):
        outcome = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
        batches.append(outcome["zeroed"])
        if not outcome["pending"]:
            break
    assert sum(batches) == count
    assert max(batches) <= 200
    assert len(batches) == (count + 199) // 200
    assert item.zero_grading_completed_at is not None
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == count
    assert (await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id}))[
        "zeroed"
    ] == 0


@pytest.mark.asyncio
async def test_reporting_scopes_current_and_historical_students(tma_world):
    w = tma_world
    a, _ = await w.student(0)
    b, _ = await w.student(1)
    item, _ = await w.assignment()
    for teacher, expected in zip(w.teachers, [a, b]):
        response = await TMAReportingService.list_assignment_participation(
            w.db, actor=teacher, assignment_id=item.id
        )
        assert response.total == 1
        assert [r.student_id for r in response.items] == [expected.id]
    response = await TMAReportingService.list_assignment_participation(
        w.db, actor=w.teachers[0], assignment_id=item.id, class_id=w.rooms[1].id
    )
    assert response.total == 0
    response = await TMAReportingService.list_assignment_participation(
        w.db, actor=w.admin, assignment_id=item.id
    )
    assert response.total == 2
    await due(w, item)
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    response = await TMAReportingService.list_assignment_participation(
        w.db, actor=w.teachers[0], assignment_id=item.id
    )
    assert response.total == 1 and response.items[0].student_id == a.id


@pytest.mark.asyncio
async def test_reassignment_and_membership_revoke_list_details_and_reports(tma_world):
    w = tma_world
    item, _ = await w.assignment()
    item.created_by_actor_type = "teacher"
    item.created_by_actor_id = w.teachers[0].id
    item.lead_teacher_membership_id = w.teachers[0].id
    w.teaching[0].effective_to = date.today() - timedelta(days=1)
    await w.db.flush()
    rows, total = await TMAAssignmentService.list_assignments(
        w.db, actor=w.teachers[0], academic_term_id=w.term.id
    )
    assert rows == [] and total == 0
    for service in (
        TMAAssignmentService.get_assignment,
        TMAReportingService.list_assignment_participation,
    ):
        with pytest.raises(ForbiddenException):
            await service(w.db, actor=w.teachers[0], assignment_id=item.id)
    assert (
        await TMAAssignmentService.get_assignment(w.db, actor=w.teachers[1], assignment_id=item.id)
    ).id == item.id
    w.teachers[1].ended_at = datetime.now(timezone.utc)
    w.teachers[1].status = TeacherMembershipStatus.INACTIVE
    await w.db.flush()
    with pytest.raises(ForbiddenException):
        await TMAAssignmentService.get_assignment(w.db, actor=w.teachers[1], assignment_id=item.id)
    assert (
        await TMAAssignmentService.get_assignment(w.db, actor=w.admin, assignment_id=item.id)
    ).id == item.id


@pytest.mark.asyncio
async def test_teacher_pagination_35_assignments_counts_and_order(tma_world):
    w = tma_world
    ids = []
    for n in range(35):
        component = await w.add(
            AssessmentComponent(
                tenant_id=w.tenant.id,
                assessment_scheme_id=w.scheme.id,
                name=f"CA{n + 2}",
                position=n + 2,
                maximum_score=Decimal("1"),
                is_examinable=False,
            )
        )
        item, _ = await w.assignment(publish=False, component_override=component)
        ids.append(item.id)
    seen = []
    for offset, length in [(0, 10), (10, 10), (20, 10), (30, 5), (40, 0)]:
        rows, total = await TMAAssignmentService.list_assignments(
            w.db, actor=w.teachers[0], offset=offset, limit=10
        )
        assert total == 35 and len(rows) == length
        seen.extend(r.id for r in rows)
    assert seen == list(reversed(ids))
    rows, total = await TMAAssignmentService.list_assignments(
        w.db, actor=w.admin, offset=30, limit=10
    )
    assert total == 35 and len(rows) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["withdraw", "elective_remove", "class_transfer", "subject_retire"]
)
async def test_changes_after_deadline_preserve_roster(tma_world, change):
    w = tma_world
    student, enrollment = await w.student()
    if change == "elective_remove":
        group = await w.add(
            CurriculumElectiveGroup(
                tenant_id=w.tenant.id,
                curriculum_id=w.cs.curriculum_id,
                name="Options",
                maximum_choices=1,
            )
        )
        w.cs.is_elective = True
        w.cs.elective_group_id = group.id
        await w.db.flush()
        await w.add(
            StudentElectiveSelection(
                tenant_id=w.tenant.id,
                student_id=student.id,
                elective_group_id=group.id,
                curriculum_subject_id=w.cs.id,
            )
        )
    item, _ = await w.assignment()
    revision = await due(w, item)
    if change == "withdraw":
        student.is_active = False
    elif change == "elective_remove":
        selection = (
            await w.db.execute(
                select(StudentElectiveSelection).where(
                    StudentElectiveSelection.tenant_id == w.tenant.id
                )
            )
        ).scalar_one()
        await w.db.delete(selection)
    elif change == "subject_retire":
        w.cs.is_active = False
    else:
        enrollment.ended_on = date.today()
        enrollment.exit_outcome = StudentEnrollmentOutcome.LEVEL_REASSIGNED
        enrollment.exit_reason = "test transfer"
    await w.db.flush()
    snapshot = (
        await w.db.execute(
            select(TMAClosureEligibility).where(
                TMAClosureEligibility.closure_run_id
                == (
                    select(TMAClosureRun.id)
                    .where(
                        TMAClosureRun.tenant_id == w.tenant.id,
                        TMAClosureRun.assignment_id == item.id,
                        TMAClosureRun.closed_at == item.closed_at,
                    )
                    .scalar_subquery()
                )
            )
        )
    ).scalar_one()
    assert snapshot.student_id == student.id and snapshot.student_enrollment_id == enrollment.id
    outcome = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert outcome == {"zeroed": 1, "blocked": 0, "pending": 0}


@pytest.mark.asyncio
async def test_late_admission_excluded_and_pre_deadline_admission_included(tma_world):
    w = tma_world
    early, _ = await w.student()
    item, _ = await w.assignment()
    revision = await due(w, item)
    late, _ = await w.student()
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    ids = list(
        (
            await w.db.execute(
                select(TMAClosureEligibility.student_id).where(
                    TMAClosureEligibility.closure_run_id
                    == (
                        select(TMAClosureRun.id)
                        .where(
                            TMAClosureRun.tenant_id == w.tenant.id,
                            TMAClosureRun.assignment_id == item.id,
                            TMAClosureRun.closed_at == item.closed_at,
                        )
                        .scalar_subquery()
                    )
                )
            )
        ).scalars()
    )
    assert ids == [early.id] and late.id not in ids


@pytest.mark.asyncio
async def test_revision_resets_zero_lifecycle_and_retains_exemption_audit(tma_world, monkeypatch):
    w = tma_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    prior = await due(w, item)
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    completed = item.zero_grading_completed_at
    await w.add(
        TMAZeroGradingFailure(
            tenant_id=w.tenant.id,
            assignment_id=item.id,
            revision_number=1,
            student_id=student.id,
            reason="old issue",
            attempts=1,
            last_failed_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            resolution="exempt",
            resolution_note="historical exemption",
        )
    )
    monkeypatch.setattr(TMACancellationService, "_enqueue", AsyncMock())
    run = await TMACancellationService.cancel(
        w.db, actor=w.admin, assignment_id=item.id, reason="correction"
    )
    with pytest.raises(ConflictException):
        await TMACancellationService.create_revision(w.db, actor=w.admin, assignment_id=item.id)
    await TMACancellationService.process(w.db, tenant_id=w.tenant.id, run_id=run.id)
    revision = await TMACancellationService.create_revision(
        w.db, actor=w.admin, assignment_id=item.id
    )
    assert revision.revision_number == 2
    assert (
        item.zero_grading_requested_at
        is item.zero_grading_completed_at
        is item.zero_grading_error
        is None
    )
    assert prior.zero_grading_completed_at == completed
    from app.modules.tma.lifecycle_service import TMALifecycleService

    item.closes_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await w.db.flush()
    await TMALifecycleService.activate_assignment(w.db, actor=w.admin, assignment_id=item.id)
    await due(w, item)
    assert (await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id}))[
        "zeroed"
    ] == 1
    assert (
        await w.db.execute(
            select(func.count(TMAZeroGradingFailure.id)).where(
                TMAZeroGradingFailure.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_legacy_deadline_fails_closed_and_tenant_boundary(tma_world):
    w = tma_world
    await w.student()
    item, _ = await w.assignment()
    revision = await due(w, item, capture=False)
    revision.eligibility_tracking_started_at = datetime.now(timezone.utc)
    await w.db.commit()
    result = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert result["blocked"] == 1 and result["pending"] == 1
    assert "tracking" in item.zero_grading_error
    from app.modules.tenant_admins.models import TenantAdmin

    outsider = TenantAdmin(id=uuid4(), tenant_id=uuid4())
    with pytest.raises(NotFoundException):
        await TMAAssignmentService.get_assignment(w.db, actor=outsider, assignment_id=item.id)


@pytest.mark.asyncio
async def test_snapshot_database_uniqueness_and_rollback(tma_world):
    w = tma_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    revision = await due(w, item)
    await TMADeadlineEligibilityRepository.capture(
        w.db, tenant_id=w.tenant.id, assignment_id=item.id
    )
    row = (
        await w.db.execute(
            select(TMAClosureEligibility).where(TMAClosureEligibility.tenant_id == w.tenant.id)
        )
    ).scalar_one()
    with pytest.raises(IntegrityError):
        async with w.db.begin_nested():
            w.db.add(
                TMAClosureEligibility(
                    tenant_id=row.tenant_id,
                    closure_run_id=row.closure_run_id,
                    student_id=row.student_id,
                    student_enrollment_id=row.student_enrollment_id,
                    class_id=row.class_id,
                    subject_id=row.subject_id,
                )
            )
            await w.db.flush()
    assert (
        await w.db.execute(
            select(func.count(TMAClosureEligibility.student_id)).where(
                TMAClosureEligibility.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_failed_student_savepoint_retries_without_duplicate_score(tma_world, monkeypatch):
    w = tma_world
    await w.student()
    await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    original = TMADeadlineZeroService._write_zero
    fail_once = True

    async def write(*args, **kwargs):
        nonlocal fail_once
        written = await original(*args, **kwargs)
        if fail_once:
            fail_once = False
            raise ConflictException("injected failure after score write")
        return written

    monkeypatch.setattr(TMADeadlineZeroService, "_write_zero", write)
    first = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert first == {"zeroed": 1, "blocked": 1, "pending": 1}
    second = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert second == {"zeroed": 1, "blocked": 0, "pending": 0}
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 2
    failure = (
        await w.db.execute(
            select(TMAZeroGradingFailure).where(TMAZeroGradingFailure.tenant_id == w.tenant.id)
        )
    ).scalar_one()
    assert failure.resolution == "graded" and failure.resolved_at is not None


@pytest.mark.asyncio
async def test_two_tenants_and_multiple_assignments_make_fair_progress(tma_world, monkeypatch):
    from .conftest import tma_world as build
    from app.tenant_management.models import Tenant

    a = tma_world
    tenant = await a.add(
        Tenant(
            school_name="Second Test",
            slug=f"test-{uuid4()}",
            email=f"{uuid4()}@example.com",
            status=a.tenant.status,
            plan=a.tenant.plan,
            verification_status=a.tenant.verification_status,
            onboarding_completed=True,
            country="Nigeria",
            timezone="Africa/Lagos",
            language="en",
        )
    )
    b = await build.__wrapped__(a.db, tenant)
    for w in (a, b):
        await w.student()
        await w.student()
        item, _ = await w.assignment()
        await due(w, item)
    component = await a.add(
        AssessmentComponent(
            tenant_id=a.tenant.id,
            assessment_scheme_id=a.scheme.id,
            name="CA2",
            position=2,
            maximum_score=Decimal("10"),
            is_examinable=False,
        )
    )
    extra, _ = await a.assignment(component_override=component)
    await due(a, extra)
    monkeypatch.setattr(TMADeadlineZeroService, "MAX_WRITES", 1)
    for _ in range(2):
        await TMADeadlineZeroService.process_pending(a.db, tenant_ids={a.tenant.id, b.tenant.id})
    for w in (a, b):
        assert (
            await a.db.execute(
                select(func.count(StudentAssessmentScore.id)).where(
                    StudentAssessmentScore.tenant_id == w.tenant.id
                )
            )
        ).scalar_one() == 1
    for _ in range(6):
        await TMADeadlineZeroService.process_pending(a.db, tenant_ids={a.tenant.id, b.tenant.id})
    assert (
        await a.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == a.tenant.id
            )
        )
    ).scalar_one() == 4
    assert (
        await a.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == b.tenant.id
            )
        )
    ).scalar_one() == 2


@pytest.mark.asyncio
async def test_concurrent_workers_and_reassignment_preserve_exactly_one_zero(
    tma_committed_world, test_engine
):
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.modules.students.models import Student

    w = tma_committed_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    await w.db.commit()

    async def worker():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            return await TMADeadlineZeroService.process_pending(db, tenant_ids={w.tenant.id})

    async def withdraw():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            person = (
                await db.execute(
                    select(Student).where(
                        Student.tenant_id == w.tenant.id, Student.id == student.id
                    )
                )
            ).scalar_one()
            person.is_active = False
            await db.commit()

    results = await asyncio.gather(worker(), worker(), withdraw())
    assert sum(r["zeroed"] for r in results[:2]) == 1
    assert (await worker())["zeroed"] == 0
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_revision_creation_only_one_succeeds(
    tma_committed_world, test_engine, monkeypatch
):
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession

    w = tma_committed_world
    item, _ = await w.assignment()
    await due(w, item)
    await w.db.commit()
    monkeypatch.setattr(TMACancellationService, "_enqueue", AsyncMock())
    # Cancellation is deliberately guarded until missing-zero reconciliation completes.
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    run = await TMACancellationService.cancel(
        w.db, actor=w.admin, assignment_id=item.id, reason="new version"
    )
    await TMACancellationService.process(w.db, tenant_id=w.tenant.id, run_id=run.id)

    async def revise():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            try:
                return await TMACancellationService.create_revision(
                    db, actor=w.admin, assignment_id=item.id
                )
            except ConflictException:
                return None

    results = await asyncio.gather(revise(), revise())
    assert sum(r is not None for r in results) == 1
    assert (
        await w.db.execute(
            select(func.count(TMAAssignmentRevision.id)).where(
                TMAAssignmentRevision.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 2


@pytest.mark.asyncio
async def test_subject_change_before_deadline_does_not_create_a_zero(tma_world):
    w = tma_world
    await w.student()
    item, _ = await w.assignment()
    w.cs.is_active = False
    await w.db.commit()
    revision = await due(w, item)
    result = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert result == {"zeroed": 0, "blocked": 0, "pending": 0}
    assert (
        await w.db.execute(
            select(func.count(TMAClosureEligibility.student_id)).where(
                TMAClosureEligibility.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_deadline_specialization_snapshot_matches_canonical_curriculum(tma_world):
    from app.modules.classes.models import AcademicCategory, Department, AcademicLevelDepartment
    from app.modules.student_academics.curriculum_models import (
        ClassTermDepartmentAssignment,
        CurriculumSubjectDepartment,
    )

    w = tma_world
    w.level.category = AcademicCategory.SENIOR_SECONDARY
    w.level.specialization_required_from_term_position = 1
    await w.db.flush()
    links = []
    for label in ("Science", "Arts"):
        department = await w.add(
            Department(
                tenant_id=w.tenant.id, name=label, normalized_name=label.lower(), is_active=True
            )
        )
        links.append(
            await w.add(
                AcademicLevelDepartment(
                    tenant_id=w.tenant.id,
                    academic_level_id=w.level.id,
                    department_id=department.id,
                    is_active=True,
                )
            )
        )
    assignments = []
    for room, link in zip(w.rooms, links):
        assignments.append(
            await w.add(
                ClassTermDepartmentAssignment(
                    tenant_id=w.tenant.id,
                    academic_term_id=w.term.id,
                    class_id=room.id,
                    academic_level_department_id=link.id,
                )
            )
        )
    await w.add(
        CurriculumSubjectDepartment(
            tenant_id=w.tenant.id,
            curriculum_subject_id=w.cs.id,
            academic_level_department_id=links[0].id,
        )
    )
    eligible, _ = await w.student(0)
    await w.student(1)
    item, _ = await w.assignment()
    live = await TMAReportingService.list_assignment_participation(
        w.db, actor=w.admin, assignment_id=item.id
    )
    assert [r.student_id for r in live.items] == [eligible.id]
    revision = await due(w, item)
    assignments[0].academic_level_department_id = links[1].id
    await w.db.commit()
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    ids = list(
        (
            await w.db.execute(
                select(TMAClosureEligibility.student_id).where(
                    TMAClosureEligibility.closure_run_id
                    == (
                        select(TMAClosureRun.id)
                        .where(
                            TMAClosureRun.tenant_id == w.tenant.id,
                            TMAClosureRun.assignment_id == item.id,
                            TMAClosureRun.closed_at == item.closed_at,
                        )
                        .scalar_subquery()
                    )
                )
            )
        ).scalars()
    )
    assert ids == [eligible.id]


@pytest.mark.asyncio
async def test_term_closure_gate_tracks_pending_zero_work(tma_world, monkeypatch):
    from app.modules.student_academics.service import StudentAcademicService

    w = tma_world
    await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    before = await StudentAcademicService.academic_term_dependency_preview(
        w.db, w.tenant.id, w.term.id
    )
    assert before.dependency_counts["tma_pending_zero_grading"] == 1
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    after = await StudentAcademicService.academic_term_dependency_preview(
        w.db, w.tenant.id, w.term.id
    )
    assert after.dependency_counts["tma_pending_zero_grading"] == 0


@pytest.mark.asyncio
async def test_draft_edit_delete_and_manual_close_reopen(tma_world):
    from app.modules.tma.draft_deletion_service import TMADraftDeletionService
    from app.modules.tma.lifecycle_service import TMALifecycleService
    from app.modules.tma.schemas import TMAAssignmentUpdate
    from app.modules.tma.repository import TMAAssignmentRepository

    w = tma_world
    draft, _ = await w.assignment(publish=False)
    await TMAAssignmentService.update_draft_assignment(
        w.db,
        actor=w.admin,
        assignment_id=draft.id,
        payload=TMAAssignmentUpdate(closes_at=datetime.now(timezone.utc) + timedelta(days=1)),
    )
    assert draft.status == TMAAssignmentStatus.DRAFT
    await TMADraftDeletionService.delete_draft(w.db, actor=w.admin, assignment_id=draft.id)
    assert await TMAAssignmentRepository.get_by_id(w.db, w.tenant.id, draft.id) is None
    item, _ = await w.assignment()
    with pytest.raises(ConflictException):
        await TMALifecycleService.activate_assignment(w.db, actor=w.admin, assignment_id=item.id)
    await TMACancellationService.close(w.db, actor=w.admin, assignment_id=item.id)
    assert item.status == TMAAssignmentStatus.CLOSED
    with pytest.raises(ConflictException):
        await TMALifecycleService.reopen_assignment(
            w.db,
            actor=w.admin,
            assignment_id=item.id,
            closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    await TMALifecycleService.reopen_assignment(
        w.db,
        actor=w.admin,
        assignment_id=item.id,
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
    )
    assert item.status == TMAAssignmentStatus.ACTIVE and item.zero_grading_requested_at is None


@pytest.mark.asyncio
async def test_direct_http_requests_cannot_bypass_revoked_teacher_access(tma_world):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.core.exception_handlers import register_exception_handlers
    from app.core.dependencies.db import get_db
    from app.modules.tma.router import author_router, _current_author

    w = tma_world
    item, _ = await w.assignment()
    w.teaching[0].effective_to = date.today() - timedelta(days=1)
    await w.db.commit()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(author_router)

    async def author():
        return w.teachers[0]

    async def database():
        yield w.db

    app.dependency_overrides[_current_author] = author
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for suffix in ("", "/questions", "/submissions", "/readiness", "/revisions"):
            response = await client.get(f"/tma/assignments/{item.id}{suffix}")
            assert response.status_code == 403
        response = await client.get(f"/tma/assignments?academic_term_id={w.term.id}")
        assert response.status_code == 200 and response.json()["total"] == 0


@pytest.mark.asyncio
async def test_cancellation_preserves_unrelated_assessment_component(tma_world, monkeypatch):
    from app.modules.student_academics.models import StudentSubjectResult

    w = tma_world
    await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    result = (
        await w.db.execute(
            select(StudentSubjectResult).where(StudentSubjectResult.tenant_id == w.tenant.id)
        )
    ).scalar_one()
    other = await w.add(
        AssessmentComponent(
            tenant_id=w.tenant.id,
            assessment_scheme_id=w.scheme.id,
            name="Unrelated CA",
            position=2,
            maximum_score=Decimal("10"),
            is_examinable=False,
        )
    )
    unrelated = await w.add(
        StudentAssessmentScore(
            tenant_id=w.tenant.id,
            student_subject_result_id=result.id,
            assessment_component_id=other.id,
            score=Decimal("7"),
        )
    )
    unrelated_id = unrelated.id
    result.total_score = Decimal("7")
    await w.db.commit()
    monkeypatch.setattr(TMACancellationService, "_enqueue", AsyncMock())
    run = await TMACancellationService.cancel(
        w.db, actor=w.admin, assignment_id=item.id, reason="correct question"
    )
    await TMACancellationService.process(w.db, tenant_id=w.tenant.id, run_id=run.id)
    rows = list(
        (
            await w.db.execute(
                select(StudentAssessmentScore).where(
                    StudentAssessmentScore.tenant_id == w.tenant.id
                )
            )
        ).scalars()
    )
    assert [(row.id, row.score) for row in rows] == [(unrelated_id, Decimal("7"))]
    assert result.total_score == Decimal("7")


@pytest.mark.asyncio
async def test_simultaneous_student_submissions_create_one_score(tma_committed_world, test_engine):
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession

    w = tma_committed_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    start = await TMAAttemptService.start_or_resume_attempt(
        w.db, student=student, assignment_id=item.id
    )
    attempt_id = start.attempt.id

    async def submit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            return await TMAAttemptService.submit_attempt(
                db, student=student, attempt_id=attempt_id
            )

    first, second = await asyncio.gather(submit(), submit())
    assert first.component_score == second.component_score == Decimal("0")
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_cancellation_and_grading_finish_without_orphaned_scores(
    tma_committed_world, test_engine, monkeypatch
):
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession

    w = tma_committed_world
    await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    monkeypatch.setattr(TMACancellationService, "_enqueue", AsyncMock())

    async def grade():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            return await TMADeadlineZeroService.process_pending(db, tenant_ids={w.tenant.id})

    async def cancel():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            return await TMACancellationService.cancel(
                db, actor=w.admin, assignment_id=item.id, reason="cancel race"
            )

    grade_result, cancel_result = await asyncio.gather(grade(), cancel(), return_exceptions=True)
    if isinstance(cancel_result, ConflictException):
        # Zero grading has the lock; complete reconciliation before cancellation.
        assert grade_result["pending"] == 0
        cancel_result = await TMACancellationService.cancel(
            w.db, actor=w.admin, assignment_id=item.id, reason="cancel race"
        )
    else:
        assert not isinstance(cancel_result, BaseException)
    await TMACancellationService.process(w.db, tenant_id=w.tenant.id, run_id=cancel_result.id)
    assert (
        await w.db.execute(
            select(func.count(StudentAssessmentScore.id)).where(
                StudentAssessmentScore.tenant_id == w.tenant.id
            )
        )
    ).scalar_one() == 0

@pytest.mark.asyncio
async def test_overdue_curriculum_mutation_captures_before_worker(tma_world):
    """The first post-deadline write must freeze the pre-write roster."""
    w = tma_world
    student, _ = await w.student()
    item, _ = await w.assignment()
    item.closes_at = datetime.now(timezone.utc) - timedelta(milliseconds=1)
    await w.db.commit()

    # BEFORE UPDATE trigger must make the closure and snapshot atomically.
    student.is_active = False
    await w.db.commit()
    closure = (
        await w.db.execute(
            select(TMAClosureRun).where(
                TMAClosureRun.tenant_id == w.tenant.id,
                TMAClosureRun.assignment_id == item.id,
            )
        )
    ).scalar_one()
    assert item.status == TMAAssignmentStatus.CLOSED
    assert closure.kind == "automatic"
    assert closure.eligibility_captured_at is not None
    assert (
        await w.db.execute(
            select(TMAClosureEligibility.student_id).where(
                TMAClosureEligibility.tenant_id == w.tenant.id,
                TMAClosureEligibility.closure_run_id == closure.id,
            )
        )
    ).scalar_one() == student.id
    outcome = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert outcome == {"zeroed": 1, "blocked": 0, "pending": 0}


@pytest.mark.asyncio
async def test_reopened_tma_maintains_separate_closure_rosters(tma_world):
    """New admission belongs to later closure, not an older closure."""
    from app.modules.tma.lifecycle_service import TMALifecycleService

    w = tma_world
    first_student, _ = await w.student()
    item, _ = await w.assignment()
    await due(w, item)
    await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    first_run = (
        await w.db.execute(
            select(TMAClosureRun).where(
                TMAClosureRun.tenant_id == w.tenant.id,
                TMAClosureRun.assignment_id == item.id,
            )
        )
    ).scalar_one()
    await TMALifecycleService.reopen_assignment(
        w.db,
        actor=w.admin,
        assignment_id=item.id,
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
    )
    new_student, _ = await w.student()
    await TMACancellationService.close(w.db, actor=w.admin, assignment_id=item.id)
    runs = list(
        (
            await w.db.execute(
                select(TMAClosureRun)
                .where(
                    TMAClosureRun.tenant_id == w.tenant.id,
                    TMAClosureRun.assignment_id == item.id,
                )
                .order_by(TMAClosureRun.closed_at)
            )
        ).scalars()
    )
    assert len(runs) == 2
    assert runs[0].id == first_run.id
    first_ids = set(
        (
            await w.db.execute(
                select(TMAClosureEligibility.student_id).where(
                    TMAClosureEligibility.tenant_id == w.tenant.id,
                    TMAClosureEligibility.closure_run_id == runs[0].id,
                )
            )
        ).scalars()
    )
    second_ids = set(
        (
            await w.db.execute(
                select(TMAClosureEligibility.student_id).where(
                    TMAClosureEligibility.tenant_id == w.tenant.id,
                    TMAClosureEligibility.closure_run_id == runs[1].id,
                )
            )
        ).scalars()
    )
    assert first_ids == {first_student.id}
    assert second_ids == {first_student.id, new_student.id}
    outcome = await TMADeadlineZeroService.process_pending(w.db, tenant_ids={w.tenant.id})
    assert outcome == {"zeroed": 1, "blocked": 0, "pending": 0}
