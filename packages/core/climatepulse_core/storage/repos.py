"""Metadata repository for sources, variables, and stations.

MetadataRepo provides upsert operations for the three metadata tables
(sources, variables, stations) and cache-loading helpers for the hot-path
IdempotentWriter.

All operations use ON CONFLICT DO UPDATE for idempotency — safe to call
repeatedly on adapter startup or after cache miss.
"""

import json

import asyncpg

from climatepulse_core.domain.models import Source, Station, Variable


class MetadataRepo:
    """Async metadata repository backed by an asyncpg pool.

    Args:
        db_pool: asyncpg.Pool connected to the TimescaleDB instance
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self._pool = db_pool

    async def upsert_source(self, source: Source) -> int:
        """Upsert a data source and return its surrogate integer id.

        INSERT ... ON CONFLICT (source_id) DO UPDATE SET name=..., ...
        Returns the SMALLSERIAL surrogate id (pk in sources table).
        """
        async with self._pool.acquire() as conn:
            pk = await conn.fetchval(
                """
                INSERT INTO sources (source_id, name, license, attribution, terms_url, enabled)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (source_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        license = EXCLUDED.license,
                        attribution = EXCLUDED.attribution,
                        terms_url = EXCLUDED.terms_url,
                        enabled = EXCLUDED.enabled
                RETURNING id
                """,
                source.source_id,
                source.name,
                source.license,
                source.attribution,
                source.terms_url,
                source.enabled,
            )
        return int(pk)

    async def upsert_variable(self, variable: Variable) -> int:
        """Upsert a WMO variable and return its surrogate integer id.

        INSERT ... ON CONFLICT (wmo_code) DO UPDATE SET ...
        """
        async with self._pool.acquire() as conn:
            pk = await conn.fetchval(
                """
                INSERT INTO variables (wmo_code, bufr_code, unit_si, description)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (wmo_code) DO UPDATE
                    SET bufr_code = EXCLUDED.bufr_code,
                        unit_si = EXCLUDED.unit_si,
                        description = EXCLUDED.description
                RETURNING id
                """,
                variable.wmo_code,
                variable.bufr_code,
                variable.unit_si,
                variable.description,
            )
        return int(pk)

    async def upsert_station(self, station: Station, source_pk: int) -> int:
        """Upsert a station and return its surrogate BIGSERIAL id.

        ON CONFLICT (source_id, external_id) DO UPDATE — allows updating
        station metadata (name, coordinates) without creating duplicates.

        Args:
            station:   Station domain object
            source_pk: surrogate integer id from the sources table
        """
        async with self._pool.acquire() as conn:
            pk = await conn.fetchval(
                """
                INSERT INTO stations (source_id, external_id, name, lat, lon, elevation_m, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (source_id, external_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        lat = EXCLUDED.lat,
                        lon = EXCLUDED.lon,
                        elevation_m = EXCLUDED.elevation_m,
                        metadata = EXCLUDED.metadata
                RETURNING id
                """,
                source_pk,
                station.external_id,
                station.name,
                station.lat,
                station.lon,
                station.elevation_m,
                json.dumps(station.metadata or {}),
            )
        return int(pk)

    async def load_sources_cache(self) -> dict[str, int]:
        """Return {source_id_str: surrogate_pk_int} for all sources."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT source_id, id FROM sources")
        return {row["source_id"]: row["id"] for row in rows}

    async def load_variables_cache(self) -> dict[str, int]:
        """Return {wmo_code: surrogate_pk_int} for all variables."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT wmo_code, id FROM variables")
        return {row["wmo_code"]: row["id"] for row in rows}

    async def load_stations_cache(self, source_pk: int) -> dict[str, int]:
        """Return {external_id: surrogate_pk_int} for all stations of source_pk."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT external_id, id FROM stations WHERE source_id = $1",
                source_pk,
            )
        return {row["external_id"]: row["id"] for row in rows}
