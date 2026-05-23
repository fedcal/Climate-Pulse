"""Integration tests: Continuous Aggregate refresh for all 4 CAGGs.

Tests:
1. obs_hourly aggregates after refresh (STO-03 raw → hourly tier)
2. obs_daily hierarchical aggregates (STO-03 obs_hourly → daily tier)
3. gridded_hourly aggregates after refresh (STO-03 grid raw → 6h tier)
4. gridded_daily hierarchical aggregates (STO-03 gridded_hourly → daily tier)

For obs_daily and gridded_daily, the tests also verify that the source of
the aggregate is the hourly CAGG (not raw), by inspecting
timescaledb_information.continuous_aggregates.view_definition.
"""

import pytest
from datetime import datetime, timezone, timedelta

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Anchor date for all test data: 2026-05-23 (UTC)
DAY = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs_at(hour: int = 0, minute: int = 0) -> datetime:
    """Return a UTC datetime on DAY at the given hour:minute."""
    return DAY + timedelta(hours=hour, minutes=minute)


def _gridded_at(hour: int = 0) -> datetime:
    """Return a UTC datetime on DAY at the given hour (for grid obs)."""
    return DAY + timedelta(hours=hour)


INSERT_OBS = """
    INSERT INTO observations
        (station_id, variable_id, observed_at, source_id, value, qc_flag)
    VALUES ($1, $2, $3, $4, $5, 0)
    ON CONFLICT (station_id, variable_id, observed_at, source_id)
    DO UPDATE SET value = EXCLUDED.value
"""

INSERT_GRIDDED = """
    INSERT INTO gridded_observations
        (valid_at, init_time, step_h, lat_idx, lon_idx, lat, lon,
         variable_id, source_id, value, qc_flag)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 0)
    ON CONFLICT (lat_idx, lon_idx, variable_id, valid_at, source_id)
    DO UPDATE SET value = EXCLUDED.value
"""


# ---------------------------------------------------------------------------
# Test 1: obs_hourly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_obs_hourly_aggregates_after_refresh(db_pool, seed_metadata):
    """6 observations in the same hour → obs_hourly shows correct aggregate.

    Values: 280, 281, 282, 283, 284, 285 → avg = 282.5, count = 6.
    """
    sid = seed_metadata["station_id"]
    vid = seed_metadata["variable_id"]
    src = seed_metadata["source_id"]

    values = [280.0, 281.0, 282.0, 283.0, 284.0, 285.0]
    expected_avg = sum(values) / len(values)  # 282.5

    async with db_pool.acquire() as conn:
        # Insert 6 observations 10 minutes apart within the 00:00–01:00 hour
        for i, val in enumerate(values):
            await conn.execute(INSERT_OBS, sid, vid, _obs_at(0, i * 10), src, val)

        # Refresh obs_hourly for the window covering our hour
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'obs_hourly',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-23 02:00+00'::timestamptz"
            ")"
        )

        row = await conn.fetchrow(
            "SELECT avg_value, sample_count FROM obs_hourly"
            " WHERE bucket = '2026-05-23 00:00+00'::timestamptz"
            "   AND station_id = $1 AND variable_id = $2 AND source_id = $3",
            sid, vid, src,
        )

        assert row is not None, "obs_hourly: no row found after refresh"
        assert row["sample_count"] == 6, (
            f"obs_hourly: expected sample_count=6, got {row['sample_count']}"
        )
        assert row["avg_value"] == pytest.approx(expected_avg, rel=1e-9), (
            f"obs_hourly: expected avg={expected_avg}, got {row['avg_value']}"
        )

        # Cleanup
        await conn.execute(
            "DELETE FROM observations WHERE station_id=$1 AND variable_id=$2"
            " AND source_id=$3 AND observed_at >= '2026-05-23 00:00+00'"
            " AND observed_at < '2026-05-23 01:00+00'",
            sid, vid, src,
        )


