"""IdempotentWriter: asyncpg COPY + INSERT...ON CONFLICT for dual-hypertable routing (ING-12, D-23).

Implements the hot-path observation write using asyncpg copy_records_to_table
into a temporary staging table, then INSERT...SELECT...ON CONFLICT DO UPDATE.

Routing by is_grid_based (D-23):
  - adapter.is_grid_based = False -> observations hypertable (station-based, ARPAE)
  - adapter.is_grid_based = True  -> gridded_observations hypertable (grid-based, ECMWF)

Idempotency (ING-12):
  - ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE SET value, qc_flag
  - ON CONFLICT (lat_idx, lon_idx, variable_id, valid_at, source_id) DO UPDATE for grid

Pitfall C (RESEARCH.md 1262-1265):
  - Rows with QcFlag.MISSING and value=0.0 are still inserted (not skipped).

ING-14 health metric:
  - After every successful write_batch, calls observability.health.record_success()

Returns from write_batch:
  - Number of rows INSERTED (xmax = 0); zero on idempotent re-run (all DO UPDATE).
"""

import structlog

import asyncpg

from climatepulse_core.adapters.base import WeatherSourceAdapter
from climatepulse_core.domain.models import RawObservation
from climatepulse_core.observability.health import record_success

logger = structlog.get_logger(__name__)


