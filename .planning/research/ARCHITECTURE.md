# Architecture Research

**Domain:** Multi-source weather / time-series aggregation pipeline (open-data, self-hosted)
**Researched:** 2026-05-23
**Confidence:** HIGH (architectural patterns are well-established; TimescaleDB / Celery / FastAPI specifics verified against official docs and community references)

## Standard Architecture

Weather aggregation pipelines that pull from heterogeneous public sources (national/regional met services, model outputs, METAR feeds, reanalysis) converge on a layered "ETL + serve" topology. The same shape appears in ECMWF's own production stack, Open-Meteo, ARSO, and DWD open-data clients: a thin adapter layer normalizes wildly different upstream formats into a canonical schema, a queue/scheduler shoves work through retry-aware workers, a time-series store persists observations as chunks, and a stateless API + dashboard reads pre-aggregated views.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                                │
│  ┌──────────────────────────┐   ┌────────────────────────────────────┐   │
│  │  Angular 21 SSR (Node)   │   │  MkDocs (static docs / OpenAPI UI) │   │
│  │  Leaflet map + Plotly    │   │                                    │   │
│  └────────────┬─────────────┘   └────────────────────────────────────┘   │
│               │ HTTPS / WSS                                              │
├───────────────┼──────────────────────────────────────────────────────────┤
│               ▼                  API LAYER                               │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  FastAPI 0.115 (uvicorn workers, async)                          │    │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │    │
│  │  │ /v1/obs │ │ /v1/stns │ │ /v1/aggr │ │ /v1/expt │ │ /ws/sub │ │    │
│  │  └─────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │    │
│  │  Middleware: rate-limit (Redis), CORS, request-id, auth(optional)│    │
│  └──────────────┬─────────────────────────┬─────────────────────────┘    │
│                 │ SQL (asyncpg)           │ pub/sub (Redis channels)     │
├─────────────────┼─────────────────────────┼──────────────────────────────┤
│                 ▼                         ▼     INGESTION LAYER          │
│  ┌────────────────────────────────┐  ┌──────────────────────────────┐    │
│  │  Celery Beat (scheduler)       │─▶│  Redis (broker + pub/sub +   │    │
│  │  cron entries per source       │  │   rate-limit store + cache)  │    │
│  └───────────────┬────────────────┘  └──────────────┬───────────────┘    │
│                  │ enqueue                          │                    │
│                  ▼                                  ▼                    │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Celery Workers (queues: ingest, normalize, alerts, dlq)         │    │
│  │  ┌─────────────────────────────────────────────────────────────┐ │    │
│  │  │  Source Adapters (WeatherSourceAdapter ABC)                 │ │    │
│  │  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐ │ │    │
│  │  │  │ARPA  │ │ARPA  │ │ARPA  │ │ECMWF │ │NOAA  │ │Copernicus│ │ │    │
│  │  │  │Puglia│ │Lomb. │ │Veneto│ │ Open │ │METAR │ │   C3S    │ │ │    │
│  │  │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────────┘ │ │    │
│  │  └──────────────────────────┬──────────────────────────────────┘ │    │
│  │                              ▼                                    │    │
│  │  Normalizer (WMO variables, SI units, QC flags)                  │    │
│  │                              ▼                                    │    │
│  │  Writer (batched COPY → observations hypertable)                 │    │
│  └──────────────────────────────┬───────────────────────────────────┘    │
├─────────────────────────────────┼────────────────────────────────────────┤
│                                 ▼            STORAGE LAYER               │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  TimescaleDB 2.x (PostgreSQL 16)                                 │    │
│  │  • stations (regular)      • variables (regular, WMO dictionary) │    │
│  │  • sources  (regular)      • observations (HYPERTABLE, 1d chunks)│    │
│  │  • obs_hourly (continuous aggregate)                             │    │
│  │  • obs_daily  (continuous aggregate, hierarchical on obs_hourly) │    │
│  │  Policies: compress >7d, retain 5y raw / 20y aggregates          │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Source Adapter | Fetch raw data from one upstream (HTTP/SOAP/FTP/S3), respect rate limits, return raw payload + metadata | Python class subclassing `WeatherSourceAdapter` ABC, one module per source |
| Normalizer | Translate adapter output to canonical `Observation` records (WMO variable codes, SI units, quality flags, station_id resolution) | Pure functions per source, shared mapping tables, Pydantic models |
| Ingestion Scheduler | Trigger adapters on cron-style cadence (ARPA 15m, ECMWF 6h, METAR 1h, C3S daily) | Celery Beat with `CELERY_BEAT_SCHEDULE` declarative dict |
| Ingestion Worker | Execute adapter→normalize→write task chain, retry with backoff, route exhausted tasks to DLQ | Celery worker, multiple queues, `autoretry_for` + exponential backoff |
| Deduplicator | Prevent double-insert when adapter overlaps (e.g. ECMWF re-publish) | Postgres `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE` |
| Writer | Bulk insert normalized rows into hypertable | psycopg `COPY` or `executemany` batched per chunk |
| Storage | Persist time-series + metadata, materialize hourly/daily aggregates, compress old chunks | TimescaleDB hypertable + continuous aggregates + native compression |
| API | Serve REST + WebSocket reads of observations, stations, aggregates, exports | FastAPI routers, asyncpg pool, Pydantic v2 response models |
| Rate Limiter | Per-IP / per-API-key throttling | `slowapi` or `fastapi-limiter` with Redis backend |
| Pub/Sub Hub | Push new-observation events to WebSocket subscribers | Redis pub/sub channels per region/station |
| Dashboard | Render map of stations, time-series charts, comparison views | Angular 21 SSR + Leaflet (browser-only) + Plotly |
| Docs | Operator and consumer documentation, OpenAPI viewer | MkDocs Material + `redoc` served from FastAPI |