# ---------------------------------------------------------------------------
# Test 2: obs_daily (hierarchical — from obs_hourly)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_obs_daily_hierarchical_aggregates_from_hourly(db_pool, seed_metadata):
    """24 observations spanning 24 hours → obs_daily shows correct daily aggregate.

    Verifies the hierarchical CAGG pattern: obs_daily is built from obs_hourly
    (not raw observations). Checks timescaledb_information.continuous_aggregates
    to confirm the view_definition references obs_hourly, not observations.
    """
    sid = seed_metadata["station_id"]
    vid = seed_metadata["variable_id"]
    src = seed_metadata["source_id"]

    # One observation per hour, values 280..303 → avg = 291.5, count = 24
    values = [280.0 + float(h) for h in range(24)]
    expected_avg = sum(values) / len(values)  # 291.5

    async with db_pool.acquire() as conn:
        # Insert one observation per hour
        for h, val in enumerate(values):
            await conn.execute(INSERT_OBS, sid, vid, _obs_at(h, 0), src, val)

        # Step 1: refresh obs_hourly for the full day
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'obs_hourly',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-24 01:00+00'::timestamptz"
            ")"
        )

        # Step 2: refresh obs_daily for the same day
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'obs_daily',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-24 00:00+00'::timestamptz"
            ")"
        )

        row = await conn.fetchrow(
            "SELECT avg_value, sample_count FROM obs_daily"
            " WHERE day_bucket = '2026-05-23 00:00+00'::timestamptz"
            "   AND station_id = $1 AND variable_id = $2 AND source_id = $3",
            sid, vid, src,
        )

        assert row is not None, "obs_daily: no row found after refresh"
        assert row["sample_count"] == 24, (
            f"obs_daily: expected sample_count=24, got {row['sample_count']}"
        )
        assert row["avg_value"] == pytest.approx(expected_avg, rel=1e-9), (
            f"obs_daily: expected avg={expected_avg}, got {row['avg_value']}"
        )

        # Verify hierarchical source: view_definition must reference obs_hourly
        cagg_info = await conn.fetchrow(
            "SELECT view_definition FROM timescaledb_information.continuous_aggregates"
            " WHERE view_name = 'obs_daily'"
        )
        assert cagg_info is not None, "obs_daily not found in continuous_aggregates"
        view_def = cagg_info["view_definition"]
        assert "obs_hourly" in view_def, (
            f"obs_daily view_definition does not reference obs_hourly: {view_def}"
        )
        assert "observations" not in view_def.lower().replace("obs_hourly", ""), (
            "obs_daily view_definition should reference obs_hourly, not raw observations"
        )

        # Cleanup
        await conn.execute(
            "DELETE FROM observations WHERE station_id=$1 AND variable_id=$2"
            " AND source_id=$3 AND observed_at >= '2026-05-23 00:00+00'"
            " AND observed_at < '2026-05-24 00:00+00'",
            sid, vid, src,
        )


# ---------------------------------------------------------------------------
# Test 3: gridded_hourly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gridded_hourly_aggregates_after_refresh(db_pool, seed_metadata):
    """3 grid-point observations in one 6h bucket → gridded_hourly shows aggregate.

    Values: 275.0, 276.0, 277.0 → avg = 276.0, count = 3.
    All in the 00:00–06:00 6-hour bucket.
    """
    vid = seed_metadata["variable_id"]
    src = seed_metadata["source_id"]

    # init_time = 00Z on 2026-05-23 (ECMWF 00Z cycle)
    init_time = DAY  # 2026-05-23 00:00 UTC

    # 3 observations at different times in the same 6h bucket (00:00–06:00)
    grid_obs = [
        # (valid_at, step_h, lat_idx, lon_idx, lat, lon, value)
        (DAY + timedelta(hours=0), 0,  10, 20, 44.0, 11.0, 275.0),
        (DAY + timedelta(hours=1), 1,  10, 20, 44.0, 11.0, 276.0),
        (DAY + timedelta(hours=2), 2,  10, 20, 44.0, 11.0, 277.0),
    ]
    expected_avg = (275.0 + 276.0 + 277.0) / 3  # 276.0

    async with db_pool.acquire() as conn:
        for valid_at, step_h, lat_idx, lon_idx, lat, lon, val in grid_obs:
            await conn.execute(
                INSERT_GRIDDED,
                valid_at, init_time, step_h, lat_idx, lon_idx, lat, lon,
                vid, src, val,
            )

        # Refresh gridded_hourly for the 6h window
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'gridded_hourly',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-23 12:00+00'::timestamptz"
            ")"
        )

        row = await conn.fetchrow(
            "SELECT avg_value, sample_count FROM gridded_hourly"
            " WHERE bucket = '2026-05-23 00:00+00'::timestamptz"
            "   AND lat_idx = 10 AND lon_idx = 20"
            "   AND variable_id = $1 AND source_id = $2",
            vid, src,
        )

        assert row is not None, "gridded_hourly: no row found after refresh"
        assert row["sample_count"] == 3, (
            f"gridded_hourly: expected sample_count=3, got {row['sample_count']}"
        )
        assert row["avg_value"] == pytest.approx(expected_avg, rel=1e-9), (
            f"gridded_hourly: expected avg={expected_avg}, got {row['avg_value']}"
        )

        # Cleanup
        await conn.execute(
            "DELETE FROM gridded_observations"
            " WHERE variable_id=$1 AND source_id=$2"
            " AND valid_at >= '2026-05-23 00:00+00'"
            " AND valid_at < '2026-05-23 06:00+00'",
            vid, src,
        )


