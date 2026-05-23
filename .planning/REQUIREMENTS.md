# Requirements: Climate Pulse

**Defined:** 2026-05-23
**Core Value:** End-to-end multi-source meteo pipeline — aggregare in modo affidabile dati pubblici da fonti EU eterogenee (ARPA, ECMWF, NOAA, Copernicus) e renderli queryabili attraverso una public API documentata + dashboard utilizzabile.

## v1 Requirements

Requirements per release v1.0.0 (target Q3 2026). 67 requisiti totali. Ogni requisito è mappato a esattamente una fase nella sezione Traceability.

### Ingestion

- [ ] **ING-01**: `WeatherSourceAdapter` ABC + decorator-based source registry (one-file-per-source plugin model)
- [ ] **ING-02**: Polite HTTP client condiviso (identifying User-Agent, robots.txt compliance, per-host rate limit Redis-shared, tenacity exponential backoff + jitter, aiocache ETag cache, snapshot fallback su sorgente down)
- [ ] **ING-03**: Adapter ARPA Emilia-Romagna (Arpae) — fonte di riferimento station-based
- [ ] **ING-04**: Adapter ECMWF Open Data — fonte di riferimento grid-based (cfgrib + xarray + libeccodes0)
- [ ] **ING-05**: Adapter NOAA METAR/TAF (via metpy `parse_metar_to_dataframe`, corpus test 100+ METAR reali con VRB/CAVOK/RVR/NIL/AUTO)
- [ ] **ING-06**: Adapter ARPA Lombardia
- [ ] **ING-07**: Adapter ARPA Veneto
- [ ] **ING-08**: Adapter Copernicus C3S (CDS-Beta, submit+poll, queue dedicata `-Q ecmwf -c 1`) — *defer-to-v1.1 ammissibile se scope tight*
- [ ] **ING-09**: Normalizer WMO con mapping per 7 variabili core (T, RH, P, vento direzione+intensità, precip, irraggiamento, copertura nuvole) in unità SI via Pint; range validation; quality flag per misurazione
- [ ] **ING-10**: Timezone-safe ingestion (input naive `Europe/Rome` → `TIMESTAMPTZ` UTC; test espliciti DST marzo + ottobre)
- [ ] **ING-11**: Celery worker + dedicated Beat service (singleton, mai colocato) con queue dedicate (`ingest`, `normalize`, `alerts`, `dlq`); retry strategy + Dead Letter Queue
- [ ] **ING-12**: Writer idempotente con `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE` via asyncpg `copy_records_to_table`
- [ ] **ING-13**: Backfill CLI (`climatepulse backfill <source> --from --to`, split per giorno)
- [ ] **ING-14**: Per-adapter health metric `last_successful_ingest_at` + canary alert su silent break

### Storage

- [ ] **STO-01**: TimescaleDB hypertable `observations` con PK `(station_id, variable_id, observed_at, source_id)`, `chunk_time_interval => INTERVAL '7 days'` (validato empiricamente)
- [ ] **STO-02**: Tabelle metadata: `stations` (id, source_id, lat/lon, elevation, WMO ID, temporal coverage), `variables` (WMO code, unit, description), `sources` (id, name, license, url)
- [ ] **STO-03**: Continuous aggregates gerarchiche `obs_hourly` (su raw) + `obs_daily` (su `obs_hourly`)
- [ ] **STO-04**: Compression policy `compress_after = INTERVAL '7 days'` con `segmentby=(station_id, variable_id)`
- [ ] **STO-05**: Retention policy configurabile per fonte (default 5y raw / 20y aggregati)
- [ ] **STO-06**: Alembic migrations + raw SQL pattern per `create_hypertable` / CAGG DDL; ordering corretto `refresh_lag < compress_after < retention_after`

### Public API

