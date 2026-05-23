"""Domain dataclasses and enums for Climate Pulse.

These are the canonical in-memory representations used by adapters, the WMO
normalizer, and the idempotent writer. They are intentionally dependency-light
so this module can be imported by both the worker and api containers.

No Pint imports here — unit conversion lives in normalize/wmo.py (Plan 03).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class QcFlag(IntEnum):
    """Quality control flag values.

    Integer values are stored directly in the `qc_flag` column (SMALLINT).
    D-20 mandates SCHEMA_VIOLATION=3 for schema-drift rows.
    D-15-17 mandates STALE_SNAPSHOT=4 for snapshot-fallback rows.
    """

    GOOD = 0
    MISSING = 1
    OUT_OF_RANGE = 2
    SCHEMA_VIOLATION = 3  # D-20: schema-drift handling
    STALE_SNAPSHOT = 4    # D-15-17: stale snapshot fallback


@dataclass(frozen=True)
class Source:
    """Metadata for a data source (e.g. 'arpa_emilia', 'ecmwf_open').

    `source_id` is the human-readable identifier used as a foreign-key lookup
    key in the `sources` table. The actual surrogate SMALLSERIAL primary key
    is loaded by the Writer via a `sources` cache at startup.
    """

    source_id: str          # 'arpa_emilia', 'ecmwf_open'
    name: str
    license: str
    attribution: str
    terms_url: str | None
    enabled: bool = True


@dataclass(frozen=True)
class Variable:
    """A meteorological variable in the WMO catalog.

    `wmo_code` is the canonical identifier (e.g. 'air_temperature').
    `bufr_code` is the WMO BUFR Table B code (e.g. 'B12101').
    `unit_si` is the SI unit string (e.g. 'K', 'm s-1', 'Pa').
    """

    wmo_code: str           # 'air_temperature', 'wind_speed'
    bufr_code: str | None   # 'B12101' for ARPAE; None for ECMWF
    unit_si: str            # 'K', 'm s-1', 'Pa'
    description: str | None = None


@dataclass(frozen=True)
class Station:
    """A meteorological station.

    `source_id` references the `sources.source_id` text field (not the
    surrogate integer id). `external_id` is the source-assigned station
    identifier (may be a number string, ICAO code, etc.).
    """

    source_id: str
    external_id: str
    name: str
    lat: float
    lon: float
    elevation_m: float | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class RawObservation:
    """Pre-normalization shape produced by adapters.

    Station-based observations: populate `station_external_id`; leave grid
    fields (lat, lon, lat_idx, lon_idx, init_time, step_h) as None.

    Grid-based observations (ECMWF): populate grid fields; leave
    `station_external_id` as None.

    IMPORTANT: `observed_at` MUST be tz-aware UTC. The constructor does not
    enforce this — the adapter is responsible for ensuring timezone awareness.
    """

    source_id: str
    observed_at: datetime       # MUST be tz-aware UTC; adapter is responsible
    station_external_id: str | None  # populated for station-based observations
    wmo_code: str
    value: float
    qc_flag: QcFlag = QcFlag.GOOD
    # Grid-based fields (populated when observation comes from a grid source)
    lat: float | None = None
    lon: float | None = None
    lat_idx: int | None = None
    lon_idx: int | None = None
    init_time: datetime | None = None
    step_h: int | None = None


@dataclass(frozen=True)
class Observation:
    """Normalized observation ready for storage.

    Produced by the WMO normalizer from a RawObservation. All values are in SI
    units. The surrogate foreign-key ids (station_id, variable_id, source_id)
    are resolved by the Writer from its metadata caches.
    """

    source_id: str
    station_external_id: str | None
    wmo_code: str
    observed_at: datetime       # tz-aware UTC
    value: float
    qc_flag: QcFlag = QcFlag.GOOD
    # Grid-based fields
    lat: float | None = None
    lon: float | None = None
    lat_idx: int | None = None
    lon_idx: int | None = None
    init_time: datetime | None = None
    step_h: int | None = None
