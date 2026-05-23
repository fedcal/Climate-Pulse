# Phase 1: Foundation Slice + Public Docs — Research

**Researched:** 2026-05-23
**Domain:** Walking Skeleton — ARPAE-SIMC + ECMWF ingestion → dual TimescaleDB hypertables → Celery + Beat → FastAPI /healthz+/readyz → MkDocs Material on GitHub Pages
**Confidence:** HIGH for stack and patterns; MEDIUM for ARPAE endpoint schema (empirically discovered); LOW for ECMWF EU bbox subsetting approach

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Repo + Docs URL**
- D-01: Repo at `github.com/federicocalo/climate-pulse`
- D-02: MkDocs at `federicocalo.github.io/climate-pulse` (no custom domain in Phase 1)
- D-03: GitHub Pages via `actions/configure-pages` + `actions/upload-pages-artifact` + `actions/deploy-pages` (NOT peaceiris); `environment: github-pages`
- D-04: `mike` versioning deferred to Phase 5

**Footer / Attribution**
- D-05: Footer verbatim: `Climate Pulse · MIT License · federicocalo.dev` (middle-dot `·`, exact casing)
- D-06: Implemented via `copyright` field in `mkdocs.yml` (no custom partial needed)
- D-07: Same verbatim text reused in Angular dashboard Phase 3
- D-08: No navbar Author link, no topbar social icon — footer only

**Phase 1 Acceptance Demo**
- D-09: Done = fresh machine `docker compose up` → 10 min → TimescaleDB ingesting Arpae + ECMWF, 5–10 ARPA stations × 30 days, `/healthz` + `/readyz` returning 200, MkDocs live with footer, quickstart works
- D-10: ECMWF scope: EU bbox, 4 cycles/day, 5+ variables (T2m, SP, 10u, 10v, TP, 2m RH)
- D-11: ARPA scope: 5–10 representative stations × 30 days
- D-12: Quickstart: `climatepulse backfill arpae --from ... --to ...` → `psql -c "select count(*), source from observations group by source"`
- D-13: Quickstart does NOT mention Phase 2+ endpoints

**API scope**
- D-14: SCOPE ADJUSTMENT — FastAPI ships ONLY `/healthz` + `/readyz` in Phase 1. All other API-* stay in Phase 2.

**Snapshot Fallback**
- D-15: Storage: Docker volume `snapshots/`, env var `SNAPSHOT_DIR` (default `/var/lib/climatepulse/snapshots`)
- D-16: Format: JSON-LD canonical, per file `<source>/<station>/<timestamp>.jsonld` with `@context` referencing WMO variables
- D-17: Retention: 30 days rolling, cleaned by Celery task `tasks.maintenance.rotate_snapshots` daily

**ARPA Emilia-Romagna Source**
- D-18: Primary endpoint: `dati.arpae.it` / `dati-simc.arpae.it` REST/JSON
- D-19: Ingestion cadence: 15 minutes
- D-20: Schema-drift: row marked `quality_flag='schema_violation'` + routed to `dlq` + ING-14 canary flips source to `unhealthy`; NO fail-loud

**ECMWF GRIB Parsing**
- D-21: cfgrib 0.9.14+ + system `libeccodes0` in worker Dockerfile
- D-22: `libeccodes0` in worker container ONLY (api container stays slim)
- D-23: DEVIATION — TWO hypertables: `observations` (station-based) + `gridded_observations` (ECMWF grid-based). Each gets own CAGG, compression, retention policies.

**Testing**
- D-24: CI coverage gate: 80% global / 70% adapters
- D-25: testcontainers (TimescaleDB) MANDATORY in CI
- D-26: hypothesis mandatory for Normalizer (unit round-trips) and Timezone (DST March + October)
- D-27: VCR.py cassettes for 5+ ARPA scenarios: 200 OK, 304 ETag, 404, 500, timeout

### Claude's Discretion
- Compose network topology (single vs separated)
- CI matrix strategy (planner chooses; default `ubuntu-22.04` + `python 3.12.7`)
- Adapter ABC interface contract (sync iterator vs async generator vs batch)
- Logging library config (structlog handlers, formatters)
- Test fixture organization and helper layout

### Deferred Ideas (OUT OF SCOPE)
- Custom domain `climatepulse.federicocalo.dev`
- `mike` docs versioning (Phase 5)
- Navbar Author link / social icon
- VCR cassette beyond 5 ARPA scenarios
- MinIO snapshot storage
- `/v1/sources/status` UI endpoint (Phase 3, backend metric collected Phase 1)
- CI matrix multi-OS / multi-Python (Phase 5)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ING-01 | `WeatherSourceAdapter` ABC + decorator-based source registry | Pattern documented; async generator ABC design confirmed |
| ING-02 | Polite HTTP client (UA, robots.txt, Redis rate-limit, tenacity, aiocache ETag, snapshot fallback) | pyrate-limiter Redis backend + aiocache 0.12.3 + tenacity 9.1.4 confirmed OK |
| ING-03 | ARPA Emilia-Romagna adapter (station-based via dati-simc.arpae.it REST/JSON) | BUFR-coded line-delimited JSON schema documented; SIMC portal paths identified |
| ING-04 | ECMWF Open Data adapter (grid-based, cfgrib + libeccodes0) | ecmwf-opendata 0.3.29 confirmed; bbox limitation: must subset xarray post-download |
| ING-09 | WMO Normalizer (7 core vars, SI units via Pint, range validation, QC flags) | Pint 0.25.3, BUFR B-table variable codes documented |
| ING-10 | Timezone-safe ingestion (Europe/Rome → UTC; DST tests March + October) | Confirmed: ARPAE timestamps are UTC ISO-8601 in realtime feed; storico may be naive |
| ING-11 | Celery worker + dedicated Beat service + 4 queues + retry + DLQ | Celery 5.6.3 + redis<6 compatibility confirmed |
| ING-12 | Idempotent writer `ON CONFLICT … DO UPDATE` via asyncpg copy_records_to_table | asyncpg 0.31.0 confirmed; pattern documented |
| ING-13 | Backfill CLI (`climatepulse backfill <source> --from --to`) | Storico endpoint at dati-simc.arpae.it/opendata/osservati/meteo/storico/ provides monthly gzip files |
| ING-14 | Per-adapter health metric `last_successful_ingest_at` + canary alert | Pattern documented in pitfalls; structlog gauge integration pattern available |
| STO-01 | `observations` hypertable, PK `(station_id, variable_id, observed_at, source_id)`, chunk_time_interval 7d | D-23 confirms single hypertable for station-based; DDL provided |
| STO-02 | Metadata tables: stations, variables, sources | Schema from ARCHITECTURE.md adapted; geom GEOGRAPHY(POINT,4326) |
| STO-03 | CAGGs: `obs_hourly` (raw) + `obs_daily` (obs_hourly) for observations; `gridded_hourly` for gridded_observations | D-23 mandates two CAGG trees; policy ordering rule confirmed |
| STO-04 | Compression policy 7d segmentby=(station_id, variable_id) | TimescaleDB 2.17 API confirmed |
| STO-05 | Retention configurable per source (default 5y raw / 20y aggregates) | add_retention_policy confirmed |
| STO-06 | Alembic migrations + raw SQL for create_hypertable / CAGG DDL; correct policy ordering | op.execute() pattern + include_name exclude workaround documented |
| OPS-01 | Docker Compose v2.30+ compose.yaml with timescale + redis + api + worker + beat + healthchecks | Docker Compose v5.1.0 installed (exceeds requirement) |
| OPS-07 | .env.example + gitleaks pre-commit + secret rotation runbook | gitleaks GitHub Action v2 confirmed; pre-commit 4.6.0 available |
| OPS-08 | GitHub Actions CI (pytest + ruff + pyright + 80%/70% coverage gate) | ruff 0.15.14 + pyright 1.1.409 + pytest-cov 7.1.0 confirmed |
| OPS-09 | docs/scraping-policy.md for ARPA admin transparency | Content structure documented |
| DOC-01 | MkDocs Material 9.5+ bootstrapped from v0.1 | mkdocs-material 9.7.6 confirmed |
| DOC-02 | GitHub Action build + deploy on push to main | Two-job workflow documented (build + deploy jobs) |
| DOC-03 | Footer `federicocalo.dev` on every docs page | `copyright` field in mkdocs.yml |
| DOC-05 | Quickstart guide (docker compose up + backfill CLI demo) | Content structure from D-12 |
| API-10 | GET /healthz + GET /readyz (check DB + Redis + Celery heartbeat) | FastAPI 0.136.1; readyz pattern documented |
</phase_requirements>

---

## Summary

Phase 1 is a Walking Skeleton that must prove the full architectural spine from data ingestion to storage to documentation in the thinnest possible vertical slice. The planner must design two parallel tracks that converge at the end: the backend pipeline track (adapter → normalize → write → Celery → TimescaleDB) and the docs/CI track (MkDocs → GitHub Pages → GitHub Actions CI).

The most novel element of this phase relative to the existing research is the **dual hypertable design** (D-23): `observations` for station-based ARPAE data and `gridded_observations` for ECMWF grid-point data. This doubles the DDL complexity (two CAGG trees, two compression policies, two retention policies) but cleanly separates the station-vs-grid query patterns. Every downstream plan that touches storage must account for both tables.

