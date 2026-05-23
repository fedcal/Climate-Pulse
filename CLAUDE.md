<!-- GSD:project-start source:PROJECT.md -->
## Project

**Climate Pulse**

Climate Pulse è una pipeline open-source che aggrega dati meteorologici da fonti pubbliche europee (stazioni ARPA regionali italiane, ECMWF Open Data, METAR/TAF NOAA, Copernicus C3S) in un unico time-series store interrogabile via public API REST/WebSocket e visualizzato attraverso una dashboard Angular con mappa interattiva. È pensata per ricercatori, giornalisti dati, comunità open-data e PMI (agricoltura, energie rinnovabili) che vogliono accesso strutturato a serie storiche meteo senza pagare API commerciali.

**Core Value:** **End-to-end multi-source meteo pipeline**: aggregare in modo affidabile dati pubblici da fonti EU eterogenee (ARPA, ECMWF, NOAA, Copernicus) e renderli queryabili attraverso una public API documentata + dashboard utilizzabile. Se l'intera catena ingestion → storage → query → visualizzazione non funziona, il progetto non ha valore.

### Constraints

- **Tech stack**: FastAPI 0.115+, Python 3.12, TimescaleDB, Angular 21 SSR, Leaflet, Plotly, Celery, Redis — già deciso, no negoziazione
- **License**: MIT — massima riusabilità community
- **Team**: sviluppatore singolo — scope ridotti per phase, no parallelism umano (parallelism solo dei plan all'interno della phase)
- **Budget**: zero cloud budget — tutto deve girare su risorse locali (Docker Compose) o tier gratuito
- **Compliance**: GDPR-aware anche se dati meteo pubblici — attenzione a log delle query API, no PII tracking, robots.txt compliance scraping
- **Deploy**: self-hosted Docker Compose only in v1.0 — niente K8s, niente cloud-native
- **Timeline**: rilascio v1.0.0 previsto Q3 2026
- **Politeness scraping**: rate limit conservative, snapshot fallback, identificazione User-Agent obbligatori per fonti ARPA
- **Attribuzione obbligatoria**: footer `federicocalo.dev` su dashboard Angular e documentazione GitHub Pages — presente in ogni release a partire dalla v0.1
- **Docs pubbliche da subito**: documentazione MkDocs Material pubblicata su GitHub Pages fin dalla v0.1 (no "docs in fase successiva")
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Executive Note
## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12.x (3.12.7+) | Backend language | Already declared. 3.12 is the 2026 sweet spot: mature ecosystem, all weather libraries (cdsapi, ecmwf-opendata, metpy) tested against it. 3.13 has GIL/JIT churn; 3.14 too new. |
| FastAPI | 0.136.x (current stable, April 2026) | Public REST + WebSocket API | Async-native, OpenAPI 3.1 out of the box, Pydantic v2 integration, mature Starlette base. Owner-declared baseline (0.115+) is satisfied; pin to a recent 0.13x for latest Starlette compat. |
| Starlette | >=0.40.0,<0.46.0 | ASGI primitives (transitive via FastAPI) | Pinned by FastAPI; do not pin separately. |
| Uvicorn | 0.32+ (with `uvicorn[standard]`) | ASGI server | Standard FastAPI runner. Use `--workers` only behind a process manager; otherwise let Docker Compose scale containers. |
| Gunicorn | 23.x | Process manager for Uvicorn workers in prod | Wrap Uvicorn with `gunicorn -k uvicorn.workers.UvicornWorker` for graceful reloads, worker recycling, signal handling in Docker. |
| Pydantic | 2.9+ | Schema validation, request/response models | v2 is mandatory in 2026 — orders of magnitude faster than v1, native FastAPI integration. |
| pydantic-settings | 2.5+ | 12-factor config from env / .env | Standard companion to Pydantic v2 (split out of pydantic core). Loads `.env` for Docker Compose. |
| TimescaleDB | 2.17+ on PostgreSQL 16 | Time-series storage | Owner-declared. Hypertables, chunk-based compression, continuous aggregates. PG16 is the current LTS-equivalent for Timescale 2.17. |
| SQLAlchemy | 2.0.36+ | ORM / query builder (async mode) | 2.0 unified API, native asyncio support, declarative models. Use for schema definitions, migrations, and ORM-heavy parts (alerts, locations, sources metadata). |
| asyncpg | 0.30+ | High-performance PG driver | Drives SQLAlchemy async (`postgresql+asyncpg://`). For hot ingest paths (batch inserts of observations) use raw asyncpg `copy_records_to_table` — ~3x faster than ORM inserts. |
| sqlalchemy-timescaledb | 0.4+ | Timescale dialect for SQLAlchemy | Adds `create_hypertable`, compression policies, retention policies as declarative options. Supports both psycopg2 and asyncpg. |
| Alembic | 1.13+ | DB migrations | Standard SQLAlchemy migrations. Configure to autogenerate skipping Timescale internal tables (`_timescaledb_*`). |
| Redis | 7.4.x | Broker (Celery), cache, rate-limit store, WebSocket pub/sub | Owner-declared. Single Redis serves four roles — keeps Docker Compose minimal. Pin `<8.0` for Celery 5.6 compatibility (see Version Compatibility). |
| Celery | 5.6.3 (Feb 2026 "recovery release") | Distributed task queue | Owner-declared. 5.6 adds Pydantic task-arg support and stable Python 3.13 typing. Battle-tested for cron-style ingest. |
| celery[redis] | bundled | Redis broker bindings | Install via extras: `celery[redis]==5.6.3`. |
| Flower | 2.0+ | Celery monitoring dashboard | Self-hosted in Docker Compose, exposes task/worker introspection — essential for a solo dev debugging ingest failures. |
| Angular | 21.2.x (21.2.4 stable, April 2026) | Frontend framework (SSR) | Owner-declared. v21 ships zoneless change detection and Vitest as default test runner — both production-ready. |
| Node.js | 22.x LTS | Build & SSR runtime | Required by Angular 21 (22.x is the current Node LTS line). |
| Leaflet | 1.9.4 | Interactive map for station markers | Owner-declared. Lightweight, no API key, plays well with OSM tiles. |
| Plotly.js | 3.x | Time-series charts | Owner-declared. v3 dropped some legacy traces — use `scattergl` for >10k points instead of removed `pointcloud`. |
### Supporting Libraries — Data Ingestion (Python)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | 0.27+ | Async HTTP client for ARPA scrapers + REST sources | Default HTTP client. Supports HTTP/2, sync+async same API, easy migration from `requests`, excellent test client. Use a single shared `AsyncClient` per ingest task with `limits=httpx.Limits(max_connections=10)` to respect ARPA endpoints. |
| selectolax | 0.3.21+ | Fast HTML parser for ARPA HTML pages | 30x faster than BeautifulSoup, CSS-selector API. Use when an ARPA endpoint returns HTML tables (some regional sites do). |
| parsel | 1.9+ | XPath/CSS selector wrapper on lxml | Use when you need XPath specifically (some ARPA pages have brittle CSS structure but stable XPath). |
| lxml | 5.3+ | XML parsing (transitive + direct) | Required for some ARPA endpoints that publish RSS/XML feeds, and for parsing GRIB metadata when ecmwf-data isn't installed. |
| ecmwf-opendata | 0.3.20+ | ECMWF Open Data downloader | Official client for the free ECMWF Open Data forecast products. Uses MARS-like request syntax. Apache 2.0. |
| cdsapi | 0.7.4+ | Copernicus Climate Data Store (CDS-Beta) | Official Copernicus client. NOTE: existing CDS credentials do not work in CDS-Beta — users need new API keys from cds.climate.copernicus.eu. Long-running requests (ERA5 reanalysis) are queued — implement async polling in a Celery task with retry. |
| cfgrib + eccodes | cfgrib 0.9.14+, eccodes 2.36+ (system lib) | Read GRIB1/GRIB2 files from ECMWF | ECMWF Open Data and CDS often return GRIB. cfgrib reads them via xarray. eccodes is a C system dependency — install in Docker image (`apt-get install libeccodes0`). |
| xarray | 2024.10+ | N-dimensional labeled arrays for GRIB/NetCDF | De-facto standard for gridded weather data. Use to slice GRIB to point-locations before inserting into TimescaleDB. |
| numpy | 2.1+ | Numeric arrays (transitive) | Required by xarray, pandas, metpy. Pin >=2.0 (most weather libs migrated in 2025). |
| pandas | 2.2+ | Tabular ETL, METAR DataFrame output | metpy.io.parse_metar_to_dataframe returns pandas. Useful for bulk transforms before TimescaleDB insert. |
| metpy | 1.7+ | METAR parsing + meteorological calculations | **Recommended over python-metar** for this project: native pandas DataFrame output (drop-in to ingest pipeline), maintained by UCAR/Unidata, includes unit conversions to SI via Pint. python-metar is older, returns Python objects per report — extra glue code. |
| Pint | 0.24+ | Physical units (transitive via metpy) | Use directly when normalizing ARPA values (hPa↔Pa, mm/h↔kg/m²/s, °C↔K) for WMO compliance. |
| tenacity | 9.0+ | Retry with exponential backoff + jitter | Decorate every external HTTP / CDS API call with `@retry(stop=stop_after_attempt(5), wait=wait_random_exponential(min=4, max=60))`. Critical for politeness + resilience. |
| aiocache | 0.12+ (or `redis` directly) | Async cache decorator backed by Redis | Cache HTTP responses (ETag/Last-Modified) for ARPA scraping — politeness requirement from PROJECT.md. |
| pyarrow | 18.0+ | Parquet export endpoint, columnar I/O | FastAPI endpoint streams Parquet via `StreamingResponse`. fastparquet retired March 2026; pyarrow is the only maintained option. |
### Supporting Libraries — FastAPI ecosystem
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| slowapi | 0.1.9+ | Rate limiting, Redis-backed | Standard FastAPI/Starlette rate limiter. IP-based limits per PROJECT.md (`@limiter.limit("60/minute")`). Use `storage_uri="redis://redis:6379"` for multi-worker correctness. |
| python-multipart | >=0.0.18 (FastAPI requirement) | Form parsing | Transitive. Pinned by FastAPI itself. |
| websockets | 13.x | WS protocol implementation | Transitive via Starlette. For Pub/Sub scaling across multiple API containers, use `redis.asyncio` Pub/Sub directly (encode/broadcaster is now archived per 2026 FastAPI discussions). |
| redis (python) | 5.0+ (NOT 6.x — see compat) | asyncio Redis client | Use `redis.asyncio.Redis` for WebSocket pub/sub, cache, and ad-hoc operations. Same client both FastAPI and Celery workers can import. |
| orjson | 3.10+ | Fast JSON serializer | Wire as FastAPI `default_response_class=ORJSONResponse` — 2-3x faster than stdlib json for time-series payloads. |
| python-jose[cryptography] OR pyjwt | 2.9+ (pyjwt preferred) | Optional API key signing (v1.0+ scope per PROJECT.md) | Defer to v1.0+ — initial release is unauthenticated. |
### Supporting Libraries — Angular Frontend
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @bluehalo/ngx-leaflet | 21.x | Angular wrapper for Leaflet | The maintained ngx-leaflet fork (asymmetrik moved to bluehalo). Tracks Angular versions; 21.2.1 matches Angular 21.2. Use this; do NOT use unmaintained `@asymmetrik/ngx-leaflet`. |
| leaflet | 1.9.4 | Map engine | Peer dep of ngx-leaflet. |
| @types/leaflet | 1.9.x | TS types | Dev dep. |
| angular-plotly.js | Latest from `master` branch (NOT npm 3.0.0 — that's from 2019) | Plotly wrapper | **CAVEAT**: npm release cadence has lagged. Verify the latest commit on `plotly/angular-plotly.js` supports standalone components and Angular 21. If broken, fall back to direct Plotly.js integration via a thin custom directive (~60 LoC). Document the decision in ADR. |
| plotly.js-dist-min | 3.x | Plotly runtime | Use the `-dist-min` bundle to avoid module resolution issues in Angular's esbuild pipeline. |
| @angular/ssr | 21.2.x | Server-side rendering | Bundled with Angular 21. Configure carefully with Leaflet — Leaflet touches `window` at import; lazy-import inside `afterNextRender` or `isPlatformBrowser` guard. |
| ng-leaflet-universal | Latest | SSR-safe Leaflet helpers | OPTIONAL: use only if the SSR `window` workaround above proves fragile. Adds dependency surface. |
| rxjs | 7.8+ | Reactive streams | Required by Angular 21. |
| zone.js | Not needed | — | Angular 21 supports zoneless change detection — opt in via `provideZonelessChangeDetection()` for cleaner SSR and better performance. |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Python package manager (Astral) | 2026 standard — 10-100x faster than pip/poetry. Use `uv sync` for reproducible installs in Docker. Replaces poetry for new projects. |
| ruff | Linter + formatter | Replaces flake8 + black + isort. One tool, rust-fast. Pin in `pyproject.toml`. |
| mypy or pyright | Static typing | pyright is faster and more accurate for modern code; mypy has broader ecosystem support. Pick pyright for solo-dev velocity. |
| pytest | 8.3+ | Test runner | Standard. |
| pytest-asyncio | 0.24+ | Async test support | Required for FastAPI/asyncpg tests. Set `asyncio_mode = "auto"` in pyproject. |
| pytest-cov | 5.0+ | Coverage | Enforce 80% per project rules. |
| hypothesis | 6.115+ | Property-based testing | Use for adapter contract tests (WMO unit conversions, METAR parsing edge cases). |
| testcontainers[postgres] | 4.14+ | Spin real TimescaleDB in tests | Use `DockerContainer("timescale/timescaledb:latest-pg16")` — `PostgresContainer` doesn't know about Timescale extension. Apply migrations + `CREATE EXTENSION timescaledb` in fixture. |
| respx | 0.21+ | Mock httpx in unit tests | Mock ARPA endpoints without hitting real servers. |
| vcrpy | 6.0+ | Record/replay HTTP cassettes | Useful for ECMWF/CDS integration tests where mocking the API surface is tedious. |
| docker compose | v2.30+ | Local orchestration | Owner-declared deploy target. Use `compose.yaml` (not legacy `docker-compose.yml`). |
| mkdocs-material | 9.5+ | Documentation site | Owner-declared MkDocs. Material theme is the de-facto standard. |
| mkdocstrings[python] | 0.27+ | API docs from docstrings | Auto-generates reference docs for adapters. |
| pre-commit | 4.0+ | Git hook framework | Run ruff/pyright before commit. |
| Vitest | (bundled with Angular 21) | Frontend test runner | Default in Angular 21 for new projects; 5-10x faster than Karma. |
| Playwright | 1.48+ | E2E tests | Tests SSR + map + chart interactions. |
### Observability
| Tool | Purpose | Notes |
|------|---------|-------|
| structlog | 24.4+ | Structured JSON logging | Bind `trace_id`, `source`, `station_id` to every log. Pair with OTel context vars. |
| opentelemetry-distro[otlp] | 1.28+ | OTel SDK + exporters | `opentelemetry-bootstrap -a install` auto-installs FastAPI / SQLAlchemy / Celery / Redis instrumentation. |
| opentelemetry-instrumentation-fastapi | 0.49b+ | FastAPI auto-instrumentation | Spans for every endpoint, automatic baggage propagation. |
| opentelemetry-instrumentation-sqlalchemy | 0.49b+ | DB span tracing | Surfaces slow Timescale queries. |
| opentelemetry-instrumentation-celery | 0.49b+ | Worker tracing | Trace ingest pipeline end-to-end. |
| prometheus-client | 0.21+ | Native Prometheus metrics | Expose `/metrics` on FastAPI for Prom scrape. Track ingest counters, queue depth (via Celery inspect), HTTP latency histograms. |
| Grafana + Prometheus + Loki + Tempo (LGTM stack) | latest stable | Self-hosted observability backend | Docker Compose profile (optional `observability` profile). Zero-cost open-source stack. Loki ingests structlog JSON; Tempo ingests OTLP traces. |
## Installation
# --- Python (uv) ---
# --- Python dev ---
# System dep for cfgrib (Dockerfile)
# RUN apt-get update && apt-get install -y libeccodes0 libeccodes-tools
# --- Angular (npm) ---
# angular-plotly.js: verify master branch supports Angular 21 first;
# otherwise build a thin custom Plotly directive.
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| TimescaleDB | InfluxDB 3 | Skip — InfluxDB 3 dropped SQL Flux drama is still settling. Timescale's PostgreSQL compatibility unlocks SQLAlchemy, Alembic, BI tools, pgAdmin — irreplaceable for a solo dev. |
| TimescaleDB | ClickHouse | Skip — ClickHouse is excellent at scale but overkill for a single-node open-data project; weak transactional guarantees complicate alert state. |
| Celery + Redis | APScheduler | Use if you NEVER need distributed workers. Climate Pulse plans multiple worker types (ingest, alerts, exports) — Celery's task routing wins. |
| Celery + Redis | Dramatiq | Lighter, cleaner API. Switch only if Celery's complexity bites — Celery is more documented and battle-tested. |
| Celery + Redis | RQ | RQ is simpler but lacks robust scheduling (no native cron equivalent without RQ-Scheduler add-on). |
| Celery + Redis | Arq | Async-native, smaller surface — strong alternative if the team is all-asyncio. Owner declared Celery, so we honor that. |
| httpx | aiohttp | Use for >300 concurrent connections per worker (raw throughput). Not needed for politeness-throttled ARPA scraping. |
| metpy (METAR) | python-metar | Use if you need fine-grained access to remarks (RMK section) — metpy strips most of those. For 99% of use cases, metpy's DataFrame output wins. |
| asyncpg + sqlalchemy-timescaledb | psycopg3 + raw SQL | psycopg3 has improving async support but smaller ecosystem. SQLAlchemy 2.0 + asyncpg is the 2026 standard. |
| @bluehalo/ngx-leaflet | Direct Leaflet integration | Use if ngx-leaflet doesn't track Angular 21 fast enough. The wrapper is thin — a custom `LeafletMapDirective` is ~80 LoC. |
| uv | poetry | Poetry is fine but uv is 10-100x faster; for Docker layer caching this matters. New projects in 2026 should pick uv. |
| pyright | mypy | mypy if you need broader plugin ecosystem (Pydantic v1 plugin etc.). Pyright is faster for solo dev. |
| prometheus-client + Grafana | Sentry / Datadog | Cloud SaaS — violates "zero cloud budget" constraint. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `requests` (sync) | Blocks FastAPI/Celery event loops; no HTTP/2 | `httpx` (sync+async, drop-in API) |
| `fastparquet` | **Retired March 2026** — pandas 3.0 depends on pyarrow exclusively | `pyarrow` |
| `aiopg` | Legacy async PG driver, slower than asyncpg, low maintenance | `asyncpg` + SQLAlchemy 2.0 async |
| `flask-restplus` / `flask-restx` for the API | Sync-only, no OpenAPI 3.1, no native Pydantic | `FastAPI` |
| `encode/broadcaster` for WebSocket pub/sub | **Archived** as of 2026 | `redis.asyncio` Pub/Sub directly, or `python-socketio` with `AsyncRedisManager` |
| `fastapi-socketio` | **Archived** | Native Starlette WebSocket + Redis Pub/Sub |
| `@asymmetrik/ngx-leaflet` | Maintenance moved to `@bluehalo` fork | `@bluehalo/ngx-leaflet` |
| `angular-plotly.js@3.0.0` from npm | Last npm release is from ~2019, predates standalone components | Latest commit from `master` branch, OR build a thin custom directive |
| Karma + Jasmine | Slower than Vitest; Angular 21 default is Vitest | `Vitest` (bundled with Angular 21) |
| `zone.js` change detection | Heavy, slower SSR | `provideZonelessChangeDetection()` (Angular 21 production-ready) |
| InfluxDB | Owner picked TimescaleDB; mixing time-series engines = waste | TimescaleDB hypertables |
| Kafka for ingest | Overkill for cron-style 15min/1h/4cycle ingest; out-of-scope per PROJECT.md | Celery beat with Redis broker |
| Kubernetes / Helm in v1.0 | Out-of-scope; zero cloud budget | Docker Compose with profiles |
| `python-dotenv` standalone | Pydantic Settings handles `.env` natively | `pydantic-settings` |
| `loguru` for production logging | Hard to integrate with OTel context propagation | `structlog` with OTel processor |
## Stack Patterns by Variant
- Use `cdsapi`/`ecmwf-opendata` to download → `xarray.open_dataset(path, engine="cfgrib")` → slice to station lat/lon → batch insert via `asyncpg.copy_records_to_table`.
- Reason: GRIB is gridded; converting to per-station rows must happen before storage.
- `httpx` (with ETag cache via `aiocache`) → `selectolax` for CSS-selector extraction → Pydantic adapter model → SQLAlchemy ORM insert.
- Reason: ARPA HTML is small but politeness-critical; caching avoids re-requests.
- `httpx` → `metpy.io.parse_metar_to_dataframe` (for METAR) or pandas (for CSV) → adapter normalization → batch insert.
- Reason: Already structured; just normalize units.
- Stream Parquet via `pyarrow.RecordBatchStreamWriter` + FastAPI `StreamingResponse`.
- Reason: JSON serialization blows up memory; Parquet is target format for researchers anyway.
- Use `scattergl` trace type instead of `scatter`. (Required — `pointcloud` was removed in Plotly 3.)
- Server-side downsample with TimescaleDB continuous aggregates before sending.
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| FastAPI 0.136 | Starlette >=0.40,<0.46 | Auto-pinned by FastAPI; do not override. |
| FastAPI 0.136 | Pydantic >=2.7 | Pydantic v1 is unsupported. |
| SQLAlchemy 2.0.36 | asyncpg >=0.27 | `postgresql+asyncpg://` URL prefix. |
| sqlalchemy-timescaledb 0.4 | SQLAlchemy 2.0 | Verified compatibility. |
| TimescaleDB 2.17 | PostgreSQL 14/15/**16** | Use PG16 for newest planner features. PG17 support may lag — check docs before upgrading. |
| Celery 5.6.3 | **redis (python) <6.0** | Celery 5.6 pins `redis<6`. Do NOT install `redis==6.x` until Celery 5.7+. |
| Celery 5.6.3 | Redis server 6.x or 7.x | Server-side Redis 7.4 is fine; the constraint is the **Python client** version. |
| Celery 5.6.3 | Python 3.9 – 3.13 | Python 3.12 ✅ |
| Angular 21 | Node.js 20 LTS or 22 LTS | Use 22 LTS for longest support. |
| Angular 21 | TypeScript 5.6+ | Auto-installed. |
| @bluehalo/ngx-leaflet 21.x | Angular 21.x | Major version tracks Angular major. |
| Leaflet 1.9.4 | Modern browsers ES2018+ | No IE11. |
| cdsapi 0.7.4 | **CDS-Beta credentials** | Old CDS API keys are invalid; users must register at cds.climate.copernicus.eu (new platform). |
| cfgrib 0.9.14 | eccodes system lib >=2.30 | Install via apt; do NOT rely on `eccodes` pip wheels in production Docker. |
| pandas 2.2 | pyarrow >=14 | pandas 3.0 (when released) hard-requires pyarrow. |
| ecmwf-opendata 0.3.20 | Python 3.8+ | No special pins. |
| metpy 1.7 | numpy 2.x, pandas 2.x | Verified. |
## Sources
- [FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/) — confirmed 0.136.x (April 2026), Python 3.10–3.14 support, Starlette pin
- [FastAPI on PyPI](https://pypi.org/project/fastapi/) — version verification
- [Angular v21 Release page](https://angular.dev/events/v21) — Nov 2025 GA, 21.2.x current
- [Angular SSR Guide](https://angular.dev/guide/ssr) — hydration timeout diagnostics, zoneless support
- [Ninja Squad — What's new in Angular 21.1](https://blog.ninja-squad.com/2026/01/15/what-is-new-angular-21.1) — Signal Forms, Vitest default
- [Celery 5.6.3 FAQ](https://docs.celeryq.dev/en/stable/faq.html) — Python/Redis client compatibility matrix
- [Celery Routing](https://docs.celeryq.dev/en/latest/userguide/routing.html) — separate queues for beat tasks
- [Programming Helper — Celery 2026 5.6 recovery release](https://www.programming-helper.com/tech/celery-2026-python-distributed-task-queue-redis-rabbitmq) — redis<6 pin, Pydantic task args
- [ecmwf/ecmwf-opendata GitHub](https://github.com/ecmwf/ecmwf-opendata) — official Apache 2.0 client
- [Copernicus CDSAPI setup](https://cds.climate.copernicus.eu/how-to-api) — CDS-Beta migration, credential reset required
- [ECMWF Forum — CDS-Beta is now live](https://forum.ecmwf.int/t/the-new-climate-data-store-beta-cds-beta-is-now-live/3315) — migration notes
- [cdsapi on PyPI](https://pypi.org/project/cdsapi/) — version + Python 3.8+ support
- [python-metar GitHub](https://github.com/python-metar/python-metar) — alternative METAR parser (still active)
- [MetPy parse_metar_to_dataframe docs](https://unidata.github.io/MetPy/latest/api/generated/metpy.io.parse_metar_to_dataframe.html) — DataFrame integration confirmed
- [Tiger Data — Top PostgreSQL Drivers for Python](https://www.tigerdata.com/learn/top-postgresql-drivers-for-python) — asyncpg performance benchmarks
- [SQLAlchemy 2.0 asyncio docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — async configuration patterns
- [sqlalchemy-timescaledb on PyPI](https://pypi.org/project/sqlalchemy-timescaledb/) — Timescale dialect, asyncpg supported
- [Decodo — HTTPX vs Requests vs AIOHTTP 2026](https://decodo.com/blog/httpx-vs-requests-vs-aiohttp) — httpx as the 2026 default
- [Web Scraping FYI — selectolax vs beautifulsoup](https://webscraping.fyi/lib/compare/python-beautifulsoup-vs-python-selectolax/) — 30x speed delta
- [ByteTunnels — Fastest Python Web Scraping Library](https://bytetunnels.com/posts/fastest-python-web-scraping-library-benchmarks/) — selectolax benchmarks
- [slowapi GitHub](https://github.com/laurentS/slowapi) — Redis-backed FastAPI rate limiting
- [tenacity GitHub](https://github.com/jd/tenacity) — exponential backoff + jitter patterns
- [testcontainers-python on PyPI](https://pypi.org/project/testcontainers/) — 4.14.2 (March 2026)
- [Testcontainers Timescale Module](https://testcontainers.com/modules/timescale/) — TimescaleDB container usage
- [SigNoz — OpenTelemetry FastAPI guide](https://signoz.io/blog/opentelemetry-fastapi/) — instrumentation setup
- [johal.in — Structlog + OTel Python 2026](https://johal.in/structlog-json-logs-middleware-opentelemetry-python-2026/) — trace context binding
- [Mojoauth — Serialize/Deserialize Parquet with FastAPI](https://mojoauth.com/serialize-and-deserialize/serialize-and-deserialize-parquet-with-fastapi) — pyarrow streaming response pattern, fastparquet retirement
- [@bluehalo/ngx-leaflet on npm](https://www.npmjs.com/package/@bluehalo/ngx-leaflet) — 21.2.1 confirms Angular 21 tracking
- [angular-plotly.js GitHub](https://github.com/plotly/angular-plotly.js/) — repo state, version tracking caveat
- [Plotly.js v3 changes](https://plotly.com/javascript/version-3-changes/) — pointcloud removal, scattergl migration
- [FastAPI Discussions #14807 — Scalable WebSocket libraries 2026](https://github.com/fastapi/fastapi/discussions/14807) — broadcaster/fastapi-socketio archival, alternatives
- [Pydantic Settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — env / .env loading patterns
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