## Recommended Project Structure

```
climate-pulse/
├── apps/
│   ├── api/                          # FastAPI service
│   │   ├── climatepulse_api/
│   │   │   ├── main.py               # app factory, middleware stack
│   │   │   ├── routers/
│   │   │   │   ├── observations.py
│   │   │   │   ├── stations.py
│   │   │   │   ├── aggregates.py
│   │   │   │   ├── exports.py        # CSV/JSON/Parquet streaming
│   │   │   │   └── ws.py             # WebSocket subscribe
│   │   │   ├── deps/                 # DI: db pool, redis, settings
│   │   │   ├── schemas/              # Pydantic v2 response models
│   │   │   ├── queries/              # SQL read models (no ORM hot path)
│   │   │   └── middleware/           # rate limit, request-id, gzip
│   │   └── pyproject.toml
│   ├── worker/                       # Celery worker + beat
│   │   ├── climatepulse_worker/
│   │   │   ├── celery_app.py         # broker, queues, beat schedule
│   │   │   ├── tasks/
│   │   │   │   ├── ingest.py         # fan-out per source
│   │   │   │   ├── normalize.py
│   │   │   │   ├── write.py
│   │   │   │   └── alerts.py
│   │   │   └── dlq.py                # dead letter inspector
│   │   └── pyproject.toml
│   └── dashboard/                    # Angular 21 SSR app
│       ├── src/app/
│       │   ├── features/
│       │   │   ├── map/              # Leaflet (browser-only, lazy)
│       │   │   ├── station/          # station detail + chart
│       │   │   └── compare/          # multi-station comparison
│       │   ├── core/                 # ApiClient, WsClient, models
│       │   └── shared/
│       └── angular.json
├── packages/
│   ├── core/                         # shared Python lib (installed by api + worker)
│   │   ├── climatepulse_core/
│   │   │   ├── domain/               # Observation, Station, Variable, QcFlag
│   │   │   ├── adapters/             # source plug-ins (one module each)
│   │   │   │   ├── base.py           # WeatherSourceAdapter ABC + registry
│   │   │   │   ├── arpa_puglia.py
│   │   │   │   ├── arpa_lombardia.py
│   │   │   │   ├── ecmwf_open.py
│   │   │   │   ├── noaa_metar.py
│   │   │   │   └── copernicus_c3s.py
│   │   │   ├── normalize/            # WMO mapping, unit conversion, QC
│   │   │   ├── storage/              # repo: stations, observations, sources
│   │   │   ├── http/                 # polite client (UA, retry, cache)
│   │   │   └── settings.py
│   │   └── pyproject.toml
│   └── migrations/                   # Alembic + raw SQL for hypertables
│       └── versions/
├── infra/
│   ├── docker-compose.yml            # timescale, redis, api, worker, beat, dashboard
│   ├── docker-compose.dev.yml
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   ├── Dockerfile.dashboard
│   └── timescale/init.sql            # extension + hypertable bootstrap
├── docs/                             # MkDocs Material
├── tests/
│   ├── unit/
│   ├── integration/                  # uses testcontainers (timescale + redis)
│   └── e2e/
└── pyproject.toml                    # workspace root (uv / hatch)
```

### Structure Rationale

- **`packages/core/` separate from `apps/`:** the adapter ABC, domain models, normalizer, and storage layer must be importable by *both* the API (read path) and the worker (write path). Putting them in a shared installable package is the only sane way to avoid copy-paste drift and lets contributors add a new adapter without touching API code.
- **`adapters/` as a flat directory of modules:** one source = one file. New ARPA region = copy `arpa_puglia.py` to `arpa_emiliaromagna.py`, register in `__init__.py` (or via entry-points). This is the literal payoff of the plug-in pattern.
- **`apps/api/queries/` instead of an ORM hot path:** time-series reads benefit from hand-written SQL hitting continuous aggregates with explicit `time_bucket` predicates. SQLAlchemy ORM is fine for the metadata tables (stations, variables, sources) but a tax on observation queries.
- **`apps/worker/` and `apps/api/` as separate Docker images:** the worker needs heavy deps (xarray, eccodes, requests-cache, BeautifulSoup), the API does not. Separate images keep the API container small and restart-fast.
- **`packages/migrations/` separate from `core`:** raw SQL for `create_hypertable`, continuous aggregates, and policies must run after Alembic creates the base table. Keeping migrations as their own package lets both apps share the schema version without circular deps.
- **Single repo (monorepo):** with one developer and tightly coupled artifacts (shared schema, shared models), a monorepo with `uv` workspace beats N repos. Splitting only makes sense when the dashboard team is different from the API team.