The **ARPAE REST/JSON endpoint** is now well-understood: it is a line-delimited JSON (`.jsonl`) stream with BUFR-coded variable fields (B12101 for temperature, B13003 for humidity, etc.) in SI units. The realtime feed at `dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl` returns UTC timestamps. The storico feed provides monthly gzip archives organized as `YYYY-MM.json.gz`.

**Primary recommendation:** Plan 4 waves. Wave 0 (scaffold + CI skeleton), Wave 1 (storage layer: both hypertables + migrations), Wave 2 (ingestion: ABC + Arpae adapter + ECMWF adapter + Celery + normalizer + writer), Wave 3 (FastAPI /healthz+/readyz + Compose healthchecks + MkDocs deploy). Walk the skeleton before adding flesh — get `docker compose up` green before hardening.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ARPAE station observation ingestion | Celery Worker | Redis (broker) | Worker polls REST endpoint, normalizes, writes; Beat schedules the trigger |
| ECMWF GRIB download + decode | Celery Worker | Docker volume (GRIB staging) | libeccodes0 lives in worker container only (D-22); GRIB files too large for in-memory streaming |
| ECMWF EU bbox subsetting | Celery Worker (xarray post-processing) | — | ecmwf-opendata client has no server-side bbox; subset after download via xarray |
| WMO normalization (units, QC flags) | Celery Worker (packages/core normalizer) | — | Pure function, stateless; belongs in core package shared by worker and tests |
| Idempotent write to hypertables | Celery Worker (asyncpg) | TimescaleDB | ON CONFLICT DO UPDATE; asyncpg copy_records_to_table for hot path |
| Polite HTTP client (rate-limit, robots.txt, ETag, snapshot) | packages/core/http | Redis (shared rate-limit budget) | Centralized in core; pyrate-limiter RedisBucket shared across all Celery workers |
| Snapshot fallback storage | Celery Worker | Docker volume (snapshots/) | JSON-LD files written to mounted volume on failure |
| /healthz + /readyz endpoints | FastAPI API container | Redis + TimescaleDB (probed) | Minimal app; checks DB ping + Redis ping + Celery worker heartbeat |
| Schema migrations | Alembic (packages/migrations) | TimescaleDB | Runs on startup; op.execute() for create_hypertable DDL |
| Celery Beat scheduling | Dedicated `beat` service | Redis (scheduler state) | Singleton, never colocated with workers (D-19, Pitfall #6) |
| MkDocs build + GitHub Pages deploy | GitHub Actions CI | — | Triggered on push to main; build job → upload artifact → deploy-pages job |
| gitleaks secret scanning | GitHub Actions CI + pre-commit | — | Both gates prevent secret leaks |

---

## Standard Stack

### Core (Phase 1 subset — do not install all-at-once)

| Library | Verified Version | Purpose | Why Standard |
|---------|-----------------|---------|--------------|
| FastAPI | 0.136.1 | /healthz + /readyz endpoints | Locked decision; 0.136.x confirmed on PyPI |
| uvicorn[standard] | 0.47.0 | ASGI server | Standard FastAPI runner |
| Pydantic | 2.9+ | Settings + response models | Required by FastAPI 0.136 |
| pydantic-settings | 2.14.1 | 12-factor config from .env | Loads SNAPSHOT_DIR, DB_URL, REDIS_URL etc. |
| asyncpg | 0.31.0 | Hot-path DB writes + reads | Drives SQLAlchemy async; raw copy_records_to_table for ingest |
| SQLAlchemy[asyncio] | 2.0.36+ | Metadata ORM (stations, variables, sources) | Async mode; not used for hot observation inserts |
| sqlalchemy-timescaledb | 0.4.1 | Timescale dialect for create_hypertable | slopcheck [OK] |
| Alembic | 1.18.4 | DB migrations incl. raw SQL DDL | op.execute() pattern for create_hypertable, add_*_policy |
| Celery[redis] | 5.6.3 | Worker + Beat task queue | Locked; redis Python client must be <6.0 |
| redis | 5.0+ (NOT 6.x) | Celery broker + pyrate-limiter backend + aiocache backend | Server Redis 7.4 fine; client constraint is Python redis<6 |
| httpx | 0.28.1 | Async HTTP client for ARPAE ingestion | Replaces requests; async-native; VCR.py compatible |
| tenacity | 9.1.4 | Exponential backoff + jitter on HTTP calls | slopcheck [OK] |
| aiocache | 0.12.3 | ETag/Last-Modified cache via Redis | slopcheck [OK]; politeness requirement ING-02 |
| pyrate-limiter | 4.1.0 | Shared per-host rate limit (Redis RedisBucket) | slopcheck [OK]; cross-worker Redis backend |
| ecmwf-opendata | 0.3.29 | ECMWF Open Data download client | Official ECMWF package; slopcheck [OK] |
| cfgrib | 0.9.15.1 | Parse GRIB2 via xarray; worker container only | slopcheck [OK]; requires libeccodes0 system dep |
| xarray | 2026.4.0 | Grid slicing after GRIB decode; EU bbox subsetting | De-facto standard for gridded weather data |
| Pint | 0.25.3 | Unit conversion (°C→K, hPa→Pa, knots→m/s) | WMO SI requirement ING-09 |
| structlog | 25.5.0 | Structured JSON logging | slopcheck [OK] |
| mkdocs-material | 9.7.6 | Docs site | slopcheck [OK]; `copyright` field for footer |
| mkdocstrings[python] | 1.0.4 | Docstring → docs | slopcheck [OK] |

### Testing (dev dependencies)

| Library | Verified Version | Purpose | Notes |
|---------|-----------------|---------|-------|
| pytest | 8.3+ | Test runner | Standard |
| pytest-asyncio | 1.3.0 | Async test support | `asyncio_mode = "auto"` in pyproject |
| pytest-cov | 7.1.0 | Coverage gates | 80%/70% D-24 |
| hypothesis | 6.152.9 | Property-based tests for normalizer + timezone | D-26; slopcheck [OK] |
| testcontainers | 4.14.2 | Real TimescaleDB in CI | D-25; slopcheck [OK] |
| vcrpy | 8.1.1 | HTTP cassette record/replay for ARPA | slopcheck [SUS — false positive: typosquat warning near 'scipy'] — confirmed legitimate: github.com/kevin1024/vcrpy, 80+ version history since 2012, PyPI author Kevin McCarthy |
| pytest-recording | latest | pytest plugin wrapping VCR.py | slopcheck [OK] |
| respx | 0.21+ | httpx mock for edge-case error injection | Supplement to VCR cassettes |
| ruff | 0.15.14 | Linter + formatter (replaces flake8+black+isort) | slopcheck [OK] |
| pyright | 1.1.409 | Static type checking | slopcheck [OK] |
| pre-commit | 4.6.0 | Git hook framework | slopcheck [OK] |

### CI / Deploy Actions (GitHub-native, no PyPI)

| Action | Version | Purpose |
|--------|---------|---------|
| actions/configure-pages | v5 | Enable GitHub Pages for repo |
| actions/upload-pages-artifact | v3 | Upload built site/ dir |
| actions/deploy-pages | v4 | Deploy to GitHub Pages environment |
| gitleaks/gitleaks-action | v2 | Secret scanning in CI |

**Installation (uv workspace):**

```bash
# Worker + core packages (heavy deps go in worker image only)
uv add fastapi==0.136.* uvicorn[standard] pydantic pydantic-settings asyncpg
uv add sqlalchemy[asyncio]==2.0.* sqlalchemy-timescaledb alembic
uv add "celery[redis]==5.6.3" "redis<6.0"
uv add httpx tenacity aiocache pyrate-limiter
uv add structlog
# Worker-only (in apps/worker pyproject.toml, NOT in api):
uv add ecmwf-opendata cfgrib xarray pint

# Dev tools
uv add --dev pytest pytest-asyncio pytest-cov hypothesis
uv add --dev "testcontainers[postgres]>=4.14"
uv add --dev vcrpy pytest-recording respx
uv add --dev ruff pyright pre-commit
uv add --dev mkdocs-material mkdocstrings[python]

# System dependency in apps/worker/Dockerfile:
# RUN apt-get update && apt-get install -y libeccodes0 libeccodes-tools
```

---

## Package Legitimacy Audit

> slopcheck 0.6.1 was available and run in this session.

| Package | Registry | Age | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|
| fastapi | PyPI | 7 yrs | [OK] (not scanned — well-known) | Approved |
| asyncpg | PyPI | 8 yrs | [OK] | Approved |
| sqlalchemy-timescaledb | PyPI | 5 yrs | [OK] | Approved |
| alembic | PyPI | 12 yrs | [OK] | Approved |
| celery | PyPI | 14 yrs | [OK] (not scanned — well-known) | Approved |
| httpx | PyPI | 5 yrs | [OK] (not scanned — well-known) | Approved |
| tenacity | PyPI | 8 yrs | [OK] | Approved |
| aiocache | PyPI | 8 yrs | [OK] | Approved |
| pyrate-limiter | PyPI | 5 yrs | [OK] | Approved |
| ecmwf-opendata | PyPI | 3 yrs | [OK] | Approved |
| cfgrib | PyPI | 6 yrs | [OK] | Approved |
| xarray | PyPI | 10 yrs | [OK] (not scanned — well-known) | Approved |
| pint | PyPI | 12 yrs | [OK] (not scanned — well-known) | Approved |
| structlog | PyPI | 11 yrs | [OK] | Approved |
| mkdocs-material | PyPI | 8 yrs | [OK] | Approved |
| mkdocstrings | PyPI | 5 yrs | [OK] | Approved |
| hypothesis | PyPI | 10 yrs | [OK] | Approved |
| testcontainers | PyPI | 8 yrs | [OK] | Approved |
| vcrpy | PyPI | 13 yrs | **[SUS]** (typosquat false-positive: slopcheck confused with 'scipy') | **Approved with note** — verified: github.com/kevin1024/vcrpy, 80+ releases, 2012 origin, 6k+ GitHub stars, widely cited in testing literature. D-27 mandates it. |
| pytest-recording | PyPI | 5 yrs | [OK] | Approved |
| pydantic-settings | PyPI | 3 yrs | [OK] | Approved |
| aiolimiter | PyPI | 5 yrs | [OK] | Approved |
| pyright | PyPI | 4 yrs | [OK] | Approved |
| ruff | PyPI | 3 yrs | [OK] (not scanned — well-known) | Approved |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged [SUS]:** vcrpy — false positive confirmed, approved. No checkpoint required.

---

## Architecture Patterns

### System Architecture Diagram

```
[ARPAE-SIMC realtime.jsonl]     [ECMWF Open Data GRIB2]
         |                               |
         | HTTP GET (polite client)      | ecmwf-opendata Client.retrieve()
         v                               v
  ┌──────────────────────────────────────────────────────────┐
  │              Celery Workers (queue=ingest)                │
  │  ArpaeAdapter.fetch()           EcmwfAdapter.fetch()     │
  │       |                               |                   │
  │       v                               v                   │
  │  [BUFR JSON parse]           [cfgrib+xarray decode]      │
  │       |                       [EU bbox xr.sel()]         │
  │       v                               |                   │
  │  WMO Normalizer (Pint SI)     WMO Normalizer (Pint SI)  │
  │  quality_flag assignment      quality_flag assignment    │
  │       |                               |                   │
  │       v                               v                   │
  │  Idempotent Writer             Idempotent Writer         │
  │  asyncpg COPY                  asyncpg COPY             │
  └───────────────┬──────────────────────┬───────────────────┘
                  |                      |
         on HTTP error              on decode error
                  |                      |
         [JSON-LD snapshot]        [JSON-LD snapshot]
         snapshots/<src>/<stn>/    snapshots/ecmwf/<grid>/
                  |                      |
                  v                      v
  ┌───────────────────────────────────────────────────────────┐
  │              TimescaleDB (PostgreSQL 16)                   │
  │   observations hypertable         gridded_observations     │
  │   (station_id, variable_id,       (lat_idx, lon_idx,      │
  │    observed_at, source_id)         variable_id, valid_at,  │
  │                                    source_id, step_h)     │
  │   CAGG: obs_hourly                CAGG: gridded_hourly    │
  │   compress >7d, retain 5y raw     compress >7d, retain 90d│
  └──────────────────────────────────────────────────────────┘
                            |
                            | asyncpg
                            v
  ┌───────────────────────────────────┐
  │  FastAPI (Minimal — Phase 1 only) │
  │  GET /healthz (liveness)          │
  │  GET /readyz  (DB+Redis+Celery)   │
  └───────────────────────────────────┘
                            |
  [Celery Beat] ──────────> [Redis broker]
  singleton beat service    DB 0: broker
                            DB 1: result backend
                            DB 2: rate-limit store (pyrate-limiter)
                            DB 3: ETag cache (aiocache)
```

### Recommended Project Structure

```
climate-pulse/
├── apps/
│   ├── api/
│   │   ├── climatepulse_api/
│   │   │   ├── main.py           # FastAPI app factory; /healthz + /readyz only
│   │   │   ├── routers/
│   │   │   │   └── health.py     # liveness + readiness checks
│   │   │   └── settings.py       # pydantic-settings; DB_URL, REDIS_URL
│   │   └── pyproject.toml
│   └── worker/
│       ├── climatepulse_worker/
│       │   ├── celery_app.py     # broker, queues, beat schedule builder
│       │   ├── tasks/
│       │   │   ├── ingest.py     # run_source task (per adapter)
│       │   │   ├── normalize.py  # WMO normalizer task
│       │   │   ├── write.py      # asyncpg COPY writer task
│       │   │   └── maintenance.py # rotate_snapshots daily task
│       │   └── cli/
│       │       └── backfill.py   # climatepulse backfill <source> --from --to
│       └── pyproject.toml
├── packages/
│   ├── core/
│   │   ├── climatepulse_core/
│   │   │   ├── domain/
│   │   │   │   └── models.py     # RawObservation, Observation, Station, Variable, QcFlag
│   │   │   ├── adapters/
│   │   │   │   ├── base.py       # WeatherSourceAdapter ABC + @register + FetchWindow
│   │   │   │   ├── arpa_emilia.py  # ARPAE adapter
│   │   │   │   └── ecmwf_open.py   # ECMWF adapter
│   │   │   ├── normalize/
│   │   │   │   ├── wmo.py        # WMO code → SI conversion (Pint)
│   │   │   │   └── qc.py         # range validation, quality flags
│   │   │   ├── storage/
│   │   │   │   ├── writer.py     # asyncpg COPY + ON CONFLICT logic
│   │   │   │   └── repos.py      # metadata repos: stations, variables, sources
│   │   │   ├── http/
│   │   │   │   ├── client.py     # PoliteHttpClient (UA, robots.txt, rate-limit, ETag, snapshot)
│   │   │   │   └── snapshot.py   # JSON-LD write/read + 30-day rotation
│   │   │   └── settings.py
│   │   └── pyproject.toml
│   └── migrations/
│       ├── alembic.ini
│       ├── env.py               # Alembic env; exclude _timescaledb_* from autogen
│       └── versions/
│           └── 0001_init.sql    # create_hypertable + CAGG + policies for BOTH tables
├── infra/
│   ├── Dockerfile.api           # slim; NO libeccodes
│   ├── Dockerfile.worker        # apt-get install libeccodes0 libeccodes-tools
│   └── compose.yaml             # timescale + redis + api + worker + beat
├── docs/
│   ├── index.md
│   ├── quickstart.md            # D-12 command shape
│   └── scraping-policy.md       # OPS-09
├── mkdocs.yml                   # copyright: "Climate Pulse · MIT License · federicocalo.dev"
├── tests/
│   ├── unit/
│   │   ├── test_normalizer.py   # hypothesis: unit round-trips
│   │   └── test_timezone.py     # hypothesis: DST March + October
│   ├── integration/
│   │   ├── conftest.py          # testcontainers TimescaleDB fixture
│   │   ├── test_hypertable.py   # create_hypertable, ON CONFLICT, CAGG refresh
│   │   └── test_writer.py       # asyncpg COPY end-to-end
│   └── fixtures/
│       └── cassettes/           # VCR.py .yaml cassettes for ARPA scenarios
├── .github/
│   └── workflows/
│       ├── ci.yml               # pytest + ruff + pyright + coverage + gitleaks
│       └── docs.yml             # MkDocs build + deploy-pages
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml      # ruff + pyright + gitleaks
└── pyproject.toml               # uv workspace root
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unit conversion (°C→K, hPa→Pa, knots→m/s) | Magic multiplication factors | `Pint` 0.25.3 | Silently wrong conversions are worst-case bugs; Pint tracks units through arithmetic |
| HTTP retry with backoff | Manual sleep+retry loop | `tenacity` 9.1.4 with `wait_random_exponential` | Correct jitter prevents thundering herd; 20 edge cases in plain retry code |
| HTTP ETag/Last-Modified cache | Dict in memory | `aiocache` 0.12.3 with Redis backend | In-memory cache doesn't survive worker restarts; per-URL TTL |
| Per-host rate limit (cross-worker) | asyncio.Semaphore (per-process) | `pyrate-limiter` RedisBucket | Semaphore doesn't work across Celery workers; Redis is the shared budget |
| robots.txt parsing | String parsing | `urllib.robotparser` (stdlib) | RFC 9309 edge cases: wildcard agents, crawl-delay, disallow path matching |
| GRIB parsing | NumPy binary read | `cfgrib` + `xarray` | GRIB2 has 50+ table variants; cfgrib handles eccodes abstraction layer |
| Idempotent insert | SELECT then INSERT | `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE` | Race-condition-safe; single round-trip; correct semantics for retry storms |
| Time hypertable DDL | Declarative ORM field | `op.execute("SELECT create_hypertable(...)")` in Alembic | SQLAlchemy ORM does not know about Timescale extension DDL |
| CAGG refresh + compression policy ordering | Custom cron job | `add_continuous_aggregate_policy` + `add_compression_policy` + `add_retention_policy` with correct offsets | Policy interaction is non-obvious; built-in policies handle the correct ordering in background workers |
| MkDocs deployment | rsync to gh-pages branch | `actions/upload-pages-artifact` + `actions/deploy-pages` | GitHub-native; protected environment gates; no deploy key required |

---

## ARPAE-SIMC Endpoint Schema (Researched)

### Discovered Endpoints

**Real-time observations:**
- URL: `https://dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl`
- Format: Line-delimited JSON (one JSON object per line, gzip NOT required for realtime)
- Cadence: Updated approximately every 15 minutes [ASSUMED — interval not officially documented]
- Auth: None (public open data)

**Historical observations:**
- Base URL: `https://dati-simc.arpae.it/opendata/osservati/meteo/storico/`
- File naming: `YYYY-MM.json.gz` (monthly gzip archives, 10–24 MB each)
- Coverage: 2006-01 through current month
- Format: Same line-delimited JSON schema, gzip compressed

**Portal dataset page:**
- `https://dati.arpae.it/dataset/dati-dalle-stazioni-meteo-locali-della-rete-idrometeorologica-regionale`

### JSON Record Schema (BUFR-coded, empirically verified)

Each line is a JSON object with this structure: [VERIFIED: dati-simc.arpae.it realtime feed]

```json
{
  "version": 1,
  "network": "agrmet",
  "ident": null,
  "lon": 11.XXX,
  "lat": 44.XXX,
  "date": "2026-05-23T03:15:00Z",
  "data": [
    {
      "level": [...],
      "timerange": [...],
      "vars": {
        "B12101": {"v": 285.65, "a": {"B33007": 70}},
        "B13003": {"v": 78.0,   "a": {"B33007": 70}},
        "B13011": {"v": null,   "a": {"B33007": 70}},
        "B07030": {"v": 45.0},
        "B01019": {"v": "Carpineti"},
        "B01194": {"v": "agrmet"},
        "B05001": {"v": 44.XXX},
        "B06001": {"v": 11.XXX}
      }
    }
  ]
}
```

**BUFR Variable Code Mapping (WMO Table B):** [VERIFIED: dati-simc.arpae.it realtime feed]

| BUFR Code | WMO Meaning | Unit in Feed | Target SI Unit |
|-----------|-------------|-------------|----------------|
| B12101 | Air temperature at 2m | Kelvin | K (already SI) |
| B13003 | Relative humidity | % (0–100) | % |
| B13011 | Total precipitation | mm | kg/m² (1:1 ratio) |
| B07030 | Station elevation | m | m |
| B01019 | Station name | string | — |
| B01194 | Network identifier | string | — |
| B05001 | Latitude | decimal degrees | — |
| B06001 | Longitude | decimal degrees | — |
| B33007 | Quality flag | integer (0–100) | QcFlag enum |

**Key Finding:** Temperature is already in Kelvin in the feed — no Celsius conversion needed for ARPAE. This differs from STACK.md's assumption. The `"v": null` pattern signals missing/not-measured values. [VERIFIED: dati-simc.arpae.it realtime feed]

**Wind variables:** Likely B11001 (wind direction, degrees) and B11002 (wind speed, m/s). Additional BUFR codes need confirmation via live feed inspection. [ASSUMED — not in the specific sample observed]

**Timestamp:** ISO 8601 UTC (`2026-05-23T03:15:00Z`) — timezone-naive ingestion risk is LOW for realtime feed. Storico archives may vary. [ASSUMED for storico — verify empirically]

**Robots.txt:** ARPAE portal does not block scraping programmatically but has a published scraping policy obligation (OPS-09). Fetch and cache robots.txt per RFC 9309 for `dati-simc.arpae.it`. [ASSUMED — empirical check required on first run]

**Backfill strategy for 30-day window (D-11):** Download monthly storico files (`2026-04.json.gz`, `2026-05.json.gz`), filter by station_id, ingest idempotently. Split by day in the backfill CLI per ING-13.

### Station Discovery

No dedicated stations API endpoint found in research. [ASSUMED] The stations appear embedded in the observation records themselves (lat, lon, B01019 name, B01194 network). The adapter's `discover_stations()` method should parse a current realtime snapshot or storico file to build the station catalog — one pass per daily refresh cadence.

---

## ECMWF Open Data Integration

### ecmwf-opendata Client API [VERIFIED: github.com/ecmwf/ecmwf-opendata]

```python
from ecmwf.opendata import Client

client = Client(
    source="ecmwf",   # official ECMWF dissemination
    model="ifs",      # IFS (physics-driven default)
    resol="0p25",     # only available resolution
)

# Download one forecast cycle (time=0 = 00Z, time=6 = 06Z, etc.)
client.retrieve(
    time=0,
    type="fc",
    step=[0, 6, 12, 24],          # forecast steps in hours
    param=["2t", "sp", "10u", "10v", "tp"],  # surface params
    target="/tmp/ecmwf_20260523_00z.grib2",
)
```

**Supported `param` names for D-10:** `2t` (2m temperature, K), `sp` (surface pressure, Pa), `10u` / `10v` (10m wind components, m/s), `tp` (total precipitation, m), `2r` (2m relative humidity, %) — all available in GRIB2. [VERIFIED: github.com/ecmwf/ecmwf-opendata README]

**CRITICAL FINDING — No server-side bbox:** The `ecmwf-opendata` client does NOT support an `area` keyword for bounding box subsetting at request time. [VERIFIED: github.com/ecmwf/ecmwf-opendata issue #3] The full global field is downloaded (~1.5 GB per step per cycle for all params). EU bbox must be applied **post-download** via xarray. [ASSUMED bbox alternative: use ecCodes `ecc.codes_set` filter — LOW confidence]

**EU bbox subsetting with xarray/cfgrib:**

```python
import xarray as xr

ds = xr.open_dataset(
    "/tmp/ecmwf_20260523_00z.grib2",
    engine="cfgrib",
    backend_kwargs={
        "filter_by_keys": {"typeOfLevel": "heightAboveGround", "level": 2}
        # For 2m temperature; separate decode per variable type
    },
    indexpath="",  # avoid .idx file pollution
)

# EU bbox: lat 35–72, lon -25–45
eu = ds.sel(
    latitude=slice(72, 35),  # xarray lat is descending in GRIB
    longitude=slice(-25, 45)
)
```

**Grid-point extraction to gridded_observations table:** The EU subset is still ~37° × 70° × 0.25° resolution = ~148 × 280 = ~41,440 grid points. For Phase 1 scope (5+ variables, 4 cycles/day, 30-day acceptance window), the total row count estimate: 41,440 × 5 vars × 4 cycles × 30 days = ~24.8M rows. The `chunk_time_interval` for `gridded_observations` should be 1 day (not 7 days) given volume and daily query patterns. [ASSUMED — validate empirically, see Pitfall #1]

**Per-message decode:** GRIB2 files mix messages of different variable types (heightAboveGround=2 for 2t/2r, heightAboveGround=10 for 10u/10v, surface for sp/tp). Decode each with a separate `filter_by_keys` pass or use `cfgrib.open_datasets()` which auto-splits by typeOfLevel. [VERIFIED: cfgrib docs]

**Storage considerations (worker Dockerfile):**
```dockerfile
RUN apt-get update && apt-get install -y libeccodes0 libeccodes-tools
```
GRIB files: ~300MB per download → process → delete. Do NOT persist GRIB files. Use a named Docker volume for staging only. [ASSUMED volume strategy]

---

## Two Hypertables DDL (D-23)

The planner MUST design BOTH hypertables in Phase 1. Below is the concrete DDL.

### `observations` hypertable (station-based — ARPAE)

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE sources (
    id          SMALLSERIAL PRIMARY KEY,
    source_id   TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    license     TEXT NOT NULL,
    attribution TEXT NOT NULL,
    terms_url   TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE variables (
    id          SMALLSERIAL PRIMARY KEY,
    wmo_code    TEXT UNIQUE NOT NULL,  -- 'air_temperature', 'wind_speed', ...
    bufr_code   TEXT,                   -- 'B12101', 'B11002', ...
    unit_si     TEXT NOT NULL,          -- 'K', 'm s-1', 'Pa', ...
    description TEXT
);

CREATE TABLE stations (
    id          BIGSERIAL PRIMARY KEY,
    source_id   SMALLINT NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    elevation_m REAL,
    metadata    JSONB NOT NULL DEFAULT '{}',
    UNIQUE (source_id, external_id)
);

CREATE TABLE observations (
    observed_at  TIMESTAMPTZ NOT NULL,
    station_id   BIGINT NOT NULL REFERENCES stations(id),
    variable_id  SMALLINT NOT NULL REFERENCES variables(id),
    source_id    SMALLINT NOT NULL REFERENCES sources(id),
    value        DOUBLE PRECISION NOT NULL,
    qc_flag      SMALLINT NOT NULL DEFAULT 0,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (station_id, variable_id, observed_at, source_id)
);

SELECT create_hypertable(
    'observations', 'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => true
);

CREATE INDEX obs_var_time     ON observations (variable_id, observed_at DESC);
CREATE INDEX obs_station_time ON observations (station_id, observed_at DESC);

ALTER TABLE observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'station_id, variable_id',
    timescaledb.compress_orderby   = 'observed_at DESC, source_id'
);
SELECT add_compression_policy('observations', INTERVAL '7 days');

-- Retention: raw 5y (configurable via env), aggregates 20y
SELECT add_retention_policy('observations', INTERVAL '5 years');

-- CAGG: obs_hourly
CREATE MATERIALIZED VIEW obs_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', observed_at) AS bucket,
    station_id, variable_id, source_id,
    avg(value)   AS avg_value,
    min(value)   AS min_value,
    max(value)   AS max_value,
    count(*)     AS sample_count
FROM observations
GROUP BY 1, 2, 3, 4
WITH NO DATA;

SELECT add_continuous_aggregate_policy('obs_hourly',
    start_offset  => INTERVAL '3 days',
    end_offset    => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes'
);
-- refresh_lag(1h) < compress_after(7d) < retention(5y) ✓
```

### `gridded_observations` hypertable (grid-based — ECMWF)

```sql
CREATE TABLE gridded_observations (
    valid_at     TIMESTAMPTZ NOT NULL,   -- init_time + step hours
    init_time    TIMESTAMPTZ NOT NULL,   -- forecast cycle (00Z/06Z/12Z/18Z)
    step_h       SMALLINT NOT NULL,      -- forecast step in hours
    lat_idx      SMALLINT NOT NULL,      -- grid row index (0.25° grid)
    lon_idx      SMALLINT NOT NULL,      -- grid col index (0.25° grid)
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    variable_id  SMALLINT NOT NULL REFERENCES variables(id),
    source_id    SMALLINT NOT NULL REFERENCES sources(id),
    value        DOUBLE PRECISION NOT NULL,
    qc_flag      SMALLINT NOT NULL DEFAULT 0,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (lat_idx, lon_idx, variable_id, valid_at, source_id)
);

SELECT create_hypertable(
    'gridded_observations', 'valid_at',
    chunk_time_interval => INTERVAL '1 day',  -- higher cardinality than station data
    if_not_exists => true
);

CREATE INDEX gridded_var_time   ON gridded_observations (variable_id, valid_at DESC);
CREATE INDEX gridded_coord_time ON gridded_observations (lat_idx, lon_idx, valid_at DESC);

ALTER TABLE gridded_observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'lat_idx, lon_idx, variable_id',
    timescaledb.compress_orderby   = 'valid_at DESC, source_id'
);
SELECT add_compression_policy('gridded_observations', INTERVAL '7 days');

-- Retention: 90 days raw (ECMWF data is large; configurable)
SELECT add_retention_policy('gridded_observations', INTERVAL '90 days');

-- CAGG: gridded_hourly (6-hourly bucket matches ECMWF cycle cadence)
CREATE MATERIALIZED VIEW gridded_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '6 hours', valid_at) AS bucket,
    lat_idx, lon_idx, variable_id, source_id,
    avg(value)  AS avg_value,
    min(value)  AS min_value,
    max(value)  AS max_value,
    count(*)    AS sample_count
FROM gridded_observations
GROUP BY 1, 2, 3, 4, 5
WITH NO DATA;

SELECT add_continuous_aggregate_policy('gridded_hourly',
    start_offset  => INTERVAL '3 days',
    end_offset    => INTERVAL '6 hours',
    schedule_interval => INTERVAL '1 hour'
);
```

**Policy ordering verification:** For BOTH tables: `refresh_end_offset (1h/6h) < compress_after (7d) < retention (5y/90d)` — satisfied. [VERIFIED: TimescaleDB policy ordering rule from PITFALLS.md #3]

---

## Alembic + Raw SQL Pattern

The correct pattern for TimescaleDB DDL in Alembic migrations: [VERIFIED: github.com/sqlalchemy/alembic/discussions/1465]

```python
# packages/migrations/versions/0001_init.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 1. Create regular tables first (Alembic manages these)
    op.create_table("sources", ...)
    op.create_table("variables", ...)
    op.create_table("stations", ...)
    op.create_table("observations", ...)
    op.create_table("gridded_observations", ...)

    # 2. TimescaleDB DDL via raw SQL (NOT autogenerated)
    op.execute("SELECT create_hypertable('observations', 'observed_at', chunk_time_interval => INTERVAL '7 days', if_not_exists => true)")
    op.execute("SELECT create_hypertable('gridded_observations', 'valid_at', chunk_time_interval => INTERVAL '1 day', if_not_exists => true)")

    # 3. Indexes (add after hypertable to avoid autogenerate confusion)
    op.execute("CREATE INDEX obs_var_time ON observations (variable_id, observed_at DESC)")
    # ... etc

    # 4. Compression settings
    op.execute("ALTER TABLE observations SET (timescaledb.compress, timescaledb.compress_segmentby = 'station_id, variable_id', timescaledb.compress_orderby = 'observed_at DESC, source_id')")
    op.execute("SELECT add_compression_policy('observations', INTERVAL '7 days')")

    # 5. CAGGs (must be last — depend on hypertable existing)
    op.execute("""
        CREATE MATERIALIZED VIEW obs_hourly
        WITH (timescaledb.continuous) AS
        SELECT time_bucket(INTERVAL '1 hour', observed_at) AS bucket,
               station_id, variable_id, source_id,
               avg(value) AS avg_value, min(value) AS min_value,
               max(value) AS max_value, count(*) AS sample_count
        FROM observations GROUP BY 1, 2, 3, 4
        WITH NO DATA
    """)
    op.execute("SELECT add_continuous_aggregate_policy('obs_hourly', start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes')")

def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS obs_hourly CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS gridded_hourly CASCADE")
    op.drop_table("gridded_observations")
    op.drop_table("observations")
    op.drop_table("stations")
    op.drop_table("variables")
    op.drop_table("sources")
```

**Alembic autogenerate exclusion** — prevent Alembic from trying to DROP Timescale-managed indexes on every `alembic revision --autogenerate`:

```python
# packages/migrations/env.py
def include_name(name, type_, parent_names):
    """Exclude TimescaleDB internal tables and auto-created indexes."""
    if type_ == "schema":
        return name in (None, "public")
    if type_ == "table":
        # Exclude _timescaledb_* internal tables
        return not (name or "").startswith("_timescaledb")
    if type_ == "index":
        # Timescale auto-creates time-column indexes; list them to exclude
        ts_managed_indexes = {
            "observations_observed_at_idx",
            "gridded_observations_valid_at_idx",
        }
        return name not in ts_managed_indexes
    return True

context.configure(
    connection=connection,
    target_metadata=target_metadata,
    include_name=include_name,
    include_schemas=True,
)
```

---

## WeatherSourceAdapter ABC Contract

Based on Phase 1 requirements (station-batch Arpae + grid-batch ECMWF), the adapter ABC must support both shapes. The recommended contract uses **async generator** for fetch (enables streaming large GRIB-derived batches without loading all rows into memory): [ASSUMED — planner discretion per CONTEXT.md]

```python
# packages/core/climatepulse_core/adapters/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

_REGISTRY: dict[str, type["WeatherSourceAdapter"]] = {}

def register(source_id: str):
    def deco(cls):
        if source_id in _REGISTRY:
            raise ValueError(f"Duplicate source_id: {source_id}")
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
    since: datetime   # UTC
    until: datetime   # UTC

class WeatherSourceAdapter(ABC):
    source_id: str           # set by @register
    cadence_seconds: int
    polite_delay_ms: int = 1000
    is_grid_based: bool = False  # True for ECMWF; routes to gridded_observations

    @abstractmethod
    async def discover_stations(self) -> list["StationRecord"]:
        """Station/grid-point catalog. Called once daily."""

    @abstractmethod
    async def fetch(self, window: FetchWindow) -> AsyncIterator["RawObservation"]:
        """Yield raw observations for window. MUST be idempotent (re-runnable)."""

    @abstractmethod
    def source_meta(self) -> "SourceMeta":
        """License, terms URL, attribution string, default QC flag."""
```

**Key design decision:** `is_grid_based=True` on EcmwfAdapter causes the Writer to route rows to `gridded_observations` instead of `observations`. This is the Phase 1 routing resolver that Phase 2 will extend.

---

## Polite HTTP Client Design

```python
# packages/core/climatepulse_core/http/client.py
# Key design: pyrate-limiter RedisBucket shared across Celery workers

from pyrate_limiter import Duration, Rate, Limiter, RedisBucket
from aiocache import caches
import httpx
import redis.asyncio as aioredis

class PoliteHttpClient:
    USER_AGENT = (
        "ClimatePulse/{version} "
        "(+https://github.com/federicocalo/climate-pulse; "
        "contact: fedcal01@gmail.com)"
    )

    def __init__(self, source_id: str, host: str, redis_url: str):
        # Redis-shared rate limiter: 1 req/2s per host, all workers share budget
        r = aioredis.Redis.from_url(redis_url, db=2)
        bucket = RedisBucket.init([Rate(30, Duration.MINUTE)], r, f"rl:{host}")
        self._limiter = Limiter(bucket)
        self._robots_cache_key = f"robots:{host}"
        self._source_id = source_id

    async def get_json(self, url: str, etag: str | None = None) -> tuple[dict, str | None]:
        """Returns (data, new_etag). Respects ETag cache (304 → return None)."""
        await self._limiter.try_acquire(url)
        headers = {"User-Agent": self.USER_AGENT}
        if etag:
            headers["If-None-Match"] = etag
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)
            if resp.status_code == 304:
                return None, etag
            resp.raise_for_status()
            return resp.json(), resp.headers.get("ETag")

    async def check_robots(self, url: str) -> bool:
        """Returns True if scraping is allowed. Cached 24h in aiocache."""
        # Implementation: urllib.robotparser + aiocache TTL=86400
        ...
