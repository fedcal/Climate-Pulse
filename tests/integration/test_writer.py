"""Integration tests for IdempotentWriter and MetadataRepo.

Tests require the testcontainers TimescaleDB fixture from conftest.py.
Run with: uv run pytest tests/integration/test_writer.py -v -x -m integration

Verifies:
  - Station-based write inserts rows into observations hypertable
  - Re-running the same batch is idempotent (0 new rows)
  - ON CONFLICT DO UPDATE overwrites value for the same PK
  - Grid-based write routes to gridded_observations
  - MISSING qc_flag + sentinel value=0.0 persists (Pitfall C)
  - record_success metric written to Redis after successful flush (ING-14)
"""

import asyncio
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest
import pytest_asyncio

from climatepulse_core.adapters.base import FetchWindow, WeatherSourceAdapter
from climatepulse_core.domain.models import QcFlag, RawObservation
from climatepulse_core.storage.writer import IdempotentWriter


# ---------------------------------------------------------------------------
# Stub adapter helpers
# ---------------------------------------------------------------------------


class _StubStationAdapter(WeatherSourceAdapter):
    """Minimal stub for station-based observations."""

    source_id = "test_src"
    cadence_seconds = 900
    is_grid_based = False

    async def discover_stations(self):
        return []

    async def fetch(self, window: FetchWindow):
        return
        yield

    def source_meta(self):
        from climatepulse_core.adapters.base import SourceMeta
        return SourceMeta(
            source_id="test_src",
            name="Test Source",
            license="MIT",
            attribution="Test",
            terms_url=None,
            default_qc_flag=0,
        )


