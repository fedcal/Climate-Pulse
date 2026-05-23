# Feature Research

**Domain:** Weather Data Aggregation Pipeline (EU public sources)
**Researched:** 2026-05-23
**Confidence:** HIGH (commercial/open-source landscape well documented; ARPA regional specifics MEDIUM)

## Executive Synthesis

Climate Pulse occupies a niche between **commercial weather APIs** (Tomorrow.io, OpenWeatherMap, Visual Crossing — paid, proprietary models, global coverage, ML/AI forecasting) and **single-source open projects** (Bright Sky for DWD, wetterdienst for DWD, Open-Meteo for forecast models). The unique value is:

1. **Multi-source EU aggregation with per-source provenance** (no commercial competitor exposes raw provenance + quality flags transparently; Open-Meteo aggregates models but blends them).
2. **Italian regional ARPA coverage** (Open-Meteo only exposes ItaliaMeteo-ARPAE ICON-2I forecast model — not raw regional observation stations from ARPAE, ARPAL, ARPAV, etc.).
3. **MIT license + self-hosted Docker Compose** — researchers/journalists can run their own instance with full data lineage; commercial APIs are SaaS-only.

The aggregation pipeline category has well-established **table stakes** (station discovery by bbox/coordinates, historical time-series by location+period, hourly/daily granularity, CSV/JSON export, unit normalization). PROJECT.md correctly excludes the commercial-model traps (proprietary forecasting, K8s, OAuth, billing).

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these means the product feels broken or unusable for the stated audience (researchers, journalists, agriculture/renewable SMEs).

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Time-series query by location + period** | Core query pattern in every weather API (NOAA CDO, Open-Meteo, Meteostat, Bright Sky) | M | `GET /v1/observations?lat=&lon=&start=&end=&variables=` — must support both lat/lon (nearest station) and explicit `station_id` |
| **Station discovery API** (search by bbox, radius, country, region) | Standard pattern across NOAA CDO, Meteomatics, NWS api.weather.gov | M | `GET /v1/stations?bbox=&country=&source=` with pagination; required for map UI |
| **Station metadata endpoint** | Users need elevation, source, WMO ID, coordinates, operational dates | S | `GET /v1/stations/{id}` returns full metadata + variables available + temporal coverage |
| **Hourly + Daily granularity** | Meteostat, Bright Sky, NOAA all expose both; researchers need hourly, journalists often want daily aggregates | M | Continuous aggregates in TimescaleDB give this for free; expose as `?granularity=hourly\|daily` |
| **WMO-standard variables in SI units** | Cross-source comparison impossible without normalization; explicitly in PROJECT.md requirements | M | Temp (°C), pressure (hPa), wind (m/s), precip (mm), humidity (%), radiation (W/m²), cloud cover (%) |
| **CSV export** | Universal expectation — every weather API offers it (Meteostat, NOAA CDO, Bright Sky, Open-Meteo) | S | Streamed response with proper Content-Disposition; researchers paste into Excel/R/Python |
| **JSON export** (default API response) | Default REST output; OpenAPI 3.1 spec drives this | S | Already implicit in FastAPI; needs consistent envelope `{data, meta, errors}` |
| **Parquet export** | Listed in PROJECT.md; standard for ML/data-science workflows (wetterdienst supports it via pyarrow) | M | Use `pyarrow` to stream; critical differentiator vs Bright Sky/NOAA (CSV-only) |
| **Rate limiting** (per IP) | Every public weather API enforces this; protects infra; PROJECT.md mandates Redis-based | M | Token-bucket via `slowapi` + Redis; return `X-RateLimit-*` headers per industry norm (Xweather, Tomorrow.io) |
| **OpenAPI 3.1 spec / docs UI** | FastAPI gives this; researchers expect Swagger/Redoc to explore | S | Already built-in to FastAPI; add examples & descriptions |
| **Interactive map of stations** (Leaflet) | Every weather dashboard has it (Meteostat, Bright Sky, ARPA portals) | M | Marker clustering for 1000+ stations; popup with station meta + "view data" link |
| **Time-series chart** (Plotly) | Core visualization for any weather UI; supports zoom/pan/export | M | Variable selector, date range picker, multi-variable overlay (e.g., temp + humidity) |
| **Cron-style ingestion with retry** | Without reliable ingestion the entire pipeline collapses; PROJECT.md mandates Celery + retry + DLQ | L | ARPA every 15min, ECMWF 4×/day, METAR hourly; exponential backoff + DLQ surface in admin view |
| **Snapshot/cache fallback when source unavailable** | ARPA endpoints flaky; without fallback ingestion failures cascade to API errors | M | HTTP cache layer + static snapshot fallback (PROJECT.md explicit) |
| **Source provenance per data point** | Researchers/journalists MUST cite source; without provenance data is unverifiable | M | Every response row carries `source: "arpae" \| "ecmwf" \| "noaa_metar" \| "copernicus_c3s"` + `ingested_at` |
| **Quality flag per measurement** | WMO recommends 5 QC tests; multi-source aggregation impossible without per-point flags | M | `quality_flag: "good" \| "suspect" \| "missing" \| "interpolated"` per measurement |
| **Pagination on list endpoints** | Standard REST hygiene; station catalog will be 1000+ items | S | Cursor or offset pagination with `?limit=&cursor=` and `meta.total` |
| **Health/readiness endpoint** | Required for Docker Compose health checks + monitoring | S | `GET /healthz` and `GET /readyz` checking DB + Redis + worker heartbeat |
| **Documentation site** (MkDocs) | Explicit in PROJECT.md; community contributions need contributor docs | M | Setup, API reference, data sources, contribution guide |

