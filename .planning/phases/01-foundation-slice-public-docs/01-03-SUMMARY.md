---
phase: 01-foundation-slice-public-docs
plan: "03"
subsystem: ingestion-core
tags: [adapter-abc, registry, wmo-normalizer, pint, hypothesis, dst, polite-http, snapshot, writer, asyncpg, timescaledb, redis, observability]
dependency_graph:
  requires: [01-01, 01-02]
  provides: [WeatherSourceAdapter-ABC, registry, FetchWindow, Settings, WMO-normalizer, QC, timezone, PoliteHttpClient, SnapshotStore, IdempotentWriter, MetadataRepo, health-metrics]
  affects: [01-04-adapters, 01-05-worker-compose]
tech_stack:
  added:
    - pint 0.25.3 (WMO SI unit conversion — offset-unit safe via UREG.Quantity)
    - tenacity 9.1.4 (exponential backoff + jitter for HTTP retries)
    - pyrate-limiter 4.1.0 (RedisBucket per-host rate limit cross-worker)
    - hypothesis 6.152.9 (property-based tests for normalizer and timezone)
    - fakeredis>=2.23 (test fixture for Redis-backed health metrics)
    - respx>=0.21 (httpx mocking for PoliteHttpClient tests)
    - structlog 25.5.0 (structured logging in writer)
  patterns:
    - ABC + decorator registry: @register("source_id") populates _REGISTRY; get_adapter() returns fresh instance
    - UREG.Quantity(value, unit).to(target) for offset-unit safe Pint conversion
    - copy_records_to_table -> temp staging -> INSERT ON CONFLICT DO UPDATE (asyncpg hot path)
    - xmax = 0 in RETURNING to distinguish INSERT vs DO UPDATE rows
    - hypothesis @given with assume() to skip DST transition windows in property tests
key_files:
  created:
    - packages/core/climatepulse_core/adapters/__init__.py
    - packages/core/climatepulse_core/adapters/base.py
    - packages/core/climatepulse_core/settings.py
    - packages/core/climatepulse_core/normalize/__init__.py
    - packages/core/climatepulse_core/normalize/wmo.py
    - packages/core/climatepulse_core/normalize/qc.py
    - packages/core/climatepulse_core/normalize/timezone.py
    - packages/core/climatepulse_core/http/__init__.py
    - packages/core/climatepulse_core/http/client.py
    - packages/core/climatepulse_core/http/snapshot.py
    - packages/core/climatepulse_core/observability/__init__.py
    - packages/core/climatepulse_core/observability/health.py
    - packages/core/climatepulse_core/storage/writer.py
    - packages/core/climatepulse_core/storage/repos.py
    - tests/unit/__init__.py
    - tests/unit/conftest.py
    - tests/unit/test_adapter_registry.py
    - tests/unit/test_normalizer.py
    - tests/unit/test_qc.py
    - tests/unit/test_timezone.py
    - tests/unit/test_snapshot.py
    - tests/unit/test_polite_http.py
    - tests/integration/test_writer.py
  modified: []
decisions:
  - "Used UREG.Quantity(value, unit) instead of value * UREG(unit) to handle Pint offset units (degC, degF) correctly — multiplication raises OffsetUnitCalculusError"
  - "PoliteHttpClient accepts redis_client=None to use InMemoryBucket in tests (fakeredis does not support SCRIPT command required by RedisBucket)"
  - "to_utc() detects DST gaps/overlaps via explicit _find_last_sunday() helper rather than Pint/pytz fold detection — zoneinfo stdlib is preferred per Python 3.12 guidance"
  - "Writer uses CTE with RETURNING xmax to count INSERT vs DO UPDATE rows without a second SELECT"
  - "Snapshot station_or_grid_id is derived from a sanitised URL fragment on terminal HTTP failure"
metrics:
  duration_seconds: 1143
  completed_at: "2026-05-23T11:15:00Z"
  tasks_completed: 4
  tasks_total: 4
  files_created: 23
  files_modified: 1
  tests_added: 70
  unit_tests: 64
  integration_tests: 6
---

# Phase 01 Plan 03: Ingestion Core (ABC + Normalizer + HTTP + Writer) Summary

**One-liner:** Full ingestion core: WeatherSourceAdapter ABC + decorator registry + Pint WMO normalizer (7 vars, hypothesis-tested) + Europe/Rome DST timezone helper + PoliteHttpClient with tenacity/rate-limit/snapshot + IdempotentWriter routing to dual TimescaleDB hypertables via asyncpg COPY.

## What Was Built

### Task 1: Adapter ABC + Registry + Settings (commit: 4d23082)

**WeatherSourceAdapter ABC** (`packages/core/climatepulse_core/adapters/base.py`):

```python
class WeatherSourceAdapter(ABC):
    source_id: str             # set by @register
    cadence_seconds: int       # must declare on subclass
    polite_delay_ms: int = 1000
    is_grid_based: bool = False  # True -> gridded_observations

    @abstractmethod
    async def discover_stations(self) -> list[Station]: ...

    @abstractmethod
    async def fetch(self, window: FetchWindow) -> AsyncIterator[RawObservation]: ...

    @abstractmethod
    def source_meta(self) -> SourceMeta: ...
```