## Architectural Patterns

### Pattern 1: Plug-in Source Adapters via Abstract Base Class + Registry

**What:** Every weather source implements a single ABC with a narrow contract. A registry (decorator or entry-points) makes them discoverable by name so Celery Beat can fan out by string id without importing each adapter.

**When to use:** Any time the set of sources grows on a contributor schedule rather than a release schedule. Adding a new ARPA region must be a one-file PR.

**Trade-offs:**
- (+) New source = new file + registration; no core changes
- (+) Each adapter is independently testable with recorded HTTP fixtures (vcrpy)
- (+) Failure of one adapter cannot break others (isolated tasks, isolated retries)
- (−) Forces all sources into one shape — some (e.g. ECMWF gridded GRIB) need a "fetch + slice to virtual stations" two-step. Solve by allowing the adapter to yield *batches* of normalized records.

**Example:**

```python
# packages/core/climatepulse_core/adapters/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

from climatepulse_core.domain import RawObservation, SourceMeta

_REGISTRY: dict[str, type["WeatherSourceAdapter"]] = {}

def register(source_id: str):
    def deco(cls: type["WeatherSourceAdapter"]) -> type["WeatherSourceAdapter"]:
        if source_id in _REGISTRY:
            raise ValueError(f"duplicate source id {source_id}")
        _REGISTRY[source_id] = cls
        cls.source_id = source_id
        return cls
    return deco

def get_adapter(source_id: str) -> "WeatherSourceAdapter":
    return _REGISTRY[source_id]()

def all_source_ids() -> list[str]:
    return sorted(_REGISTRY)

@dataclass(frozen=True)
class FetchWindow:
    since: datetime
    until: datetime

class WeatherSourceAdapter(ABC):
    """Contract every weather source must satisfy."""

    source_id: str           # set by @register
    cadence_seconds: int     # informational, used by beat schedule builder
    polite_delay_ms: int = 1000

    @abstractmethod
    async def discover_stations(self) -> list["StationRecord"]:
        """Return current station catalog (called daily, cheap upsert)."""

    @abstractmethod
    async def fetch(self, window: FetchWindow) -> AsyncIterator[RawObservation]:
        """Yield raw observations for the time window. Must be idempotent."""

    @abstractmethod
    def source_meta(self) -> SourceMeta:
        """License, terms-of-use URL, attribution string, default QC flag."""
```

```python
# packages/core/climatepulse_core/adapters/arpa_puglia.py
from .base import WeatherSourceAdapter, register, FetchWindow
from climatepulse_core.http import polite_client

@register("arpa_puglia")
class ArpaPugliaAdapter(WeatherSourceAdapter):
    cadence_seconds = 900  # 15 min
    polite_delay_ms = 2000

    async def discover_stations(self):
        async with polite_client(self) as http:
            payload = await http.get_json("https://www.arpa.puglia.it/stations.json")
            return [parse_station(s) for s in payload["stations"]]

    async def fetch(self, window: FetchWindow):
        async with polite_client(self) as http:
            for st in await self._station_ids():
                rows = await http.get_csv(f".../obs?station={st}&from={window.since}")
                for r in rows:
                    yield parse_observation(st, r)

    def source_meta(self):
        return SourceMeta(
            name="ARPA Puglia",
            license="CC BY 4.0",
            attribution="© ARPA Puglia",
            terms_url="https://www.arpa.puglia.it/terms",
        )
```

### Pattern 2: Cron-style Ingestion with Celery Beat + Per-Source Retry/DLQ

**What:** A single Celery Beat process schedules `ingest.run_source(source_id, window)` tasks per cadence. Workers consume from named queues, retry transient failures with exponential backoff, and route permanently failed tasks to a `dlq` queue for human inspection.

**When to use:** Multi-source pollers with mixed cadences and varying reliability. Beat solves "fire every N minutes." Per-queue workers solve "ECMWF downloads are slow and must not block ARPA polls."

**Trade-offs:**
- (+) Battle-tested, single binary for scheduler and workers, no external orchestrator (Airflow/Prefect overkill at this scope)
- (+) Native retry, rate-limit, time-limit, and result-backend support
- (−) Beat is single-instance; if Beat dies, scheduling stops. Mitigated by Docker `restart: unless-stopped` and a "Beat heartbeat" healthcheck task.
- (−) Redis as broker is fine to ~100 tasks/sec; well above this project's needs (sum of all sources << 1 task/sec)

**Example:**