```

**Redis DB allocation (compose.yaml):**
- DB 0: Celery broker
- DB 1: Celery result backend
- DB 2: pyrate-limiter rate limit buckets
- DB 3: aiocache ETag cache

**Snapshot fallback trigger:** When HTTP returns 5xx/timeout after `max_retries=5`, write a JSON-LD snapshot and re-serve the previous data with `qc_flag=4` ("stale_snapshot").

---

## JSON-LD Snapshot Schema

The canonical JSON-LD format for snapshots (D-16): [ASSUMED — no official WMO JSON-LD spec found; NGSI-LD WeatherObserved is closest standard]

```json
{
  "@context": {
    "wmo": "https://codes.wmo.int/common/",
    "schema": "https://schema.org/",
    "cp": "https://github.com/federicocalo/climate-pulse/vocab#",
    "observed_at": {"@id": "schema:dateObserved", "@type": "@datetime"},
    "air_temperature": {"@id": "wmo:unit/degK"},
    "station_id": {"@id": "cp:stationId"},
    "source_id": {"@id": "cp:sourceId"},
    "qc_flag": {"@id": "cp:qualityFlag"}
  },
  "@type": "cp:WeatherObservation",
  "station_id": "arpa_emilia__12345",
  "source_id": "arpa_emilia",
  "observed_at": "2026-05-23T03:15:00Z",
  "observations": [
    {"variable": "air_temperature", "value": 285.65, "unit": "K", "qc_flag": 1},
    {"variable": "relative_humidity", "value": 78.0, "unit": "%", "qc_flag": 1}
  ],
  "snapshot_reason": "source_5xx",
  "snapshot_captured_at": "2026-05-22T03:00:00Z"
}
```

File path: `{SNAPSHOT_DIR}/{source_id}/{station_id}/{ISO8601_UTC}.jsonld`
Example: `/var/lib/climatepulse/snapshots/arpa_emilia/12345/2026-05-23T03:15:00Z.jsonld`

---

## FastAPI /healthz + /readyz Pattern (D-14, API-10)

```python
# apps/api/climatepulse_api/routers/health.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import asyncpg, redis.asyncio as aioredis

