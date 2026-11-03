from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.students.admin_contracts import StudentAdminContractService
from app.modules.students.read_service import StudentReadService
from app.modules.students.lifecycle_service import StudentLifecycleService


@pytest.mark.asyncio
async def test_tenant_admin_list_materializes_due_returns_before_status_filtering() -> None:
    tenant_id = uuid.uuid4()
    actor = SimpleNamespace(tenant_id=tenant_id)
    db = AsyncMock()

    with (
        patch(
            "app.modules.students.lifecycle_service.StudentLifecycleService.activate_due_returns_for_tenant",
            new=AsyncMock(return_value=1),
        ) as activate_due,
        patch(
            "app.modules.students.admin_contracts.StudentRepository.list_for_tenant",
            new=AsyncMock(return_value=([], 0)),
        ) as list_students,
    ):
        items, total = await StudentAdminContractService.list_students(
            db,
            actor=actor,
            status=None,
        )

    assert items == []
    assert total == 0
    activate_due.assert_awaited_once_with(db, tenant_id=tenant_id)
    list_students.assert_awaited_once()
    assert activate_due.await_count == 1


@pytest.mark.asyncio
async def test_general_student_list_materializes_due_returns_before_query() -> None:
    tenant_id = uuid.uuid4()
    actor = SimpleNamespace(tenant_id=tenant_id)
    db = AsyncMock()

    with (
        patch(
            "app.modules.students.lifecycle_service.StudentLifecycleService.activate_due_returns_for_tenant",
            new=AsyncMock(return_value=1),
        ) as activate_due,
        patch(
            "app.modules.students.read_service.StudentRepository.list_for_tenant",
            new=AsyncMock(return_value=([], 0)),
        ) as list_students,
    ):
        items, total = await StudentReadService.list_students(db, actor)

    assert items == []
    assert total == 0
    activate_due.assert_awaited_once_with(db, tenant_id=tenant_id)
    list_students.assert_awaited_once()


@pytest.mark.asyncio
async def test_due_return_scan_avoids_locking_historical_enrollments() -> None:
    tenant_id = uuid.uuid4()
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    changed = await StudentLifecycleService.activate_due_returns_for_tenant(
        db,
        tenant_id=tenant_id,
    )

    assert changed == 0
    db.execute.assert_awaited_once()
    db.commit.assert_not_awaited()

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "student_enrollments.ended_on IS NULL" in sql
    assert "FOR UPDATE OF students SKIP LOCKED" in sql