**Decorator registry:**
```python
@register("arpa_emilia")
class ArpaeAdapter(WeatherSourceAdapter): ...

adapter = get_adapter("arpa_emilia")  # fresh instance every call
ids = all_source_ids()                 # sorted list
```

**FetchWindow:** frozen dataclass that rejects naive datetimes and inverted ranges via `__post_init__`.

**Settings** (pydantic-settings 2.x): `database_url` (required), `redis_url`, `snapshot_dir`, `log_level`, `environment`. Redis DB allocation constants: `REDIS_DB_BROKER=0`, `REDIS_DB_RESULTS=1`, `REDIS_DB_RATELIMIT=2`, `REDIS_DB_ETAG=3`, `REDIS_DB_METRICS=4`.

### Task 2: WMO Normalizer + QC + Timezone (commit: b0b2883)

**WMO_VARIABLES catalog** (7 variables per ING-09):

| wmo_code | unit_si | physical_range | bufr_codes |
|---|---|---|---|
| air_temperature | K | (180, 340) | [B12101] |
| relative_humidity | % | (0, 100) | [B13003, 2r] |
| surface_pressure | Pa | (87000, 109000) | [B10004, sp] |
| wind_direction | degree | (0, 360) | [B11001, 10wd] |
| wind_speed | m / s | (0, 120) | [B11002] |
| total_precipitation | kg m-2 | (0, 500) | [B13011, tp] |
| cloud_cover | % | (0, 100) | [B20010] |

**Pint UnitRegistry custom units:** `mm_water = kg / m**2 = mmw` (precipitation 1:1 mapping).

**Key API:**
```python
value_si, unit_si = normalize_to_si("air_temperature", 20.0, "degC")  # -> (293.15, "K")
wmo_code = bufr_to_wmo_code("B12101")  # -> "air_temperature"
rh = rh_from_dewpoint(t2m_kelvin=293.15, d2m_kelvin=283.15)  # -> ~52.5%
```

**Timezone helpers** (D-26 explicit DST cases both pass):
- `to_utc(datetime(2026, 3, 29, 2, 30))` raises `NonExistentTimeError` (spring-forward gap)
- `to_utc(datetime(2026, 10, 25, 2, 30))` raises `AmbiguousTimeError` (fall-back overlap)
- `to_utc_strict(gap_dt)` -> (advanced+1h UTC, QcFlag.OUT_OF_RANGE)
- `to_utc_strict(overlap_dt, fold=0)` -> (first occurrence = CEST UTC+2)

**Hypothesis coverage (D-26):** 200 examples each for K↔°C, Pa↔hPa, m/s↔knots, and UTC round-trip.

### Task 3: PoliteHttpClient + SnapshotStore + Health (commit: 6d5043a)

**PoliteHttpClient** (ING-02 full contract):
- User-Agent: `ClimatePulse/0.1.0 (+https://github.com/federicocalo/climate-pulse; contact: fedcal01@gmail.com)`
- robots.txt: `urllib.robotparser` with 24h in-memory cache per host
- Rate limit: `pyrate-limiter` RedisBucket (production) or InMemoryBucket (test)
- Retry: tenacity 5 attempts, `wait_random_exponential(min=1, max=4)` on HTTPStatusError/Timeout
- ETag: passes `If-None-Match`, returns `(None, etag)` on 304
- Snapshot fallback: writes JSON-LD on terminal failure

**SnapshotStore** (D-15/D-16/D-17):
- Path layout: `{snapshot_dir}/{source_id}/{station_or_grid_id}/{ISO8601_UTC}.jsonld`
- Security guard: `^[a-zA-Z0-9_-]+$` regex rejects path traversal (T-03-04)
- `rotate(max_age_days=30)`: deletes files older than 30 days; returns count

**JSON-LD snapshot @context** references: WMO codes registry, schema.org, and `cp:` vocab namespace.

**Health metrics** (ING-14):
```python
await record_success(redis, "arpa_emilia")    # SETEX 86400
last = await get_last_success(redis, "arpa_emilia")  # -> datetime | None
stale = await is_stale(redis, "arpa_emilia", cadence_seconds=900)  # True if >1800s
```

**Redis DB allocation:**
```
DB 0: Celery broker
DB 1: Celery result backend
DB 2: pyrate-limiter per-host rate-limit buckets
DB 3: aiocache ETag cache
DB 4: ING-14 metrics:last_success:{source_id}
```

### Task 4: IdempotentWriter + MetadataRepo (commit: 224b677)

**IdempotentWriter.write_batch** routes by `adapter.is_grid_based`:

```python
writer = IdempotentWriter(
    db_pool=db_pool,
    redis_client=redis,
    sources_cache={"arpa_emilia": 1},
    variables_cache={"air_temperature": 1},
    stations_cache={"arpa_emilia": {"stn001": 42}},
)
count = await writer.write_batch(station_adapter, observations)   # -> observations table
count = await writer.write_batch(ecmwf_adapter, grid_obs)         # -> gridded_observations table
```

