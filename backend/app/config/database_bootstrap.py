"""Read-only database readiness gate for Weave API startup.

Schema creation and upgrades belong exclusively to the Railway pre-deploy
migration command. API replicas NEVER create tables, run migrations or stamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.config.logging import get_logger
from app.config.schema_baseline import BASELINE_REVISION
from app.shared.base_model import Base

_BOOTSTRAP_LOCK_KEY = 8_733_241_109_202_609_11
_ALEMBIC_VERSION_TABLE = "alembic_version"

logger = get_logger(__name__)


class SchemaState(str, Enum):
    FRESH = "fresh"
    INITIALIZED = "initialized"
    PARTIAL = "partial"


@dataclass(frozen=True)
class BootstrapResult:
    state: SchemaState
    initialized_now: bool


def migration_config() -> Config:
    """Resolve Alembic config regardless of the current working directory."""
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


def migration_head() -> str:
    heads = ScriptDirectory.from_config(migration_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one Weave Alembic head; found {heads!r}.")
    return heads[0]


def classify_schema_state(
    existing_tables: set[str],
    expected_tables: set[str],
) -> SchemaState:
    """An unversioned schema is NEVER treated as initialized."""
    if not existing_tables:
        return SchemaState.FRESH
    application_tables = existing_tables - {_ALEMBIC_VERSION_TABLE}
    if (
        _ALEMBIC_VERSION_TABLE in existing_tables
        and expected_tables
        and expected_tables.issubset(application_tables)
    ):
        return SchemaState.INITIALIZED
    return SchemaState.PARTIAL


async def _read_public_table_names(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(
        text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
    )
    return set(result.scalars())


def _read_revisions(sync_connection) -> tuple[str, ...]:
    return MigrationContext.configure(
        sync_connection, opts={"version_table_schema": "public"}
    ).get_current_heads()


async def bootstrap_database(engine: AsyncEngine) -> BootstrapResult:
    """Reject unmigrated/partial databases; never perform DDL during API startup."""
    configure_mappers()
    expected_tables = {table.name for table in Base.metadata.tables.values()}
    if not expected_tables:
        raise RuntimeError("The SQLAlchemy model registry is empty; refusing startup.")

    async with engine.begin() as connection:
        # Wait for an in-flight deployment migration before checking readiness.
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _BOOTSTRAP_LOCK_KEY},
        )
        existing_tables = await _read_public_table_names(connection)
        state = classify_schema_state(existing_tables, expected_tables)
        if state is SchemaState.FRESH:
            raise RuntimeError(
                "Weave database is empty. Run the Alembic pre-deploy migration "
                "command before starting the API; refusing runtime creation or stamping."
            )
        if state is SchemaState.PARTIAL:
            raise RuntimeError(
                "Weave database is unversioned or missing expected tables. "
                "Refusing automatic repair or stamping; inspect the target schema."
            )
        current = await connection.run_sync(_read_revisions)
        head = migration_head()
        if current != (head,):
            raise RuntimeError(
                f"Weave database revision {current!r} does not match Alembic "
                f"head {head!r}. Run the deployment migration command first."
            )
        logger.info("Database is already at Alembic head; API startup permitted")
        return BootstrapResult(state=SchemaState.INITIALIZED, initialized_now=False)