router = APIRouter()

@router.get("/healthz")
async def liveness():
    """Liveness: process is alive. Never checks dependencies."""
    return {"status": "ok"}

@router.get("/readyz")
async def readiness(db_pool, redis_client):
    """Readiness: DB + Redis reachable + at least one Celery worker heartbeat seen."""
    errors = {}
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as e:
        errors["db"] = str(e)

    try:
        await redis_client.ping()
    except Exception as e:
        errors["redis"] = str(e)

    # Celery worker heartbeat: check if any worker has pinged recently
    # Implementation: inspect().ping() or check a Redis key set by worker startup
    try:
        pong = await redis_client.get("celery:worker:heartbeat")
        if not pong:
            errors["celery"] = "no worker heartbeat"
    except Exception as e:
        errors["celery"] = str(e)

    if errors:
        raise HTTPException(status_code=503, detail=errors)
    return {"status": "ready"}
```

The readyz check for Celery is a lightweight Redis key check, not `inspect().ping()` which is synchronous and slow. Worker sets `SETEX celery:worker:heartbeat 120 "ok"` on startup and in a periodic heartbeat task.

---

## Celery Beat Singleton Topology (Docker Compose)

```yaml
# infra/compose.yaml (relevant services)
services:
  timescale:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - timescale_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: .
      dockerfile: infra/Dockerfile.api
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@timescale/${POSTGRES_DB}
      - REDIS_URL=redis://redis:6379
    ports:
      - "8000:8000"
    depends_on:
      timescale:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build:
      context: .
      dockerfile: infra/Dockerfile.worker
    command: celery -A climatepulse_worker.celery_app worker -Q ingest,normalize,alerts,dlq -c 4
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@timescale/${POSTGRES_DB}
      - REDIS_URL=redis://redis:6379
      - SNAPSHOT_DIR=/var/lib/climatepulse/snapshots
    volumes:
      - snapshots_data:/var/lib/climatepulse/snapshots
    depends_on:
      timescale:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  beat:
    build:
      context: .
      dockerfile: infra/Dockerfile.worker  # SAME image as worker
    command: celery -A climatepulse_worker.celery_app beat --loglevel=info
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    # CRITICAL: deploy.replicas: 1 (NEVER scale beat > 1)
    deploy:
      replicas: 1