class _StubGridAdapter(WeatherSourceAdapter):
    """Minimal stub for grid-based observations."""

    source_id = "test_src"
    cadence_seconds = 21600
    is_grid_based = True

    async def discover_stations(self):
        return []

    async def fetch(self, window: FetchWindow):
        return
        yield

    def source_meta(self):
        from climatepulse_core.adapters.base import SourceMeta
        return SourceMeta(
            source_id="test_src",
            name="Test Source",
            license="MIT",
            attribution="Test",
            terms_url=None,
            default_qc_flag=0,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis():
    r = await fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def writer(db_pool, seed_metadata, fake_redis):
    """Build an IdempotentWriter with pre-seeded metadata caches."""
    meta = seed_metadata
    sources_cache = {"test_src": meta["source_id"]}
    variables_cache = {"air_temperature": meta["variable_id"]}
    stations_cache = {"test_src": {"stn001": meta["station_id"]}}

    w = IdempotentWriter(
        db_pool=db_pool,
        redis_client=fake_redis,
        sources_cache=sources_cache,
        variables_cache=variables_cache,
        stations_cache=stations_cache,
    )
    return w


def _make_station_obs(
    value: float = 285.0,
    observed_at: datetime | None = None,
    qc_flag: QcFlag = QcFlag.GOOD,
) -> RawObservation:
    if observed_at is None:
        observed_at = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    return RawObservation(
        source_id="test_src",
        observed_at=observed_at,
        station_external_id="stn001",
        wmo_code="air_temperature",
        value=value,
        qc_flag=qc_flag,
    )


def _make_grid_obs(
    lat_idx: int = 10,
    lon_idx: int = 20,
    valid_at: datetime | None = None,
    value: float = 290.0,
) -> RawObservation:
    if valid_at is None:
        valid_at = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    return RawObservation(
        source_id="test_src",
        observed_at=valid_at,
        station_external_id=None,
        wmo_code="air_temperature",
        value=value,
        qc_flag=QcFlag.GOOD,
        lat=44.0 + lat_idx * 0.25,
        lon=11.0 + lon_idx * 0.25,
        lat_idx=lat_idx,
        lon_idx=lon_idx,
        init_time=datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc),
        step_h=12,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_write_station_batch_inserts_rows(writer, db_pool):
    """5 observations for distinct timestamps are inserted into observations."""
    adapter = _StubStationAdapter()
    base_time = datetime(2026, 5, 23, 6, 0, 0, tzinfo=timezone.utc)
    observations = [
        _make_station_obs(value=280.0 + i, observed_at=base_time + timedelta(hours=i))
        for i in range(5)
    ]

    count = await writer.write_batch(adapter, observations)
    assert count == 5

    # Verify in DB
    async with db_pool.acquire() as conn:
        row_count = await conn.fetchval("SELECT count(*) FROM observations WHERE source_id = $1", 1)
    assert row_count >= 5


@pytest.mark.integration
async def test_write_station_batch_idempotent(writer, db_pool):
    """Re-running write_batch with same observations produces zero new rows."""
    adapter = _StubStationAdapter()
    base_time = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    observations = [
        _make_station_obs(value=285.0, observed_at=base_time + timedelta(hours=i))
        for i in range(5)
    ]

    first_count = await writer.write_batch(adapter, observations)
    assert first_count == 5

    second_count = await writer.write_batch(adapter, observations)
    assert second_count == 0  # all updates, no new inserts


@pytest.mark.integration
async def test_write_station_batch_updates_on_conflict(writer, db_pool):
    """Same PK with different value updates the value in place."""
    adapter = _StubStationAdapter()
    observed_at = datetime(2026, 5, 21, 10, 0, 0, tzinfo=timezone.utc)

    # First write
    obs_v1 = [_make_station_obs(value=285.0, observed_at=observed_at)]
    await writer.write_batch(adapter, obs_v1)

    # Second write with updated value
    obs_v2 = [_make_station_obs(value=290.0, observed_at=observed_at)]
    count = await writer.write_batch(adapter, obs_v2)
    assert count == 0  # ON CONFLICT DO UPDATE, not INSERT

    # Verify updated value persisted
    async with db_pool.acquire() as conn:
        value = await conn.fetchval(
            """
            SELECT value FROM observations
            WHERE observed_at = $1
              AND source_id = (SELECT id FROM sources WHERE source_id = 'test_src')
              AND station_id = (SELECT id FROM stations WHERE external_id = 'stn001')
            """,
            observed_at,
        )
    assert value == pytest.approx(290.0)


@pytest.mark.integration
async def test_write_grid_batch_routes_to_gridded(writer, db_pool):
    """Grid-based observations go to gridded_observations, not observations."""
    adapter = _StubGridAdapter()
    valid_at = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    grid_obs = [
        _make_grid_obs(lat_idx=i, lon_idx=i, valid_at=valid_at)
        for i in range(4)
    ]

    count = await writer.write_batch(adapter, grid_obs)
    assert count == 4

    async with db_pool.acquire() as conn:
        grid_count = await conn.fetchval(
            "SELECT count(*) FROM gridded_observations WHERE source_id = $1", 1
        )
        obs_count = await conn.fetchval(
            "SELECT count(*) FROM observations WHERE observed_at = $1", valid_at
        )

    assert grid_count >= 4
    assert obs_count == 0  # Nothing in station table for grid source


@pytest.mark.integration
async def test_write_missing_value_inserts_with_qc_missing(writer, db_pool):
    """QcFlag.MISSING + value=0.0 (Pitfall C sentinel) persists in observations."""
    adapter = _StubStationAdapter()
    observed_at = datetime(2026, 5, 19, 8, 0, 0, tzinfo=timezone.utc)

    missing_obs = [
        _make_station_obs(value=0.0, observed_at=observed_at, qc_flag=QcFlag.MISSING)
    ]
    count = await writer.write_batch(adapter, missing_obs)
    assert count == 1

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT value, qc_flag FROM observations
            WHERE observed_at = $1
              AND source_id = (SELECT id FROM sources WHERE source_id = 'test_src')
              AND station_id = (SELECT id FROM stations WHERE external_id = 'stn001')
            """,
            observed_at,
        )

    assert row is not None
    assert row["value"] == pytest.approx(0.0)
    assert row["qc_flag"] == QcFlag.MISSING.value


@pytest.mark.integration
async def test_write_batch_records_success_metric(writer, db_pool, fake_redis):
    """After successful write_batch, the ING-14 Redis metric is set."""
    adapter = _StubStationAdapter()
    observed_at = datetime(2026, 5, 18, 10, 0, 0, tzinfo=timezone.utc)

    obs = [_make_station_obs(value=288.0, observed_at=observed_at)]
    await writer.write_batch(adapter, obs)

    # Verify Redis key was set
    key = b"metrics:last_success:test_src"
    raw = await fake_redis.get(key)
    assert raw is not None, "Expected ING-14 last_success metric in Redis"

    # Verify it's a valid ISO datetime
    ts_str = raw.decode() if isinstance(raw, bytes) else raw
    dt = datetime.fromisoformat(ts_str)
    assert dt.tzinfo is not None
