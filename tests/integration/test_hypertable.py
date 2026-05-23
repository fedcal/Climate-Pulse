"""Integration tests: verify BOTH hypertables exist and are correctly configured.

Tests:
- observations hypertable exists
- gridded_observations hypertable exists
- observations chunk_time_interval = 7 days
- gridded_observations chunk_time_interval = 1 day

Note: For TIMESTAMPTZ-based hypertables, TimescaleDB uses the `time_interval`
column (as PostgreSQL INTERVAL type) rather than `integer_interval` (which is
only populated for integer-based time columns). We compare the `time_interval`
field against expected INTERVAL values.
"""

from datetime import timedelta

import pytest
import pytest_asyncio

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_observations_hypertable_exists(db_pool):
    """observations must appear in timescaledb_information.hypertables."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM timescaledb_information.hypertables"
            " WHERE hypertable_name = 'observations'"
        )
    assert len(rows) == 1, (
        f"Expected exactly 1 hypertable row for 'observations', got {len(rows)}"
    )
    assert rows[0]["num_dimensions"] == 1, (
        f"Expected 1 dimension (time-only), got {rows[0]['num_dimensions']}"
    )


@pytest.mark.asyncio
async def test_gridded_observations_hypertable_exists(db_pool):
    """gridded_observations must appear in timescaledb_information.hypertables."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM timescaledb_information.hypertables"
            " WHERE hypertable_name = 'gridded_observations'"
        )
    assert len(rows) == 1, (
        f"Expected exactly 1 hypertable row for 'gridded_observations', got {len(rows)}"
    )
    assert rows[0]["num_dimensions"] == 1, (
        f"Expected 1 dimension (time-only), got {rows[0]['num_dimensions']}"
    )


@pytest.mark.asyncio
async def test_observations_chunk_interval_7d(db_pool):
    """observations chunk_time_interval must be exactly 7 days.

    For TIMESTAMPTZ-based hypertables, TimescaleDB stores the interval in
    the `time_interval` column (PostgreSQL INTERVAL type), not `integer_interval`
    (which is NULL for timestamp columns).
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT time_interval FROM timescaledb_information.dimensions"
            " WHERE hypertable_name = 'observations'"
        )
    assert row is not None, "No dimension found for 'observations'"
    actual_interval = row["time_interval"]
    expected_interval = timedelta(days=7)
    assert actual_interval == expected_interval, (
        f"Expected chunk_time_interval = 7 days, got {actual_interval}"
    )


@pytest.mark.asyncio
async def test_gridded_chunk_interval_1d(db_pool):
    """gridded_observations chunk_time_interval must be exactly 1 day.

    For TIMESTAMPTZ-based hypertables, TimescaleDB stores the interval in
    the `time_interval` column (PostgreSQL INTERVAL type), not `integer_interval`
    (which is NULL for timestamp columns).
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT time_interval FROM timescaledb_information.dimensions"
            " WHERE hypertable_name = 'gridded_observations'"
        )
    assert row is not None, "No dimension found for 'gridded_observations'"
    actual_interval = row["time_interval"]
    expected_interval = timedelta(days=1)
    assert actual_interval == expected_interval, (
        f"Expected chunk_time_interval = 1 day, got {actual_interval}"
    )