**Write path:**
1. `COPY records` into `obs_staging` (temp, ON COMMIT DROP)
2. `INSERT INTO observations SELECT ... FROM obs_staging ON CONFLICT (...) DO UPDATE`
3. `RETURNING xmax`: `xmax=0` → inserted, `xmax!=0` → updated
4. `record_success(redis, source_id)` (ING-14)

**MetadataRepo:** `upsert_source / upsert_variable / upsert_station` with ON CONFLICT DO UPDATE; `load_sources_cache / load_variables_cache / load_stations_cache` for hot-path pre-loading.

## Test Results

| Test File | Tests | Status |
|---|---|---|
| tests/unit/test_adapter_registry.py | 9 | PASS |
| tests/unit/test_normalizer.py | 14 | PASS (hypothesis 200ex each) |
| tests/unit/test_qc.py | 9 | PASS |
| tests/unit/test_timezone.py | 9 | PASS (hypothesis 200ex + explicit DST) |
| tests/unit/test_snapshot.py | 8 | PASS |
| tests/unit/test_polite_http.py | 13 | PASS |
| tests/integration/test_writer.py | 6 | PASS (real TimescaleDB) |
| **TOTAL** | **68** | **ALL PASS** |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pint OffsetUnitCalculusError for degC conversion**
- **Found during:** Task 2, first test run
- **Issue:** `value * UREG('degC')` raises `OffsetUnitCalculusError` — Pint prohibits multiplication with offset (non-multiplicative) units like degC, degF
- **Fix:** Changed to `UREG.Quantity(value, unit).to(target_unit)` — the constructor handles offset units correctly
- **Files modified:** `packages/core/climatepulse_core/normalize/wmo.py`
- **Commit:** b0b2883

**2. [Rule 2 - Missing functionality] fakeredis incompatibility with RedisBucket**
- **Found during:** Task 3, test fixture design
- **Issue:** `pyrate_limiter.RedisBucket.init()` calls `SCRIPT LOAD` which fakeredis does not support — test would fail with `ResponseError: unknown command 'script'`
- **Fix:** PoliteHttpClient accepts `redis_client=None` to fall back to `InMemoryBucket` in tests; production code still uses `RedisBucket` when a real redis_client is passed
- **Files modified:** `packages/core/climatepulse_core/http/client.py`, `tests/unit/test_polite_http.py`
- **Commit:** 6d5043a

**3. [Rule 1 - Bug] UnboundLocalError in test_write_batch_records_success_metric**
- **Found during:** Task 4, last integration test
- **Issue:** `from datetime import datetime` inside the test function body shadowed the module-level import of `datetime`, causing `UnboundLocalError: cannot access local variable 'datetime'`
- **Fix:** Removed redundant inline import; used `datetime.fromisoformat()` directly from module-level import
- **Files modified:** `tests/integration/test_writer.py`
- **Commit:** 224b677 (final commit included this fix)

## Known Stubs

None — all implemented modules are fully wired. No hardcoded empty values or placeholders in the production code path.

## Threat Flags

No new network endpoints or trust boundaries beyond those in the plan's `<threat_model>`. All T-03-04 path traversal guards are implemented in `SnapshotStore`.

## Requirements Satisfied

| ID | Description | Status |
|---|---|---|
| ING-01 | WeatherSourceAdapter ABC + decorator-based source registry | DONE |
| ING-02 | Polite HTTP client (UA, robots.txt, Redis rate-limit, tenacity, aiocache ETag, snapshot) | DONE |
| ING-09 | WMO Normalizer (7 core vars, SI units via Pint, range validation, QC flags) | DONE |
| ING-10 | Timezone-safe ingestion (Europe/Rome -> UTC; DST tests March + October) | DONE |
| ING-12 | Idempotent writer ON CONFLICT ... DO UPDATE via asyncpg copy_records_to_table | DONE |
| ING-14 | Per-adapter health metric last_successful_ingest_at + canary alert | DONE |
| D-23 | Dual-hypertable routing in Writer.write_batch by is_grid_based | DONE |
| D-26 | hypothesis coverage for Normalizer round-trips + Timezone DST | DONE |

## Self-Check: PASSED

Files verified to exist:
- packages/core/climatepulse_core/adapters/base.py ✓
- packages/core/climatepulse_core/normalize/wmo.py ✓
- packages/core/climatepulse_core/http/client.py ✓
- packages/core/climatepulse_core/http/snapshot.py ✓
- packages/core/climatepulse_core/observability/health.py ✓
- packages/core/climatepulse_core/storage/writer.py ✓
- packages/core/climatepulse_core/storage/repos.py ✓

Commits verified to exist:
- 4d23082: Task 1 — Adapter ABC + registry + Settings ✓
- b0b2883: Task 2 — WMO normalizer + QC + timezone ✓
- 6d5043a: Task 3 — PoliteHttpClient + SnapshotStore + health ✓
- 224b677: Task 4 — IdempotentWriter + MetadataRepo ✓
