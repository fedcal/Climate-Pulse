"""pytest fixtures for integration tests requiring Docker + TimescaleDB.

Uses testcontainers (DockerContainer) — NOT PostgresContainer — because
PostgresContainer does not know about the TimescaleDB extension.

Image: timescale/timescaledb:2.17.2-pg16 (pinned — Pitfall E forbids latest-pg16).

Design notes on event loop scope:
    The timescale_container fixture is session-scoped (sync) to share a single
    Docker container. The Alembic migration is run once per session (sync
    subprocess). Test fixtures that need DB access create fresh asyncpg
    connections per test function to avoid event-loop-scoping issues with
    session-scoped asyncpg pools.

    The `db_pool` session fixture provides a pool backed by the shared container.
    Since asyncpg pools are tied to an event loop, and pytest-asyncio 1.x uses
    function-scoped loops by default, tests acquire individual connections from
    the pool only within the same loop context.
"""

import asyncio
import os
import subprocess
import time

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

# Pinned image tag per Pitfall E (never use latest-pg16 in CI).
# If 2.17.2-pg16 is not available on the target runner, adjust to the closest
# available 2.17.x-pg16 tag and document in SUMMARY.md.
TIMESCALE_IMAGE = "timescale/timescaledb:2.17.2-pg16"


@pytest.fixture(scope="session")
def timescale_container():
    """Start a TimescaleDB testcontainer for the entire test session.

    Uses DockerContainer (not PostgresContainer) because PostgresContainer
    does not activate the TimescaleDB extension automatically.
    """
    container = DockerContainer(TIMESCALE_IMAGE)
    container.with_env("POSTGRES_DB", "test_climatepulse")
    container.with_env("POSTGRES_USER", "test")
    container.with_env("POSTGRES_PASSWORD", "test")
    container.with_exposed_ports(5432)

    with container:
        # Wait for PostgreSQL to be ready to accept connections.
        # Uses the deprecated string-predicate API — log message is stable
        # across TimescaleDB 2.17.x so we accept the deprecation warning.
        wait_for_logs(
            container,
            "database system is ready to accept connections",
            timeout=60,
        )
        # Extra wait for TimescaleDB extension to fully initialize after
        # PostgreSQL signals readiness (TimescaleDB loader runs post-startup).
        time.sleep(2)
        yield container


@pytest.fixture(scope="session")
def db_connection_info(timescale_container):
    """Return (host, port) for the running testcontainer."""
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return host, port


@pytest.fixture(scope="session")
def db_dsn(db_connection_info):
    """Return the asyncpg-compatible DSN for the testcontainer."""
    host, port = db_connection_info
    return f"postgresql://test:test@{host}:{port}/test_climatepulse"


@pytest.fixture(scope="session")
def _run_migrations(timescale_container, db_connection_info, db_dsn):
    """Session-scoped sync fixture: run Alembic migrations once per session.

    Creates the extension and runs the migration synchronously via asyncio.run
    and subprocess to avoid any event-loop-scoping conflicts.
    """
    host, port = db_connection_info

    # Activate TimescaleDB extension synchronously
    async def _init():
        conn = None
        for attempt in range(5):
            try:
                conn = await asyncpg.connect(db_dsn)
                break
            except Exception as exc:
                if attempt == 4:
                    raise RuntimeError(
                        f"Failed to connect to testcontainer after 5 attempts: {exc}"
                    ) from exc
                await asyncio.sleep(2 * (attempt + 1))
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        finally:
            await conn.close()

    asyncio.run(_init())

    # Run Alembic upgrade head via subprocess
    alembic_dsn = (
        f"postgresql+asyncpg://test:test@{host}:{port}/test_climatepulse"
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "alembic",
            "-c",
            "packages/migrations/alembic.ini",
            "upgrade",
            "head",
        ],
        env={**os.environ, "DATABASE_URL": alembic_dsn},
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic upgrade failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    # Seed metadata once for the session
    async def _seed():
        conn = await asyncpg.connect(db_dsn)
        try:
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (source_id, name, license, attribution)
                VALUES ('test_src', 'Test Source', 'MIT', 'Test Attribution')
                ON CONFLICT (source_id) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            )
            variable_id = await conn.fetchval(
                """
                INSERT INTO variables (wmo_code, bufr_code, unit_si)
                VALUES ('air_temperature', 'B12101', 'K')
                ON CONFLICT (wmo_code) DO UPDATE SET unit_si = EXCLUDED.unit_si
                RETURNING id
                """
            )
            station_id = await conn.fetchval(
                """
                INSERT INTO stations (source_id, external_id, name, lat, lon)
                VALUES ($1, 'stn001', 'Test Station', 44.6, 11.0)
                ON CONFLICT (source_id, external_id) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                source_id,
            )
            return {"source_id": source_id, "variable_id": variable_id, "station_id": station_id}
        finally:
            await conn.close()

    metadata = asyncio.run(_seed())
    return metadata


@pytest.fixture(scope="session")
def db_pool_dsn(db_dsn, _run_migrations):
    """Return the DSN for use in per-test async fixtures.

    Depends on _run_migrations to guarantee schema is ready.
    """
    return db_dsn


@pytest.fixture(scope="session")
def seed_metadata(_run_migrations):
    """Return session-level metadata ids for use in tests.

    Session-scoped sync fixture that returns the pre-seeded surrogate ids.
    """
    return _run_migrations


@pytest_asyncio.fixture
async def db_pool(db_pool_dsn):
    """Per-test asyncpg pool connected to the shared testcontainer.

    Function-scoped so the pool is created in the same event loop as the test.
    Creates a fresh pool per test, which is slightly slower but avoids all
    event-loop-scoping issues with session-scoped asyncpg pools.
    """
    pool = await asyncpg.create_pool(db_pool_dsn, min_size=1, max_size=3)
    yield pool
    await pool.close()
