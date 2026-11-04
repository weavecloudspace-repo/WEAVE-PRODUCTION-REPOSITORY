"""Regression: tenant-scoped search and filters must precede LIMIT/OFFSET."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.report_cards.repository import ReportCardRepository
from app.modules.tma.models import TMAAssignmentStatus
from app.modules.tma.repository import TMAAssignmentRepository


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


class _CapturingSession:
    def __init__(self):
        self.queries = []

    async def execute(self, query):
        self.queries.append(str(query.compile(dialect=postgresql.dialect())))
        return _Result(42) if len(self.queries) % 2 else _Result()


@pytest.mark.asyncio
async def test_tma_filters_search_before_offset_and_counts_matches() -> None:
    db = _CapturingSession()
    rows, total = await TMAAssignmentRepository.list_for_scope(
        db, uuid.uuid4(), academic_term_id=uuid.uuid4(),
        status=TMAAssignmentStatus.ACTIVE, search="Mathematics", offset=24, limit=24,
    )
    assert rows == [] and total == 42
    count, page = db.queries
    assert "FROM tma_assignments" in count
    assert "EXISTS" in count and "subjects" in count and "academic_levels" in count
    assert "tma_assignments.status" in count
    assert "LIMIT" not in count and "OFFSET" not in count
    assert "LIMIT" in page and "OFFSET" in page


@pytest.mark.asyncio
async def test_report_cards_search_before_offset_and_counts_matches() -> None:
    db = _CapturingSession()
    rows, total = await ReportCardRepository.list_cards(
        db, uuid.uuid4(), search="Ade", skip=24, limit=24,
    )
    assert rows == [] and total == 42
    count, page = db.queries
    assert "FROM report_cards" in count and "EXISTS" in count and "students" in count
    assert "LIMIT" not in count and "OFFSET" not in count
    assert "LIMIT" in page and "OFFSET" in page
