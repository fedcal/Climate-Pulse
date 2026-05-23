# Roadmap: Climate Pulse

**Project:** Climate Pulse — Multi-source EU weather aggregation pipeline
**Target release:** v1.0.0, Q3 2026
**Mode:** Vertical MVP (every phase delivers an end-to-end user-visible capability)
**Granularity:** coarse (5 phases)
**Created:** 2026-05-23

## Core Value

End-to-end multi-source meteo pipeline: aggregate public EU sources (ARPA, ECMWF, NOAA, Copernicus) into a queryable public API + usable dashboard. If the entire chain ingestion → storage → query → visualization doesn't work, the project has no value. Each phase therefore ships a thinner-but-complete slice of that chain.

## Phases

- [ ] **Phase 1: Foundation Slice + Public Docs** - End-to-end thinnest pipeline (1 ARPA + ECMWF → TimescaleDB → CLI query) + MkDocs on GitHub Pages live with `federicocalo.dev` footer
- [ ] **Phase 2: Public REST API** - FastAPI public read API (stations / observations / sources / exports / OpenAPI / rate limit) with API reference docs
- [ ] **Phase 3: Angular Dashboard MVP** - Angular 21 SSR dashboard (map + station detail chart + source health) with `federicocalo.dev` footer
- [ ] **Phase 4: Live Updates + Source Breadth** - WebSocket live feed, multi-station compare, METAR + 2 more ARPA regions + Copernicus, reverse proxy with TLS
- [ ] **Phase 5: Alerts + Ops Hardening + v1.0 Release** - Threshold alerts (webhook/email), observability profile, DLQ CLI, security pass, contributor docs, v1.0.0 release

## Phase Details

### Phase 1: Foundation Slice + Public Docs
**Goal:** Validate the entire architectural spine end-to-end with the thinnest possible vertical slice, and ship public documentation from day one.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** ING-01, ING-02, ING-03, ING-04, ING-09, ING-10, ING-11, ING-12, ING-13, ING-14, STO-01, STO-02, STO-03, STO-04, STO-05, STO-06, OPS-01, OPS-07, OPS-08, OPS-09, DOC-01, DOC-02, DOC-03, DOC-05, API-10
**Success Criteria** (what must be TRUE):
  1. A self-hoster can run `docker compose up` on a fresh machine and within 10 minutes have TimescaleDB ingesting real observations from ARPA Emilia-Romagna and ECMWF Open Data (raw + hourly continuous aggregate populated).
  2. A developer can run `climatepulse backfill arpae --from 2026-05-01 --to 2026-05-07` and verify idempotent rows in the `observations` hypertable (re-running the command produces zero duplicates).
  3. The MkDocs Material documentation site is live on GitHub Pages at the project URL, auto-deployed on every push to `main`, and every page shows a `federicocalo.dev` clickable footer.
  4. A reader of the docs can follow the quickstart page to bring up the stack and run their first `psql` query against the hypertable.
  5. CI (GitHub Actions) blocks any PR that breaks pytest, ruff, pyright, or leaks a secret detected by gitleaks.
  6. The /healthz endpoint returns 200 with {"status":"ok"} on container start and /readyz returns 200 with {"status":"ready"} once TimescaleDB, Redis and Celery worker are all healthy (D-14 anticipation of API-10).
**Plans:** 2/5 plans executed
Plans:
- [x] 01-01-PLAN.md — uv workspace scaffold + MkDocs Material site live on GitHub Pages + CI gates (DOC-01/02/03/05 + OPS-07/08/09)
- [x] 01-02-PLAN.md — Alembic migrations + BOTH TimescaleDB hypertables (D-23) + CAGGs + compression + retention + testcontainers integration tests (STO-01..06)
- [ ] 01-03-PLAN.md — Core ingestion machinery: WeatherSourceAdapter ABC + PoliteHttpClient + WMO Normalizer + DST-safe timezone + IdempotentWriter dual-hypertable routing + per-source health metric (ING-01/02/09/10/12/14)
- [ ] 01-04-PLAN.md — ARPA Emilia-Romagna adapter + ECMWF Open Data adapter (EU bbox + cfgrib) + Backfill CLI + 5 VCR cassettes (ING-03/04/13)
- [ ] 01-05-PLAN.md — Celery worker + dedicated singleton Beat + 4 queues + FastAPI minimal /healthz + /readyz + Docker Compose + REQUIREMENTS/ROADMAP D-14 migration + acceptance demo (ING-11 + OPS-01 + API-10)
**UI hint:** no