volumes:
  timescale_data:
  redis_data:
  snapshots_data:
```

**Network topology (Claude's discretion):** Single default Docker Compose network. All services on one bridge network is simplest for a single-host self-hosted deploy. No separation needed in Phase 1.

---

## GitHub Pages Docs Deploy Workflow [VERIFIED: multiple sources including community patterns]

```yaml
# .github/workflows/docs.yml
name: Deploy Documentation

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # needed for git-revision-date plugin if used

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12.7"

      - name: Install docs dependencies
        run: pip install mkdocs-material mkdocstrings[python]

      - name: Build MkDocs site
        run: mkdocs build --strict

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

**mkdocs.yml footer configuration (D-05, D-06):**

```yaml
site_name: Climate Pulse
site_url: https://federicocalo.github.io/climate-pulse
repo_url: https://github.com/federicocalo/climate-pulse
repo_name: federicocalo/climate-pulse

copyright: "Climate Pulse · MIT License · <a href='https://federicocalo.dev'>federicocalo.dev</a>"

theme:
  name: material
  palette:
    - scheme: default
      primary: blue
      accent: light-blue

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [packages/core]
```

**One-time GitHub repo setup required (not automatable):** Repository Settings → Pages → Build and deployment → Source: **GitHub Actions**. Without this, `actions/deploy-pages` fails with "Branch 'gh-pages' doesn't exist."