### Differentiators (Competitive Advantage)

Features that set Climate Pulse apart from both commercial APIs (which are paid + proprietary) and existing OSS (which are usually single-source).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Multi-source aggregation with explicit provenance** | Commercial APIs blend sources opaquely (Tomorrow.io ML, Open-Meteo model ensembles); we expose which source each datum came from — critical for scientific reproducibility | L | Core architectural commitment: never collapse provenance; allow `?sources=arpae,ecmwf` to filter |
| **Italian regional ARPA coverage** (Emilia-Romagna, Lombardia, Veneto, Piemonte at minimum) | Unique: Open-Meteo only has ItaliaMeteo-ARPAE forecast model (ICON-2I), not raw regional observation stations. Existing Italian work is fragmented per-region | L | Pluggable adapter per region (PROJECT.md mandates); start with 2-3 regions, grow community-driven |
| **WebSocket live updates** for ingested data | Researchers tracking ongoing events (heatwave, flood) get push updates without polling; uncommon in OSS (Bright Sky doesn't have it) | M | `/v1/ws/observations?station_id=&variables=` — broadcasts when new data ingested for subscribed station |
| **Per-source quality flags exposed** | Most commercial APIs hide QC internally; researchers need to know if data passed range/spike/consistency checks | M | WMO-aligned flags (good/suspect/missing/interpolated); allow filtering `?min_quality=good` |
| **Multi-station comparison view** in dashboard | Journalists compare drought-hit regions, researchers compare model vs station; commercial dashboards usually focus on single location | M | Side-by-side time series with synchronized time cursor (Plotly subplot grid) |
| **Configurable threshold alerts** (webhook + email) | Open-source equivalents of paid Tomorrow.io / Xweather webhook alerting; agriculture/renewable SMEs need frost/wind alerts | M | PROJECT.md explicit; per-location threshold rules; idempotent webhook delivery with retry |
| **MIT license + self-hosted** | Researchers + universities can run their own instance with their own data sources added; competitors are SaaS-locked | S | Filosofia open-data already in PROJECT.md |
| **Snapshot fallback + scraping politeness** | Demonstrates responsible relationship with ARPA endpoints; PROJECT.md commits to robots.txt compliance, conservative rate limits, User-Agent identification | M | Differentiator vs ad-hoc scrapers; build trust with data providers |
| **Bulk downloads** (per-station-per-year archives) | Meteostat offers this for bulk research workflows; researchers want gzipped CSV/Parquet they can analyze offline | M | Pre-generated archive files on schedule + signed URLs; reduces API load |
| **OpenAPI client generation** (Python SDK, TypeScript SDK auto-generated) | Lowers integration friction for SMEs; commercial APIs sell SDKs as premium | S | Use `openapi-generator` in CI; publish as `climate-pulse-sdk` on PyPI/npm |
| **Reproducible query URLs** (citation-friendly) | Journalists/researchers can include exact data URL in publication; Open-Meteo does this well | S | All query state encoded in URL; documented "How to cite" page |
| **Heatmap / choropleth overlay on map** for spatial visualization | Aggregate variable across all stations in viewport (e.g., max temp today by region) — strong story-telling for journalists | M | Server-side aggregation endpoint feeding Leaflet heatmap layer |
| **Source health dashboard** (which ARPA regions are currently failing ingestion) | Transparency for users about data freshness; informs whether to trust a given query | S | `GET /v1/sources/status` returns last successful ingestion + error rate per source |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem appealing but conflict with the open-data philosophy, constraints, or solo-developer scope from PROJECT.md.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Proprietary forecasting models / ML predictions** | "Add ML to predict tomorrow's weather" — common request | Climate Pulse aggregates observations and re-serves model outputs (ECMWF, ICON-2I); building proprietary forecasts requires ML team + compute budget = different product. PROJECT.md explicit out-of-scope | Re-serve ECMWF/Copernicus model outputs with provenance; let downstream users train ML on the data |
| **OAuth / SSO user authentication** | "Users want accounts" | Public open-data API; auth adds friction for the target persona (researcher pulling data in a Jupyter notebook). PROJECT.md out-of-scope | Optional API key (rate-limit tier) in v1.0 — not full user auth |
| **Real-time Kafka streaming** | "Real-time architecture is modern" | ARPA cadence is 15min, ECMWF 4×/day, METAR hourly — Celery cron is sufficient. Kafka adds operational complexity contradicting Docker Compose constraint | WebSocket push from API tier when new data ingested — gives "live feel" without Kafka |
| **Kubernetes / Helm chart deployment** | "Production-grade deploy" | Zero cloud budget, single developer, target audience runs on laptops/single VPS. K8s = wasted effort | Docker Compose only in v1.0; community-contributed K8s manifests post-1.0 if demanded |
| **Multi-tenancy / SaaS billing** | "Monetize the project" | Conflicts with MIT/open-data philosophy; billing systems are huge scope. PROJECT.md out-of-scope | Self-hosted only; document hosted-by-third-party pattern (let others run SaaS) |
| **Mobile native apps (iOS/Android)** | "Need an app" | 2× platform code, app-store overhead; web SSR works on mobile. PROJECT.md out-of-scope | Angular 21 SSR with responsive layout; optionally PWA for offline access |
| **Global coverage beyond EU + METAR** | "Why not worldwide?" | Each region needs adapter + politeness compliance + maintenance. Scope creep. PROJECT.md out-of-scope (EU + global METAR only) | EU focus is the differentiator; let forks handle other continents |
| **Push notifications (mobile, in-browser)** | "Alert me when threshold crossed" | Requires service worker + VAPID + per-user state — significant scope for marginal use | Webhook + email already covered in PROJECT.md alerts; users plug webhooks into Slack/Telegram/PagerDuty |
| **User-uploaded weather station data** ("citizen science") | "Let users add their own stations" | Quality control nightmare (Personal Weather Stations have well-documented QC issues per HESS paper); requires moderation pipeline | Out of scope; downstream forks can add this with their own QC |
| **Built-in BI / dashboard builder** (Grafana-style) | "Let users build custom dashboards" | Reinvents Grafana; the pre-built map+chart UI is enough for v1.0 | Document how to connect Grafana to TimescaleDB directly (TimescaleDB has native Grafana data source) |
| **Live radar imagery / satellite layers** | "Weather apps have radar" | Radar data is huge (GBs/day), licensing varies, storage cost prohibitive for self-host | Defer; link to upstream sources (DWD, EUMETSAT) for radar imagery |
| **Air quality / pollutant data** | "ARPA already publishes it, add it" | Different domain (chemistry, not meteorology), different variables/units, scope creep | Document architecture so a fork can add adapters; keep core focused on weather |
| **GraphQL endpoint** | "Modern API surface" | REST + OpenAPI is sufficient and lower-maintenance for solo dev; GraphQL adds resolver complexity for time-series queries | Stick with REST; the URL-as-citation property of REST suits research use cases better |
| **Custom proprietary variable derivations** (e.g., "feels-like" temp formula X) | "Add wet-bulb temperature, heat index" | Risk of opinionated formulas being wrong; researchers prefer raw data + their own formulas | Expose raw observations only in v1.0; derived variables as community-contributed post-processing recipes |
| **In-app data annotations / comments** | "Researchers want to collaborate on data points" | Requires user accounts (anti-feature above) + moderation; out of scope | Provide stable citation URLs; collaboration happens in users' own tooling (Zenodo, GitHub) |

## Feature Dependencies

```
Ingestion Layer
  Adapter framework (pluggable)
      requires no other features
  ARPA adapters (per region)
      requires Adapter framework
      requires Snapshot fallback + scraping politeness
  ECMWF / Copernicus adapters
      requires Adapter framework
  METAR adapter
      requires Adapter framework
  Celery cron + retry + DLQ
      requires Adapter framework
      requires Source health dashboard (consumes its data)

Storage Layer
  TimescaleDB hypertable
      requires no other features
  Continuous aggregates (hourly + daily)
      requires TimescaleDB hypertable
      enables Hourly + Daily granularity API
  Compression + retention policy
      requires TimescaleDB hypertable

Variable Normalization
  WMO variables + SI units
      requires Adapter framework
      enables Multi-source aggregation
  Quality flag per measurement
      requires WMO variables + SI units
      enables Per-source quality flags API filter
  Source provenance per row
      requires WMO variables + SI units
      enables Multi-source aggregation with explicit provenance

API Layer
  Time-series query endpoint
      requires TimescaleDB hypertable
      requires WMO variables
  Station discovery / metadata
      requires Station registry (part of Adapter framework)
  Rate limiting (Redis token bucket)
      requires no other features
  WebSocket live updates
      requires Time-series query endpoint
      requires Celery cron (triggers WS broadcast on ingest)
  Export formats (CSV, JSON, Parquet)
      requires Time-series query endpoint
  Bulk downloads
      requires Continuous aggregates
      requires Export formats
  Threshold alerts (webhook + email)
      requires Time-series query endpoint
      requires Celery cron (alert evaluation task)
  OpenAPI 3.1 spec
      requires all endpoints defined
      enables SDK generation
  SDK generation (Python, TypeScript)
      requires OpenAPI 3.1 spec

Dashboard
  Leaflet map of stations
      requires Station discovery API
  Plotly time-series chart
      requires Time-series query endpoint
  Multi-station comparison
      requires Plotly time-series chart
  Heatmap overlay
      requires server-side spatial aggregation endpoint
      requires Leaflet map
  Source health dashboard
      requires Source health endpoint

Cross-cutting
  Documentation (MkDocs)
      requires all features stabilized
  Docker Compose deploy
      requires all services defined
```

### Critical Dependency Notes

- **Adapter framework is the keystone** — every ingestion-side feature depends on it. Build first, build well.
- **WMO normalization gates multi-source value** — without it, the "aggregation" claim is false advertising. Provenance + quality flags hang off normalization.
- **Continuous aggregates unlock hourly+daily endpoints + bulk archives cheaply** — design hypertable + aggregates together upfront; retrofit is painful.
- **WebSocket depends on ingest pipeline broadcasting events** — ingest workers need to publish to Redis pub/sub (already deployed for rate limiting) that API tier subscribes to.
- **Alert engine reuses Celery worker pool** — schedule periodic alert-evaluation task that runs queries and triggers webhooks; do not build a separate scheduler.
- **OpenAPI completeness gates SDK generation** — discipline around schemas/examples in FastAPI pays off downstream.

## MVP Definition

### Launch With (v1.0.0 — Q3 2026)

Strict minimum for the pipeline to be useful end-to-end (PROJECT.md core value: "if the entire chain ingestion → storage → query → visualization doesn't work, the project has no value").

**Ingestion**
- [ ] Adapter framework (pluggable, documented contract)
- [ ] 2-3 ARPA regional adapters (start with Emilia-Romagna — Arpae open data is best-documented — plus Lombardia and Veneto)
- [ ] ECMWF Open Data adapter (forecast model output)
- [ ] METAR/TAF NOAA adapter (global airport observations)
- [ ] Celery cron with retry + DLQ
- [ ] Snapshot fallback + scraping politeness (User-Agent, robots.txt, rate limits)
- [ ] Source health endpoint

**Storage**
- [ ] TimescaleDB hypertable (location × variable × timestamp)
- [ ] Continuous aggregates (hourly + daily)
- [ ] Compression policy + configurable retention per source

**Normalization**
- [ ] WMO variables in SI units (temp, humidity, pressure, wind speed+direction, precipitation, radiation, cloud cover)
- [ ] Source provenance per row
- [ ] Quality flag per measurement (good/suspect/missing/interpolated)

**API**
- [ ] `GET /v1/stations` (bbox, country, source filters, pagination)
- [ ] `GET /v1/stations/{id}` (metadata + temporal coverage)
- [ ] `GET /v1/observations` (location or station_id, period, variables, granularity, sources filter, min_quality filter)
- [ ] `GET /v1/sources/status` (per-source health, last ingestion)
- [ ] CSV + JSON + Parquet export
- [ ] WebSocket `/v1/ws/observations` for live updates
- [ ] Redis rate limiting with `X-RateLimit-*` headers
- [ ] OpenAPI 3.1 spec + Swagger/Redoc UI
- [ ] Health (`/healthz`) + readiness (`/readyz`) endpoints

**Dashboard (Angular 21 SSR)**
- [ ] Leaflet map with clustered station markers
- [ ] Station detail popup + "view data" link
- [ ] Plotly time-series chart (variable selector, date picker)
- [ ] Multi-station comparison (2-4 stations side-by-side)
- [ ] Source health page

**Alerts**
- [ ] Configurable threshold alerts per location/variable (temp, wind, precipitation)
- [ ] Webhook + email delivery with retry

**Ops + Docs**
- [ ] Docker Compose deploy (timescale + redis + api + worker + dashboard + reverse proxy)
- [ ] MkDocs documentation (setup, API reference, data sources, contributing)
- [ ] Community contribution guide for new adapters

### Add After Validation (v1.1 – v1.x)

Features triggered by community adoption signals.

- [ ] **Additional ARPA regions** (Piemonte, Toscana, Sicilia, etc.) — trigger: community PRs
- [ ] **Copernicus C3S adapter** (deferred from v1.0 if scope tight — large/complex CDS API) — trigger: validated demand
- [ ] **Heatmap/choropleth overlay** — trigger: journalist user feedback on storytelling needs
- [ ] **Bulk downloads** (per-station-per-year archives) — trigger: heavy researcher API usage triggering rate limits
- [ ] **Auto-generated SDKs** (Python + TypeScript via openapi-generator) — trigger: external integration requests
- [ ] **Optional API key tier** (higher rate limits, opt-in) — trigger: abusive anonymous traffic
- [ ] **Grafana data-source guide** — trigger: ops/agriculture users asking for dashboards

### Future Consideration (v2+)

Defer until product-market fit established.

- [ ] **Interpolation between stations** (à la wetterdienst's bilinear interpolation) — defer: needs careful UX to avoid implying false precision
- [ ] **Derived variables** (heat index, wet-bulb, evapotranspiration) — defer: scientific scrutiny + community-validated formulas
- [ ] **Radar / satellite imagery layers** — defer: storage + licensing cost
- [ ] **Climate normals / anomaly endpoints** (deviation from 30-year baseline) — defer: requires WMO standard normals integration
- [ ] **R / Julia SDKs** — defer: Python + TS cover 95% of audience
- [ ] **Federation across Climate Pulse instances** — defer: only relevant once multiple instances exist

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Adapter framework | HIGH | MEDIUM | P1 |
| ARPA Emilia-Romagna adapter | HIGH | MEDIUM | P1 |
| Additional ARPA regions (LO, VE) | HIGH | MEDIUM | P1 |
| ECMWF Open Data adapter | HIGH | MEDIUM | P1 |
| METAR adapter | MEDIUM | LOW | P1 |
| Copernicus C3S adapter | MEDIUM | HIGH | P2 (defer if scope tight) |
| TimescaleDB hypertable + aggregates | HIGH | MEDIUM | P1 |
| WMO variable normalization | HIGH | MEDIUM | P1 |
| Provenance + quality flags | HIGH | MEDIUM | P1 |
| Celery cron + retry + DLQ | HIGH | MEDIUM | P1 |
| Snapshot fallback + politeness | HIGH | MEDIUM | P1 |
| REST: stations + observations + sources/status | HIGH | MEDIUM | P1 |
| CSV + JSON export | HIGH | LOW | P1 |
| Parquet export | MEDIUM | LOW | P1 |
| Rate limiting | HIGH | LOW | P1 |
| WebSocket live updates | MEDIUM | MEDIUM | P1 |
| OpenAPI 3.1 + docs UI | HIGH | LOW | P1 |
| Health/readiness endpoints | HIGH | LOW | P1 |
| Leaflet map + station markers | HIGH | MEDIUM | P1 |
| Plotly time-series chart | HIGH | MEDIUM | P1 |
| Multi-station comparison | MEDIUM | MEDIUM | P1 |
| Source health dashboard | MEDIUM | LOW | P1 |
| Threshold alerts (webhook + email) | MEDIUM | MEDIUM | P1 |
| Docker Compose deploy | HIGH | MEDIUM | P1 |
| MkDocs documentation | HIGH | MEDIUM | P1 |
| Bulk downloads | MEDIUM | MEDIUM | P2 |
| Heatmap overlay | MEDIUM | MEDIUM | P2 |
| Auto-generated SDKs | MEDIUM | LOW | P2 |
| Optional API key tier | LOW | MEDIUM | P2 |
| Citation URL stability | MEDIUM | LOW | P1 (free; bake in early) |
| Interpolation between stations | LOW | HIGH | P3 |
| Derived variables | LOW | HIGH | P3 |
| Radar imagery | LOW | HIGH | P3 |

**Priority key:**
- **P1**: Must have for v1.0 launch (MVP scope)
- **P2**: Should have, target v1.1–v1.x post-launch
- **P3**: Future consideration, v2+

## Competitor Feature Analysis

| Feature | Open-Meteo | Meteostat | Bright Sky (DWD) | wetterdienst (lib) | Tomorrow.io / OpenWeatherMap | **Climate Pulse approach** |
|---------|-----------|-----------|------------------|--------------------|-----------------------------|----------------------------|
| **License** | Open-source (non-commercial free) | Open data, AGPL lib | MIT | MIT | Commercial proprietary | **MIT — fully open** |
| **Geographic focus** | Global (model-based) | Global (station-based) | Germany (DWD only) | Germany (DWD primarily) | Global | **EU focus + global METAR; Italian regional ARPA depth** |
| **Sources blended or separated?** | Blended ensembles | Single-source per station | DWD only | DWD only | Proprietary blend | **Multi-source with explicit per-row provenance** |
| **Historical depth** | Back to 1940 (ERA5) | Decades | Limited (DWD horizon) | Decades (DWD) | Variable (paid tier) | **As far back as each source publishes; no synthesis** |
| **Forecasting** | Yes (30+ models) | No | Yes (MOSMIX from DWD) | Limited | Yes (proprietary ML) | **Re-serve ECMWF + ICON-2I only; no proprietary models** |
| **Authentication** | None | API key for JSON API | None | N/A | API key | **None (optional API key tier in v1.x)** |
| **Rate limiting** | Yes (10k/day fair-use) | Yes (per-key tiers) | Yes (per-IP) | N/A | Tier-based | **Redis token bucket per IP** |
| **Export formats** | JSON | JSON (API), CSV (bulk) | JSON | CSV, JSON, Feather, Parquet, Excel | JSON | **JSON + CSV + Parquet** |
| **WebSocket** | No | No | No | No | No (some paid have webhooks) | **Yes — live ingest broadcast** (differentiator) |
| **Map UI** | Yes (forecast comparison) | Yes (station explorer) | Yes (basic) | No (library only) | Yes (commercial dashboard) | **Yes — Leaflet, station discovery focus** |
| **Time-series chart** | Yes | Yes | No (API only) | No (library only) | Yes | **Yes — Plotly with multi-variable** |
| **Multi-station comparison** | No (forecast model compare) | Limited | No | No | Paid | **Yes (P1 feature)** |
| **Threshold alerts** | No | No | DWD alerts pass-through | No | Yes (paid webhooks) | **Yes — webhook + email (P1)** |
| **Quality flags exposed** | No | Partial | No (DWD-internal) | Yes (DWD codes) | No | **Yes — WMO-aligned flags per row** |
| **Self-hostable** | Yes (Swift app) | No (SaaS) | Yes (Python app) | Yes (library) | No | **Yes — Docker Compose first-class** |
| **OpenAPI spec** | No | Partial | Yes | N/A | Yes | **Yes (FastAPI-generated)** |
| **SDK availability** | No | Python | Multiple community | Python | Multiple official | **Python + TS auto-generated (P2)** |

**Gap exploited by Climate Pulse:** No existing project combines (a) multi-source EU aggregation, (b) Italian regional ARPA depth, (c) explicit provenance + quality flags, (d) self-hosted Docker Compose, (e) MIT license, (f) WebSocket + REST + threshold alerts in one package. Open-Meteo aggregates models but blends; wetterdienst/Bright Sky are DWD-only; commercial APIs are SaaS-locked with proprietary blending.

## Sources

- [Open-Meteo Features](https://open-meteo.com/en/features)
- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo ItaliaMeteo ARPAE ICON-2i](https://open-meteo.com/en/docs/italia-meteo-arpae-api)
- [Open-Meteo GitHub](https://github.com/open-meteo/open-meteo)
- [Meteostat Developers](https://dev.meteostat.net/)
- [Meteostat Bulk Data](https://dev.meteostat.net/bulk/)
- [Meteostat Formats & Units](https://dev.meteostat.net/formats.html)
- [Bright Sky](https://brightsky.dev/)
- [Bright Sky API Docs](https://brightsky.dev/docs/)
- [Bright Sky GitHub](https://github.com/jdemaeyer/brightsky)
- [Wetterdienst Docs](https://wetterdienst.readthedocs.io/)
- [Wetterdienst GitHub](https://github.com/earthobservations/wetterdienst)
- [Tomorrow.io Weather API](https://www.tomorrow.io/weather-api/)
- [Tomorrow.io vs OpenWeatherMap](https://www.tomorrow.io/blog/tomorrow-vs-openweathermap/)
- [Visual Crossing Best Weather APIs 2025](https://www.visualcrossing.com/resources/blog/best-weather-api-for-2025/)
- [Xweather Top Weather APIs 2026](https://www.xweather.com/blog/top-weather-apis-for-production-2026)
- [Xweather Webhooks](https://www.xweather.com/docs/weather-api/reference/webhooks-pushed-data)
- [Xweather Rate Limiting](https://www.xweather.com/docs/weather-api/getting-started/rate-limiting)
- [NOAA CDO Web Services](https://www.ncdc.noaa.gov/cdo-web/webservices/v2)
- [NWS api.weather.gov FAQ](https://weather-gov.github.io/api/general-faqs)
- [Dati Arpae — meteo datasets](https://dati.arpae.it/dataset?q=meteo)
- [Arpae meteo observed data](https://dati.arpae.it/dataset/dati-dalle-stazioni-meteo-locali-della-rete-idrometeorologica-regionale)
- [ARPA Lombardia data access](https://www.arpalombardia.it/temi-ambientali/meteo-e-clima/guida-richiesta-dati/)
- [MISTRAL Italian meteorological portal](https://rmets.onlinelibrary.wiley.com/doi/10.1002/met.2004)
- [ARPALData R package paper](https://link.springer.com/article/10.1007/s10651-024-00599-6)
- [WMO/ECMWF Data Quality Monitoring System](https://www.ecmwf.int/en/about/media-centre/news/2020/wmo-and-ecmwf-launch-new-web-tool-monitor-quality-observations)
- [HESS QC algorithms for rainfall data](https://hess.copernicus.org/articles/28/4715/2024/)
- [WMO QC Guidelines for Automatic Weather Stations](https://www.researchgate.net/publication/228826920_Guidelines_on_Quality_Control_Procedures_for_Data_from_Automatic_Weather_Stations)
- [TimescaleDB Continuous Aggregates](https://www.tigerdata.com/blog/real-time-analytics-for-time-series-continuous-aggregates)
- [TimescaleDB Downsampling for long-term storage](https://www.tigerdata.com/blog/how-to-proactively-manage-long-term-data-storage-with-downsampling)

---
*Feature research for: Weather Data Aggregation Pipeline (EU public sources)*
*Researched: 2026-05-23*