# ---------------------------------------------------------------------------
# Test 4: gridded_daily (hierarchical — from gridded_hourly)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gridded_daily_hierarchical_aggregates_from_hourly(db_pool, seed_metadata):
    """4 ECMWF cycles × 1 grid point spanning a day → gridded_daily aggregate.

    Verifies the hierarchical CAGG pattern: gridded_daily is built from
    gridded_hourly (not raw gridded_observations). Checks
    timescaledb_information.continuous_aggregates view_definition.

    4 cycles: 00Z, 06Z, 12Z, 18Z → values 273.0, 274.0, 275.0, 276.0
    → avg = 274.5, sample_count = 4 (one per 6h bucket per cycle)
    """
    vid = seed_metadata["variable_id"]
    src = seed_metadata["source_id"]

    # 4 ECMWF forecast cycles at 00Z, 06Z, 12Z, 18Z
    cycles = [
        # (valid_at, init_time, step_h, value)
        (DAY + timedelta(hours=0),  DAY,                          0, 273.0),
        (DAY + timedelta(hours=6),  DAY + timedelta(hours=6),     0, 274.0),
        (DAY + timedelta(hours=12), DAY + timedelta(hours=12),    0, 275.0),
        (DAY + timedelta(hours=18), DAY + timedelta(hours=18),    0, 276.0),
    ]
    expected_avg = (273.0 + 274.0 + 275.0 + 276.0) / 4  # 274.5
    lat_idx, lon_idx, lat, lon = 15, 25, 45.0, 12.0

    async with db_pool.acquire() as conn:
        for valid_at, init_time, step_h, val in cycles:
            await conn.execute(
                INSERT_GRIDDED,
                valid_at, init_time, step_h, lat_idx, lon_idx, lat, lon,
                vid, src, val,
            )

        # Step 1: refresh gridded_hourly for the full day
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'gridded_hourly',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-24 01:00+00'::timestamptz"
            ")"
        )

        # Step 2: refresh gridded_daily for the day
        await conn.execute(
            "CALL refresh_continuous_aggregate("
            "    'gridded_daily',"
            "    '2026-05-23 00:00+00'::timestamptz,"
            "    '2026-05-24 00:00+00'::timestamptz"
            ")"
        )

        row = await conn.fetchrow(
            "SELECT avg_value, sample_count FROM gridded_daily"
            " WHERE day_bucket = '2026-05-23 00:00+00'::timestamptz"
            "   AND lat_idx = $1 AND lon_idx = $2"
            "   AND variable_id = $3 AND source_id = $4",
            lat_idx, lon_idx, vid, src,
        )

        assert row is not None, "gridded_daily: no row found after refresh"
        assert row["sample_count"] == 4, (
            f"gridded_daily: expected sample_count=4, got {row['sample_count']}"
        )
        assert row["avg_value"] == pytest.approx(expected_avg, rel=1e-9), (
            f"gridded_daily: expected avg={expected_avg}, got {row['avg_value']}"
        )

        # Verify hierarchical source: view_definition must reference gridded_hourly
        cagg_info = await conn.fetchrow(
            "SELECT view_definition FROM timescaledb_information.continuous_aggregates"
            " WHERE view_name = 'gridded_daily'"
        )
        assert cagg_info is not None, "gridded_daily not found in continuous_aggregates"
        view_def = cagg_info["view_definition"]
        assert "gridded_hourly" in view_def, (
            f"gridded_daily view_definition does not reference gridded_hourly: {view_def}"
        )

        # Cleanup
        await conn.execute(
            "DELETE FROM gridded_observations"
            " WHERE variable_id=$1 AND source_id=$2"
            " AND valid_at >= '2026-05-23 00:00+00'"
            " AND valid_at < '2026-05-24 00:00+00'",
            vid, src,
        )
