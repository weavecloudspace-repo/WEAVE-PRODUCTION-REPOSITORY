"""Real PostgreSQL query budgets: adding rows must not add per-row SELECTs."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select

from app.modules.subjects.models import Subject
from app.modules.student_academics.curriculum_models import CurriculumSubject
from app.modules.student_academics.models import AssessmentComponent, TeacherAssignment
from app.modules.tma.attempt_service import TMAAttemptService
from app.modules.tma.configuration_service import get_authoring_configuration
from app.modules.tma.ai_service import TMAAIService
from app.modules.tma.ai_schemas import TMAAIBulkImportRequest


@contextmanager
def select_queries(engine):
    calls = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            calls.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield calls
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "teacher"])
async def test_configuration_select_count_is_constant_as_subjects_grow(
    tma_world, test_engine, role
):
    w = tma_world
    actor = w.admin if role == "admin" else w.teachers[0]
    await get_authoring_configuration(w.db, actor)
    with select_queries(test_engine) as first:
        baseline = await get_authoring_configuration(w.db, actor)
    for index in range(9):
        subject = await w.add(
            Subject(
                tenant_id=w.tenant.id, name=f"Subject {index}", normalized_name=f"subject {index}"
            )
        )
        cs = await w.add(
            CurriculumSubject(
                tenant_id=w.tenant.id, curriculum_id=w.cs.curriculum_id, subject_id=subject.id
            )
        )
        for room, teacher in zip(w.rooms, w.teachers):
            await w.add(
                TeacherAssignment(
                    tenant_id=w.tenant.id,
                    class_id=room.id,
                    curriculum_subject_id=cs.id,
                    teacher_membership_id=teacher.id,
                    effective_from=date.today() - timedelta(days=1),
                )
            )
    await w.db.commit()
    with select_queries(test_engine) as grown:
        expanded = await get_authoring_configuration(w.db, actor)
    assert len(baseline["scopes"]) == 1 and len(expanded["scopes"]) == 10
    assert len(grown) <= len(first) + 1
    assert len(grown) <= 16


@pytest.mark.asyncio
async def test_student_listing_select_count_is_constant_as_assignments_grow(tma_world, test_engine):
    w = tma_world
    student, _ = await w.student()
    await w.assignment()
    with select_queries(test_engine) as first:
        baseline = await TMAAttemptService.list_available_assignments(w.db, student=student)
    for index in range(9):
        component = await w.add(
            AssessmentComponent(
                tenant_id=w.tenant.id,
                assessment_scheme_id=w.scheme.id,
                name=f"CA {index + 2}",
                position=index + 2,
                maximum_score=Decimal("1"),
                is_examinable=False,
            )
        )
        await w.assignment(component_override=component)
    with select_queries(test_engine) as grown:
        expanded = await TMAAttemptService.list_available_assignments(w.db, student=student)
    assert len(baseline) == 1 and len(expanded) == 10
    assert len(grown) <= len(first) + 1


@pytest.mark.asyncio
async def test_text_ai_import_select_count_is_constant_as_batch_grows(tma_world, test_engine):
    w = tma_world
    counts = []
    for index, count in enumerate((2, 10)):
        component = await w.add(
            AssessmentComponent(
                tenant_id=w.tenant.id,
                assessment_scheme_id=w.scheme.id,
                name=f"AI CA {index}",
                position=index + 2,
                maximum_score=Decimal("1"),
                is_examinable=False,
            )
        )
        item, _ = await w.assignment(publish=False, component_override=component)
        payload = TMAAIBulkImportRequest(
            draft_id=uuid4(),
            revision_number=1,
            questions=[
                {
                    "question_type": "single_choice",
                    "prompt": f"Question {i}?",
                    "options": [{"text": str(n), "is_correct": n == 1} for n in range(1, 5)],
                }
                for i in range(count)
            ],
        )
        with select_queries(test_engine) as queries:
            imported = await TMAAIService.import_questions(
                w.db, actor=w.admin, assignment_id=item.id, payload=payload
            )
        assert imported == count
        counts.append(len(queries))
    assert counts[1] <= counts[0] + 1
    assert counts[1] <= 8


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 20])
async def test_cbt_ai_expiry_locks_buckets_once_and_preserves_balances(
    tma_world, test_engine, monkeypatch, count
):
    from app.modules.cbt.ai.quota.models import (
        AIQuotaAccount,
        AIQuotaActorType,
        AIWeeklyQuota,
        AIExtraCreditBalance,
        AICreditReservation,
        AICreditReservationStatus,
    )
    from app.modules.cbt.ai.quota import service as mod

    w = tma_world
    now = datetime.now(timezone.utc)
    account = await w.add(
        AIQuotaAccount(
            tenant_id=w.tenant.id,
            actor_type=AIQuotaActorType.TEACHER,
            teacher_membership_id=w.teachers[0].id,
        )
    )
    weekly = await w.add(
        AIWeeklyQuota(
            tenant_id=w.tenant.id,
            quota_account_id=account.id,
            week_start=mod.AIQuotaService._week_start(now.date()),
            credit_limit=100,
            used_credits=7,
            reserved_credits=count,
        )
    )
    extra = await w.add(
        AIExtraCreditBalance(
            tenant_id=w.tenant.id,
            quota_account_id=account.id,
            available_credits=100,
            reserved_credits=count,
        )
    )
    for _ in range(count):
        await w.add(
            AICreditReservation(
                tenant_id=w.tenant.id,
                quota_account_id=account.id,
                weekly_quota_id=weekly.id,
                reserved_free_credits=1,
                reserved_extra_credits=1,
                expires_at=now - timedelta(seconds=1),
            )
        )
    await w.db.commit()
    monkeypatch.setattr(mod, "invalidate_quota_cache", AsyncMock())
    with select_queries(test_engine) as queries:
        expired = await mod.AIQuotaService.expire_stale_reservations(
            w.db, as_of=now, limit=100, tenant_ids={w.tenant.id}
        )
    assert expired == count
    assert len(queries) == 3
    assert weekly.reserved_credits == extra.reserved_credits == 0
    assert weekly.used_credits == 7 and extra.available_credits == 100
    assert (
        await mod.AIQuotaService.expire_stale_reservations(
            w.db, as_of=now, tenant_ids={w.tenant.id}
        )
        == 0
    )
    rows = (
        (
            await w.db.execute(
                select(AICreditReservation).where(AICreditReservation.tenant_id == w.tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(r.status == AICreditReservationStatus.EXPIRED for r in rows)
