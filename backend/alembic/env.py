from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config.settings import settings  # noqa: E402
import app.models  # noqa: E402,F401
from app.shared.base_model import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


def _normalized_compiled_type(dialect: Any, column_type: Any) -> str:
    """Compile a type through the active dialect for semantic comparison."""

    implementation = column_type.dialect_impl(dialect)
    compiled = dialect.type_compiler.process(implementation)
    return " ".join(compiled.upper().split())


def _compare_type(
    migration_context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Suppress PostgreSQL reflection noise while preserving real type drift."""

    _ = inspected_column, metadata_column

    inspected_enums = tuple(getattr(inspected_type, "enums", ()) or ())
    metadata_enums = tuple(getattr(metadata_type, "enums", ()) or ())
    if inspected_enums and set(inspected_enums) == set(metadata_enums):
        inspected_name = getattr(inspected_type, "name", None)
        metadata_name = getattr(metadata_type, "name", None)
        if inspected_name == metadata_name:
            return False

    # SQLAlchemy may reflect a non-native Enum, including one used as an ARRAY
    # item type, as its VARCHAR implementation. Equal dialect output means the
    # two declarations use the same PostgreSQL storage type.
    try:
        inspected_compiled = _normalized_compiled_type(
            migration_context.dialect,
            inspected_type,
        )
        metadata_compiled = _normalized_compiled_type(
            migration_context.dialect,
            metadata_type,
        )
    except (AttributeError, TypeError, ValueError):
        return None

    if inspected_compiled == metadata_compiled:
        return False

    return None


def _normalized_schema(value: str | None) -> str:
    return value or "public"


def _normalized_fk_action(value: str | None) -> str:
    normalized = (value or "").strip().upper().replace("_", " ")
    # PostgreSQL reflection may omit explicit RESTRICT from Inspector options
    # while Alembic's reflected constraint retains it. For non-deferrable
    # constraints RESTRICT and NO ACTION are equivalent, so normalize both.
    return "" if normalized in {"", "NO ACTION", "RESTRICT"} else normalized


def _fk_signature(
    *,
    source_schema: str | None,
    source_table: str,
    local_columns: tuple[str, ...] | list[str],
    referent_schema: str | None,
    referent_table: str,
    remote_columns: tuple[str, ...] | list[str],
    ondelete: str | None = None,
    onupdate: str | None = None,
    deferrable: bool | None = None,
    initially: str | None = None,
) -> tuple[Any, ...]:
    return (
        _normalized_schema(source_schema),
        source_table,
        tuple(local_columns),
        _normalized_schema(referent_schema),
        referent_table,
        tuple(remote_columns),
        _normalized_fk_action(ondelete),
        _normalized_fk_action(onupdate),
        bool(deferrable),
        (initially or "").strip().upper(),
    )


def _constraint_fk_signature(
    constraint: sa.ForeignKeyConstraint,
) -> tuple[Any, ...]:
    elements = tuple(constraint.elements)
    if not elements:
        raise ValueError("Foreign-key constraint has no elements.")

    referred_table = elements[0].column.table
    return _fk_signature(
        source_schema=constraint.table.schema,
        source_table=constraint.table.name,
        local_columns=tuple(column.name for column in constraint.columns),
        referent_schema=referred_table.schema,
        referent_table=referred_table.name,
        remote_columns=tuple(element.column.name for element in elements),
        ondelete=elements[0].ondelete,
        onupdate=elements[0].onupdate,
        deferrable=constraint.deferrable,
        initially=constraint.initially,
    )


def _metadata_fk_signatures() -> set[tuple[Any, ...]]:
    return {
        _constraint_fk_signature(constraint)
        for table in target_metadata.tables.values()
        for constraint in table.foreign_key_constraints
    }


def _database_fk_signatures(
    connection: Any,
) -> tuple[set[tuple[Any, ...]], dict[str, tuple[Any, ...]]]:
    inspector = sa.inspect(connection)
    signatures: set[tuple[Any, ...]] = set()
    named_signatures: dict[str, tuple[Any, ...]] = {}

    for table_name in inspector.get_table_names(schema="public"):
        for reflected_fk in inspector.get_foreign_keys(table_name, schema="public"):
            referred_table = reflected_fk.get("referred_table")
            if not referred_table:
                continue

            options = reflected_fk.get("options") or {}
            signature = _fk_signature(
                source_schema="public",
                source_table=table_name,
                local_columns=reflected_fk.get("constrained_columns") or (),
                referent_schema=reflected_fk.get("referred_schema"),
                referent_table=referred_table,
                remote_columns=reflected_fk.get("referred_columns") or (),
                ondelete=options.get("ondelete"),
                onupdate=options.get("onupdate"),
                deferrable=options.get("deferrable"),
                initially=options.get("initially"),
            )
            signatures.add(signature)
            if name := reflected_fk.get("name"):
                named_signatures[name] = signature

    return signatures, named_signatures


METADATA_FK_SIGNATURES = _metadata_fk_signatures()
METADATA_NAMED_FK_SIGNATURES = {
    constraint.name: _constraint_fk_signature(constraint)
    for table in target_metadata.tables.values()
    for constraint in table.foreign_key_constraints
    if constraint.name
}


def _schema_neutral_index_name(name: str | None) -> str:
    return (name or "").replace("ix_public_", "ix_", 1)


def _index_signature(index: sa.Index) -> tuple[Any, ...]:
    return (
        index.table.name,
        tuple(column.name for column in index.columns),
        bool(index.unique),
        _schema_neutral_index_name(index.name),
    )


def _public_schema_index_signatures() -> set[tuple[Any, ...]]:
    signatures: set[tuple[Any, ...]] = set()
    for table in target_metadata.tables.values():
        for index in table.indexes:
            if index.name != _schema_neutral_index_name(index.name):
                signatures.add(_index_signature(index))
    return signatures


PUBLIC_SCHEMA_INDEX_SIGNATURES = _public_schema_index_signatures()


def _include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Limit autogeneration to the application's public PostgreSQL schema."""

    _ = parent_names
    if type_ == "schema":
        return name in {None, "public"}
    return True


def _include_object(
    database_fk_signatures: set[tuple[Any, ...]],
    database_named_fk_signatures: dict[str, tuple[Any, ...]],
):
    def include_object(
        obj: Any,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: Any,
    ) -> bool:
        """Suppress known representation noise without hiding real schema drift."""

        if type_ == "table" and name == "alembic_version":
            return False

        # Alembic can materialize public-schema composite FKs differently from
        # both Inspector and model objects. Suppress those unmatched halves only
        # when the database and metadata independently report the same named,
        # fully normalized constraint. A missing or changed FK still surfaces.
        if type_ == "foreign_key_constraint" and name:
            database_signature = database_named_fk_signatures.get(name)
            metadata_signature = METADATA_NAMED_FK_SIGNATURES.get(name)
            if database_signature is not None and database_signature == metadata_signature:
                return False

        if type_ == "index" and isinstance(obj, sa.Index) and compare_to is None:
            if obj.name != _schema_neutral_index_name(obj.name):
                return False
            if _index_signature(obj) in PUBLIC_SCHEMA_INDEX_SIGNATURES:
                return False

        if type_ == "unique_constraint" and isinstance(obj, sa.UniqueConstraint):
            columns = tuple(column.name for column in obj.columns)
            primary_key_columns = tuple(column.name for column in obj.table.primary_key.columns)
            if columns == ("id",) and primary_key_columns == ("id",):
                return False

        # PostgreSQL reflection may represent an unqualified public-schema FK as
        # a different object from the metadata FK. Alembic then reports the same
        # constraint once as removed and once as added. Suppress both unmatched
        # halves only when their full normalized signatures are identical.
        if (
            type_ == "foreign_key_constraint"
            and compare_to is None
            and isinstance(obj, sa.ForeignKeyConstraint)
        ):
            signature = _constraint_fk_signature(obj)
            if reflected and signature in METADATA_FK_SIGNATURES:
                return False
            if not reflected and signature in database_fk_signatures:
                return False

        return True

    return include_object


def _configure_context(
    *,
    connection: Any | None = None,
    database_fk_signatures: set[tuple[Any, ...]] | None = None,
    database_named_fk_signatures: dict[str, tuple[Any, ...]] | None = None,
) -> None:
    """Apply one comparison policy to online and offline migration runs."""

    options: dict[str, Any] = {
        "target_metadata": target_metadata,
        "include_schemas": True,
        "include_name": _include_name,
        "version_table_schema": "public",
        "compare_type": _compare_type,
        "compare_server_default": False,
        "include_object": _include_object(
            database_fk_signatures or set(),
            database_named_fk_signatures or {},
        ),
    }
    if connection is None:
        options.update(
            {
                "url": settings.DATABASE_URL or "",
                "literal_binds": True,
                "dialect_opts": {"paramstyle": "named"},
            }
        )
    else:
        options["connection"] = connection

    context.configure(**options)


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    _configure_context()
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    database_url = (settings.DATABASE_URL or "").replace("%", "%%")
    config.set_main_option("sqlalchemy.url", database_url)

    def do_run_migrations(sync_connection: Any, *, externally_managed: bool = False) -> None:
        # FK reflection opens an implicit read transaction. Close it before
        # Alembic begins its migration transaction so DDL is not rolled back when
        # the async connection context exits.
        database_fk_signatures, database_named_fk_signatures = _database_fk_signatures(
            sync_connection
        )
        if not externally_managed and sync_connection.in_transaction():
            sync_connection.commit()

        _configure_context(
            connection=sync_connection,
            database_fk_signatures=database_fk_signatures,
            database_named_fk_signatures=database_named_fk_signatures,
        )

        try:
            with context.begin_transaction():
                context.run_migrations()

            # Persist both transactional DDL and the alembic_version update when
            # Alembic joins SQLAlchemy's implicit transaction on an async bridge.
            if not externally_managed and sync_connection.in_transaction():
                sync_connection.commit()
        except Exception:
            if not externally_managed and sync_connection.in_transaction():
                sync_connection.rollback()
            raise

    async def run_async_migrations() -> None:
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            connect_args={"statement_cache_size": 0},
        )

        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

        await connectable.dispose()

    # Railway's deployment runner owns this connection, transaction and advisory
    # lock. Never commit or roll back a transaction managed by that caller.
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        do_run_migrations(provided_connection, externally_managed=True)
        return

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