- [ ] **API-01**: Endpoint `GET /v1/stations` (filtri bbox, country, source, paginazione cursor-based)
- [ ] **API-02**: Endpoint `GET /v1/stations/{id}` (metadata, temporal coverage)
- [ ] **API-03**: Endpoint `GET /v1/observations` con resolution resolver (raw <1h, hourly 1h-1d, daily >=1d) e filtri location/variable/period/sources
- [ ] **API-04**: Endpoint `GET /v1/sources` + `GET /v1/sources/status` (source health: `last_successful_ingest_at`, freshness, error rate)
- [ ] **API-05**: Endpoint `GET /v1/meta/variables` (WMO codes, unità SI, descrizioni)
- [ ] **API-06**: Export streaming CSV / JSON / Parquet (pyarrow `StreamingResponse`)
- [ ] **API-07**: WebSocket `/v1/ws/observations` (Redis pub/sub `obs:{source}:{station}` channels)
- [ ] **API-08**: Rate limiting Redis-backed (slowapi, headers `X-RateLimit-*`, default 60/min stations / 30/min observations / 10/min export)
- [ ] **API-09**: OpenAPI 3.1 spec + Swagger + Redoc UI
- [ ] **API-10**: Endpoint `GET /healthz` + `GET /readyz` (check DB + Redis + Celery worker heartbeat)
- [ ] **API-11**: Per-row provenance (source) + per-measurement quality flag esposti in ogni response
- [ ] **API-12**: GDPR-aware logging (IP truncation /24 IPv4 / /48 IPv6; retention configurabile)
- [ ] **API-13**: orjson default response + gzip + CORS + request-id middleware

### Dashboard

- [ ] **DSH-01**: Angular 21 SSR shell con zoneless change detection + Vitest test suite
- [ ] **DSH-02**: Typed `ApiClient` auto-generato da OpenAPI 3.1 schema
- [ ] **DSH-03**: Mappa Leaflet (lazy-loaded in `afterNextRender` + `isPlatformBrowser` guard) con marker clustering stazioni e filtri source/region
- [ ] **DSH-04**: Pagina station detail con grafico Plotly time-series (variable selector, date range picker, source/license/last-updated badge)
- [ ] **DSH-05**: Vista comparazione multi-station (2-4 stazioni side-by-side, cursore sincronizzato, Plotly subplot grid)
- [ ] **DSH-06**: Pagina source health (consuma `/v1/sources/status`)
- [ ] **DSH-07**: Live updates via WebSocket subscription (station detail + compare view)
- [ ] **DSH-08**: UI alert configuration (thresholds per station + variable, webhook URL, email)
- [ ] **DSH-09**: **Footer `federicocalo.dev`** presente su ogni route della dashboard (link cliccabile)
- [ ] **DSH-10**: SSR smoke test in CI (zero `NG0500/NG0501` hydration errors per route)
- [ ] **DSH-11**: Lighthouse perf budget in CI (Plotly bundle subsetting `plotly.js-basic-dist` o custom build)

### Alerts

- [ ] **ALR-01**: Tabella `alert_rules` (station_id, variable_id, operator, threshold, channels)
- [ ] **ALR-02**: Periodic Celery task `tasks.alerts.evaluate` con valutazione soglie post-ingestion
- [ ] **ALR-03**: Webhook delivery (HMAC-SHA256 signed payload, SSRF allow-list, retry policy)
- [ ] **ALR-04**: Email delivery (aiosmtplib, retry, templating Jinja2)
- [ ] **ALR-05**: CRUD API `/v1/alerts` per gestione rules

### Operations

- [ ] **OPS-01**: Docker Compose v2.30+ (`compose.yaml`) con servizi `timescale + redis + api + worker + beat + dashboard`, healthchecks + `condition: service_healthy`
- [ ] **OPS-02**: Reverse proxy Caddy con Let's Encrypt (default) + nginx documentato come alternativa
- [ ] **OPS-03**: Optional Compose profile `observability` (Grafana + Prometheus + Loki + Tempo / LGTM stack)
- [ ] **OPS-04**: structlog + OpenTelemetry distro (FastAPI + SQLAlchemy + Celery + Redis auto-instrumentation) + prometheus-client `/metrics`
- [ ] **OPS-05**: Flower 2.0+ per monitoring Celery
- [ ] **OPS-06**: DLQ CLI (`climatepulse dlq list / replay / drop`)
- [ ] **OPS-07**: `.env.example` + gitleaks pre-commit hook + secret rotation runbook
- [ ] **OPS-08**: GitHub Actions CI (pytest + ruff + pyright + Angular build + Lighthouse + SSR smoke)
- [ ] **OPS-09**: Docs `docs/scraping-policy.md` per trasparenza verso admin ARPA
- [ ] **OPS-10**: Privacy notice docs + GDPR-aware log retention runbook

### Documentation