### Phase 2: Public REST API
**Goal:** Make the ingested data publicly queryable through a versioned, documented, rate-limited REST API — the integration surface external researchers and downstream tooling will consume.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** API-01, API-02, API-03, API-04, API-05, API-06, API-08, API-09, API-11, API-12, API-13, OPS-04, OPS-10, DOC-04
**Success Criteria** (what must be TRUE):
  1. A researcher can call `GET /v1/observations?station_id=...&variable=air_temperature&start=...&end=...` and receive a paginated, source-attributed, quality-flagged JSON response in under 1s P95 for a 30-day window (CAGG-routed).
  2. A data scientist can stream a multi-year Parquet export of one variable for one station via `GET /v1/observations?format=parquet` without the API process exceeding 200MB RSS.
  3. A consumer hitting `GET /v1/sources/status` sees per-source `last_successful_ingest_at`, freshness, and error rate — sufficient to decide whether to trust a query at a given moment.
  4. Rate limiting returns HTTP 429 with `X-RateLimit-*` headers when defaults (60/min stations, 30/min observations, 10/min export) are exceeded, and the limit is shared correctly across multiple API workers via Redis.
  5. The OpenAPI 3.1 spec is browsable at `/docs` (Swagger) and `/redoc`, the published mkdocstrings API reference renders without errors, and all access logs truncate client IPs (/24 v4, /48 v6) before persistence.
**Plans:** TBD
**UI hint:** no

### Phase 3: Angular Dashboard MVP
**Goal:** Give non-developer users (journalists, researchers, SME operators) a usable visual interface to discover stations and explore time-series — the visible product of the pipeline.
**Mode:** mvp
**Depends on:** Phase 2 (consumes OpenAPI 3.1 spec to generate the typed `ApiClient`)
**Requirements:** DSH-01, DSH-02, DSH-03, DSH-04, DSH-06, DSH-09, DSH-10, DSH-11, DOC-07
**Success Criteria** (what must be TRUE):
  1. A visitor lands on the dashboard, sees a Leaflet map with clustered station markers across covered regions, filters by source/region, clicks a marker, and lands on a station detail page.
  2. On the station detail page, the visitor selects a variable and date range and a Plotly time-series chart renders showing source, license, and last-updated badge — without any hydration errors in the browser console.
  3. The source health page consumes `/v1/sources/status` and shows per-source freshness so a visitor can see at a glance which feeds are healthy.
  4. Every route of the Angular SSR app displays the `federicocalo.dev` footer as a clickable link, and a documented "How to cite Climate Pulse" page is reachable from the footer.
  5. CI fails any PR whose SSR smoke test produces `NG0500`/`NG0501` hydration errors, or whose Lighthouse perf budget exceeds the configured Plotly bundle size budget.
**Plans:** TBD
**UI hint:** yes

