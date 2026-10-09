"""Deployment migrator refuses unversioned/partial schemas and serializes upgrades."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import schema_migrations
from app.config.schema_baseline import BASELINE_REVISION, BASELINE_TABLES


class _Tables:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.items)


class _Connection:
    def __init__(self, tables, revisions=(BASELINE_REVISION,)):
        self.tables = tables
        self.execute = AsyncMock(side_effect=self._execute)
        self.run_sync = AsyncMock(return_value=revisions)

    async def _execute(self, statement, parameters=None):
        del parameters
        if "pg_catalog.pg_tables" in str(statement):
            return _Tables(self.tables)
        return _Tables(())


class _Engine:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def begin(self):
        yield self.connection


@pytest.fixture
def configured(monkeypatch):
    config = MagicMock()
    config.attributes = {}
    scripts = MagicMock()
    scripts.get_heads.return_value = [BASELINE_REVISION]
    scripts.get_revision.return_value = object()
    monkeypatch.setattr(schema_migrations, "migration_config", lambda: config)
    monkeypatch.setattr(schema_migrations.ScriptDirectory, "from_config", lambda _: scripts)
    return config, scripts


@pytest.mark.asyncio
async def test_fresh_install_uses_migrations_instead_of_orm(configured) -> None:
    connection = _Connection(set())
    await schema_migrations.upgrade_database(_Engine(connection))
    connection.run_sync.assert_awaited_once()
    assert connection.execute.await_count == 3  # advisory lock, search_path, table check


@pytest.mark.asyncio
async def test_versioned_database_can_upgrade(configured) -> None:
    connection = _Connection(BASELINE_TABLES | {"alembic_version"})
    await schema_migrations.upgrade_database(_Engine(connection))
    assert connection.run_sync.await_count == 2  # revision read, Alembic upgrade


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tables",
    [
        {"students"},
        {"alembic_version"},
        BASELINE_TABLES,
        (BASELINE_TABLES - {"students"}) | {"alembic_version"},
    ],
)
async def test_refuses_partial_or_unversioned_databases(configured, tables) -> None:
    connection = _Connection(tables)
    with pytest.raises(RuntimeError, match="Refusing|missing frozen baseline"):
        await schema_migrations.upgrade_database(_Engine(connection))
    connection.run_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_refuses_unknown_revision(configured) -> None:
    _, scripts = configured
    scripts.get_revision.side_effect = lambda rev: object() if rev == BASELINE_REVISION else None
    connection = _Connection(BASELINE_TABLES | {"alembic_version"}, ("unknown_revision",))
    with pytest.raises(RuntimeError, match="not known"):
        await schema_migrations.upgrade_database(_Engine(connection))
    assert connection.run_sync.await_count == 1


def test_alembic_uses_caller_connection_and_checks_schema_drift(configured, monkeypatch):
    config, _ = configured
    upgrade = MagicMock()
    check = MagicMock()
    monkeypatch.setattr(schema_migrations.command, "upgrade", upgrade)
    monkeypatch.setattr(schema_migrations.command, "check", check)
    connection = object()

    schema_migrations._upgrade_on_connection(connection)

    upgrade.assert_called_once_with(config, "head")
    check.assert_called_once_with(config)
    assert "connection" not in config.attributes


def test_failure_cleans_injected_connection(configured, monkeypatch):
    config, _ = configured
    monkeypatch.setattr(
        schema_migrations.command, "upgrade", MagicMock(side_effect=RuntimeError("failure"))
    )
    with pytest.raises(RuntimeError, match="failure"):
        schema_migrations._upgrade_on_connection(object())
    assert "connection" not in config.attributes