- [ ] **DOC-01**: MkDocs Material 9.5+ site bootstrapped fin dalla v0.1
- [ ] **DOC-02**: GitHub Action build + deploy MkDocs su **GitHub Pages** (deploy automatico on push to `main`)
- [ ] **DOC-03**: **Footer `federicocalo.dev`** custom su MkDocs theme — presente su ogni pagina docs
- [ ] **DOC-04**: API reference auto-generata via mkdocstrings[python]
- [ ] **DOC-05**: Guide quickstart (Docker Compose up + curl prima query)
- [ ] **DOC-06**: Pagina "How to add a new ARPA region" (contributor guide)
- [ ] **DOC-07**: Pagina "How to cite Climate Pulse" (citation URLs, DOI optional)
- [ ] **DOC-08**: Docs versioning su GitHub Pages (mike) — selettore versione per release

## v2 Requirements

Deferred to v1.1+ release. Tracciati ma non in roadmap corrente.

### Extended Sources

- **EXT-01**: Adapter Copernicus C3S (se non incluso in v1.0 per scope tight)
- **EXT-02**: Adapter ARPA Lazio
- **EXT-03**: Adapter ARPA Sicilia
- **EXT-04**: Adapter ARPA Piemonte
- **EXT-05**: Adapter ARPA Toscana
- **EXT-06**: Framework community per contribuire adapter ARPA tramite PR singolo file

### API Extensions

- **EXT-07**: API key opzionale per higher rate-limit tier
- **EXT-08**: Bulk per-station-per-year archive download (S3-compatible storage)
- **EXT-09**: Auto-generated SDK Python via openapi-generator
- **EXT-10**: Auto-generated SDK TypeScript via openapi-generator
- **EXT-11**: Heatmap / choropleth spatial overlay endpoint

### Dashboard Extensions

- **EXT-12**: Heatmap geografica multi-variable real-time
- **EXT-13**: PWA installable (offline cache delle ultime query)
- **EXT-14**: Multi-language (IT + EN) i18n

## Out of Scope

Esplicitamente esclusi. Documentati per prevenire scope creep.

| Feature | Reason |
|---------|--------|
| Forecasting proprietario / modelli ML | Climate Pulse aggrega osservazioni, non genera previsioni — diverso prodotto |
| OAuth / SSO user authentication | API pubblica open-data; auth aggiunge frizione per persona ricercatore Jupyter |
| Real-time Kafka streaming | Cadenza ARPA 15min / ECMWF 4×/day / METAR 1h — Celery cron è sufficiente |
| Kubernetes / Helm chart | Zero cloud budget, solo dev — solo Docker Compose in v1.0 |
| Multi-tenancy / SaaS billing | Conflitto con filosofia MIT/open-data |
| Mobile native apps iOS/Android | Angular 21 SSR responsive è sufficiente |
| Push notifications mobile/VAPID | Webhook + email coprono già canale alert |
| User-uploaded citizen-science PWS | QC nightmare documentato (HESS paper) |
| BI / dashboard builder Grafana-style | Reinventa Grafana — documentare integrazione TimescaleDB↔Grafana invece |
| Live radar / satellite imagery | Storage cost + licensing prohibitive per self-host |
| Air quality / pollutant data | Dominio diverso (chimica) — fork-friendly via adapter pattern |
| GraphQL endpoint | REST + OpenAPI sufficiente, lower-maintenance, URL-as-citation suits research |
| Derived variables ("feels-like") | Rischio formule opinionate — esporre solo dati raw |
| Real-time chat / data annotations | Richiede user accounts (anti-feature) |
| Custom hand-rolled METAR parser | Silent data loss su VRB/CAVOK/RVR — sempre usare metpy |
| InfluxDB / ClickHouse storage | TimescaleDB scelto — Postgres-compatible, ecosistema Python maturo |
| OAuth login per dashboard | Dashboard pubblica read-only, no user accounts |

## Traceability