### Phase 4: Live Updates + Source Breadth
**Goal:** Deliver the differentiating "live + multi-source EU" promise — WebSocket live updates, multi-station comparison, additional ARPA regions, METAR + Copernicus, and production reverse proxy with TLS.
**Mode:** mvp
**Depends on:** Phase 3 (live UI surfaces consume WS; new sources benefit from visual validation in the dashboard)
**Requirements:** ING-05, ING-06, ING-07, ING-08, API-07, DSH-05, DSH-07, OPS-02, OPS-05
**Success Criteria** (what must be TRUE):
  1. A user on the station detail page or compare view sees the chart auto-append new observations within seconds of ingestion, with no manual refresh, via a WebSocket subscription to `obs:{source}:{station}` channels.
  2. A researcher selects 2-4 stations and compares them side-by-side on a synchronized-cursor Plotly subplot grid, including stations from different sources (e.g. ARPA Lombardia vs ECMWF grid-point).
  3. The pipeline ingests live observations from at least three Italian ARPA regions (Emilia-Romagna, Lombardia, Veneto), NOAA global METAR (parsed via `metpy.parse_metar_to_dataframe`, validated against a 100+ real-METAR corpus including VRB/CAVOK/RVR/NIL/AUTO), and Copernicus C3S (with documented defer-to-v1.1 path if scope is tight).
  4. The deployed instance is reachable over HTTPS via Caddy (with Let's Encrypt auto-cert) with nginx documented as an alternative, and Flower exposes Celery worker/task introspection on a non-public port.
  5. The self-hoster can monitor per-adapter `last_successful_ingest_at` and visually identify a silent-break adapter from the dashboard's source health page within one missed cadence.
**Plans:** TBD
**UI hint:** yes

### Phase 5: Alerts + Ops Hardening + v1.0 Release
**Goal:** Close the v1.0 loop with configurable threshold alerts (agriculture/renewable SME promise), opt-in observability stack, security hardening, contributor onboarding, and a tagged release on GitHub Pages with versioned docs.
**Mode:** mvp
**Depends on:** Phase 4 (alerts require a stable multi-source ingestion stream and a working dashboard to configure rules)
**Requirements:** ALR-01, ALR-02, ALR-03, ALR-04, ALR-05, DSH-08, OPS-03, OPS-06, DOC-06, DOC-08
**Success Criteria** (what must be TRUE):
  1. An SME operator can configure a threshold alert from the dashboard UI (station + variable + operator + threshold + webhook URL and/or email) and receive a signed (HMAC-SHA256) webhook POST and an email within minutes of the threshold being crossed in ingested data.
  2. An operator can opt into the observability stack with `docker compose --profile observability up` and see FastAPI / SQLAlchemy / Celery / Redis traces, structured JSON logs, and Prometheus metrics in self-hosted Grafana/Loki/Tempo without paying any cloud bill.
  3. An operator can list, replay, and drop failed tasks via `climatepulse dlq list / replay / drop` and the secret-rotation runbook in docs guides them through rotating Postgres/SMTP/CDS credentials without downtime.
  4. A new contributor can follow the "How to add a new ARPA region" guide to ship a working adapter PR by editing only a single file in `packages/core/.../adapters/`, with the regional adapter integration test passing against recorded fixtures.
  5. The `v1.0.0` git tag is pushed, release notes are published, the docs site shows a version selector (mike) listing `v1.0.0` as the current version, and the "Looks Done But Isn't" checklist from PITFALLS.md is signed off in the release artifact.
**Plans:** TBD
**UI hint:** yes

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation Slice + Public Docs | 2/5 | In Progress|  |
| 2. Public REST API | 0/? | Not started | - |
| 3. Angular Dashboard MVP | 0/? | Not started | - |
| 4. Live Updates + Source Breadth | 0/? | Not started | - |
| 5. Alerts + Ops Hardening + v1.0 Release | 0/? | Not started | - |

## Coverage Summary

| Category | Total | Mapped |
|----------|-------|--------|
| Ingestion (ING) | 14 | 14 |
| Storage (STO) | 6 | 6 |
| Public API (API) | 13 | 13 |
| Dashboard (DSH) | 11 | 11 |
| Alerts (ALR) | 5 | 5 |
| Operations (OPS) | 10 | 10 |
| Documentation (DOC) | 8 | 8 |
| **Total v1** | **67** | **67** |

100% requirement coverage achieved. No orphans, no duplicates. See REQUIREMENTS.md for full requirement→phase traceability.

## Phase Ordering Rationale

- **Phase 1 ships end-to-end thinnest slice + docs from day one** — PROJECT.md core value mandates this ("se l'intera catena ingestion → storage → query → visualizzazione non funziona, il progetto non ha valore"); docs+footer are non-negotiable hard requirements per PROJECT.md from v0.1.
- **API before Dashboard (Phase 2 before Phase 3)** — a typed `ApiClient` generated from a stable OpenAPI 3.1 spec dramatically reduces dashboard rework.
- **Dashboard before more sources / WebSocket (Phase 3 before Phase 4)** — visible product accelerates feedback for solo dev, and the source health page in Phase 3 makes silent adapter breaks visible.
- **Live updates + source breadth in Phase 4** — WebSocket fan-out depends on a stable ingest stream; additional sources benefit from a working dashboard for visual validation.
- **Alerts last (Phase 5)** — alert evaluation requires a stable ingestion stream to test against and cannot ship before users can see data in the dashboard.

## Hard-Requirement Anchors

- **DOC-01 / DOC-02 / DOC-03** (MkDocs Material on GitHub Pages + `federicocalo.dev` footer): bootstrapped in Phase 1; expanded with API reference in Phase 2; "How to cite" page added in Phase 3; contributor guide + version selector added in Phase 5. Footer present from Phase 1 onwards on every docs page.
- **DSH-09** (`federicocalo.dev` footer in Angular dashboard layout): satisfied in Phase 3 (the phase that introduces the dashboard) and present on every route from that phase onwards.

---
*Last updated: 2026-05-23 after initialization*
