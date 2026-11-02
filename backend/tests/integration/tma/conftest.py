"""Real PostgreSQL academic graph; external queue delivery alone is mocked."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from app.modules.classes.models import (
    AcademicLevel,
    AcademicLevelStatus,
    AcademicCategory,
    ArmLabel,
    ClassRoom,
)
from app.modules.student_academics.curriculum_models import Curriculum, CurriculumSubject
from app.modules.student_academics.models import (
    AcademicSession,
    AcademicSessionStatus,
    AcademicTerm,
    AcademicTermName,
    AcademicTermStatus,
    AssessmentScheme,
    AssessmentSchemeStatus,
    AssessmentComponent,
    TeacherAssignment,
)
from app.modules.students.models import Student, StudentEnrollment
from app.modules.teachers.models import TeacherAccount, TeacherMembership, TeacherMembershipStatus
from app.modules.tenant_admins.models import TenantAdmin
from app.modules.subjects.models import Subject
from app.modules.tma.assignment_service import TMAAssignmentService
from app.modules.tma.schemas import TMAAssignmentCreate, TMAQuestionCreate, TMAOptionInput
from app.modules.tma.question_service import TMAQuestionService
from app.modules.tma.lifecycle_service import TMALifecycleService


@pytest_asyncio.fixture
async def db_session(_create_test_tables, test_engine):
    # SQLAlchemy 2 owns savepoints for service commits. The legacy event-based
    # restart hook cannot run inside a worker's nested transaction context.
    from sqlalchemy.ext.asyncio import AsyncSession

    async with test_engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await outer.rollback()


@pytest_asyncio.fixture
async def tma_world(db_session, tenant):
    db = db_session

    async def add(obj):
        db.add(obj)
        await db.flush()
        return obj

    today = date.today()
    now = datetime.now(timezone.utc)
    admin = await add(
        TenantAdmin(
            tenant_id=tenant.id, email=f"admin-{uuid4()}@example.com", password_hash="test-only"
        )
    )
    level = await add(
        AcademicLevel(
            tenant_id=tenant.id,
            name="JSS1",
            normalized_name="jss1",
            category=AcademicCategory.JUNIOR_SECONDARY,
            position=1,
            status=AcademicLevelStatus.ACTIVE,
        )
    )
    rooms = []
    for label in ("A", "B"):
        arm = await add(ArmLabel(tenant_id=tenant.id, label=label, normalized_label=label.lower()))
        rooms.append(
            await add(
                ClassRoom(tenant_id=tenant.id, academic_level_id=level.id, arm_label_id=arm.id)
            )
        )
    session = await add(
        AcademicSession(
            tenant_id=tenant.id,
            name="2026/2027",
            status=AcademicSessionStatus.OPEN,
            is_current=True,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=300),
        )
    )
    term = await add(
        AcademicTerm(
            tenant_id=tenant.id,
            academic_session_id=session.id,
            name=AcademicTermName.FIRST_TERM,
            status=AcademicTermStatus.OPEN,
            is_current=True,
            opened_at=now,
            opened_by_admin_id=admin.id,
            start_date=today - timedelta(days=20),
            end_date=today + timedelta(days=90),
        )
    )
    subject = await add(
        Subject(
            tenant_id=tenant.id,
            name="Mathematics",
            normalized_name="mathematics",
            code="MATH",
            normalized_code="math",
        )
    )
    curriculum = await add(Curriculum(tenant_id=tenant.id, academic_level_id=level.id))
    cs = await add(
        CurriculumSubject(tenant_id=tenant.id, curriculum_id=curriculum.id, subject_id=subject.id)
    )
    teachers, teaching = [], []
    for room in rooms:
        account = await add(
            TeacherAccount(email=f"teacher-{uuid4()}@example.com", password_hash="test-only")
        )
        teacher = await add(
            TeacherMembership(
                tenant_id=tenant.id,
                teacher_account_id=account.id,
                joined_at=now,
                status=TeacherMembershipStatus.ACTIVE,
            )
        )
        teachers.append(teacher)
        teaching.append(
            await add(
                TeacherAssignment(
                    tenant_id=tenant.id,
                    class_id=room.id,
                    curriculum_subject_id=cs.id,
                    teacher_membership_id=teacher.id,
                    effective_from=today - timedelta(days=15),
                )
            )
        )
    scheme = await add(
        AssessmentScheme(
            tenant_id=tenant.id, name="CA", status=AssessmentSchemeStatus.ACTIVE, activated_at=now
        )
    )
    component = await add(
        AssessmentComponent(
            tenant_id=tenant.id,
            assessment_scheme_id=scheme.id,
            name="CA1",
            maximum_score=Decimal("20"),
            position=1,
            is_examinable=False,
        )
    )

    async def student(room=0, **kwargs):
        person = await add(
            Student(
                tenant_id=tenant.id,
                admission_number=uuid4().hex[:16],
                first_name="Test",
                last_name=uuid4().hex[:8],
                **kwargs,
            )
        )
        enrollment = await add(
            StudentEnrollment(
                tenant_id=tenant.id,
                student_id=person.id,
                class_id=rooms[room].id,
                academic_level_id=level.id,
                academic_session_id=session.id,
                started_on=today - timedelta(days=10),
            )
        )
        return person, enrollment

    async def assignment(publish=True, component_override=None):
        item = await TMAAssignmentService.create_assignment(
            db,
            actor=admin,
            payload=TMAAssignmentCreate(
                academic_level_id=level.id,
                curriculum_subject_id=cs.id,
                academic_session_id=session.id,
                academic_term_id=term.id,
                assessment_component_id=(component_override or component).id,
                closes_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        )
        question = await TMAQuestionService.add_question(
            db,
            actor=admin,
            assignment_id=item.id,
            payload=TMAQuestionCreate(
                position=1,
                question_text="1+1?",
                options=[
                    TMAOptionInput(position=i, option_text=str(i), is_correct=i == 2)
                    for i in range(1, 5)
                ],
            ),
        )
        if publish:
            await TMALifecycleService.activate_assignment(db, actor=admin, assignment_id=item.id)
        return item, question

    return SimpleNamespace(
        db=db,
        tenant=tenant,
        admin=admin,
        level=level,
        rooms=rooms,
        session=session,
        term=term,
        subject=subject,
        cs=cs,
        teachers=teachers,
        teaching=teaching,
        scheme=scheme,
        component=component,
        student=student,
        assignment=assignment,
        add=add,
    )


@pytest_asyncio.fixture
async def tma_committed_world(_create_test_tables, test_engine):
    """Committed seed for independent connections; delete only its unique tenant."""
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.shared.base_model import Base
    from app.tenant_management.models import Tenant
    from tests.fixtures.tenants import tenant as tenant_fixture

    assert test_engine.url.host in ("localhost", "127.0.0.1")
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        own_tenant = await tenant_fixture.__wrapped__(db)
        world = await tma_world.__wrapped__(db, own_tenant)
        await db.commit()
        tenant_id = own_tenant.id
        print(f"Committed test tenant: {tenant_id}")
        try:
            yield world
        finally:
            await db.rollback()
            account_ids = list(
                (
                    await db.execute(
                        select(TeacherMembership.teacher_account_id).where(
                            TeacherMembership.tenant_id == tenant_id
                        )
                    )
                ).scalars()
            )
            # This list contains only the graph created above, never existing
            # development rows. Children precede their restricted parents.
            for name in (
                "tma_answers",
                "tma_attempts",
                "tma_participants",
                "tma_question_options",
                "tma_questions",
                "tma_deadline_eligibility",
                "tma_zero_grading_failures",
                "tma_cancellation_runs",
                "tma_assignment_revisions",
                "tma_assignments",
                "student_assessment_scores",
                "student_subject_results",
                "teacher_assignments",
                "student_elective_selections",
                "student_enrollments",
                "students",
                "assessment_components",
                "assessment_schemes",
                "curriculum_subject_departments",
                "curriculum_subjects",
                "curricula",
                "subjects",
                "academic_terms",
                "academic_sessions",
                "classes",
                "arm_labels",
                "academic_levels",
                "teacher_memberships",
                "tenant_admins",
            ):
                table = Base.metadata.tables[f"public.{name}"]
                await db.execute(delete(table).where(table.c.tenant_id == tenant_id))
            await db.execute(delete(TeacherAccount).where(TeacherAccount.id.in_(account_ids)))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await db.commit()