Mapping requirement → phase. Each v1 requirement appears in exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ING-01 | Phase 1 | Pending |
| ING-02 | Phase 1 | Pending |
| ING-03 | Phase 1 | Pending |
| ING-04 | Phase 1 | Pending |
| ING-05 | Phase 4 | Pending |
| ING-06 | Phase 4 | Pending |
| ING-07 | Phase 4 | Pending |
| ING-08 | Phase 4 | Pending |
| ING-09 | Phase 1 | Pending |
| ING-10 | Phase 1 | Pending |
| ING-11 | Phase 1 | Pending |
| ING-12 | Phase 1 | Pending |
| ING-13 | Phase 1 | Pending |
| ING-14 | Phase 1 | Pending |
| STO-01 | Phase 1 | Pending |
| STO-02 | Phase 1 | Pending |
| STO-03 | Phase 1 | Pending |
| STO-04 | Phase 1 | Pending |
| STO-05 | Phase 1 | Pending |
| STO-06 | Phase 1 | Pending |
| API-01 | Phase 2 | Pending |
| API-02 | Phase 2 | Pending |
| API-03 | Phase 2 | Pending |
| API-04 | Phase 2 | Pending |
| API-05 | Phase 2 | Pending |
| API-06 | Phase 2 | Pending |
| API-07 | Phase 4 | Pending |
| API-08 | Phase 2 | Pending |
| API-09 | Phase 2 | Pending |
| API-10 | Phase 1 | Pending |
| API-11 | Phase 2 | Pending |
| API-12 | Phase 2 | Pending |
| API-13 | Phase 2 | Pending |
| DSH-01 | Phase 3 | Pending |
| DSH-02 | Phase 3 | Pending |
| DSH-03 | Phase 3 | Pending |
| DSH-04 | Phase 3 | Pending |
| DSH-05 | Phase 4 | Pending |
| DSH-06 | Phase 3 | Pending |
| DSH-07 | Phase 4 | Pending |
| DSH-08 | Phase 5 | Pending |
| DSH-09 | Phase 3 | Pending |
| DSH-10 | Phase 3 | Pending |
| DSH-11 | Phase 3 | Pending |
| ALR-01 | Phase 5 | Pending |
| ALR-02 | Phase 5 | Pending |
| ALR-03 | Phase 5 | Pending |
| ALR-04 | Phase 5 | Pending |
| ALR-05 | Phase 5 | Pending |
| OPS-01 | Phase 1 | Pending |
| OPS-02 | Phase 4 | Pending |
| OPS-03 | Phase 5 | Pending |
| OPS-04 | Phase 2 | Pending |
| OPS-05 | Phase 4 | Pending |
| OPS-06 | Phase 5 | Pending |
| OPS-07 | Phase 1 | Pending |
| OPS-08 | Phase 1 | Pending |
| OPS-09 | Phase 1 | Pending |
| OPS-10 | Phase 2 | Pending |
| DOC-01 | Phase 1 | Pending |
| DOC-02 | Phase 1 | Pending |
| DOC-03 | Phase 1 | Pending |
| DOC-04 | Phase 2 | Pending |
| DOC-05 | Phase 1 | Pending |
| DOC-06 | Phase 5 | Pending |
| DOC-07 | Phase 3 | Pending |
| DOC-08 | Phase 5 | Pending |

**Coverage:**

- v1 requirements: **67 total** (ING 14 + STO 6 + API 13 + DSH 11 + ALR 5 + OPS 10 + DOC 8)
- Mapped to phases: **67** (100% coverage)
- Unmapped: 0
- Note: the initial scaffold mentioned "60 requirements"; the actual category count is 67. All are mapped 1:1, no orphans, no duplicates.

**Per-phase distribution:**

| Phase | Count | Categories |
|-------|-------|------------|
| Phase 1 (Foundation Slice + Public Docs) | 25 | ING (10) + STO (6) + API (1) + OPS (4) + DOC (4) |
| Phase 2 (Public REST API) | 14 | API (11) + OPS (2) + DOC (1) |
| Phase 3 (Angular Dashboard MVP) | 9 | DSH (8) + DOC (1) |
| Phase 4 (Live Updates + Source Breadth) | 9 | ING (4) + API (1) + DSH (2) + OPS (2) |
| Phase 5 (Alerts + Ops Hardening + v1.0 Release) | 10 | ALR (5) + DSH (1) + OPS (2) + DOC (2) |
| **Total** | **67** | |

*Updated 2026-05-23 per Phase 1 CONTEXT D-14: API-10 (/healthz + /readyz) anticipated to Phase 1 to enable Walking Skeleton acceptance demo.*

---
*Requirements defined: 2026-05-23*
*Traceability populated by roadmapper: 2026-05-23*
