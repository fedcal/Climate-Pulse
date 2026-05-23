"""Alembic environment for Climate Pulse migrations.

Run migrations via:
    alembic -c packages/migrations/alembic.ini upgrade head

This env uses the async SQLAlchemy pattern (create_async_engine + run_sync) to
support asyncpg. DATABASE_URL must be a postgresql+asyncpg:// URL.

TimescaleDB awareness:
    The `include_name` callback excludes TimescaleDB-managed internal tables and
    auto-created indexes from Alembic autogenerate. This prevents spurious DROP
    statements when running `alembic revision --autogenerate`.

    Excluded by table type:
    - Tables starting with '_timescaledb' (internal TimescaleDB catalog)
    - Tables starting with '_hyper_' (per-chunk internal tables)

    Excluded by index type:
    - Indexes starting with '_hyper_' (per-chunk TimescaleDB indexes)
    - Indexes starting with '_timescaledb_internal' (internal catalog indexes)
    - 'observations_observed_at_idx' (auto-created by create_hypertable on
      the observations time column)
    - 'gridded_observations_valid_at_idx' (auto-created by create_hypertable on
      the gridded_observations time column)

    See RESEARCH.md Q5 resolution for full rationale.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from climatepulse_core.storage.models import Base

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata

# Read DATABASE_URL from environment variable.
# Raises loud KeyError if not set — never use a default in production.
_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://climatepulse:changeme@localhost:5432/climatepulse",
)
if not _db_url:
    raise ValueError(
        "DATABASE_URL environment variable is not set. "
        "Set it to a postgresql+asyncpg:// connection URL."
    )


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Exclude TimescaleDB internal tables and auto-created indexes.

    Called by Alembic autogenerate to decide whether to include a database
    object in the generated migration. Returns False for TimescaleDB-managed
    objects to prevent spurious DROP statements.

    See RESEARCH.md Open Questions Q5 resolution for full rationale.
    Resolution: Use prefix matching for per-chunk objects + explicit set for
    hypertable-level time-column indexes (Pitfall D mitigation).
    """
    if type_ == "schema":
        return name in (None, "public")

    if type_ == "table":
        # Exclude TimescaleDB internal tables and per-chunk tables
        return not (name or "").startswith(("_timescaledb", "_hyper_"))

    if type_ == "index":
        # Exclude per-chunk TimescaleDB indexes (prefix matching)
        if (name or "").startswith(("_hyper_", "_timescaledb_internal")):
            return False
        # Exclude the two known hypertable-level time-column indexes
        # that create_hypertable auto-creates (stable names, not chunked)
        return name not in {
            "observations_observed_at_idx",
            "gridded_observations_valid_at_idx",
        }

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = _db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure context and run migrations on an active connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async engine (asyncpg driver)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _db_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
