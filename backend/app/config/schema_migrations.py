"""Serialized, Alembic-only schema upgrades for a dedicated deploy step.

Run with: python -m app.config.schema_migrations
Never invoke this module from the FastAPI lifespan or a worker process.
"""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.database import engine
from app.config.database_bootstrap import (
    _BOOTSTRAP_LOCK_KEY,
    _read_public_table_names,
    migration_config,
)
from app.config.logging import get_logger
from app.config.schema_baseline import BASELINE_REVISION, BASELINE_TABLES

logger = get_logger(__name__)


def _upgrade_on_connection(connection: Connection) -> None:
    """Run Alembic and drift validation inside the caller's PostgreSQL transaction."""
    config = migration_config()
    config.attributes["connection"] = connection
    try:
        command.upgrade(config, "head")
        # A revision marker is not proof the physical schema is correct.
        # Fail the deployment on unexpected schema/model drift.
        command.check(config)
    finally:
        config.attributes.pop("connection", None)


async def upgrade_database(database_engine: AsyncEngine = engine) -> None:
    """Upgrade fresh or known-versioned schemas, rejecting unknown/partial state."""
    config = migration_config()
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected a single Alembic head; got {heads!r}.")
    if scripts.get_revision(BASELINE_REVISION) is None:
        raise RuntimeError("Frozen Weave Alembic baseline cannot be located.")

    async with database_engine.begin() as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _BOOTSTRAP_LOCK_KEY},
        )
        await connection.execute(text("SET LOCAL search_path TO public"))
        tables = await _read_public_table_names(connection)
        if tables:
            if "alembic_version" not in tables:
                raise RuntimeError(
                    "Existing Weave database has no Alembic version table. "
                    "Refusing automatic adoption or stamping."
                )
            missing = BASELINE_TABLES - tables
            if missing:
                raise RuntimeError(
                    "Versioned Weave database is missing frozen baseline tables; "
                    "refusing automatic repair. Missing: "
                    + ", ".join(sorted(missing)[:12])
                )
            revisions = await connection.run_sync(
                lambda sync: MigrationContext.configure(
                    sync, opts={"version_table_schema": "public"}
                ).get_current_heads()
            )
            if len(revisions) != 1:
                raise RuntimeError(
                    f"Expected exactly one existing Alembic revision, got {revisions!r}. "
                    "Refusing ambiguous or unversioned schema."
                )
            if scripts.get_revision(revisions[0]) is None:
                raise RuntimeError(
                    f"Database revision {revisions[0]!r} is not known to this release."
                )
            logger.info("Upgrading existing Weave schema from %s", revisions[0])
        else:
            logger.info("Creating new Weave schema from frozen Alembic migrations")

        await connection.run_sync(_upgrade_on_connection)
        logger.info("Weave schema migrations and drift validation succeeded")


async def _main() -> None:
    try:
        await upgrade_database()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