class IdempotentWriter:
    """Async writer routing observations to the correct TimescaleDB hypertable.

    Uses asyncpg copy_records_to_table into temp staging then INSERT ON CONFLICT.
    All cache lookups use pre-loaded in-memory dicts for hot-path performance.

    Args:
        db_pool:         asyncpg.Pool for the TimescaleDB instance
        redis_client:    async Redis client for ING-14 health metrics
        sources_cache:   {source_id_str: surrogate_pk_int}
        variables_cache: {wmo_code: surrogate_pk_int}
        stations_cache:  {source_id_str: {external_id: station_pk_int}}
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        redis_client,
        sources_cache: dict[str, int],
        variables_cache: dict[str, int],
        stations_cache: dict[str, dict[str, int]],
    ) -> None:
        self._pool = db_pool
        self._redis = redis_client
        self._sources = sources_cache
        self._variables = variables_cache
        self._stations = stations_cache

    async def write_batch(
        self,
        adapter: WeatherSourceAdapter,
        observations: list[RawObservation],
    ) -> int:
        """Write a batch of RawObservation objects to the appropriate hypertable.

        Args:
            adapter:      the WeatherSourceAdapter that produced the observations
            observations: list of RawObservation objects to persist

        Returns:
            Number of rows newly INSERTed (zero means all were DO UPDATE).

        Raises:
            asyncpg.PostgresError: on database errors
        """
        if not observations:
            return 0

        if adapter.is_grid_based:
            count = await self._write_grid_batch(adapter, observations)
        else:
            count = await self._write_station_batch(adapter, observations)

        # ING-14: record successful flush in Redis
        await record_success(self._redis, adapter.source_id)

        return count

    async def _write_station_batch(
        self,
        adapter: WeatherSourceAdapter,
        observations: list[RawObservation],
    ) -> int:
        """Write station-based observations to the observations hypertable."""
        source_pk = self._sources.get(adapter.source_id)
        if source_pk is None:
            logger.warning(
                "source_id not in cache — skipping batch",
                source_id=adapter.source_id,
            )
            return 0

        station_map = self._stations.get(adapter.source_id, {})

        # Build tuples for COPY, deduping by composite PK (station_id, variable_id,
        # observed_at, source_id) — adapters may emit duplicate observations within
        # a single batch (e.g., overlapping snapshot + realtime windows) which would
        # break ON CONFLICT DO UPDATE ("cannot affect row a second time"). Last value wins.
        records_by_pk: dict[tuple, tuple] = {}
        skipped = 0
        for obs in observations:
            variable_pk = self._variables.get(obs.wmo_code)
            if variable_pk is None:
                logger.warning(
                    "wmo_code not in variables cache — skipping row",
                    wmo_code=obs.wmo_code,
                    source_id=obs.source_id,
                )
                skipped += 1
                continue

            station_pk = station_map.get(obs.station_external_id or "")
            if station_pk is None:
                logger.warning(
                    "station not in cache — skipping row",
                    external_id=obs.station_external_id,
                    source_id=obs.source_id,
                )
                skipped += 1
                continue

            pk = (station_pk, variable_pk, obs.observed_at, source_pk)
            records_by_pk[pk] = (
                obs.observed_at,   # TIMESTAMPTZ
                station_pk,        # BIGINT
                variable_pk,       # SMALLINT
                source_pk,         # SMALLINT
                obs.value,         # DOUBLE PRECISION
                int(obs.qc_flag),  # SMALLINT
            )
        records: list[tuple] = list(records_by_pk.values())

        if not records:
            return 0

        if skipped:
            logger.info("skipped rows due to cache miss", count=skipped)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Temp staging table (dropped on COMMIT)
                await conn.execute("""
                    CREATE TEMP TABLE IF NOT EXISTS obs_staging (
                        observed_at  TIMESTAMPTZ NOT NULL,
                        station_id   BIGINT NOT NULL,
                        variable_id  SMALLINT NOT NULL,
                        source_id    SMALLINT NOT NULL,
                        value        DOUBLE PRECISION NOT NULL,
                        qc_flag      SMALLINT NOT NULL
                    ) ON COMMIT DROP
                """)
                await conn.execute("TRUNCATE obs_staging")

                await conn.copy_records_to_table(
                    "obs_staging",
                    records=records,
                    columns=["observed_at", "station_id", "variable_id", "source_id", "value", "qc_flag"],
                )

                # INSERT ... ON CONFLICT; count inserted (xmax = 0) vs updated (xmax != 0)
                row = await conn.fetchrow("""
                    WITH ins AS (
                        INSERT INTO observations
                            (observed_at, station_id, variable_id, source_id, value, qc_flag)
                        SELECT observed_at, station_id, variable_id, source_id, value, qc_flag
                        FROM obs_staging
                        ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE
                            SET value    = EXCLUDED.value,
                                qc_flag  = EXCLUDED.qc_flag
                        RETURNING xmax
                    )
                    SELECT
                        count(*) FILTER (WHERE xmax = 0)   AS inserted,
                        count(*) FILTER (WHERE xmax != 0)  AS updated
                    FROM ins
                """)

        inserted = int(row["inserted"]) if row else 0
        logger.info(
            "station batch written",
            inserted=inserted,
            updated=int(row["updated"]) if row else 0,
            skipped=skipped,
            source_id=adapter.source_id,
        )
        return inserted

    async def _write_grid_batch(
        self,
        adapter: WeatherSourceAdapter,
        observations: list[RawObservation],
    ) -> int:
        """Write grid-based observations to the gridded_observations hypertable."""
        source_pk = self._sources.get(adapter.source_id)
        if source_pk is None:
            logger.warning(
                "source_id not in cache — skipping grid batch",
                source_id=adapter.source_id,
            )
            return 0

        # Dedup by gridded PK (lat_idx, lon_idx, variable_id, valid_at, source_id) — same
        # rationale as station batch (overlapping windows from adapter).
        records_by_pk: dict[tuple, tuple] = {}
        skipped = 0
        for obs in observations:
            variable_pk = self._variables.get(obs.wmo_code)
            if variable_pk is None:
                logger.warning(
                    "wmo_code not in variables cache — skipping grid row",
                    wmo_code=obs.wmo_code,
                )
                skipped += 1
                continue

            if obs.lat_idx is None or obs.lon_idx is None:
                logger.warning(
                    "grid observation missing lat_idx/lon_idx — skipping",
                    wmo_code=obs.wmo_code,
                )
                skipped += 1
                continue

            pk = (obs.lat_idx, obs.lon_idx, variable_pk, obs.observed_at, source_pk)
            records_by_pk[pk] = (
                obs.observed_at,                  # valid_at TIMESTAMPTZ
                obs.init_time or obs.observed_at,  # init_time TIMESTAMPTZ
                obs.step_h or 0,                  # step_h SMALLINT
                obs.lat_idx,                      # lat_idx SMALLINT
                obs.lon_idx,                      # lon_idx SMALLINT
                float(obs.lat or 0.0),            # lat REAL
                float(obs.lon or 0.0),            # lon REAL
                variable_pk,                      # variable_id SMALLINT
                source_pk,                        # source_id SMALLINT
                obs.value,                        # value DOUBLE PRECISION
                int(obs.qc_flag),                 # qc_flag SMALLINT
            )
        records: list[tuple] = list(records_by_pk.values())

        if not records:
            return 0

        if skipped:
            logger.info("skipped grid rows due to cache miss", count=skipped)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    CREATE TEMP TABLE IF NOT EXISTS grid_staging (
                        valid_at    TIMESTAMPTZ NOT NULL,
                        init_time   TIMESTAMPTZ NOT NULL,
                        step_h      SMALLINT NOT NULL,
                        lat_idx     SMALLINT NOT NULL,
                        lon_idx     SMALLINT NOT NULL,
                        lat         REAL NOT NULL,
                        lon         REAL NOT NULL,
                        variable_id SMALLINT NOT NULL,
                        source_id   SMALLINT NOT NULL,
                        value       DOUBLE PRECISION NOT NULL,
                        qc_flag     SMALLINT NOT NULL
                    ) ON COMMIT DROP
                """)
                await conn.execute("TRUNCATE grid_staging")

                await conn.copy_records_to_table(
                    "grid_staging",
                    records=records,
                    columns=["valid_at", "init_time", "step_h", "lat_idx", "lon_idx",
                             "lat", "lon", "variable_id", "source_id", "value", "qc_flag"],
                )

                row = await conn.fetchrow("""
                    WITH ins AS (
                        INSERT INTO gridded_observations
                            (valid_at, init_time, step_h, lat_idx, lon_idx, lat, lon,
                             variable_id, source_id, value, qc_flag)
                        SELECT valid_at, init_time, step_h, lat_idx, lon_idx, lat, lon,
                               variable_id, source_id, value, qc_flag
                        FROM grid_staging
                        ON CONFLICT (lat_idx, lon_idx, variable_id, valid_at, source_id) DO UPDATE
                            SET value     = EXCLUDED.value,
                                qc_flag   = EXCLUDED.qc_flag,
                                init_time = EXCLUDED.init_time,
                                step_h    = EXCLUDED.step_h
                        RETURNING xmax
                    )
                    SELECT
                        count(*) FILTER (WHERE xmax = 0)  AS inserted,
                        count(*) FILTER (WHERE xmax != 0) AS updated
                    FROM ins
                """)

        inserted = int(row["inserted"]) if row else 0
        logger.info(
            "grid batch written",
            inserted=inserted,
            updated=int(row["updated"]) if row else 0,
            skipped=skipped,
            source_id=adapter.source_id,
        )
        return inserted

    async def refresh_caches(self) -> None:
        """Reload all metadata caches from the database.

        Called at worker startup and on cache-miss.
        """
        from climatepulse_core.storage.repos import MetadataRepo

        repo = MetadataRepo(self._pool)
        self._sources = await repo.load_sources_cache()
        self._variables = await repo.load_variables_cache()

        new_stations: dict[str, dict[str, int]] = {}
        for source_id_str, source_pk in self._sources.items():
            new_stations[source_id_str] = await repo.load_stations_cache(source_pk)
        self._stations = new_stations