```python
# apps/worker/climatepulse_worker/celery_app.py
from celery import Celery
from celery.schedules import crontab
from climatepulse_core.adapters import all_source_ids, get_adapter

app = Celery("climatepulse", broker="redis://redis:6379/0", backend="redis://redis:6379/1")

app.conf.task_queues = {
    "ingest":    {"exchange": "ingest"},
    "normalize": {"exchange": "normalize"},
    "alerts":    {"exchange": "alerts"},
    "dlq":       {"exchange": "dlq"},
}
app.conf.task_default_queue = "ingest"
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1   # fair scheduling for slow ECMWF
app.conf.task_reject_on_worker_lost = True

# Build beat schedule from adapter cadences
def _build_schedule():
    out = {}
    for sid in all_source_ids():
        cad = get_adapter(sid).cadence_seconds
        out[f"ingest:{sid}"] = {
            "task": "tasks.ingest.run_source",
            "schedule": cad,
            "args": (sid,),
            "options": {"queue": "ingest", "expires": cad * 2},
        }
    out["discover:stations:daily"] = {
        "task": "tasks.ingest.discover_all_stations",
        "schedule": crontab(hour=2, minute=15),
    }
    return out

app.conf.beat_schedule = _build_schedule()
```

```python
# apps/worker/climatepulse_worker/tasks/ingest.py
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

@shared_task(
    bind=True,
    name="tasks.ingest.run_source",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,            # exponential
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    time_limit=600,
    soft_time_limit=540,
)
def run_source(self, source_id: str):
    try:
        window = compute_window(source_id)
        adapter = get_adapter(source_id)
        raw_batch = run_async(collect(adapter.fetch(window)))
        normalize_and_write.delay(source_id, raw_batch)
    except MaxRetriesExceededError as exc:
        send_to_dlq.apply_async(args=(source_id, str(exc)), queue="dlq")
        raise
```

### Pattern 3: TimescaleDB Hypertable + Hierarchical Continuous Aggregates

**What:** One narrow `observations` hypertable partitioned on `observed_at`, with native compression after 7 days and retention measured in years. Hourly and daily aggregates are continuous (materialized + auto-refreshed) so the API never scans raw chunks for dashboard reads.

**When to use:** Any sensor/observation workload with mixed real-time and historical queries. The continuous aggregate pattern is the single biggest dashboard performance win.

**Trade-offs:**
- (+) 10–20x compression on weather data (verified in TimescaleDB official docs)
- (+) Sub-100ms responses for "last 30 days at this station" queries
- (+) Aggregates auto-refresh in the background; no cron job to maintain
- (−) Schema changes on the hypertable require care (continuous aggregates depend on column shape)
- (−) Compression makes individual-row UPDATE/DELETE on old chunks expensive — fine here because observations are append-only

**Schema sketch:**

```sql
-- packages/migrations/versions/0001_init.sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE sources (
    id          SMALLSERIAL PRIMARY KEY,
    source_id   TEXT UNIQUE NOT NULL,        -- 'arpa_puglia', 'ecmwf_open', ...
    name        TEXT NOT NULL,
    license     TEXT NOT NULL,
    attribution TEXT NOT NULL,
    terms_url   TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE variables (
    id        SMALLSERIAL PRIMARY KEY,
    wmo_code  TEXT UNIQUE NOT NULL,          -- 'air_temperature', 'wind_speed', ...
    unit_si   TEXT NOT NULL,                 -- 'K', 'm s-1', 'Pa', ...
    description TEXT
);

CREATE TABLE stations (
    id          BIGSERIAL PRIMARY KEY,
    source_id   SMALLINT NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,               -- ARPA/WMO/ICAO id at the source
    name        TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    elevation_m REAL,
    geom        GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS
                (ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED,
    metadata    JSONB NOT NULL DEFAULT '{}',
    UNIQUE (source_id, external_id)
);
CREATE INDEX stations_geom_gix ON stations USING GIST (geom);

CREATE TABLE observations (
    observed_at  TIMESTAMPTZ NOT NULL,
    station_id   BIGINT NOT NULL REFERENCES stations(id),
    variable_id  SMALLINT NOT NULL REFERENCES variables(id),
    source_id    SMALLINT NOT NULL REFERENCES sources(id),
    value        DOUBLE PRECISION NOT NULL,
    qc_flag      SMALLINT NOT NULL DEFAULT 0,  -- 0=raw, 1=ok, 2=suspect, 3=bad
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (station_id, variable_id, observed_at, source_id)
);

SELECT create_hypertable(
    'observations', 'observed_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => true
);

-- Read indexes (in addition to PK)
CREATE INDEX obs_var_time   ON observations (variable_id, observed_at DESC);
CREATE INDEX obs_station_time ON observations (station_id, observed_at DESC);

-- Compression
ALTER TABLE observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'station_id, variable_id',
    timescaledb.compress_orderby   = 'observed_at DESC, source_id'
);
SELECT add_compression_policy('observations', INTERVAL '7 days');

-- Retention (raw): 5 years
SELECT add_retention_policy('observations', INTERVAL '5 years');

-- Hourly continuous aggregate
CREATE MATERIALIZED VIEW obs_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', observed_at) AS bucket,
    station_id, variable_id, source_id,
    avg(value)  AS avg_value,
    min(value)  AS min_value,
    max(value)  AS max_value,
    count(*)    AS sample_count
FROM observations
GROUP BY 1, 2, 3, 4
WITH NO DATA;

SELECT add_continuous_aggregate_policy('obs_hourly',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes');

-- Daily hierarchical aggregate (built on top of hourly)
CREATE MATERIALIZED VIEW obs_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', bucket) AS bucket,
    station_id, variable_id, source_id,
    avg(avg_value) AS avg_value,
    min(min_value) AS min_value,
    max(max_value) AS max_value,
    sum(sample_count) AS sample_count
FROM obs_hourly
GROUP BY 1, 2, 3, 4
WITH NO DATA;

SELECT add_continuous_aggregate_policy('obs_daily',
    start_offset => INTERVAL '30 days',
    end_offset   => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour');
```