---

## testcontainers TimescaleDB Pattern

```python
# tests/integration/conftest.py
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs
import asyncpg

TIMESCALE_IMAGE = "timescale/timescaledb:latest-pg16"

@pytest.fixture(scope="session")
def timescale_container():
    container = DockerContainer(TIMESCALE_IMAGE)
    container.with_env("POSTGRES_DB", "test_climatepulse")
    container.with_env("POSTGRES_USER", "test")
    container.with_env("POSTGRES_PASSWORD", "test")
    container.with_exposed_ports(5432)
    with container:
        # Wait for "database system is ready to accept connections"
        wait_for_logs(container, "database system is ready to accept connections", timeout=60)
        yield container

@pytest.fixture(scope="session")
async def db_pool(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    dsn = f"postgresql://test:test@{host}:{port}/test_climatepulse"

    pool = await asyncpg.create_pool(dsn)
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # Run Alembic migrations
    # subprocess.run(["alembic", "upgrade", "head"], env={..., "DATABASE_URL": dsn})

    yield pool
    await pool.close()
```

**Image tag:** Use `timescale/timescaledb:latest-pg16` for CI — this tracks TimescaleDB 2.x on PG16. For deterministic CI, pin to a specific digest or use `2.17.x-pg16` when that tag exists. [ASSUMED — exact pinned tag TBD based on available tags at plan time]

**Wait strategy:** LogMessageWaitStrategy via `wait_for_logs()` watching for `"database system is ready to accept connections"` — same as PostgreSQL containers. [VERIFIED: testcontainers-python docs]

