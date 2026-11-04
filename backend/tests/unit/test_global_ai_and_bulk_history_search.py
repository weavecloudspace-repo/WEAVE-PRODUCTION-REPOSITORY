"""Ensure authorized global searches run before pagination and compute matching totals."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.bulk_imports.repository import ImportJobRepository
from app.modules.cbt.ai.quota.repository import AIQuotaRequestRepository


class _Rows:
    def all(self):
        return []


class _Result:
    def __init__(self, count=None):
        self.count = count

    def scalar_one(self):
        return self.count

    def scalars(self):
        return _Rows()

    def all(self):
        return []


class _CaptureSession:
    def __init__(self, *, count_first: bool):
        self.queries = []
        self.count_first = count_first

    async def execute(self, statement):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.queries.append(sql)
        is_count = "count(" in sql.lower()
        return _Result(37) if is_count else _Result()


@pytest.mark.asyncio
async def test_bulk_filename_search_filters_before_pagination() -> None:
    db = _CaptureSession(count_first=False)
    rows, total = await ImportJobRepository.list_jobs(
        db, tenant_id=uuid.uuid4(), search="jss2-import.csv", skip=20, limit=20
    )
    assert rows == [] and total == 37
    page, count = db.queries
    assert "original_filename ILIKE" in page
    assert "original_filename ILIKE" in count
    assert "OFFSET" in page and "LIMIT" in page
    assert "OFFSET" not in count and "LIMIT" not in count
    assert "tenant_id" in page and "tenant_id" in count


@pytest.mark.asyncio
async def test_ai_credit_request_search_filters_before_pagination() -> None:
    db = _CaptureSession(count_first=True)
    rows, total = await AIQuotaRequestRepository.list_for_tenant_with_requester(
        db, tenant_id=uuid.uuid4(), search="ade", offset=20, limit=20
    )
    assert rows == [] and total == 37
    count, page = db.queries
    assert "EXISTS" in count and "teacher_accounts" in count
    assert "EXISTS" in page and "teacher_accounts" in page
    assert "OFFSET" not in count and "LIMIT" not in count
    assert "OFFSET" in page and "LIMIT" in page
    assert "tenant_id" in count and "tenant_id" in page