### Pattern 4: API Read-Through Continuous Aggregates with Versioned Routes

**What:** FastAPI routers grouped under `/v1/...` always route bucket queries to the *coarsest sufficient* aggregate. A small resolver picks `observations` for ranges <24h, `obs_hourly` for <30d, `obs_daily` otherwise. OpenAPI is generated automatically; the `/v1` prefix protects future breaking changes.

**Why this layering:** Mixing raw and aggregate reads behind one endpoint keeps the dashboard simple ("give me the series, you figure out resolution") while keeping p99 latency flat regardless of zoom level.

**Key endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/stations` | List stations, filter by bbox / source / variable availability |
| GET | `/v1/stations/{id}` | Station detail + currently available variables |
| GET | `/v1/observations` | Time-series for `station_id` + `variable` + range; resolver picks table |
| GET | `/v1/aggregates/daily` | Force daily aggregate (e.g. climatology export) |
| GET | `/v1/exports/observations.csv` | Streaming CSV/JSON/Parquet export with `Content-Disposition` |
| GET | `/v1/sources` | Registered sources + license + attribution (open-data compliance) |
| WS  | `/v1/ws/stream` | Subscribe to `{station_id, variable}` channels, receive new-obs events |
| GET | `/v1/meta/variables` | WMO variable dictionary |
| GET | `/v1/healthz`, `/v1/readyz` | Liveness + readiness |

### Pattern 5: WebSocket Fan-out via Redis Pub/Sub

**What:** When the writer commits a batch, it `PUBLISH`es a compact event to `obs:{source_id}:{station_id}`. The API holds in-memory subscription maps and forwards matching events to client WebSockets.

**Why:** Postgres `LISTEN/NOTIFY` would also work but ties WebSocket fan-out to a long-held DB connection. Redis is already on the wire for the broker and rate limiter, so it costs zero new infra. Verified pattern in FastAPI + WebSocket community references.

**Trade-off:** Pub/sub is at-most-once. Acceptable because the canonical source is Postgres — a missed event just means the client reloads on reconnect.

## Data Flow

### Ingestion Flow (write path)

```
Celery Beat (every N seconds per source)
    ↓ enqueue tasks.ingest.run_source(source_id)
Celery Worker (queue=ingest)
    ↓ get_adapter(source_id).fetch(window)
Source Adapter (polite HTTP client: UA, rate-limit, cache, robots.txt)
    ↓ async generator of RawObservation
Normalizer (WMO mapping, unit → SI, station resolution, QC flag)
    ↓ List[Observation]
Writer (asyncpg COPY, ON CONFLICT DO UPDATE for dedup)
    ↓ INSERT … RETURNING
TimescaleDB (observations hypertable, chunked daily)
    ↓ trigger-free: writer also PUBLISHes
Redis pub/sub channel obs:{source}:{station}
    ↓
WebSocket subscribers (API → browsers)

(Async, decoupled): TimescaleDB background workers refresh
obs_hourly every 15min, obs_daily every 1h, compress chunks >7d, retain 5y.
```

### Query Flow (read path)

```
Browser (Angular dashboard)
    ↓ HTTPS GET /v1/observations?station=42&variable=air_temperature&from=…&to=…
FastAPI router
    ↓ resolve_resolution(range) → "raw" | "hourly" | "daily"
Read query (asyncpg, hand-written SQL against chosen table/CAGG)
    ↓
TimescaleDB
    ↑
Pydantic response model (gzip if >1KB)
    ↑