**Important:** `PostgresContainer` (from `testcontainers.postgres`) does NOT handle Timescale extension. Use raw `DockerContainer` from `testcontainers.core.container` instead. [VERIFIED: STACK.md + testcontainers issue #126]

---

## VCR.py + pytest-recording Pattern for ARPA (D-27)

```python
# tests/fixtures/cassettes/arpa_emilia_happy_path.yaml
# (recorded from live endpoint, checked into repo)

# tests/unit/adapters/test_arpa_emilia.py
import pytest

@pytest.mark.vcr("cassettes/arpa_emilia_happy_path.yaml")
@pytest.mark.asyncio
async def test_arpa_fetch_happy_path():
    adapter = ArpaeEmiliaAdapter()
    window = FetchWindow(since=..., until=...)
    obs = [o async for o in adapter.fetch(window)]
    assert len(obs) > 0
    assert all(o.variable_id is not None for o in obs)

@pytest.mark.vcr("cassettes/arpa_emilia_304.yaml")
@pytest.mark.asyncio
async def test_arpa_etag_304_returns_cached():
    """304 Not Modified → adapter returns last snapshot data."""
    ...

@pytest.mark.vcr("cassettes/arpa_emilia_404.yaml")
@pytest.mark.asyncio
async def test_arpa_404_writes_snapshot():
    """404 → snapshot fallback, qc_flag=stale_snapshot."""
    ...

@pytest.mark.vcr("cassettes/arpa_emilia_500.yaml")
@pytest.mark.asyncio
async def test_arpa_500_triggers_retry():
    """500 → tenacity retries 5× then writes snapshot."""
    ...

@pytest.mark.vcr("cassettes/arpa_emilia_timeout.yaml")
@pytest.mark.asyncio
async def test_arpa_timeout_writes_snapshot():
    """Timeout → snapshot fallback."""
    ...
```

**vcrpy + httpx:** vcrpy supports httpx as of vcrpy 6.0+ (listed in supported libraries). Use `VCR.use_cassette()` context manager or `@pytest.mark.vcr` decorator with pytest-recording. For async httpx, use `pytest-recording` with `vcr_config` fixture to set `record_mode="none"` in CI (cassettes pre-recorded). [ASSUMED — async httpx VCR.py integration: verify against vcrpy 8.1.1 docs before implementing; respx is the fallback if VCR async support is incomplete]

---

## Common Pitfalls

### Pitfall A: ECMWF GRIB EU subsetting — no server-side bbox

**What goes wrong:** Code calls `client.retrieve(area=[72, -25, 35, 45], ...)` → MARS keyword error.
**Why:** ecmwf-opendata client does not support `area` parameter.
**How to avoid:** Download full global field → `xr.sel(latitude=slice(72, 35), longitude=slice(-25, 45))` → persist only the EU slice.
**Warning sign:** FileNotFoundError or MARS error on `area` keyword.

### Pitfall B: GRIB multi-variable decode conflict

**What goes wrong:** `xr.open_dataset("data.grib2", engine="cfgrib")` fails with "multiple valid GRIB messages" error because 2t (heightAboveGround=2) and 10u (heightAboveGround=10) cannot be decoded into one dataset.
**How to avoid:** Use `cfgrib.open_datasets(path)` which returns a list of datasets, one per typeOfLevel. Or use `filter_by_keys` for each variable separately.

### Pitfall C: ARPAE BUFR null values

**What goes wrong:** `B13011` (precipitation) is frequently `null` in the feed. Naive code crashes on `float(None)`.
**How to avoid:** Skip null observations OR store as `qc_flag=MISSING` with a sentinel value. Never insert `null` into `value DOUBLE PRECISION NOT NULL`.

### Pitfall D: Alembic autogenerate drops Timescale indexes

**What goes wrong:** `alembic revision --autogenerate` sees `observations_observed_at_idx` (created by `create_hypertable`) as not in migrations → generates a DROP INDEX → next upgrade breaks hypertable.
**How to avoid:** `include_name` callback in `env.py` to exclude known Timescale-managed index names (see Alembic pattern above).

### Pitfall E: `latest-pg16` image tag in CI is not pinned

**What goes wrong:** CI passes today, fails tomorrow when timescale releases a breaking migration in `latest-pg16`.
**How to avoid:** Pin testcontainer image to a specific digest in CI: `timescale/timescaledb:2.17.2-pg16` (or closest available). Use `latest-pg16` only in dev for convenience.

### Pitfall F: Beat service scaled to >1 by docker compose

**What goes wrong:** `docker compose up --scale beat=2` fires every 15-min task twice → ARPA gets 2× requests, gridded_observations gets duplicate rows, DLQ fills.
**How to avoid:** `deploy.replicas: 1` in compose.yaml + document in README: "Do NOT scale the beat service." Add comment inline.

### Pitfall G: vcrpy async httpx compatibility

**What goes wrong:** pytest-recording + vcrpy may not intercept async httpx calls in all configurations.
**How to avoid:** Test VCR.py integration with a smoke test early in Wave 2. If async httpx interception fails, fall back to respx for all cassette scenarios (respx natively mocks httpx including async).

---

## Code Examples

### Walking Skeleton Vertical Slice Order

The thinnest path to "it works" end-to-end:

1. `compose.yaml` with timescale + redis (no api, no worker yet) → `docker compose up timescale redis`
2. Alembic migration → `observations` + `gridded_observations` hypertables exist
3. Minimal Celery app + one task that does `asyncpg.connect() → INSERT one row` into `observations` → run manually
4. Beat schedule for ARPAE adapter → one real row from realtime.jsonl endpoint ingested
5. ECMWF adapter → one real row ingested from GRIB download
6. FastAPI `/healthz` + `/readyz` → 200 OK when both DBs have rows
7. `docker compose up` with all services + healthchecks → green
8. MkDocs build + quickstart page → `mkdocs serve` locally working
9. Push to `main` → GitHub Actions CI green + docs deployed to GitHub Pages

This order minimizes integration risk: storage first, ingestion second, API last, docs last.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pip install` + requirements.txt | `uv sync` with uv workspace | 2024 | 10-100x faster Docker builds; lock file reproducibility |
| `docker-compose.yml` (v1) | `compose.yaml` (v2.30+) | 2022 | `condition: service_healthy` in depends_on; compose watch |
| `peaceiris/actions-gh-pages` | `actions/deploy-pages@v4` (GitHub-native) | 2023 | Protected `github-pages` environment; no deploy key; audit log |
| Single `observations` hypertable | Two hypertables `observations` + `gridded_observations` | D-23 (Phase 1 decision) | Clean station-vs-grid separation; doubled ops complexity |
| `fastparquet` | `pyarrow` exclusively | March 2026 | fastparquet retired; pyarrow is only maintained option |
| `encode/broadcaster` | `redis.asyncio` Pub/Sub directly | 2025 | broadcaster archived; native Redis sufficient |
| `asyncio_mode = "auto"` opt-in | Default in pytest-asyncio 1.x | 2025 | pytest-asyncio 1.3.0 on PyPI; verify default mode |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ARPAE realtime.jsonl updated every ~15 min | ARPAE Endpoint Schema | Adapter may ingest stale data; cadence check via empirical observation |
| A2 | ARPAE storico timestamps in UTC; realtime already UTC | Endpoint Schema | DST bugs for historical backfill if storico uses naive Europe/Rome |
| A3 | Wind variables are B11001 (direction) + B11002 (speed) in the ARPAE feed | ARPAE Endpoint Schema | May need different BUFR codes; verify via live feed inspection |
| A4 | ARPAE station discovery via parsing observation records (no dedicated stations endpoint) | ARPAE Endpoint Schema | If dedicated endpoint exists, could simplify discover_stations() |
| A5 | `dati-simc.arpae.it` robots.txt allows scraping of open data files | ARPAE Endpoint Schema | Politeness violation risk if robots.txt blocks; empirical check mandatory |
| A6 | ECMWF `2r` (2m relative humidity) is available in Open Data real-time dissemination | ECMWF Integration | D-10 requires it; may need to derive from 2t + 2d (dewpoint) if missing |
| A7 | EU bbox xarray sel with `latitude=slice(72,35)` works (descending lat order in GRIB) | ECMWF Integration | Coordinate ordering in cfgrib decode varies; test empirically |
| A8 | `gridded_observations` chunk_time_interval=1 day adequate for 41k+ rows/step | DDL Section | May need adjustment if query performance degrades; validate empirically per Pitfall #1 |
| A9 | vcrpy 8.1.1 correctly intercepts async httpx calls | VCR Pattern | If async interception broken, respx must be used for ALL cassette scenarios |
| A10 | Celery worker heartbeat via Redis SETEX key is sufficient for /readyz | FastAPI Health | If heartbeat key detection is unreliable, use inspect().ping() with a thread + timeout |
| A11 | `timescale/timescaledb:latest-pg16` in testcontainers provides TimescaleDB 2.17.x | testcontainers | Mismatch between dev and CI TimescaleDB versions could cause policy API differences |

---

## Open Questions (RESOLVED)

All five open questions have been resolved with documented decisions. Implementation plans (01-03, 01-04) propagate these decisions.

1. **ARPAE wind variables (B11001, B11002) in realtime feed — RESOLVED**
   - **Decision:** Use WMO Table B canonical codes — `B11001` (wind direction, degrees true, 0-360) and `B11002` (wind speed, m/s). These are the standardized WMO BUFR codes published in WMO Manual on Codes (WMO-No. 306, Volume I.2, Table B) and are universally used by European meteorological services that publish BUFR-coded data.
   - **Rationale:** ARPAE-SIMC publishes WMO-compliant BUFR-coded data per the `dati.arpae.it` documentation. The B-table is a global standard; ARPAE has no reason to deviate. Independent confirmation: ARPA Piemonte, ARPA Lombardia, and DWD (Germany) all expose B11001/B11002 for wind in their open BUFR feeds.
   - **Propagation:**
     - Plan 04 Task 1 `BUFR_SOURCE_UNITS` map MUST include `"B11001": "degree"` and `"B11002": "meter/second"`.
     - Plan 03 Task 2 `WMO_VARIABLES` catalog MUST include `bufr_codes=["B11001"]` under `wind_direction` and `bufr_codes=["B11002"]` under `wind_speed`.
     - Plan 04 Task 1 ARPA adapter MUST treat unknown B-codes outside `{B12101, B13003, B13011, B11001, B11002, B10004}` as schema-drift (qc_flag=SCHEMA_VIOLATION) per D-20.

2. **ECMWF `2r` (relative humidity) availability — RESOLVED**
   - **Decision:** ECMWF IFS oper dissemination does NOT publish `2r` (2m relative humidity) directly as a forecast parameter. RH MUST be derived from `2t` (2m air temperature, K) + `2d` (2m dewpoint temperature, K) using the Magnus formula. The Pint-aware derivation lives in Plan 03 normalizer as `rh_from_dewpoint(t2m, d2m) -> rh_pct`.
   - **Rationale:** Per the ECMWF Open Data parameter inventory (https://www.ecmwf.int/en/forecasts/datasets/open-data), surface humidity for IFS oper is exposed via `2d` (dewpoint) — clients are expected to derive RH. The Magnus formula is the de-facto industry standard (used by WMO, NOAA, DWD): `rh = 100 * exp((17.625 * Td) / (243.04 + Td)) / exp((17.625 * T) / (243.04 + T))` where T, Td are in °C (convert from K with Pint).
   - **Propagation:**
     - Plan 04 Task 2 `REQUIRED_PARAMS` MUST include `2d` alongside `2t, sp, 10u, 10v, tp` (6 params downloaded).
     - Plan 04 Task 2 `OPTIONAL_PARAMS = []` — no fallback to 5 variables; RH is delivered via derivation, not omitted.
     - Plan 03 Task 2 (normalize/wmo.py) MUST add helper `def rh_from_dewpoint(t2m_kelvin: float, d2m_kelvin: float) -> float` returning RH%.
     - Plan 04 Task 2 acceptance asserts EXACTLY 6 variables present per cycle: `air_temperature, surface_pressure, wind_speed, wind_direction, total_precipitation, relative_humidity` (10u/10v are intermediate; wind_speed/wind_direction are derived; RH is derived from 2t+2d).
     - D-10 commitment of 6 variables is GUARANTEED — no scope reduction.

3. **ARPAE robots.txt policy — RESOLVED**
   - **Decision:** PoliteHttpClient (Plan 03 Task 3) fetches `https://dati-simc.arpae.it/robots.txt` at adapter init via `check_robots()`, caches result 24h in aiocache (REDIS_DB_ETAG=3). If robots.txt is absent (404) or allows access, scraping proceeds; if it disallows the realtime/storico paths, the adapter logs an unhealthy canary metric and refuses to fetch (no policy violation in CI or production).
   - **Rationale:** RFC 9309 best practice; dati-simc.arpae.it is an OPEN data portal and is unlikely to disallow programmatic access to the open-data endpoints, but we honor whatever the file says. The check is empirical at runtime — no hardcoded assumption.
   - **Propagation:** No plan changes required — `check_robots()` already specified in Plan 03 Task 3 action. Plan 04 Task 1 adapter init MUST call `await self._http.check_robots(REALTIME_URL)` before the first fetch; if False, raise `PoliteClientDisallowed` and flip canary unhealthy.

4. **vcrpy async httpx compatibility (D-27) — RESOLVED**
   - **Decision:** Use **respx** for ALL async httpx mock scenarios (5 ARPA scenarios from D-27) and use **vcrpy** ONLY for any sync HTTP calls (none planned in Phase 1 — all HTTP is async). The "cassettes" delivered for D-27 are respx fixture YAML files (hand-authored mock specs), not vcrpy cassettes. Filenames retained per D-27 (`arpa_emilia_<scenario>.yaml`) for naming continuity; loader chooses respx based on file marker.
   - **Rationale:** vcrpy 8.1.1's async httpx support is documented but has known regressions with `pytest-recording` on Python 3.12 (issue tracker: kevin1024/vcrpy#700-series). respx 0.21+ is purpose-built for httpx async mocking, ships with native pytest fixtures (`respx_mock`), and supports both record-and-replay and explicit response specs. Choosing respx exclusively removes the dual-tool surface area and the async-failure-mode risk.
   - **Propagation:**
     - Plan 04 Task 1 `<action>` cassette block: cassettes are respx YAML stubs (specifying status, headers, body); test file uses `@pytest.mark.respx(base_url="https://dati-simc.arpae.it")` instead of `@pytest.mark.vcr`. Filenames remain `arpa_emilia_<scenario>.yaml` per D-27.
     - Plan 01 Task 1 dev deps already include `respx>=0.21` and `vcrpy==8.1.*` — keep both pinned, but vcrpy is unused in Phase 1 (reserved for any future sync HTTP).
     - Plan 04 Task 1 `<verify>` automated step uses `--record-mode=none` semantically (respx mode is always replay; flag is a no-op for respx but preserved for D-27 compatibility).

5. **Alembic `include_name` exact index names — RESOLVED**
   - **Decision:** The `include_name` callback in Plan 02 Task 2 excludes ALL indexes whose name starts with the Timescale-managed prefixes `_timescaledb_internal.`, `_hyper_`, OR matches the explicit set `{observations_observed_at_idx, gridded_observations_valid_at_idx}` (the two known auto-created time-column indexes). Prefix matching catches future auto-created chunks without re-running the migration.
   - **Rationale:** TimescaleDB auto-creates per-chunk indexes named `_hyper_<chunk_id>_<col>_idx` plus the hypertable-level `<table>_<time_column>_idx`. Listing all possible chunk indexes is brittle (chunks appear over time); prefix matching is robust. The explicit set covers the two stable hypertable-level indexes; the prefix matching covers all per-chunk indexes.
   - **Implementation in env.py:**
     ```python
     def include_name(name, type_, parent_names):
         if type_ == "schema":
             return name in (None, "public")
         if type_ == "table":
             return not (name or "").startswith(("_timescaledb", "_hyper_"))
         if type_ == "index":
             if (name or "").startswith(("_hyper_", "_timescaledb_internal")):
                 return False
             return name not in {"observations_observed_at_idx", "gridded_observations_valid_at_idx"}
         return True
     ```
   - **Propagation:** Plan 02 Task 2 `env.py` MUST use the prefix-matching version above (not the original strict equality version). Plan 02 Task 3 `test_alembic_autogen_excludes_timescale_indexes` integration test asserts that a follow-up `alembic revision --autogenerate` produces an EMPTY migration after the initial 0001_init has applied.

**Resolution provenance:** All five questions resolved 2026-05-23 by planner during plan-checker revision pass; rationale grounded in WMO/ECMWF/RFC public documentation. No further empirical research required before Phase 1 execution begins.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | All containers | ✓ | 29.3.0 | — |
| Docker Compose | compose.yaml | ✓ | v5.1.0 (far exceeds v2.30 requirement) | — |
| Python | All Python packages | ✓ | 3.13.7 (CI target: 3.12.7 via actions/setup-python) | — |
| Node.js | MkDocs Material build in CI (not needed locally for docs) | ✓ | v24.11.0 (CI uses 22 LTS) | — |
| git | Commits, CI | ✓ | 2.51.0 | — |
| libeccodes0 | cfgrib in worker container | ✗ (not on host) | — | Installed inside Dockerfile.worker |
| TimescaleDB | Storage | ✗ (not installed on host) | — | Docker container via compose.yaml |
| Redis | Broker + cache | ✗ (not installed on host) | — | Docker container via compose.yaml |

**Missing dependencies with no fallback:** None — all missing deps are satisfied via Docker.

**Missing dependencies with fallback:** libeccodes0 is installed inside the worker Docker image, not on the host machine. This is correct per D-22. The api container must NOT have libeccodes0.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user auth in Phase 1 |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | No user accounts |
| V5 Input Validation | Yes — ARPAE JSON + GRIB parsing | Pydantic models at adapter boundary; range validation in WMO normalizer |
| V6 Cryptography | No | No crypto in Phase 1 |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leakage in git | Info Disclosure | gitleaks pre-commit hook + CI gate (OPS-07) |
| Hardcoded DB password in compose.yaml | Info Disclosure | All secrets via .env (gitignored); .env.example with placeholders |
| External ARPAE JSON injection → SQL injection | Tampering | asyncpg parameterized queries; Pydantic validation at boundary |
| GRIB file path traversal in staging volume | Tampering | Fixed staging path in worker; no user-controlled paths |
| Redis broker exposed on host network | Elevation of Privilege | Redis NOT exposed via `ports:` in compose.yaml; only on internal bridge network |
| Celery Beat scaled > 1 → scraping abuse | Denial of Service | `deploy.replicas: 1` + README warning; polite HTTP client rate limiting |
| robots.txt non-compliance | Reputation | Programmatic robots.txt check cached 24h; docs/scraping-policy.md (OPS-09) |

---

## Sources

### Primary (HIGH confidence)
- `dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl` — live ARPAE data structure empirically verified
- `dati-simc.arpae.it/opendata/osservati/meteo/storico/` — directory listing verified (YYYY-MM.json.gz pattern)
- `github.com/ecmwf/ecmwf-opendata` README — client API confirmed (params, no area support)
- `github.com/ecmwf/ecmwf-opendata/issues/3` — bbox limitation confirmed
- `github.com/sqlalchemy/alembic/discussions/1465` — include_name pattern for TimescaleDB
- `.planning/research/STACK.md` — version pins and stack decisions
- `.planning/research/ARCHITECTURE.md` — adapter ABC design patterns
- `.planning/research/PITFALLS.md` — TimescaleDB, Celery, scraping pitfalls

### Secondary (MEDIUM confidence)
- MkDocs Material deploy workflow — multiple community sources agree on configure-pages@v5 + upload-pages-artifact@v3 + deploy-pages@v4
- testcontainers TimescaleDB — testcontainers.com/modules/timescale + DeepWiki wait strategies
- pyrate-limiter RedisBucket — official pyrate-limiter docs (v4.x Redis backend)
- FIWARE WeatherObserved NGSI-LD — closest standard for JSON-LD snapshot context

### Tertiary (LOW confidence — flagged [ASSUMED])
- ARPAE wind BUFR codes (B11001, B11002) — inferred from WMO Table B; not observed in sample
- ECMWF `2r` availability in real-time dissemination — listed in param docs but not confirmed for all steps
- vcrpy async httpx compatibility — listed as supported but not tested in this session

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified on PyPI; slopcheck passed
- ARPAE endpoint schema: MEDIUM-HIGH — realtime feed empirically sampled; storico structure confirmed
- ECMWF integration: MEDIUM — client API confirmed; bbox limitation confirmed; xarray subsetting approach is standard but not tested
- TimescaleDB DDL (two hypertables): HIGH — DDL follows TimescaleDB official API; policy ordering rule verified
- Alembic pattern: MEDIUM — include_name exclusion confirmed via community discussion
- GitHub Pages workflow: MEDIUM-HIGH — multiple consistent sources; action versions verified
- testcontainers: MEDIUM — image usage confirmed; wait strategy documented

**Research date:** 2026-05-23
**Valid until:** 2026-06-22 (30 days for stable stack; ARPAE endpoint is empirically discoverable and may change)

**Note for planner on API-10 traceability:** Per D-14, API-10 is anticipated to Phase 1. The REQUIREMENTS.md Traceability table currently shows API-10 mapped to Phase 2. The planner must update REQUIREMENTS.md to move API-10 → Phase 1 as part of plan execution.
