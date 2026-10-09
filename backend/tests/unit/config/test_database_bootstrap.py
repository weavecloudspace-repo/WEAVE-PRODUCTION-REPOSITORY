"""Safety, version-gating, and idempotency tests for Weave API startup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.config import database_bootstrap
from app.config.database_bootstrap import BootstrapResult, SchemaState, classify_schema_state
from app.config.schema_baseline import BASELINE_REVISION
from app.shared.base_model import Base


class _ScalarResult:
    def __init__(self, values: set[str]) -> None:
        self._values = values

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._values)


class _Connection:
    def __init__(self, tables: set[str], revisions=(BASELINE_REVISION,)) -> None:
        self.tables = tables
        self.execute = AsyncMock(side_effect=self._execute)
        self.run_sync = AsyncMock(return_value=revisions)

    async def _execute(self, statement, parameters=None):
        del parameters
        if "pg_catalog.pg_tables" in str(statement):
            return _ScalarResult(self.tables)
        return _ScalarResult(set())


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def begin(self):
        yield self.connection


def _expected_tables() -> set[str]:
    return {table.name for table in Base.metadata.tables.values()}


def test_fresh_database_detection_requires_no_tables_or_marker() -> None:
    expected = _expected_tables()
    assert classify_schema_state(set(), expected) is SchemaState.FRESH
    assert classify_schema_state({"alembic_version"}, expected) is SchemaState.PARTIAL
    assert classify_schema_state(expected, expected) is SchemaState.PARTIAL
    assert (
        classify_schema_state(expected | {"alembic_version"}, expected) is SchemaState.INITIALIZED
    )


@pytest.mark.asyncio
async def test_api_never_creates_a_fresh_database() -> None:
    connection = _Connection(set())
    with pytest.raises(RuntimeError, match="Run the Alembic pre-deploy"):
        await database_bootstrap.bootstrap_database(_Engine(connection))
    connection.run_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_initialized_database_checks_revision_at_each_startup(monkeypatch) -> None:
    connection = _Connection(_expected_tables() | {"alembic_version"})
    monkeypatch.setattr(database_bootstrap, "migration_head", lambda: BASELINE_REVISION)

    first = await database_bootstrap.bootstrap_database(_Engine(connection))
    second = await database_bootstrap.bootstrap_database(_Engine(connection))

    assert first == second == BootstrapResult(SchemaState.INITIALIZED, False)
    assert connection.run_sync.await_count == 2
    assert not any("CREATE " in str(call.args[0]) for call in connection.execute.call_args_list)


@pytest.mark.asyncio
async def test_api_rejects_outdated_revision(monkeypatch) -> None:
    connection = _Connection(_expected_tables() | {"alembic_version"}, ("older",))
    monkeypatch.setattr(database_bootstrap, "migration_head", lambda: BASELINE_REVISION)
    with pytest.raises(RuntimeError, match="does not match Alembic head"):
        await database_bootstrap.bootstrap_database(_Engine(connection))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tables",
    [
        lambda: {"alembic_version"},
        lambda: _expected_tables(),
        lambda: {next(iter(_expected_tables()))},
    ],
)
async def test_partial_or_unversioned_schema_is_rejected(tables) -> None:
    connection = _Connection(tables())
    with pytest.raises(RuntimeError, match="Refusing automatic repair or stamping"):
        await database_bootstrap.bootstrap_database(_Engine(connection))
    connection.run_sync.assert_not_awaited()