Browser (Plotly chart) — or WebSocket /v1/ws/stream for live append
```

### Key Data Flows

1. **Cold backfill** (one-off): operator triggers `worker.tasks.ingest.backfill(source_id, since, until)` from a CLI; the same adapter is reused, just with a larger window split into 1-day batches to avoid blowing memory.
2. **Live ingestion**: Beat ticks → worker fetches → writer inserts → pub/sub event → dashboard chart appends.
3. **Dashboard cold load**: SSR renders the page server-side (HTTP only, no WebSocket on the server) → hydrates on the client → opens WebSocket for live updates.
4. **Export**: streaming response with `StreamingResponse` reads from the appropriate aggregate in chunks (no full materialization in memory).
5. **DLQ inspection**: failed task lands in `dlq` queue; a CLI command (`climatepulse dlq list/replay/drop`) operates on it. No automatic replay — failures must be diagnosed.

## Suggested Build Order (Solo Dev, 3-5 Coarse Phases)

This ordering deliberately ships the **end-to-end thinnest slice first**, because the Core Value in PROJECT.md states "se l'intera catena ingestion → storage → query → visualizzazione non funziona, il progetto non ha valore." Every phase ends with something demonstrably useful.

| Phase | Name | Goal | What's in | What's deferred |
|-------|------|------|-----------|------------------|
| **1** | **Foundation slice** | End-to-end pipeline with one ARPA region + one model source proving the architecture | TimescaleDB hypertable + 1 continuous aggregate, `WeatherSourceAdapter` ABC + registry, ARPA Puglia adapter, ECMWF Open Data adapter, Celery worker + Beat, normalizer (5 core variables: T, RH, P, wind, precip), polite HTTP client, Docker Compose (timescale + redis + worker + beat), Alembic migrations, dev CLI for backfill, unit + integration tests with testcontainers | API, dashboard, alerts, exports, NOAA, Copernicus, more ARPA regions |
| **2** | **Public API** | Read path goes live; data becomes consumable | FastAPI app, `/v1/stations`, `/v1/observations` with resolution resolver, `/v1/sources`, `/v1/meta/variables`, OpenAPI 3.1 docs, rate limiting (slowapi + Redis), CORS, request-id middleware, gzip, healthz/readyz, integration tests, MkDocs site bootstrap | WebSocket, exports, alerts, dashboard |
| **3** | **Dashboard MVP** | Visual product: map + chart + station detail | Angular 21 SSR app, ApiClient (typed via OpenAPI generator), Leaflet map (lazy-loaded browser-only to avoid SSR issues), station detail page with Plotly time-series, source attribution UI, basic theming, Dockerfile, compose integration | Multi-station compare, live WebSocket updates, alerts UI |
| **4** | **Live + Exports + Source breadth** | Production-grade features that round out v1.0 | WebSocket `/v1/ws/stream` + Redis pub/sub from writer, dashboard live-chart hydration, CSV/JSON/Parquet streaming exports, NOAA METAR adapter, Copernicus C3S adapter, 2-3 more ARPA regions (Lombardia, Veneto, Emilia-Romagna), backfill CLI polish, compression policy + retention policy in production | Alerts |
| **5** | **Alerts + Ops + 1.0 polish** | Alerting, observability, hardening for release | Alert rules table, evaluator task (`tasks.alerts.evaluate`), webhook + email delivery, alerts UI in dashboard, Prometheus `/metrics` (prometheus-fastapi-instrumentator), Flower for Celery, DLQ CLI, GDPR-aware logging review, contributor docs ("how to add a new ARPA region"), release checklist | Anything in Out of Scope |

**Why this order:**
- Phase 1 alone proves every architectural risk (adapter ABC, hypertable, Celery + Beat, normalization). If something is wrong with the foundations, you discover it now, not in Phase 4.
- Postponing the API and dashboard until data exists prevents the classic "demo UI on top of mocks that never matches real data shape."
- Adding extra adapters in Phase 4 (not Phase 1) keeps Phase 1 small; ARPA Puglia + ECMWF Open Data is enough to validate that the ABC handles both station-based and grid-based sources, which is the load-bearing variety.
- Alerts last because they require a stable ingestion stream to test against and cannot ship before users can see data in the dashboard.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0–10 stations, 1 source, dev | Single Docker Compose, default chunk_time_interval=1d, no compression |
| 50 stations × 5 sources × 5 variables × 15-min cadence (~144k rows/day, ~50M/year) | Compression after 7d (≈10–20x reduction), hourly + daily continuous aggregates, single API container behind a reverse proxy, single worker container with concurrency=4 |
| 1k+ stations or full Copernicus reanalysis ingest | Split Celery worker by queue type (ingest / normalize / alerts), bump `chunk_time_interval` to 6h if write rate >10k/s (rare), add read replica for API (Timescale supports streaming replication), front the API with a CDN for `/v1/sources` and `/v1/meta/variables` |
| Beyond Docker Compose / multi-region | Out of scope per PROJECT.md (v1.0 = self-hosted Docker Compose only). If ever needed: K8s with separate StatefulSet for Timescale, HPA on stateless API/workers. |

### Scaling Priorities

1. **First bottleneck (likely):** dashboard chart queries scanning raw observations. **Fix:** ensure resolution resolver routes to continuous aggregates by default; add a "raw" opt-in flag for power users.
2. **Second bottleneck:** writer throughput during large backfills. **Fix:** batch with `COPY` (not `executemany`); split backfill task by day to control transaction size.
3. **Third bottleneck:** Celery Beat being a single point of failure. **Fix:** `restart: unless-stopped` + heartbeat task that fails healthcheck if not seen in 2× max cadence.
4. **Fourth (only if real users come):** Redis as broker + rate-limit + pub/sub on a single instance. **Fix:** split rate-limit Redis from broker Redis (still one container, two databases, then later two containers).

## Anti-Patterns

### Anti-Pattern 1: One "fat" table per source

**What people do:** `arpa_puglia_observations`, `ecmwf_observations`, etc., each with source-specific columns.
**Why it's wrong:** Cross-source queries (the entire point of an aggregator) become UNION nightmares; continuous aggregates must be defined per table; new source = new schema migration.
**Do this instead:** One narrow `observations` hypertable keyed on `(station_id, variable_id, observed_at, source_id)`. Normalize at write time. Source-specific extras live in `stations.metadata` JSONB or a sibling `observation_provenance` table if truly needed.

### Anti-Pattern 2: Storing values in source-native units

**What people do:** Persist Celsius for ARPA, Kelvin for ECMWF, knots for METAR wind.
**Why it's wrong:** Every consumer must replicate unit logic; comparisons silently break; aggregates become meaningless.
**Do this instead:** Always store in SI (Kelvin, m/s, Pa). Convert at normalize time. Expose unit in the `/v1/meta/variables` endpoint; let the dashboard convert for display.

### Anti-Pattern 3: Adapter does the database write

**What people do:** Adapter fetches and inserts in one method.
**Why it's wrong:** Couples ingestion to storage; impossible to dry-run / replay / test an adapter in isolation; retries re-fetch upstream unnecessarily.
**Do this instead:** Adapter yields `RawObservation`. Normalizer transforms. Writer commits. Three separate Celery tasks chained with `chain()` or a single task that just orchestrates them — but the adapter never touches the DB.

### Anti-Pattern 4: Using SQLAlchemy ORM for hot-path time-series reads

**What people do:** Load 100k `Observation` ORM rows for a chart.
**Why it's wrong:** Object overhead + identity map = 10–100x slower than raw asyncpg; defeats the entire point of TimescaleDB.
**Do this instead:** ORM for metadata (stations, variables, sources, alerts). Hand-written SQL through asyncpg for observations, returning tuples or Pydantic models directly.

### Anti-Pattern 5: `time.sleep` / synchronous HTTP inside Celery tasks

**What people do:** `requests.get` + manual sleep for polite rate limiting.
**Why it's wrong:** Blocks the worker process; throughput collapses.
**Do this instead:** Either run the task with `asyncio.run(adapter.fetch(...))` (Celery 5.3+ supports async tasks via wrapper) and use `httpx.AsyncClient`, OR use Celery's `rate_limit` task option for source-level throttling.

### Anti-Pattern 6: Forgetting `ON CONFLICT` for deduplication

**What people do:** Plain INSERT and rely on schedules not overlapping.
**Why it's wrong:** ECMWF re-publishes, ARPA backfills late, retries re-ingest a window → primary key violations crash the writer.
**Do this instead:** `INSERT … ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE SET value=EXCLUDED.value, qc_flag=EXCLUDED.qc_flag, ingested_at=now()`. Idempotency is non-negotiable.

### Anti-Pattern 7: Leaflet imported at SSR time

**What people do:** Top-level `import * as L from 'leaflet'` in an Angular SSR app.
**Why it's wrong:** Leaflet references `window`/`document` at import; SSR crashes. Documented friction in Angular + Leaflet community discussions.
**Do this instead:** Dynamic `import('leaflet')` inside `ngAfterViewInit` guarded by `isPlatformBrowser(this.platformId)`. Render a placeholder during SSR.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| ARPA regional portals | Polite HTTPS scraping (User-Agent identifying project + contact, conservative rate, robots.txt check, optional disk cache via `hishel`/`requests-cache`) | Endpoints change without notice; record fixtures in tests; ship snapshot fallback file in repo |
| ECMWF Open Data | HTTPS download of GRIB2 files from `data.ecmwf.int`; parse with `eccodes` or `cfgrib`+`xarray`; slice to virtual station points by nearest-neighbor lookup | Files are large (~100MB+); store on local volume, parse, discard. Cache by cycle datetime to allow re-runs. |
| NOAA METAR / TAF | HTTPS to aviationweather.gov; flat text parse (use `python-metar`) | Hourly cadence; station list well-known (ICAO codes) |
| Copernicus C3S | CDS API via `cdsapi` Python client (needs API key in env) | Async-ish (queued on Copernicus side); use a "submit + poll" two-stage task |
| SMTP (alerts) | aiosmtplib via worker; SMTP creds in env | Optional; webhook alternative for users without SMTP |
| Webhook (alerts) | httpx POST with HMAC signature | Retries handled by Celery |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| API ↔ TimescaleDB | asyncpg pool, hand-written SQL for observations, SQLAlchemy 2.x for metadata | Pool size tuned per Uvicorn worker |
| Worker ↔ TimescaleDB | asyncpg for bulk COPY; SQLAlchemy for metadata upserts | Separate pool from API |
| API ↔ Worker | No direct call. API may enqueue (e.g. `/v1/admin/backfill`) via Celery client; Worker never calls API. | One-way to prevent cycles |
| Writer ↔ API (live events) | Redis pub/sub (`obs:{source}:{station}` channels) | Decoupled, at-most-once |
| Dashboard ↔ API | HTTPS REST + WSS; generated client from OpenAPI 3.1 schema | Single source of truth = OpenAPI |
| Adapter ↔ HTTP layer | Adapter receives a `PoliteHttpClient` via `polite_client(self)` context manager | UA, rate-limit, cache, retry centralized |
| Alembic ↔ Hypertable SQL | Alembic creates base table; raw SQL migration step calls `create_hypertable` and CAGG DDL | Don't try to ORM-ify TimescaleDB DDL |

## Deployment Topology (Docker Compose)

```
services:
  timescale:     # timescale/timescaledb:latest-pg16, volume for /var/lib/postgresql/data
  redis:         # redis:7-alpine, append-only persistence
  api:           # build apps/api, uvicorn --workers 2, depends_on: timescale, redis
  worker:        # build apps/worker, celery worker -Q ingest,normalize,alerts -c 4
  beat:          # build apps/worker, celery beat (single instance, restart: unless-stopped)
  dashboard:     # build apps/dashboard, node SSR server, depends_on: api
  docs:          # nginx serving MkDocs build (optional in prod)
  caddy/nginx:   # reverse proxy, TLS via Let's Encrypt, single entry point
