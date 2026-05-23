# Phase 2: Public REST API - Research

**Researched:** 2026-05-23
**Domain:** FastAPI public REST API — rate limiting, streaming exports, observability, OpenAPI enrichment, GDPR-aware logging, cursor pagination, mkdocstrings docs
**Confidence:** HIGH (all core stack confirmed via PyPI registry, official docs, and codebase inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Resolution Resolver + Range Limits**
- D-API-01: Auto-route fisso (no override): `<1h` → `observations` raw, `1h-1d` → `obs_hourly` CAGG, `≥1d` → `obs_daily` CAGG. Same pattern per gridded_observations.
- D-API-02: Max range per resolution — raw: 7 days, hourly: 90 days, daily: 5 years. Exceeded → Problem Details 400.
- D-API-03: Default period (no start+end): last 24h.
- D-API-04: Time range `[start, end)` half-open. Documented in OpenAPI `end` parameter description.

**Pagination + Error Response**
- D-API-05: Cursor: opaque base64 encoding of `{last_row PK + resolution + filters_sha256 + exp_ts}`. Cursor self-contained. Filter change during pagination → 400.
- D-API-06: Page size default 1000, max 10000. Header `X-Page-Size`. Export endpoints NOT paginated.
- D-API-07: Error format: RFC 7807 Problem Details (`Content-Type: application/problem+json`) — `{type, title, status, detail, instance, request_id, code?, extras?}`.
- D-API-08: Every error includes `X-Request-ID` (UUIDv7), `request_id` in body, OTel span attribute `request.id`.

**CORS + API Keys + Rate Limiting**
- D-API-09: CORS allowlist via env `CORS_ORIGINS` (comma-separated). Default dev: `http://localhost:*`. `allow_credentials=true` only for explicit origins, never with `*`.
- D-API-10: No API keys in v1.0. Per-IP rate-limit only.
- D-API-11: Rate-limit budgets: `/v1/stations*` 60/min, `/v1/observations` 30/min, `/v1/observations?format=*` 10/min, `/v1/sources*`+`/v1/meta/*` 120/min.
- D-API-12: Rate-limit overrun: HTTP 429 + `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` + Problem Details body `type=urn:climatepulse:rate-limited`.

**Source Health + Export Format**
- D-API-13: Stale = 2× cadence per source. Arpae: 30min, ECMWF: 12h.
- D-API-14: `/v1/sources/status` always returns 200. Body: `[{source_id, name, status, last_ingest_at, freshness_seconds, error_rate_24h, threshold_seconds}]`. Status `down` when >5× cadence.
- D-API-15: Parquet schema: long format — 1 row per `(station_id, variable_id, observed_at)` with `[station_id, source_id, lat, lon, wmo_code, variable_name, observed_at, value, unit, quality_flag]`.
- D-API-16: CSV: gzip on-the-fly (`Content-Encoding: gzip`), chunk 10k rows, `Content-Disposition: attachment; filename="climate-pulse-{source}-{start}-{end}.csv.gz"`.

**WMO Variable Dictionary + Filter**
- D-API-17: BUFR codes mapped: B04001-B04006 → silently dropped. B07031 → `station.elevation_m`. B13215 → `quality_flag=SUSPECT` if != 0.
- D-API-18: `/v1/meta/variables` exposes: `wmo_code, name, si_unit, description, valid_range: [min, max]`.
- D-API-19: `?variable=` accepts WMO code OR human-readable name (case-insensitive alias resolution).

**Observability**
- D-API-20: OTel exporter: OTLP/HTTP via env `OTEL_EXPORTER_OTLP_ENDPOINT`. Default no-op.
- D-API-21: `/metrics` public, NOT `include_in_schema=False`.
- D-API-22: OTel auto-instrumentation: FastAPI + SQLAlchemy + asyncpg + Redis + httpx. Custom span for resolution resolver.
- D-API-23: structlog: JSON in prod, console in dev — env `LOG_FORMAT=json|console`. Default `json`.

**OpenAPI Metadata + Examples**
- D-API-24: OpenAPI 3.1 `info` with title/version/description/contact/license/tags.
- D-API-25: `x-codeSamples` per endpoint: curl + Python httpx + sample response.
- D-API-26: `servers` section: localhost dev + `https://fedcal.github.io/Climate-Pulse/api` placeholder. Configurable via env `API_PUBLIC_URL`.
- D-API-27: Pydantic `Field(..., description="...", examples=[...])` on every field.

**API Reference Docs (DOC-04)**
- D-API-28: mkdocstrings: one page per router under `docs/api/` (stations.md, observations.md, sources.md, meta.md, health.md).
- D-API-29: mkdocstrings documents routers + Pydantic schemas + curl/Python examples.
- D-API-30: `docs/api/spec.md` with Redoc embed (CDN) + openapi.json download button.
- D-API-31: Four additional docs pages: how-to-query.md, rate-limits.md, authentication.md, changelog.md.

### Claude's Discretion
- HTTP cache headers (Cache-Control, ETag, Last-Modified) for `/v1/stations` and `/v1/meta/variables` — planner decides TTL.
- Redis cache layer in API process (separate from rate-limit) — optional, planner decides if needed.
- Pydantic v2 v1-compat shim — not needed (Python 3.12 native).
- Error code catalog (`urn:climatepulse:rate-limited`, `urn:climatepulse:resolution-too-fine`, etc.) — planner expands list during implementation.
- Cursor encoding scheme detailed (HMAC-SHA256 with secret? plain base64?) — planner decides; default HMAC if integrity guarantee needed.
- Test fixture layout for FastAPI TestClient — planner discretion.

### Deferred Ideas (OUT OF SCOPE)
- WebSocket `/v1/ws/observations` → Phase 4
- Angular dashboard → Phase 3
- Alert rules + webhook + email → Phase 5
- mike docs versioning → Phase 5
- LGTM Compose profile → Phase 5
- API key tier → v1.1+ (EXT-07)
- `/v2/` versioning policy execution → when breaking change needed
- Reverse proxy + TLS (Caddy / Let's Encrypt) → Phase 3-4
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| API-01 | `GET /v1/stations` with bbox/country/source filters + cursor pagination | Cursor HMAC pattern, asyncpg pool reuse, MetadataRepo |
| API-02 | `GET /v1/stations/{id}` — metadata + temporal coverage | asyncpg direct query, Pydantic DTO, domain models |
| API-03 | `GET /v1/observations` with resolution resolver auto-routing | CAGG query patterns, real-time gap UNION ALL, custom OTel span |
| API-04 | `GET /v1/sources` + `GET /v1/sources/status` | health.py `is_stale()` / `get_last_success()` reuse, always-200 pattern |
| API-05 | `GET /v1/meta/variables` (WMO codes + valid_range) | MetadataRepo `load_variables_cache()`, Pydantic Field examples |
| API-06 | Export streaming CSV / JSON / Parquet via `?format=` | pyarrow ipc.new_stream, gzip StreamingResponse, chunk 10k |
| API-08 | Rate limiting slowapi Redis-backed per-IP + per-route, 429 + Problem Details | slowapi 0.1.9, `_default_error_responder` override |
| API-09 | OpenAPI 3.1 spec + Swagger + Redoc | FastAPI `custom_openapi()`, x-codeSamples injection pattern |
| API-11 | Per-row provenance (source) + quality flag in responses | Pydantic DTOs wrapping asyncpg rows, QcFlag enum reuse |
| API-12 | GDPR IP truncation /24 IPv4 / /48 IPv6 logging | Starlette middleware, ipaddress stdlib |
| API-13 | orjson + gzip + CORS + request-id middleware | ORJSONResponse default, GZipMiddleware, CORSMiddleware, UUIDv7 request-id |
| OPS-04 | structlog + OTel auto-instrumentation + prometheus-client `/metrics` | structlog 25.5, OTel 0.62b0, prometheus-client 0.25 |
| OPS-10 | Privacy notice docs + GDPR log retention runbook | MkDocs page, retention policy documentation |
| DOC-04 | API reference via mkdocstrings per router | mkdocstrings 1.0.4, Python handler, mkdocs.yml nav extension |
</phase_requirements>

---

## Summary

Phase 2 builds directly on the Phase 1 FastAPI skeleton (`apps/api/climatepulse_api/main.py`) — which already wires asyncpg pool, Redis client, structlog, and lifespan — by adding the complete public read path. The app extension pattern is: add new routers in `apps/api/climatepulse_api/routers/`, new schemas in `apps/api/climatepulse_api/schemas/`, new query functions in `apps/api/climatepulse_api/queries/`, and new middleware in `apps/api/climatepulse_api/middleware/`. The existing `health.py` router is left untouched.

The most technically nuanced areas are: (1) the resolution resolver which must perform CAGG routing AND handle the real-time aggregation gap via UNION ALL; (2) the streaming export path for Parquet which must stay under 200MB RSS; (3) the HMAC cursor which requires a rotatable secret stored in Redis; (4) the structlog + OTel integration where OTel must initialize before structlog processors are configured; and (5) the FastAPI middleware ordering where CORS must be outermost.

**Primary recommendation:** Extend `main.py` lifespan and `settings.py` without rewriting them. All new surface goes into new files in `routers/`, `schemas/`, `queries/`, and `middleware/`. No existing Phase 1 code is modified unless extending Settings fields.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Resolution routing (raw vs CAGG) | API (query layer) | Database | API decides table, DB executes — routing logic in `queries/observations.py` |
| Rate limiting per-IP+per-route | API middleware | Redis | slowapi stores counters in Redis DB 2, enforced in FastAPI middleware stack |
| Cursor integrity (HMAC) | API (cursor module) | Redis | Secret lives in Redis (rotatable), HMAC computed in API process |
| GDPR IP truncation | API middleware | — | Single enforcement point before structlog context binding |
| Streaming export (Parquet/CSV) | API router | Database | asyncpg cursor fetches in batches; pyarrow/gzip writes chunks to response |
| Source freshness status | API router | Redis | `get_last_success()` reads Redis key set by worker's `record_success()` |
| OpenAPI spec enrichment | API (custom_openapi) | — | One-time schema post-processing at startup, cached |
| Prometheus metrics | API (prometheus-client) | — | `/metrics` endpoint served directly from API process, public |
| OTel trace propagation | API (auto-instrumentation) | — | FastAPI + asyncpg + Redis spans auto-generated; custom span for resolver |
| mkdocstrings API reference | Build (MkDocs) | — | MkDocs build reads router docstrings; not runtime |
| GDPR log retention policy | Docs | — | Runbook-only; not enforced by code in Phase 2 |

---

## Standard Stack

### Core (Phase 1 already installed — verify pyproject.toml before adding)

| Library | Version (PyPI confirmed) | Purpose | Why Standard |
|---------|--------------------------|---------|--------------|
| FastAPI | 0.136.x [VERIFIED: pyproject.toml] | ASGI web framework | Already in api/pyproject.toml |
| Pydantic | 2.9+ [ASSUMED] | Response schema validation | Already in api/pyproject.toml via FastAPI |
| pydantic-settings | 2.5+ [ASSUMED] | Settings from env | Already in api/pyproject.toml |
| asyncpg | 0.31.x [VERIFIED: pyproject.toml] | DB queries (raw SQL) | Already in api/pyproject.toml |
| redis[hiredis] | <6.0 [VERIFIED: pyproject.toml] | slowapi storage + cursor secret + health | Already in api/pyproject.toml |
| orjson | 3.11.9 [VERIFIED: PyPI registry] | Fast JSON responses | 2-3x faster than stdlib; standard for time-series APIs |

### New in Phase 2

| Library | Version (PyPI confirmed) | Purpose | Why Standard |
|---------|--------------------------|---------|--------------|
| slowapi | 0.1.9 [VERIFIED: PyPI registry] | Rate limiting (Redis-backed) | Standard FastAPI/Starlette limiter; Redis storage across workers |
| pyarrow | 24.0.0 [VERIFIED: PyPI registry] | Parquet streaming export | fastparquet retired March 2026; pyarrow is the only maintained option |
| structlog | 25.5.0 [VERIFIED: PyPI registry] | Structured JSON logging | OTel context processor integration; already in worker |
| prometheus-client | 0.25.0 [VERIFIED: PyPI registry] | `/metrics` endpoint | Standard Prometheus Python client |
| opentelemetry-distro | 0.62b0 [ASSUMED: WebSearch] | OTel SDK + auto-bootstrap | Installs all instrumentations via `opentelemetry-bootstrap` |
| opentelemetry-instrumentation-fastapi | 0.62b0 [ASSUMED: WebSearch] | FastAPI spans | Spans for every endpoint, baggage propagation |
| opentelemetry-instrumentation-sqlalchemy | 0.62b0 [ASSUMED: WebSearch] | DB span tracing | Surfaces slow Timescale queries |
| opentelemetry-instrumentation-asyncpg | 0.62b0 [ASSUMED: WebSearch] | asyncpg spans | Traces raw asyncpg calls in queries layer |
| opentelemetry-instrumentation-redis | 0.62b0 [ASSUMED: WebSearch] | Redis spans | Traces slowapi + cursor Redis calls |
| opentelemetry-instrumentation-httpx | 0.62b0 [ASSUMED: WebSearch] | httpx spans | Needed by worker; optional for API |
| mkdocstrings[python] | 1.0.4 [VERIFIED: PyPI registry] | API reference docs | Already configured in mkdocs.yml plugins |

**Installation (uv, from api package):**
```bash
uv add --package climatepulse-api "slowapi==0.1.9" "orjson>=3.11" "pyarrow>=24.0" \
       "structlog>=25.5" "prometheus-client>=0.25" \
       "opentelemetry-distro>=0.62b0" \
       "opentelemetry-instrumentation-fastapi>=0.62b0" \
       "opentelemetry-instrumentation-sqlalchemy>=0.62b0" \
       "opentelemetry-instrumentation-asyncpg>=0.62b0" \
       "opentelemetry-instrumentation-redis>=0.62b0"
```

---

## Package Legitimacy Audit

> slopcheck 0.6.1 was available and ran against all packages. PyPI registry verified via `pip index versions`. All packages are Python/PyPI — not npm or Rust.

| Package | Registry | slopcheck | Disposition |
|---------|----------|-----------|-------------|
| slowapi | PyPI (0.1.9) | [OK] | Approved |
| orjson | PyPI (3.11.9) | [OK] | Approved |
| pyarrow | PyPI (24.0.0) | [OK] | Approved |
| structlog | PyPI (25.5.0) | [OK] | Approved |
| prometheus-client | PyPI (0.25.0) | [OK] — note: "name ends with '-client', classic LLM naming pattern but package is established" | Approved |
| mkdocstrings | PyPI (1.0.4) | [OK] | Approved |
| opentelemetry-distro | PyPI | [OK] | Approved |
| opentelemetry-instrumentation-fastapi | PyPI | [OK] | Approved |
| opentelemetry-instrumentation-sqlalchemy | PyPI | [OK] | Approved |
| opentelemetry-instrumentation-asyncpg | PyPI | [OK] | Approved |
| opentelemetry-instrumentation-redis | PyPI | [OK] | Approved |
| opentelemetry-instrumentation-httpx | PyPI | [OK] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

**Note on OTel versions:** PyPI `pip index versions` failed for OTel packages on this machine due to the externally-managed-environment restriction. Versions tagged `[ASSUMED]` based on WebSearch reporting 0.62b0 as latest. The planner should confirm with `uv add opentelemetry-distro --dry-run` before locking.

---

## Architecture Patterns

### System Architecture Diagram (Phase 2 additions in focus)

```
Browser / curl / researcher tool
    |
    | HTTPS GET /v1/{stations,observations,sources,meta,exports}
    v
FastAPI (apps/api/climatepulse_api/)
    |
    +-- Middleware stack (outermost → innermost for requests):
    |     CORSMiddleware             ← must be first (outermost)
    |     TrustedHostMiddleware      ← (optional, env-gated)
    |     RequestIDMiddleware        ← injects X-Request-ID (UUIDv7) into context
    |     GDPRIPTruncationMiddleware ← masks client IP before structlog binding
    |     OTel auto-instrumentation  ← wraps FastAPI with trace spans
    |     GZipMiddleware             ← compresses responses >512 bytes
    |     slowapi Limiter            ← per-IP + per-route rate-limit (Redis DB 2)
    |
    +-- Routers:
    |     /v1/stations    ← MetadataRepo + asyncpg + cursor decode/encode
    |     /v1/observations← resolution_resolver → queries/raw_obs | obs_hourly | obs_daily
    |     /v1/sources     ← MetadataRepo + is_stale() from health.py
    |     /v1/meta        ← MetadataRepo.load_variables_cache()
    |     /v1/exports     ← StreamingResponse (pyarrow IPC or gzip CSV)
    |     /metrics        ← prometheus-client (public, not in OpenAPI schema)
    |     /healthz /readyz← Phase 1, untouched
    |
    +-- Dependency injection (Depends):
    |     get_db_pool()   → asyncpg.Pool (from app.state)
    |     get_redis()     → redis.asyncio.Redis (from app.state)
    |     get_settings()  → ApiSettings (lru_cache singleton)
    |
    v
TimescaleDB (asyncpg raw SQL)
    |
    +-- observations hypertable   ← raw, range <1h
    +-- obs_hourly CAGG           ← materialized hourly buckets
    +-- obs_daily CAGG (hierarchical) ← materialized daily buckets
    +-- stations / variables / sources (metadata, read via MetadataRepo)
    |
    v (freshness data)
Redis (DB 2 = rate-limit, DB 4 = health metrics)
    |
    +-- slowapi counters          ← rate-limit budget per IP + route
    +-- metrics:last_success:{id} ← written by worker, read by /v1/sources/status
    +-- cursor_hmac_secret        ← rotatable secret for cursor signing
```

### Recommended Project Structure Additions (Phase 2)

```
apps/api/climatepulse_api/
├── main.py                  # EXTEND lifespan + CORS + middleware + OTel init
├── settings.py              # EXTEND with Phase 2 fields (CORS, OTel, LOG_FORMAT, etc.)
├── routers/
│   ├── health.py            # Phase 1 — DO NOT MODIFY
│   ├── stations.py          # NEW: GET /v1/stations + /v1/stations/{id}
│   ├── observations.py      # NEW: GET /v1/observations (+ resolution resolver call)
│   ├── sources.py           # NEW: GET /v1/sources + /v1/sources/status
│   ├── meta.py              # NEW: GET /v1/meta/variables
│   └── exports.py           # NEW: GET /v1/observations?format=csv|json|parquet
├── schemas/
│   ├── station.py           # NEW: StationResponse, StationDetailResponse
│   ├── observation.py       # NEW: ObservationRow, ObservationsPage
│   ├── source.py            # NEW: SourceResponse, SourceStatusResponse
│   ├── variable.py          # NEW: VariableResponse
│   ├── pagination.py        # NEW: CursorPage, CursorMeta
│   └── errors.py            # NEW: ProblemDetail (RFC 7807)
├── queries/
│   ├── stations.py          # NEW: SQL for /v1/stations (bbox, cursor, source filters)
│   ├── observations.py      # NEW: resolution_resolver + SQL per table
│   ├── sources.py           # NEW: SQL for /v1/sources list
│   └── exports.py           # NEW: async generator for streaming rows
├── middleware/
│   ├── request_id.py        # NEW: inject X-Request-ID (UUIDv7) + structlog bind
│   ├── gdpr_ip.py           # NEW: truncate IP /24 (IPv4) / /48 (IPv6) before log
│   └── openapi_enrich.py    # NEW: custom_openapi() with x-codeSamples + servers
├── cursor.py                # NEW: encode/decode + HMAC sign/verify
└── observability.py         # NEW: structlog config + OTel init + Prometheus setup
```

### Pattern 1: Middleware Ordering (Critical — CORS must be outermost)

**What:** FastAPI/Starlette middleware executes in reverse add-order for requests (last-added runs first). CORSMiddleware MUST be added last (so it runs first on requests) to handle preflight OPTIONS correctly before any other middleware can reject the request.

**Correct `main.py` order (add last = runs first):**
```python
# Source: https://fastapi.tiangolo.com/advanced/middleware/ + CORS dilemma community post
# Order: add last → execute first for requests

app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(GDPRIPTruncationMiddleware)   # custom — before structlog bind
app.add_middleware(RequestIDMiddleware)           # custom — inject UUIDv7
# OTel is wired via FastAPIInstrumentor().instrument_app(app) in lifespan, not add_middleware
app.add_middleware(
    CORSMiddleware,                               # MUST be last-added (outermost)
    allow_origins=settings.cors_origins,
    allow_credentials=True,                       # only valid for explicit origins
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
# slowapi is attached via app.state.limiter + ExceptionHandler — not add_middleware
```

**Why CORS must be outermost:** An error response from RequestIDMiddleware or rate-limit would not include CORS headers, causing preflight to fail for browser clients (Angular dashboard Phase 3). [CITED: https://medium.com/@saurabhbatham17/navigating-middleware-ordering-in-fastapi-a-cors-dilemma-8be88ab2ee7b]

### Pattern 2: Resolution Resolver

**What:** Given `start` + `end` query params (defaulting to last 24h), compute the time delta and dispatch to the appropriate table. Add a custom OTel span for observability.

```python
# apps/api/climatepulse_api/queries/observations.py
# Source: D-API-01 (locked), ARCHITECTURE.md Pattern 4, TimescaleDB CAGG docs
from datetime import timedelta
from opentelemetry import trace

_TRACER = trace.get_tracer("climatepulse.api")

def resolve_table(start: datetime, end: datetime) -> tuple[str, str]:
    """Return (table_name, resolution_label) based on requested time range.

    Resolution routing (D-API-01):
      delta < 1h  → observations (raw)
      1h <= delta < 1d → obs_hourly
      delta >= 1d → obs_daily
    """
    delta = end - start
    if delta < timedelta(hours=1):
        return "observations", "raw"
    elif delta < timedelta(days=1):
        return "obs_hourly", "hourly"
    else:
        return "obs_daily", "daily"

async def query_observations(pool, station_id, variable_id, start, end, limit, cursor_state):
    table, resolution = resolve_table(start, end)
    with _TRACER.start_as_current_span("resolution_resolver") as span:
        span.set_attribute("resolution", resolution)
        span.set_attribute("table", table)
        span.set_attribute("range_hours", (end - start).total_seconds() / 3600)
        rows = await _fetch_from_table(pool, table, station_id, variable_id, start, end, limit)
        span.set_attribute("row_count", len(rows))
    return rows, resolution
```

**Real-time gap handling for CAGGs:** TimescaleDB CAGGs with `end_offset=1h` leave the last hour unmaterialized. When `timescaledb.materialized_only=false` (the default), querying a CAGG view automatically UNION ALL's materialized + raw data — no manual gap fill needed in most cases. For explicit control or when crossing the `end_offset` boundary:

```sql
-- Source: TimescaleDB docs — real-time aggregation gap pattern
-- Use when you need guaranteed up-to-the-minute data alongside materialized hourly data
WITH cagg_boundary AS (
  SELECT max(bucket) + INTERVAL '1 hour' AS boundary FROM obs_hourly
  WHERE station_id = $1 AND variable_id = $2
)
SELECT bucket AS observed_at, avg_value, min_value, max_value, 'hourly' AS resolution
FROM obs_hourly
WHERE station_id = $1 AND variable_id = $2
  AND bucket >= $3 AND bucket < (SELECT boundary FROM cagg_boundary)
UNION ALL
SELECT time_bucket(INTERVAL '1 hour', observed_at), avg(value), min(value), max(value), 'hourly_realtime'
FROM observations
WHERE station_id = $1 AND variable_id = $2
  AND observed_at >= (SELECT boundary FROM cagg_boundary) AND observed_at < $4
GROUP BY 1
ORDER BY 1 DESC
```

[CITED: https://dev.to/philip_mcclarence_2ef9475/timescaledb-continuous-aggregates-real-time-vs-materialized-only-4k75]

### Pattern 3: Cursor Pagination with HMAC Integrity

**What:** Cursor encodes the last row's sort values + resolution + filters hash + expiry, signed with HMAC-SHA256. Stored in Redis as a rotatable secret. Plain base64 without HMAC allows clients to jump arbitrarily in the data, defeating rate limiting.

```python
# apps/api/climatepulse_api/cursor.py
# Source: Community research on cursor pagination + HMAC signing pattern [ASSUMED]
import base64, hashlib, hmac, json, time
from datetime import datetime

CURSOR_TTL_SECONDS = 3600  # 1 hour

async def _get_secret(redis) -> bytes:
    """Fetch rotatable HMAC secret from Redis (key: cursor:hmac:secret)."""
    raw = await redis.get("cursor:hmac:secret")
    if raw is None:
        raise ValueError("cursor HMAC secret not configured in Redis")
    return raw if isinstance(raw, bytes) else raw.encode()

async def encode_cursor(redis, last_observed_at: datetime, last_station_id: int,
                        last_variable_id: int, resolution: str,
                        filters_sha256: str) -> str:
    """Encode and sign a cursor token."""
    payload = {
        "ts": last_observed_at.isoformat(),
        "sid": last_station_id,
        "vid": last_variable_id,
        "res": resolution,
        "fhash": filters_sha256,
        "exp": int(time.time()) + CURSOR_TTL_SECONDS,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    secret = await _get_secret(redis)
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(body).decode() + "." + sig[:16]
    return token

async def decode_cursor(redis, token: str) -> dict:
    """Decode and verify a cursor token. Raises ValueError on tamper/expiry."""
    try:
        b64_part, sig_prefix = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(b64_part + "==")
        secret = await _get_secret(redis)
        expected_sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig[:16], sig_prefix):
            raise ValueError("cursor integrity check failed")
        payload = json.loads(body)
        if payload["exp"] < int(time.time()):
            raise ValueError("cursor expired — regenerate query")
        return payload
    except (ValueError, KeyError) as e:
        raise ValueError(f"invalid cursor: {e}") from e
```

**Secret rotation:** Store `cursor:hmac:secret` in Redis. On rotation, set a new value — old cursors (with old sig) automatically fail integrity check and clients regenerate. Document rotation as an operator runbook action in the changelog page. [ASSUMED — rotation strategy based on common HMAC rotation patterns]

### Pattern 4: slowapi Redis-Backed Rate Limiting

**What:** One `Limiter` instance with Redis storage URI. Per-route limits via decorators. Override default 429 handler to return RFC 7807 Problem Details.

```python
# apps/api/climatepulse_api/main.py additions
# Source: https://slowapi.readthedocs.io/ [CITED]
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://redis:6379/2",   # DB 2 = rate-limit (isolated from broker DB 0)
    headers_enabled=True,                 # emits X-RateLimit-* headers
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _problem_details_rate_limit_handler)

# Per-route usage:
# @router.get("/v1/stations")
# @limiter.limit("60/minute")  # D-API-11
# async def list_stations(request: Request, ...): ...
```

**Custom 429 handler returning RFC 7807:**
```python
# Source: slowapi docs + RFC 7807 spec [CITED: https://datatracker.ietf.org/doc/html/rfc7807]
from fastapi import Request
from fastapi.responses import JSONResponse

async def _problem_details_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "type": "urn:climatepulse:rate-limited",
            "title": "Too Many Requests",
            "status": 429,
            "detail": f"Rate limit exceeded: {exc.detail}",
            "instance": str(request.url),
            "request_id": request.state.request_id,  # set by RequestIDMiddleware
        },
        headers={
            "Content-Type": "application/problem+json",
            "Retry-After": str(exc.retry_after),
            "X-Request-ID": request.state.request_id,
        },
    )
```

**Multi-worker correctness:** Redis storage makes rate-limit counters consistent across multiple Uvicorn workers. The `storage_uri` must point to the same Redis instance all workers use. [CITED: https://slowapi.readthedocs.io/]

### Pattern 5: Parquet Streaming (pyarrow IPC + FastAPI StreamingResponse)

**What:** pyarrow `ipc.new_stream()` writes Arrow IPC format (not Parquet file format) to a `BufferOutputStream`. For true Parquet streaming, use `pyarrow.parquet.ParquetWriter` to a `BufferOutputStream` and yield chunks.

```python
# apps/api/climatepulse_api/routers/exports.py
# Source: https://arrow.apache.org/docs/python/ipc.html [CITED]
import io
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.responses import StreamingResponse

PARQUET_SCHEMA = pa.schema([
    pa.field("station_id", pa.int64()),
    pa.field("source_id", pa.int16()),
    pa.field("lat", pa.float64()),
    pa.field("lon", pa.float64()),
    pa.field("wmo_code", pa.string()),
    pa.field("variable_name", pa.string()),
    pa.field("observed_at", pa.timestamp("us", tz="UTC")),
    pa.field("value", pa.float64()),
    pa.field("unit", pa.string()),
    pa.field("quality_flag", pa.int16()),
])

async def stream_parquet(pool, query_params) -> StreamingResponse:
    async def generate():
        buf = io.BytesIO()
        writer = pq.ParquetWriter(buf, PARQUET_SCHEMA, compression="snappy")
        batch = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                async for row in conn.cursor(build_export_sql(query_params)):
                    batch.append(row_to_dict(row))
                    if len(batch) >= 10_000:   # D-API-16: chunk 10k rows
                        table = pa.Table.from_pylist(batch, schema=PARQUET_SCHEMA)
                        writer.write_table(table)
                        yield buf.getvalue()
                        buf.seek(0); buf.truncate(0)
                        batch = []
        if batch:
            table = pa.Table.from_pylist(batch, schema=PARQUET_SCHEMA)
            writer.write_table(table)
        writer.close()
        yield buf.getvalue()

    return StreamingResponse(
        generate(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="climate-pulse-...parquet"'},
    )
```

**Memory safety:** chunking 10k rows keeps each batch ~1-5MB in RAM regardless of total query size. Writer never materializes the full result. The `asyncpg` `conn.cursor()` async iterator is the key — it fetches in server-side cursor batches, not a full Python list. [CITED: https://arrow.apache.org/docs/python/ipc.html]

### Pattern 6: structlog + OTel Trace Context Injection

**What:** A structlog processor extracts the current OTel span context and injects `trace_id` + `span_id` into every log event. OTel must be initialized BEFORE structlog is configured.

```python
# apps/api/climatepulse_api/observability.py
# Source: https://docs.bswen.com/blog/2026-04-29-structlog-opentelemetry-setup/ [CITED]
from opentelemetry import trace
import structlog

def add_otel_context(logger, method, event_dict):
    """Structlog processor: inject OTel trace_id + span_id."""
    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

def configure_structlog(log_format: str):
    """Configure structlog. Call AFTER OTel TracerProvider is set."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_otel_context,                    # must come after OTel init
    ]
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(processors=processors)
```

**OTel init order in lifespan:**
```python
# In main.py lifespan, BEFORE configure_structlog():
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

if settings.otel_exporter_otlp_endpoint:
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
FastAPIInstrumentor().instrument_app(app)  # auto-instr before configure_structlog
configure_structlog(settings.log_format)   # structlog AFTER OTel
```

### Pattern 7: GDPR IP Truncation Middleware

**What:** A Starlette middleware that truncates the client IP before it can be logged anywhere. Must run before `RequestIDMiddleware` binds structlog context (so the truncated IP is what lands in logs).

```python
# apps/api/climatepulse_api/middleware/gdpr_ip.py
# Source: D-API-12 locked decision + ipaddress stdlib
import ipaddress
from starlette.middleware.base import BaseHTTPMiddleware

class GDPRIPTruncationMiddleware(BaseHTTPMiddleware):
    """Truncate client IP before structlog context binding (GDPR compliance).

    IPv4: truncate to /24 (last octet → 0).
    IPv6: truncate to /48 (last 80 bits → 0).
    """
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        try:
            addr = ipaddress.ip_address(client_ip)
            if isinstance(addr, ipaddress.IPv4Address):
                network = ipaddress.ip_network(f"{client_ip}/24", strict=False)
                truncated = str(network.network_address)
            else:
                network = ipaddress.ip_network(f"{client_ip}/48", strict=False)
                truncated = str(network.network_address)
        except ValueError:
            truncated = "invalid"
        request.state.client_ip_truncated = truncated
        return await call_next(request)
```

**Note:** European DPAs (French CNIL, Italian Garante) have ruled that truncated IPs remain personal data under GDPR. Truncation is a documented mitigation, not full anonymization. The runbook (OPS-10) must state the retention policy and legal basis. [CITED: https://00f.net/2025/10/27/ip-anonymization/]

### Pattern 8: OpenAPI x-codeSamples Injection

**What:** Override `app.openapi()` to post-process the generated schema and inject `x-codeSamples` (curl + Python httpx) per endpoint. Redoc renders these as code tabs.

```python
# apps/api/climatepulse_api/middleware/openapi_enrich.py
# Source: https://fastapi.tiangolo.com/how-to/extending-openapi/ [CITED]
from fastapi.openapi.utils import get_openapi

CODE_SAMPLES = {
    "GET /v1/stations": [
        {"lang": "Shell", "label": "curl", "source": "curl 'https://api.example.com/v1/stations?bbox=9,44,13,47'"},
        {"lang": "Python", "label": "httpx", "source": "import httpx\nr = httpx.get('https://api.example.com/v1/stations', params={'bbox': '9,44,13,47'})\nprint(r.json())"},
    ],
    # ... per endpoint
}

def custom_openapi(app, settings):
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Climate Pulse API",
        version="1.0.0",
        description="Multi-source EU weather aggregation API...",
        contact={"name": "Federico Calo", "email": "fedcal01@gmail.com", "url": "https://federicocalo.dev"},
        license_info={"name": "MIT", "identifier": "MIT"},
        routes=app.routes,
        tags=[
            {"name": "Stations"}, {"name": "Observations"},
            {"name": "Sources"}, {"name": "Meta"}, {"name": "Health"},
        ],
    )
    # Inject servers (D-API-26)
    schema["servers"] = [
        {"url": settings.api_public_url or "https://fedcal.github.io/Climate-Pulse/api", "description": "Public"},
        {"url": "http://localhost:8000", "description": "Local dev"},
    ]
    # Inject x-codeSamples per path+method (D-API-25)
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            key = f"{method.upper()} {path}"
            if key in CODE_SAMPLES:
                op["x-codeSamples"] = CODE_SAMPLES[key]
    # Add API-Version header to every response (D-API-26 specifics)
    app.openapi_schema = schema
    return schema
```

### Pattern 9: mkdocstrings Router Documentation

**What:** mkdocstrings[python] 1.0.4 uses Griffe to extract docstrings from Python source. For FastAPI routers, document the router module (not the route function decorated with `@router.get`) so mkdocstrings can render the module-level docstring + all public functions. Add `apps/api` to `mkdocstrings` paths.

**mkdocs.yml extension (extend, not replace):**
```yaml
# Append to existing plugins.mkdocstrings.handlers.python.paths:
plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths:
            - packages/core
            - apps/api           # Phase 2 addition

nav:
  # ... existing nav entries ...
  - API Reference:
    - Stations: api/stations.md
    - Observations: api/observations.md
    - Sources: api/sources.md
    - Meta: api/meta.md
    - Health: api/health.md
    - OpenAPI Spec: api/spec.md
  - API Guide:
    - How to Query: api/how-to-query.md
    - Rate Limits: api/rate-limits.md
    - Authentication: api/authentication.md
    - Changelog: api/changelog.md
```

**docs/api/stations.md pattern:**
```markdown
# Stations

::: climatepulse_api.routers.stations
    options:
      show_root_heading: true
      show_source: false
      members:
        - list_stations
        - get_station
```

**Limitation:** mkdocstrings is optimized for plain Python functions and classes. FastAPI route decorators add metadata that mkdocstrings processes correctly through Griffe's AST visitor — the function signature and docstring are fully captured. Pydantic response models (schemas/) are also fully documented via `:::` directives. [CITED: https://mkdocstrings.github.io/python/]

### Anti-Patterns to Avoid

- **Querying raw `observations` for multi-day requests:** Always route through `obs_hourly` or `obs_daily`. A 5-year query on raw will scan ~50M rows. Resolution resolver is the guard. (Pitfall #12)
- **OTel after structlog:** structlog processor calls `trace.get_current_span()` — if OTel tracer provider is not yet set, this returns a no-op span and trace_id will be all zeros. (Research finding — must init in correct order)
- **CORS not outermost:** A 429 from slowapi without CORS headers will fail browser preflight. Angular dashboard (Phase 3) breaks silently. (Community pattern, CORS dilemma)
- **Rewriting `main.py`:** Phase 1's lifespan, asyncpg pool, Redis client, and heartbeat check are all production-tested. Only ADD to them, don't rewrite.
- **Storing full IP in structlog bound context:** Even temporarily — the GDPR middleware must truncate before any log binding.
- **ORM for observation queries:** SQLAlchemy ORM on `observations` hypertable rows will load Pydantic models via object identity map — 10-100x slower than raw asyncpg tuples. Use `asyncpg` directly for all observation reads. (ARCHITECTURE.md Anti-Pattern 4)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limiting per-IP across multiple workers | Custom Redis counter + TTL logic | `slowapi 0.1.9` | Edge cases: race conditions, missing headers (Retry-After, X-RateLimit-*), per-route budget isolation |
| Parquet streaming | Custom binary framing | `pyarrow.parquet.ParquetWriter` + `asyncpg` cursor iterator | Column encoding, compression, schema evolution — all complex |
| CSV gzip streaming | `zlib.compress` accumulate + send | `gzip.GzipFile(fileobj=io.BytesIO())` + async generator | gzip header/trailer, chunk boundary correctness, streaming semantics |
| RFC 7807 Problem Details | Custom error dict shape | Pydantic `ProblemDetail` model + `JSONResponse(content_type="application/problem+json")` | Content-Type matters for tooling (Insomnia, Postman) to render correctly |
| HMAC cursor | Random token → Redis lookup | HMAC-SHA256 self-contained cursor | Redis lookup per page request adds latency; self-contained is O(1) |
| OTel trace_id in logs | `traceback.extract_stack()` | `trace.get_current_span().get_span_context()` | Only OTel knows the active span across async context switches |
| IP anonymization | String split on "." | `ipaddress.ip_network(f"{ip}/24", strict=False)` | Handles IPv4-mapped IPv6 (`::ffff:1.2.3.4`), link-local, IPv6 prefix correctly |

---

## Common Pitfalls

### Pitfall 1: slowapi key_func returns full IP (not truncated)

**What goes wrong:** `get_remote_address` returns the raw client IP. If the GDPR middleware runs after slowapi, the rate-limit key contains the full IP and the rate-limit log events leak full IPs.

**How to avoid:** Use a custom `key_func` that reads `request.state.client_ip_truncated` (set by GDPRIPTruncationMiddleware) instead of `request.client.host`. This also ensures rate-limit keys are consistent with logging — the truncated IP is the bucket key.

```python
def truncated_ip_key_func(request: Request) -> str:
    return getattr(request.state, "client_ip_truncated", get_remote_address(request))

limiter = Limiter(key_func=truncated_ip_key_func, storage_uri="redis://redis:6379/2")
```

**Warning signs:** Logs show `192.168.1.42` when they should show `192.168.1.0`.

### Pitfall 2: CAGG end_offset gap — recent data missing

**What goes wrong:** Query for "last 2 hours hourly data" returns 1 hour of results. The `obs_hourly` CAGG has `end_offset=1h`, so the most recent bucket is never materialized by policy. API silently returns truncated series.

**How to avoid:** Rely on `timescaledb.materialized_only=false` (the default) which auto-UNION ALL's the real-time tail. Verify this is not overridden in the CAGG definition. If the CAGG was created with `materialized_only=true`, modify it. (TimescaleDB docs)

**Warning signs:** Integration tests show missing last-hour bucket consistently.

### Pitfall 3: Cursor HMAC secret not seeded in Redis → 500 on first cursor request

**What goes wrong:** `cursor:hmac:secret` key is absent from Redis (fresh Redis, no initialization). First paginated request raises `ValueError("cursor HMAC secret not configured in Redis")` → 500.

**How to avoid:** In the FastAPI `lifespan` startup, check for the key and generate a random secret if absent:
```python
if not await redis.get("cursor:hmac:secret"):
    await redis.set("cursor:hmac:secret", secrets.token_hex(32))
```

### Pitfall 4: pyarrow ParquetWriter not closed → truncated file

**What goes wrong:** If the async generator is interrupted mid-stream (client disconnect), the `ParquetWriter` is not closed and the footer is not written. The client receives a corrupt Parquet file.

**How to avoid:** Use `try/finally` around the writer close, and handle `GeneratorExit` in the async generator:
```python
async def generate():
    writer = None
    try:
        buf = io.BytesIO()
        writer = pq.ParquetWriter(buf, PARQUET_SCHEMA)
        # ... write batches ...
    finally:
        if writer:
            writer.close()
```

### Pitfall 5: orjson fails on `datetime` without timezone → 500

**What goes wrong:** asyncpg returns `datetime` objects as naive (no timezone) from non-`TIMESTAMPTZ` columns. `orjson` serializes naive datetimes but the behavior changed across versions. `datetime` with no tzinfo may serialize without `Z` suffix, confusing clients.

**How to avoid:** All `observed_at`, `last_ingest_at`, etc. fields in response schemas must be `datetime` annotated with `tz=UTC`. asyncpg returns `TIMESTAMPTZ` columns as timezone-aware. Verify Pydantic schemas declare `datetime` (not `str`) and that all DB columns used are `TIMESTAMPTZ`.

### Pitfall 6: OTel auto-instrumentation double-instruments FastAPI

**What goes wrong:** `FastAPIInstrumentor().instrument_app(app)` called twice (e.g., once in lifespan, once in test fixture setup) creates duplicate spans and middleware layers.

**How to avoid:** Call `instrument_app` exactly once, in `main.py` lifespan startup. Tests that create `TestClient(app)` reuse the same instrumented app — no re-instrumentation in test fixtures.

### Pitfall 7: mkdocstrings fails to find `climatepulse_api` on build

**What goes wrong:** mkdocs build runs from the repo root but `apps/api` is not in Python path. `:::` directive fails silently or raises ImportError.

**How to avoid:** In `mkdocs.yml`, set `paths` under the Python handler to include `apps/api`. Run `mkdocs build` once locally after adding the path to verify. The `apps/api` package uses `hatchling` build backend — it must be installed in the docs-build environment (`uv run mkdocs build` in the repo root with workspace deps).

---

## Code Examples

### ApiSettings Extension (settings.py)

```python
# Source: Pydantic Settings docs + D-API-09, D-API-20, D-API-23, D-API-26 [CITED]
from __future__ import annotations
from functools import lru_cache
from typing import Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Phase 1 (unchanged)
    database_url: str
    redis_url: str = "redis://localhost:6379"
    environment: Literal["development", "production"] = "development"

    # Phase 2 additions
    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:8080"]
    otel_exporter_otlp_endpoint: str | None = None   # D-API-20
    log_format: Literal["json", "console"] = "json"  # D-API-23
    api_public_url: str | None = None                # D-API-26

    # Rate limit overrides (D-API-11 defaults)
    rate_limit_stations: str = "60/minute"
    rate_limit_observations: str = "30/minute"
    rate_limit_exports: str = "10/minute"
    rate_limit_meta: str = "120/minute"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v
```

### Pydantic Response Model with Field Examples (API-11, D-API-27)

```python
# Source: Pydantic v2 docs + D-API-27 [CITED: https://docs.pydantic.dev/]
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from climatepulse_core.domain.models import QcFlag

class ObservationRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # asyncpg Record → model

    station_id: int = Field(..., description="Internal station surrogate ID", examples=[42])
    source_id: int = Field(..., description="Internal source surrogate ID", examples=[1])
    wmo_code: str = Field(..., description="WMO variable code", examples=["air_temperature"])
    observed_at: datetime = Field(..., description="Observation timestamp (UTC)", examples=["2026-01-15T12:00:00Z"])
    value: float = Field(..., description="Measured value in SI units", examples=[283.15])
    unit: str = Field(..., description="SI unit string", examples=["K"])
    quality_flag: int = Field(..., description="QC flag: 0=GOOD, 1=MISSING, 2=OUT_OF_RANGE, 3=SCHEMA_VIOLATION, 4=STALE_SNAPSHOT", examples=[0])
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fastparquet` for Parquet | `pyarrow` only | March 2026 (fastparquet retired) | Must use pyarrow; STACK.md confirms this |
| `python-jose` for JWT/signing | `pyjwt` (preferred) | 2025 — python-jose maintenance concerns | Phase 2 uses HMAC (no JWT), so not blocking |
| `encode/broadcaster` for pub/sub | `redis.asyncio` directly | 2026 (archived) | Phase 4 concern; Phase 2 not affected |
| `orjson` < 3.10 | `orjson` 3.11.x | 2025 | Better datetime serialization, `OPT_UTC_Z` flag |
| `mkdocstrings` < 1.0 | `mkdocstrings` 1.0.x | 2025 | Breaking API change in handlers; 1.0.4 is current |

**Deprecated/outdated:**
- `loguru`: Do not use. Hard to integrate with OTel context propagation. `structlog` is the correct choice per STACK.md.
- `fastapi-limiter` (separate package): slowapi is the community standard for FastAPI rate limiting. Do not introduce a second rate-limit library.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OTel instrumentation packages are version 0.62b0 (current) | Standard Stack | pip would resolve a different version; planner should verify with `uv add --dry-run` |
| A2 | HMAC cursor secret rotation strategy (Redis key + auto-seed on startup) | Pattern 3 | If Redis is flushed, all outstanding cursors invalid (one-time disruption, not data loss) |
| A3 | `timescaledb.materialized_only=false` is default — auto-UNION ALL works | Pattern 2 | If Phase 1 created CAGGs with `materialized_only=true`, explicit UNION ALL is needed; must verify in DB |
| A4 | `asyncpg` `conn.cursor()` async iterator is memory-safe for streaming | Pattern 5 | asyncpg cursor semantics confirmed in docs but not tested at 10M-row scale in this project |
| A5 | slowapi `headers_enabled=True` emits `Retry-After` automatically | Pattern 4 | slowapi docs confirm header support but exact header names should be integration-tested |

---

## Open Questions

1. **CAGG `materialized_only` setting**
   - What we know: Phase 1 ARCHITECTURE.md defines CAGGs with `WITH NO DATA` but does not specify `materialized_only`. TimescaleDB default is `false` (real-time mode).
   - What's unclear: Whether the Phase 1 Alembic migration explicitly set `materialized_only=true` for any CAGG.
   - Recommendation: Planner adds a Wave 0 task: `SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates;` and documents the result. If `true`, add UNION ALL fallback to `queries/observations.py`.

2. **asyncpg pool size for Phase 2 (concurrent streaming)**
   - What we know: Phase 1 set `min_size=1, max_size=5`. Export streaming holds a connection open for the full duration of a large query.
   - What's unclear: Whether 5 connections is sufficient for 3 concurrent export requests + N observation queries.
   - Recommendation: Planner increases `max_size` to 10-15 for Phase 2, or uses a separate pool for streaming exports.

3. **OTel asyncpg instrumentation version compatibility**
   - What we know: `opentelemetry-instrumentation-asyncpg` exists on PyPI (slopcheck OK). Phase 1 uses asyncpg 0.31.x.
   - What's unclear: Whether the 0.62b0 asyncpg instrumentation supports asyncpg 0.31 (recent release).
   - Recommendation: `uv add opentelemetry-instrumentation-asyncpg --dry-run` before adding to pyproject.toml; check release notes for asyncpg 0.31 support.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | API runtime | ✓ (3.13 on host) | 3.13 host / 3.12 in Docker | Docker container uses 3.12.7-slim-bookworm |
| Docker | Build + run | ✓ | 29.3.0 | — |
| Docker Compose | Orchestration | ✓ | v5.1.0 | — |
| uv | Package management | ✓ | 0.11.13 | — |
| TimescaleDB | Storage | Via Docker | 2.17.2-pg16 (compose.yaml) | Must `docker compose up timescale` |
| Redis | Rate-limit + cursor + health | Via Docker | 7.4-alpine (compose.yaml) | Must `docker compose up redis` |
| mkdocs | Docs build | Via uv workspace | — | `uv run mkdocs build` |

**Missing dependencies with no fallback:** None — all runtime dependencies are Docker-based and already in compose.yaml from Phase 1.

**Missing dependencies with fallback:** None.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (Phase 2 is unauthenticated) | — |
| V3 Session Management | No | — |
| V4 Access Control | Partial (rate-limit as access control) | slowapi per-IP limiter |
| V5 Input Validation | Yes | Pydantic query param models, bbox validation, date range validation |
| V6 Cryptography | Yes (HMAC cursor) | `hmac.compare_digest` (constant-time), `secrets.token_hex` for seed |
| V7 Error Handling | Yes | RFC 7807 Problem Details; no stack traces in 4xx/5xx responses |
| V9 Communication | Deferred | TLS via Caddy → Phase 3-4 |

### Known Threat Patterns for FastAPI + TimescaleDB

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via query params (station_id, variable filter) | Tampering | asyncpg parameterized queries (`$1`, `$2`, ...); never f-string interpolation |
| Rate-limit bypass via IP spoofing (X-Forwarded-For) | Elevation of Privilege | Do NOT trust X-Forwarded-For without reverse proxy trust config; use `request.client.host` as authoritative IP in v1.0 (no reverse proxy yet) |
| Cursor tampering (jump to arbitrary page) | Tampering | HMAC-SHA256 signature + expiry; `hmac.compare_digest` (constant-time) |
| Parquet export DoS (multi-year, multi-variable query) | DoS | Rate-limit exports at 10/min; max range 5 years daily only; asyncpg cursor (not full materialization) |
| OTel endpoint disclosure (OTLP HTTP) | Information Disclosure | `OTEL_EXPORTER_OTLP_ENDPOINT` default = no-op; self-hosters configure own collector |
| GDPR log retention violation | Compliance | IP truncation middleware + OPS-10 runbook; no raw IPs in any log output |

---

## Sources

### Primary (HIGH confidence — official docs or confirmed codebase)
- Phase 1 codebase (`main.py`, `settings.py`, `health.py`, `repos.py`, `health.py` observability) — confirmed via Read tool
- `.planning/research/STACK.md` — version pins confirmed via PyPI registry
- `.planning/research/ARCHITECTURE.md` — FastAPI layering, resolution resolver pattern
- `.planning/research/PITFALLS.md` — #11, #12, #19 directly applicable to Phase 2
- [FastAPI Extending OpenAPI](https://fastapi.tiangolo.com/how-to/extending-openapi/) — custom_openapi() pattern
- [Apache Arrow IPC docs](https://arrow.apache.org/docs/python/ipc.html) — RecordBatchStreamWriter + new_stream()
- [slowapi ReadTheDocs](https://slowapi.readthedocs.io/) — Redis backend, per-route limits, headers
- [mkdocstrings Python handler](https://mkdocstrings.github.io/python/) — path config, Griffe AST
- [RFC 7807 Problem Details](https://datatracker.ietf.org/doc/html/rfc7807) — error response format

### Secondary (MEDIUM confidence — verified via official source)
- [TimescaleDB CAGGs real-time mode](https://dev.to/philip_mcclarence_2ef9475/timescaledb-continuous-aggregates-real-time-vs-materialized-only-4k75) — `materialized_only=false` default + UNION ALL gap pattern
- [structlog + OTel processor](https://docs.bswen.com/blog/2026-04-29-structlog-opentelemetry-setup/) — `add_otel_context` processor pattern, init order requirement
- [CORS middleware ordering](https://medium.com/@saurabhbatham17/navigating-middleware-ordering-in-fastapi-a-cors-dilemma-8be88ab2ee7b) — CORS must be outermost
- [IP anonymization GDPR limits](https://00f.net/2025/10/27/ip-anonymization/) — truncated IPs still personal data

### Tertiary (LOW confidence — WebSearch only, confirmed by package existence)
- OTel package versions (0.62b0) — WebSearch; verify with `uv add --dry-run`
- HMAC cursor rotation strategy — pattern research; not a single authoritative source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — packages verified on PyPI, Phase 1 already using base; OTel versions LOW (pip index versions unavailable on this machine, WebSearch only)
- Architecture: HIGH — built directly on Phase 1 codebase which was inspected
- Pitfalls: HIGH — sourced from project PITFALLS.md + OTel init order research

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (30 days; stable libraries; OTel beta versions may increment sooner)
