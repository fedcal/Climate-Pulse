# Project Research Summary

**Project:** Climate Pulse
**Domain:** Multi-source weather/time-series aggregation pipeline (open-data, EU focus, self-hosted)
**Researched:** 2026-05-23
**Confidence:** HIGH

## Executive Summary

Climate Pulse is an **open-data ETL+serve pipeline** for European weather observations: heterogeneous public sources (ARPA regional Italy via polite scraping, ECMWF Open Data GRIB, NOAA METAR, Copernicus C3S CDS) are normalized to WMO variables in SI units, persisted in a TimescaleDB hypertable with continuous aggregates, and exposed via a FastAPI public REST + WebSocket API and an Angular 21 SSR dashboard with Leaflet map + Plotly charts. The architectural shape — pluggable source adapters → Celery cron workers → TimescaleDB → FastAPI → SSR dashboard — is the established convention for this category (used by Open-Meteo, Bright Sky, wetterdienst, and ECMWF's own stack). The owner's pre-declared stack (FastAPI 0.115+, Python 3.12, TimescaleDB, Angular 21 SSR, Leaflet, Plotly, Celery, Redis) is validated by the research and pinned to current 2026 versions (FastAPI 0.136, Angular 21.2, Celery 5.6.3, TimescaleDB 2.17 on PG16, Node 22 LTS).

The unique value vs. existing competitors is the **combination** of (a) multi-source EU aggregation with **explicit per-row provenance + WMO quality flags**, (b) Italian regional ARPA coverage at the **raw observation level** (Open-Meteo only exposes the ICON-2I forecast model, not raw ARPAE/ARPAL/ARPAV stations), (c) MIT license + self-hosted Docker Compose first-class, and (d) WebSocket live updates + threshold alerts in a single package. The MVP scope (5 coarse phases targeting v1.0 in Q3 2026) is well-bounded by PROJECT.md and the research confirms no scope creep is required to be competitive in this niche.

The dominant risks are **operational, not architectural**: (1) TimescaleDB hypertable design (wrong `chunk_time_interval`, missing time in PK, mis-ordered compression/CAGG/retention policies) is hard to reverse at scale and must be right on day one; (2) ARPA scraping politeness (User-Agent, robots.txt, per-host rate limit, snapshot fallback, exponential backoff) is a community/legal risk that gates project survival; (3) Celery idempotency + Beat-as-singleton are non-negotiable to avoid duplicate ingestion; (4) timezone handling (`Europe/Rome` naive timestamps from ARPA) and unit normalization (°C / K / hPa / Pa / knots / m/s) are silent-corruption traps that must be solved at the adapter boundary; (5) Angular SSR + Leaflet/Plotly hydration requires `afterNextRender` + `isPlatformBrowser` guards. All are well-documented with clear mitigations.

## Key Findings

### Recommended Stack

The owner's declared stack is validated end-to-end. Research adds prescriptive **version pins**, the **specific glue libraries** required to assemble the system, and **explicit warnings** about archived or retired dependencies (encode/broadcaster, fastapi-socketio, fastparquet, @asymmetrik/ngx-leaflet, angular-plotly.js@3.0.0 from npm).

**Core technologies (final, version-pinned):**

| Layer | Tech | Version | Why |
|-------|------|---------|-----|
| Language (backend) | Python | 3.12.7+ | All weather libs (cdsapi, ecmwf-opendata, metpy, cfgrib) tested against 3.12; 3.13 still has JIT churn |
| API framework | FastAPI | 0.136.x | OpenAPI 3.1, Pydantic v2 native, async-first |
| ASGI runtime | Uvicorn 0.32+ behind Gunicorn 23 (`UvicornWorker`) | — | Graceful reloads + worker recycling in Docker |
| Validation | Pydantic 2.9+ + pydantic-settings 2.5+ | — | v2 mandatory; pydantic-settings loads `.env` |
| Database | TimescaleDB | 2.17 on PostgreSQL 16 | Hypertables, chunk compression, continuous aggregates, full PG ecosystem |
| DB driver | asyncpg 0.30+ (hot path: raw `copy_records_to_table`) | — | ~3× faster than ORM for bulk inserts |
| ORM | SQLAlchemy 2.0.36+ (async) + sqlalchemy-timescaledb 0.4+ + Alembic 1.13+ | — | ORM only for metadata (stations, variables, sources, alerts) — never for observation hot path |
| Broker / cache / rate-limit / pub-sub | Redis | 7.4 (server) + `redis` Python client `<6.0` | Single Redis serves four roles; **Celery 5.6.3 pins redis<6** |
| Task queue | Celery | 5.6.3 (Feb 2026 recovery release) | Cron-style ingest, retry, DLQ, Pydantic task args |
| Worker observability | Flower 2.0+ | — | Essential for solo-dev debugging |
| HTTP client (ingest) | httpx 0.27+ | — | Async, HTTP/2, polite client |
| HTML scraping | selectolax 0.3.21+ (CSS) + parsel 1.9+ (XPath fallback) + lxml 5.3+ | — | selectolax is 30× faster than BeautifulSoup |
| Weather data | ecmwf-opendata 0.3.20+, cdsapi 0.7.4+ (CDS-Beta credentials required), cfgrib 0.9.14+ + system `libeccodes0`, xarray 2024.10+, metpy 1.7+ (METAR → DataFrame), Pint 0.24+ (units), pandas 2.2+, numpy 2.1+ | — | metpy preferred over python-metar for native DataFrame output |
| Retry / cache | tenacity 9.0+, aiocache 0.12+ (Redis-backed HTTP cache) | — | Exponential backoff + jitter mandatory for politeness |
| Export | pyarrow 18.0+ (Parquet streaming via `StreamingResponse`) | — | fastparquet retired March 2026 |
| Rate limit | slowapi 0.1.9+ (Redis storage) | — | Per-IP token bucket; multi-worker correct |
| Serializer | orjson 3.10+ as FastAPI default response class | — | 2-3× faster JSON for time-series payloads |
| Frontend | Angular 21.2.x on Node.js 22 LTS, zoneless change detection (`provideZonelessChangeDetection()`), Vitest (default) | — | Owner-declared, validated |
| Map | Leaflet 1.9.4 + `@bluehalo/ngx-leaflet` 21.x (NOT `@asymmetrik/ngx-leaflet`) | — | bluehalo is the maintained fork tracking Angular majors |
| Charts | `plotly.js-dist-min` 3.x; angular-plotly.js from **master** branch (npm 3.0.0 is from 2019) OR custom 60-LoC directive | — | Use `scattergl` for >10k points (`pointcloud` removed in v3) |
| SSR | `@angular/ssr` 21.2.x with lazy `import('leaflet')` inside `afterNextRender` | — | Leaflet touches `window` at import |
| Observability | structlog 24.4+, OpenTelemetry distro 1.28+ (FastAPI + SQLAlchemy + Celery + Redis auto-instrumentation), prometheus-client 0.21+, self-hosted LGTM stack (Grafana + Prometheus + Loki + Tempo) as optional `observability` Compose profile | — | Zero cloud budget; LGTM is fully self-hosted |
| Dev tooling | uv (10-100× faster than pip/poetry), ruff (lint+format), pyright (typing), pytest 8.3+ + pytest-asyncio + pytest-cov + hypothesis + testcontainers[postgres] 4.14+ + respx + vcrpy, pre-commit 4.0+, Playwright 1.48+ (E2E) | — | uv is the 2026 standard |
| Deploy | Docker Compose v2.30+ (`compose.yaml`), Caddy or nginx reverse proxy with Let's Encrypt | — | Owner-declared; zero cloud budget |
| Docs | MkDocs Material 9.5+ + mkdocstrings[python] 0.27+ → published to **GitHub Pages** via GitHub Action **from v0.1 onwards** | — | Hard requirement: docs ship with first release |

**Explicit do-not-use list (would silently rot the project):** `requests` (sync), `fastparquet` (retired), `aiopg`, `flask-restplus`, `encode/broadcaster` (archived), `fastapi-socketio` (archived), `@asymmetrik/ngx-leaflet`, `angular-plotly.js@3.0.0` from npm, Karma + Jasmine, `zone.js` change detection, InfluxDB, Kafka, Kubernetes/Helm, `python-dotenv`, `loguru` for production.

### Expected Features

**Must have (table stakes for v1.0 — users assume these exist):**

- Time-series query by lat/lon (nearest station) OR `station_id` with period + variable filters
- Station discovery API (bbox / country / source filters, pagination)
- Station metadata endpoint (elevation, source, WMO ID, temporal coverage)
- Hourly + daily granularity (served from continuous aggregates, not raw)
- WMO-standard variables in SI units (T, RH, P, wind, precip, radiation, cloud cover)
- CSV + JSON + Parquet export (streaming for large queries)
- Per-IP rate limiting (Redis token bucket) with `X-RateLimit-*` headers
- OpenAPI 3.1 spec + Swagger/Redoc UI
- Interactive Leaflet map with clustered station markers
- Plotly time-series chart with variable selector + date range
- Celery cron ingestion with retry + DLQ + snapshot fallback
- **Source provenance per data point** + **per-measurement WMO quality flag** (good/suspect/missing/interpolated)
- Pagination (cursor-based for time-series; offset breaks at scale)
- `/healthz` + `/readyz` endpoints
- MkDocs documentation site **published to GitHub Pages from v0.1**
- Footer `federicocalo.dev` attribution on every dashboard page and every docs page

**Should have (differentiators vs Open-Meteo / Tomorrow.io / Meteostat / Bright Sky):**

- **Multi-source aggregation with explicit per-row provenance** — commercial APIs (Tomorrow.io) and open-source aggregators (Open-Meteo) blend sources opaquely; we never collapse provenance and allow `?sources=arpae,ecmwf` filtering
- **Italian regional ARPA coverage at observation level** — Open-Meteo only exposes the ICON-2I forecast model, not raw ARPAE/ARPAL/ARPAV stations
- WebSocket live updates `/v1/ws/observations` (Bright Sky / wetterdienst don't have this)
- Multi-station comparison view (side-by-side time-series with synchronized cursor)
- Configurable threshold alerts (webhook + email) for agriculture/renewable SMEs
- Self-hosted Docker Compose first-class (competitors are SaaS-locked)
- Source health dashboard (`/v1/sources/status`) — transparency about ingestion freshness
- Reproducible / citation-friendly query URLs
- Snapshot fallback + scraping politeness (builds trust with ARPA data providers)

**Defer to v1.1+:**

- Copernicus C3S adapter (large/complex CDS API — keep in v1.0 only if scope permits; otherwise defer)
- Bulk per-station-per-year archive downloads
- Auto-generated SDKs (Python + TypeScript via openapi-generator)
- Optional API key tier for higher rate limits
- Heatmap / choropleth spatial overlay
- Additional ARPA regions beyond initial 2-3 (community PRs)

**Defer to v2+:** spatial interpolation between stations, derived variables (heat index, wet-bulb), radar/satellite imagery, climate normals/anomaly endpoints, R/Julia SDKs, federation across instances.

### Anti-Features — Explicitly NOT Building

Consolidated from PROJECT.md out-of-scope + research-discovered traps. **All of these have been considered and rejected** with clear rationale:

- **Proprietary forecasting models / ML predictions** — Climate Pulse aggregates observations and re-serves third-party model outputs (ECMWF, ICON-2I); building proprietary forecasts is a different product
- **OAuth / SSO user authentication** — public open-data API; auth adds friction for the Jupyter-notebook researcher persona (optional API key tier may come in v1.1+, not full user auth)
- **Real-time Kafka streaming** — ARPA cadence is 15min, ECMWF 4×/day, METAR hourly; Celery cron is sufficient. WebSocket gives the "live feel" without Kafka operational complexity
- **Kubernetes / Helm chart deployment** — zero cloud budget, solo dev; Docker Compose only in v1.0
- **Multi-tenancy / SaaS billing** — conflicts with MIT/open-data philosophy
- **Mobile native apps (iOS/Android)** — Angular 21 SSR with responsive layout (optionally PWA) is sufficient
- **Global coverage beyond EU + global METAR** — EU focus is the differentiator; forks handle other continents
- **Push notifications (mobile / browser VAPID)** — webhook + email already cover the alert channel; users pipe webhooks to Slack/Telegram/PagerDuty
- **User-uploaded citizen-science weather stations** — QC nightmare (Personal Weather Stations have documented quality issues per HESS); out of scope
- **Built-in BI / dashboard builder (Grafana-style)** — reinvents Grafana; document how to connect Grafana directly to TimescaleDB instead
- **Live radar / satellite imagery layers** — storage cost + licensing prohibitive for self-host
- **Air quality / pollutant data** — different domain (chemistry, not meteorology); fork-friendly via adapter pattern but not in core
- **GraphQL endpoint** — REST + OpenAPI is sufficient and lower-maintenance; URL-as-citation suits research use
- **Proprietary derived variables** ("feels-like" temp formulas) — risk of opinionated wrong formulas; expose raw data only
- **In-app data annotations / collaboration features** — requires user accounts (anti-feature); citation URLs are the collaboration substrate
- **Custom hand-rolled METAR parser** — silent data loss on VRB/CAVOK/RVR/NIL/AUTO edge cases; always use `metpy` or `python-metar`

### Architecture Approach

The pipeline follows the standard "ETL + serve" topology for weather aggregation. A thin **plug-in adapter layer** (`WeatherSourceAdapter` ABC + registry, one file per source) normalizes wildly different upstream formats into canonical `Observation` records. **Celery Beat** schedules per-source cron tasks; **Celery workers** consume named queues (`ingest`, `normalize`, `alerts`, `dlq`) with retry and exponential backoff. The **normalizer** translates to WMO variable codes + SI units + QC flags. The **writer** batch-inserts via raw asyncpg `COPY` with `ON CONFLICT … DO UPDATE` for idempotency. **TimescaleDB** stores observations in a narrow hypertable partitioned daily, with hierarchical continuous aggregates (`obs_hourly`, `obs_daily`), native compression after 7 days, and configurable retention. **FastAPI** routes time-series reads to the coarsest sufficient aggregate via a resolution resolver. **Redis pub/sub** fans new-observation events to WebSocket subscribers. **Angular 21 SSR** dashboard renders the shell server-side; Leaflet and Plotly init only in the browser via `afterNextRender` + `isPlatformBrowser` guards.

**Major components:**

1. **Source Adapters** (`packages/core/.../adapters/`) — one Python module per source implementing the ABC; pluggable via decorator registry
2. **Polite HTTP Client** — shared `httpx.AsyncClient` wrapper enforcing identifying User-Agent, robots.txt compliance (per-host cached 24h), per-host rate limit shared across workers via Redis, ETag/Last-Modified cache via aiocache, tenacity exponential backoff with jitter, snapshot fallback
3. **Normalizer** — pure functions per source mapping raw payloads to WMO variables in SI units via Pint; emits `quality_flag` per measurement
4. **Celery Worker Tier** — separate from API container (heavier deps: xarray, eccodes, cfgrib); separate `beat` service (singleton, never colocated with worker)
5. **TimescaleDB Hypertable** — single narrow `observations` table keyed `(station_id, variable_id, observed_at, source_id)`; compression `segmentby=(station_id, variable_id)`; hierarchical CAGGs; policy ordering `refresh_lag < compress_after < retention`
6. **FastAPI Read Layer** — `apps/api/queries/` uses hand-written SQL against the right table/CAGG; resolution resolver picks raw vs hourly vs daily; ORM only for metadata
7. **Redis Pub/Sub Fanout** — writer `PUBLISH`es to `obs:{source}:{station}` channels; API subscribes and forwards to WebSocket clients (at-most-once is acceptable; Postgres is canonical)
8. **Angular SSR Dashboard** — `apps/dashboard/` with `features/map`, `features/station`, `features/compare`; typed `ApiClient` generated from OpenAPI 3.1 schema
9. **Docs Tier** — MkDocs Material built and deployed to GitHub Pages via GitHub Action on every push to `main`; footer customized with `federicocalo.dev` attribution
10. **Reverse Proxy** — Caddy or nginx terminating TLS (Let's Encrypt) in front of API + dashboard

**Project layout:** monorepo with `apps/{api,worker,dashboard}` + `packages/{core,migrations}` + `infra/` (Docker Compose, Dockerfiles) + `docs/` + `tests/{unit,integration,e2e}`. `uv` workspace at repo root.

### Critical Pitfalls (top 5-7 driving architectural choices)

1. **TimescaleDB hypertable design (PK + chunk interval + policy ordering)** — Use `PRIMARY KEY (station_id, variable_id, observed_at, source_id)` with **time column always included**; initial `chunk_time_interval => INTERVAL '7 days'` (validated empirically with `chunks_detailed_size`); policy ordering must be `refresh_lag < compress_after < retention_after`. Wrong choices are irreversible at scale; this gates all storage decisions.

2. **Idempotent ingestion (`ON CONFLICT … DO UPDATE` + `acks_late=True` + visibility_timeout > runtime × 2)** — Celery+Redis is at-least-once by design; retries and visibility-timeout expiries will re-fire tasks. Without `ON CONFLICT` keyed on the natural composite key, duplicates corrupt the time-series silently. Non-negotiable.

3. **Scraping politeness (identifying User-Agent + robots.txt + per-host rate limit + snapshot fallback + exponential backoff)** — ARPA endpoints are public but rate-limited at the network edge by some regions; a hammering scraper risks IP ban and project shutdown. Build the polite HTTP client **first**, before any adapter. Document in `docs/scraping-policy.md` for ARPA admin transparency.

4. **Celery Beat as singleton (dedicated `beat` service, never `--beat` on workers)** — Colocating Beat with workers means `docker compose scale worker=3` triggers each cron 3×. Beat lives in its own Compose service with `restart: unless-stopped`; document "do not scale `beat` > 1" in README; consider `celery-redbeat` for Redis-backed lock as belt-and-suspenders.

5. **Timezone + unit normalization at the adapter boundary** — ARPA Lombardia returns naive `Europe/Rome` ISO strings (DST trap: October 02:30 appears twice, March 02:30 is missing). All DB timestamps are `TIMESTAMPTZ` in UTC; adapter attaches `zoneinfo.ZoneInfo("Europe/Rome")` then `.astimezone(UTC)`. Units: convert to SI at the adapter using Pint (never magic-number multiplication); range-validate per variable; outliers flagged `quality_flag='range_violation'`, never silently dropped. Property-based tests for round-trips; explicit DST tests for March + October.

6. **API queries hit continuous aggregates, not raw hypertable** — Dashboard P95 latency depends on a resolution resolver that routes range >= 1d to `obs_daily`, 1h–1d to `obs_hourly`, <1h to raw. `EXPLAIN ANALYZE` in CI fails if any non-export endpoint touches > 10 chunks. Also: public API rate limit on day one (`slowapi` + Redis, 60/min stations, 30/min observations, 10/min export) — open APIs without rate limit get DoS'd by first scraper.

7. **Angular SSR + Leaflet/Plotly hydration** — Both libraries touch `window` at import and do imperative DOM manipulation. Wrap map/chart components with `ngSkipHydration` or `afterNextRender` lifecycle; dynamic `import('leaflet')` only in browser; render skeleton server-side. CI runs headless SSR per route and asserts no `NG0500/NG0501` hydration errors.

**Also high-priority (must address but less architecturally load-bearing):** CDS API quota / queue (submit + poll pattern, dedicated low-concurrency queue), METAR parser edge cases (always use library), Compose healthchecks (`condition: service_healthy`), secret management (`.env` + gitleaks pre-commit), GDPR-aware logging (IP truncation, log retention).

## Implications for Roadmap

Based on combined research, **5 coarse phases** (matching PROJECT.md "coarse 3-5 phases" granularity). Each phase ends with something demonstrably useful; the end-to-end thinnest slice ships first to validate every architectural assumption early (per PROJECT.md core value: "se l'intera catena ingestion → storage → query → visualizzazione non funziona, il progetto non ha valore").

### Phase 1: Foundation slice (end-to-end thinnest pipeline)
**Rationale:** Prove every architectural risk with the thinnest possible vertical slice + ship docs from day one. If anything is wrong with the foundations, discovery happens immediately, not in Phase 4.
**Delivers:**
- Monorepo skeleton (uv workspace, `apps/{api,worker,dashboard}`, `packages/{core,migrations}`, `infra/`, `docs/`, `tests/`)
- TimescaleDB hypertable + Alembic migrations + raw SQL for `create_hypertable`, 1 continuous aggregate (`obs_hourly`), compression policy, retention policy (correct ordering)
- `WeatherSourceAdapter` ABC + registry + polite HTTP client (User-Agent, robots.txt, Redis-shared rate limit, aiocache ETag, tenacity backoff, snapshot fallback)
- ONE ARPA regional adapter (Emilia-Romagna — Arpae has the best-documented open data) + ONE model adapter (ECMWF Open Data) → validates both station-based and grid-based source shapes
- Normalizer with WMO mapping for 5 core variables (T, RH, P, wind, precip) in SI units via Pint; range validation; quality flags
- Celery worker + dedicated Beat service + DLQ; idempotent writer with `ON CONFLICT DO UPDATE`
- Docker Compose v2.30+ skeleton (`compose.yaml`) with healthchecks + `condition: service_healthy`
- `.env.example` + gitleaks pre-commit + GitHub Actions CI (pytest + ruff + pyright)
- **MkDocs Material site bootstrapped + GitHub Pages deploy Action** (PROJECT.md hard requirement: docs from v0.1)
- **`federicocalo.dev` footer in MkDocs theme** (PROJECT.md hard requirement)
- Backfill CLI; testcontainers-based integration tests; 70%+ coverage on adapters

### Phase 2: Public API
**Rationale:** Read path goes live; data becomes consumable; OpenAPI spec stable for downstream dashboard generation.
**Delivers:**
- FastAPI app with `/v1/stations`, `/v1/stations/{id}`, `/v1/observations` (with resolution resolver: raw/hourly/daily), `/v1/sources`, `/v1/sources/status`, `/v1/meta/variables`
- CSV + JSON + Parquet streaming export (pyarrow `StreamingResponse`)
- Redis-backed slowapi rate limit with `X-RateLimit-*` headers (day-one, not "later")
- OpenAPI 3.1 spec + Swagger/Redoc UI; orjson default response class; gzip; CORS; request-id middleware
- `/healthz` + `/readyz` checking DB + Redis + Celery worker heartbeat
- Cursor pagination (not offset); statement_timeout per Postgres role
- structlog + OpenTelemetry FastAPI/SQLAlchemy/Redis instrumentation; prometheus-client `/metrics`
- GDPR-aware logging (IP truncation to /24 IPv4 / /48 IPv6; configurable log retention)
- MkDocs expanded with API reference (mkdocstrings) + "How to cite" page

### Phase 3: Dashboard MVP (Angular 21 SSR)
**Rationale:** Visual product accelerates feedback for solo dev; typed `ApiClient` from stable OpenAPI 3.1 spec dramatically reduces dashboard rework.
**Delivers:**
- Angular 21 SSR app with zoneless change detection + Vitest tests
- Typed `ApiClient` auto-generated from OpenAPI 3.1 schema
- Leaflet map (lazy-loaded inside `afterNextRender` + `isPlatformBrowser` guard) with marker clustering for station discovery
- Station detail page with Plotly time-series chart (variable selector, date range picker)
- Source attribution UI on every chart (source, license, last-updated badge)
- **`federicocalo.dev` footer in dashboard layout** present on every route (PROJECT.md hard requirement)
- SSR build smoke test in CI (no `NG0500/NG0501` hydration errors per route)
- Lighthouse perf budget in CI (Plotly bundle subsetting: `plotly.js-basic-dist` or custom build)
- Dockerfile for Node SSR runtime; Compose integration; reverse proxy (Caddy/nginx) wiring with Let's Encrypt

### Phase 4: Live updates + Exports breadth + Source breadth
**Rationale:** WebSocket fan-out depends on stable ingest stream (only safe after Phases 1-2); additional sources benefit from working dashboard for visual validation.
**Delivers:**
- WebSocket `/v1/ws/observations` + Redis pub/sub from writer (`obs:{source}:{station}` channels)
- Dashboard live-chart hydration (subscribe on station detail / compare views)
- Multi-station comparison view (2-4 stations side-by-side, synchronized cursor, Plotly subplot grid)
- NOAA METAR adapter (using `metpy.io.parse_metar_to_dataframe`; test corpus 100+ real METARs covering VRB/CAVOK/RVR/NIL/AUTO)
- 2 more ARPA regional adapters (Lombardia + Veneto)
- Copernicus C3S adapter (CDS-Beta credentials; submit + poll pattern; dedicated low-concurrency queue `-Q ecmwf -c 1`) — **may defer to v1.1 if scope tight per FEATURES.md**
- Source health dashboard page (consumes `/v1/sources/status`)
- Backfill CLI polish (split by day to control transaction size)
- Compression policy + retention policy validated in production

### Phase 5: Alerts + Ops + v1.0 polish
**Rationale:** Alert evaluation requires stable ingestion stream to test against and cannot ship before users see data in the dashboard. Bundles all "release polish".
**Delivers:**
- Alert rules table; `tasks.alerts.evaluate` periodic Celery task; webhook (HMAC-SHA256 signed; SSRF allow-list) + email (aiosmtplib) delivery with retry
- Alerts UI in dashboard
- Flower for Celery monitoring; LGTM observability profile (`docker compose --profile observability up`)
- DLQ CLI (`climatepulse dlq list/replay/drop`)
- GDPR-aware logging review; privacy notice in docs
- Security pass: SRI hashes for any CDN-loaded assets, internal endpoints `include_in_schema=False`, robots.txt verifier as adapter unit test, secret rotation runbook
- Contributor docs ("How to add a new ARPA region")
- Release checklist; `v1.0.0` tag; release notes; docs versioning on GitHub Pages
- Final audit against "Looks Done But Isn't" checklist from PITFALLS.md

### Phase Ordering Rationale

- **End-to-end thinnest slice first (Phase 1)** because PROJECT.md core value states the project has no value unless the whole chain works.
- **API before Dashboard (Phase 2 before Phase 3)** because a typed `ApiClient` generated from a stable OpenAPI 3.1 spec dramatically reduces dashboard rework.
- **Dashboard before more sources / WebSocket (Phase 3 before Phase 4)** because visible product accelerates feedback and motivation for a solo dev.
- **Live updates + source breadth in Phase 4** because WebSocket fan-out depends on a stable ingest stream and additional sources benefit from a working dashboard for visual validation.
- **Alerts last (Phase 5)** because alert evaluation requires a stable ingestion stream to test against.
- **Docs ship in every phase, not at the end** — PROJECT.md mandates MkDocs on GitHub Pages from v0.1; bootstrapped in Phase 1, expanded each phase. `federicocalo.dev` footer satisfied in Phase 1 (MkDocs theme) and Phase 3 (Angular layout).

### Research Flags

**Phases likely needing deeper research during planning (`/gsd:plan-phase --research-phase <N>`):**

- **Phase 1 (Foundation):** TimescaleDB-specific decisions are irreversible at scale and benefit from one more targeted pass — specifically (a) empirical validation of `chunk_time_interval` against expected ingestion volume, (b) exact policy ordering values, (c) Alembic + raw SQL migration pattern for hypertable + CAGG DDL. The `WeatherSourceAdapter` ABC contract (especially around gridded GRIB sources) also warrants a focused design pass.
- **Phase 4 (Live + Exports + Source breadth):** Copernicus CDS-Beta integration is the highest-uncertainty item (queue semantics, request size limits, GRIB parsing memory profile); METAR edge case corpus assembly needs a small focused effort.

**Phases with standard / well-documented patterns (likely skip research-phase):** Phase 2, Phase 3, Phase 5.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Owner pre-declared core; research validated all versions against 2026 official sources; MEDIUM only on `angular-plotly.js` (fallback to custom directive documented) |
| Features | HIGH | Competitive landscape exhaustively documented; differentiator gap clear; MEDIUM only on exact ARPA regional endpoint specifics |
| Architecture | HIGH | Standard ETL + serve pattern with extensive precedent; TimescaleDB + Celery + FastAPI + Angular SSR specifics verified |
| Pitfalls | HIGH | TimescaleDB ops, Celery semantics, scraping politeness verified; MEDIUM only on Angular SSR + Leaflet/Plotly hydration specifics and per-region ARPA behavior |

**Overall confidence:** HIGH — well-scoped project, mature stack, conventional architecture, documented mitigations.

### Gaps to Address

- **Per-region ARPA endpoint behavior** — only discoverable empirically. Mitigation: build polite client + ABC in Phase 1, add one ARPA region, iterate; per-adapter `last_successful_ingest_at` metric + canary alerts.
- **Copernicus CDS-Beta exact queue/quota behavior** — account-specific. Mitigation: dedicated low-concurrency queue, submit+poll, defer to Phase 4 or v1.1.
- **`angular-plotly.js` Angular 21 compatibility** — verify in Phase 3; fallback ~60-LoC custom directive (ADR documented).
- **Exact `chunk_time_interval` value** — bake empirical validation into Phase 1 acceptance criteria.
- **WMO variable code dictionary completeness** — `variables` table as registry, new variables = data migration not schema migration.
- **Reverse proxy choice (Caddy vs nginx)** — default Caddy for solo dev / community ease (auto Let's Encrypt); nginx documented as alternative.

## Sources

### Primary (HIGH confidence)
- FastAPI release notes (0.136.x, April 2026); Angular v21 release page (Nov 2025 GA); Celery 5.6.3 FAQ + Periodic Tasks docs
- TimescaleDB official docs: hypertables, continuous aggregates, compression, policies, chunk_time_interval; TigerData forum + blog
- ECMWF Open Data Python package; Copernicus CDSAPI setup (CDS-Beta migration); CDS forum
- SQLAlchemy 2.0 asyncio docs; sqlalchemy-timescaledb on PyPI; MetPy `parse_metar_to_dataframe` docs
- @bluehalo/ngx-leaflet on npm; Plotly.js v3 changes; Angular Hydration guide; Leaflet SSR compatibility discussion
- Docker Compose depends_on healthcheck reference; Mindful Chase TimescaleDB troubleshooting
- HESS QC algorithms for rainfall data

### Secondary (MEDIUM confidence)
- Open-Meteo, Meteostat, Bright Sky, wetterdienst public docs; Tomorrow.io / OpenWeatherMap / Visual Crossing / Xweather public docs
- NOAA CDO Web Services + NWS api.weather.gov FAQ
- Dati Arpae; ARPA Lombardia data access; MISTRAL portal paper; ARPALData R package paper; WMO/ECMWF Data Quality Monitoring System
- Web Scraping FYI (selectolax benchmarks); SigNoz OpenTelemetry FastAPI guide; johal.in structlog+OTel 2026 patterns
- FastAPI WebSocket community references (broadcaster/fastapi-socketio archival, Redis pub/sub); Celery Beat singleton patterns; celery-redbeat

### Tertiary (LOW confidence — validate during implementation)
- `angular-plotly.js` master branch Angular 21 compatibility (Phase 3); ARPA regional endpoint schemas per region (per-adapter); empirical `chunk_time_interval` at production ingest rate (Phase 1)

---
*Research completed: 2026-05-23*
*Ready for roadmap: yes*