```

Single host, single Compose file. `.env` carries DB password, Copernicus CDS key, SMTP creds, allowed CORS origins. Volumes: `timescale_data`, `redis_data`, `caddy_data`. Healthchecks on every service. `restart: unless-stopped` for everything except one-off jobs.

## Sources

- [Tiger Data — Continuous Aggregates documentation](https://www.tigerdata.com/docs/use-timescale/latest/continuous-aggregates/create-a-continuous-aggregate)
- [Tiger Data — Understanding Continuous Aggregates](https://www.tigerdata.com/docs/learn/continuous-aggregates)
- [TimescaleDB docs — Continuous Aggregates source](https://github.com/timescale/docs/blob/latest/use-timescale/continuous-aggregates/about-continuous-aggregates.md)
- [TimescaleDB docs — Compression](https://github.com/timescale/docs.timescale.com-content/blob/master/using-timescaledb/compression.md)
- [Policy Types and Configuration (DeepWiki on timescale/timescaledb)](https://deepwiki.com/timescale/timescaledb/5.1-policy-types-and-configuration)
- [TimescaleDB Compression: 95%+ storage reduction (community guide)](https://dev.to/philip_mcclarence_2ef9475/timescaledb-compression-a-complete-guide-to-95-storage-reduction-2mo4)
- [Troubleshooting TimescaleDB at Scale (chunk design, CAGGs, compression)](https://mindfulchase.com/explore/troubleshooting-tips/databases/troubleshooting-timescaledb-at-scale-chunk-design,-compression,-continuous-aggregates,-and-wal-resilience.html)
- [How to Design TimescaleDB Hypertables (OneUptime)](https://oneuptime.com/blog/post/2026-01-26-timescaledb-hypertables/view)
- [Asynchronous Tasks with FastAPI and Celery (TestDriven.io)](https://testdriven.io/blog/fastapi-and-celery/)
- [Periodic Tasks / Cronjob with Celery + FastAPI (FastAPI Tutorial)](https://fastapitutorial.com/blog/periodic-tasks-celery-fastapi/)
- [Advanced Celery: Priority Queues, Dead Letter Queues, Scaling Workers](https://medium.com/@sumanb1720/advanced-celery-monitoring-priority-queues-dead-letter-queues-and-scaling-workers-405c94ba33dd)
- [Adapter Pattern in Python (Refactoring Guru)](https://refactoring.guru/design-patterns/adapter/python/example)
- [Adapter Pattern in Python — design pattern series (Medium)](https://medium.com/design-patterns-in-python/adapter-design-pattern-9755c5467c47)
- [Real-Time GPS Tracking on a Web Map using FastAPI & Leaflet](https://araz.me/2025/02/17/real-time-gps-tracking-on-a-web-map-using-fastapi-leaflet/)
- [Building a Realtime Dashboard with FastAPI + WebSockets](https://medium.com/@kaushalsinh73/building-a-realtime-dashboard-with-fastapi-websockets-863d5b90dc8e)
- [Angular SSR + Leaflet compatibility discussion (GitHub)](https://github.com/Leaflet/Leaflet/discussions/9412)

---
*Architecture research for: open-source multi-source weather aggregation pipeline (Climate Pulse)*
*Researched: 2026-05-23*
