# Phase 2: Public REST API - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the ingested data publicly queryable through a versioned, documented, rate-limited FastAPI REST API — the integration surface external researchers and downstream tooling will consume. Build on Phase 1's minimal FastAPI skeleton (`/healthz` + `/readyz` already shipped) by adding the public read path + exports + observability + docs.

**In scope (14 requirements):**
- `GET /v1/stations` (filtri bbox / country / source / paginazione cursor-based)
- `GET /v1/stations/{id}` (metadata + temporal coverage)
- `GET /v1/observations` con resolution resolver auto-route (raw <1h / hourly 1h-1d / daily ≥1d)
- `GET /v1/sources` + `GET /v1/sources/status` (per-source last_successful_ingest_at, freshness, error rate, stale flag)
- `GET /v1/meta/variables` (WMO codes + nomi human-readable + SI units + descriptions + valid_range)
- Export streaming CSV / JSON / Parquet (long format, gzip on-the-fly per CSV, chunk 10k row)
- Rate limiting Redis-backed slowapi (per-IP + per-route: 60/min stations, 30/min observations, 10/min export; HTTP 429 + Retry-After + Problem Details body)
- OpenAPI 3.1 spec completa con metadata branded + esempi inline curl/Python per ogni endpoint + servers multipli + Pydantic schema con field descriptions+examples; Swagger UI a `/docs`, Redoc a `/redoc`
- Per-row provenance (source) + per-measurement quality flag esposti in ogni response
- GDPR-aware logging (IP truncation /24 v4 / /48 v6) — già implementato in /readyz path, esteso a tutti gli endpoint
- orjson default response + gzip + CORS configurabile via env + request-id middleware
- OPS-04: structlog + OpenTelemetry distro auto-instrumentation (FastAPI + SQLAlchemy + asyncpg + Redis + httpx) + prometheus-client `/metrics` public
- OPS-10: Privacy notice docs page + GDPR-aware log retention runbook
- DOC-04: API reference docs su MkDocs (una pagina per router) + Redoc embed + openapi.json download + tutorial "How to query" + rate-limit reference + auth placeholder v1.1 + API changelog

**WMO variable dictionary expansion (Phase 2 scope adjustment):**
- Mappa codici BUFR ARPAE aggiuntivi emersi in Phase 1 (97k row/giorno skipped come `unknown:`)
  - B04001-B04006 (date fields) → silently dropped (ridondanti con observed_at)
  - B07031 (height of barometer) → estratto come `station.elevation_m` durante upsert
  - B13215 (precipitation flag) → estratto come `quality_flag` context
- Zero perdita dati, zero rumore log

**Out of scope (= other phases):**
- WebSocket `/v1/ws/observations` → Phase 4
- Angular dashboard → Phase 3
- Alert rules + webhook + email → Phase 5
- mike docs versioning → Phase 5 (paired with v1.0.0 tag)
- LGTM Compose profile (Grafana + Loki + Tempo + Prometheus actual stack) → Phase 5
- API key tier (skeleton + auth) → v1.1+ (EXT-07)
- `/v2/` versioning policy execution → quando ci sarà breaking change
- Reverse proxy + TLS (Caddy / Let's Encrypt) → Phase 3-4

</domain>

<decisions>
## Implementation Decisions

### Resolution Resolver + Range Limits
- **D-API-01:** Auto-route fisso (no override): server decide la resolution dal range di query — `<1h` → `observations` raw, `1h-1d` → `obs_hourly` CAGG, `≥1d` → `obs_daily` CAGG. Stesso pattern per gridded_observations (gridded_hourly / gridded_daily). Filosofia: contratto API semplice e prevedibile, prevenire query costose.
- **D-API-02:** Max range scalato per resolution (returned in `Problem Details` quando superato):
  - raw: **7 giorni** max
  - hourly: **90 giorni** max
  - daily: **5 anni** max
- **D-API-03:** Default period se utente non specifica `start`+`end`: **last 24h** (sicuro + utile per quick-check; raw resolution su 24h è leggero).
- **D-API-04:** Time range boundaries: **`[start, end)` half-open** (standard Python/TimescaleDB; concatenare query consecutive è banale, no overlap di 1 punto). Documentato esplicitamente in OpenAPI description del parametro `end`.

### Pagination + Error Response
- **D-API-05:** Cursor format: **opaque base64 (encoded last_row PK + resolution + filters hash)**. Cursor self-contained: include resolution e hash dei filtri della query originale; cambiare filtri durante paginazione restituisce 400 con explanation.
- **D-API-06:** Page size: default **1000**, max **10000**. Header `X-Page-Size` riflette quello applicato. Export endpoints (CSV/JSON/Parquet streaming) NON paginano — stream illimitato.
- **D-API-07:** Error response format: **RFC 7807 Problem Details** (`Content-Type: application/problem+json`) — `{type, title, status, detail, instance, request_id, code?, extras?}`. Standard IETF, OpenAPI-friendly, riconoscibile da tooling generico (es. `httpie`, `Insomnia`).
- **D-API-08:** Every error response include:
  - Header `X-Request-ID` (UUIDv7, stesso formato richiesta in)
  - Body `request_id` field (visibile a utente per bug report)
  - OTel span attribute `request.id` (debug nightmare-proof: utente segnala bug → trace ritrovabile in Tempo/Jaeger via request_id)

### CORS + API Keys + Rate Limiting
- **D-API-09:** CORS allowlist: **configurabile via env `CORS_ORIGINS`** (comma-separated). Default in dev: `http://localhost:*`. Prod: imposti dominio dashboard Phase 3 + altri client autorizzati. `allow_credentials=true` solo se origin esplicitamente nell'allowlist (mai con `*`).
- **D-API-10:** API keys: **NON in v1.0** — solo per-IP rate-limit strict. Quando si aggiunge EXT-07 in v1.1+, scala il rate-limit per IP (tier free → tier higher con API key). Zero skeleton API key in Phase 2 (filosofia open-data).
- **D-API-11:** Rate-limit key scheme: **per-IP + per-route** (slowapi default `slowapi:{ip}:{route}`). Budget separati:
  - `/v1/stations*`: 60/min
  - `/v1/observations`: 30/min
  - `/v1/observations?format=*` (exports): 10/min
  - `/v1/sources*` + `/v1/meta/*`: 120/min (metadata frequently polled da dashboard)
- **D-API-12:** Rate-limit overrun: HTTP **429** + headers `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` + Problem Details body con `type=urn:climatepulse:rate-limited`.

### Source Health + Export Format
- **D-API-13:** Stale definition: **stale_after = 2× cadence** per source (configurabile via env per-source).
  - Arpae: stale dopo 30min (2× 15min)
  - ECMWF: stale dopo 12h (2× 6h)
  - METAR (Phase 4): stale dopo 2h
- **D-API-14:** `/v1/sources/status` HTTP status: **sempre 200** (endpoint di monitoring, deve sempre rispondere). Body: array `[{source_id, name, status: "healthy"|"stale"|"down", last_ingest_at, freshness_seconds, error_rate_24h, threshold_seconds}]`. Status `down` quando >5× cadence senza ingest success.
- **D-API-15:** Parquet schema: **long format** — 1 row per `(station_id, variable_id, observed_at)` con colonne `[station_id, source_id, lat, lon, wmo_code, variable_name, observed_at, value, unit, quality_flag]`. Coerente con DB layout, query SQL-friendly, supporta `?variable=` filter senza pivot.
- **D-API-16:** CSV streaming: **gzip on-the-fly** (header `Content-Encoding: gzip`, client decompress trasparente) + chunk **10k row** (~1MB chunk in RAM). Header `Content-Disposition: attachment; filename="climate-pulse-{source}-{start}-{end}.csv.gz"`.

### WMO Variable Dictionary + Filter
- **D-API-17:** BUFR codes oltre i 7 core: mappati esplicitamente, **zero perdita dati**:
  - B04001-B04006 (Y/M/D/H/Min/Sec components) → silently dropped (ridondanti con `observed_at`)
  - B07031 (height of barometer above MSL) → estratto come `station.elevation_m` durante station upsert
  - B13215 (precipitation quality flag) → mapped to `quality_flag` con valore `SUSPECT` se != 0
- **D-API-18:** `/v1/meta/variables` espone per ogni variabile: `wmo_code, name (human-readable, e.g. air_temperature), si_unit (e.g. K), description, valid_range: [min, max]`. `valid_range` utile per outlier detection client-side.
- **D-API-19:** Filtro `?variable=` accetta **sia WMO code che nome human-readable** — `?variable=B12101` ed `?variable=air_temperature` equivalenti. Alias resolution case-insensitive.

### Observability
- **D-API-20:** OTel exporter: **OTLP/HTTP configurabile via env `OTEL_EXPORTER_OTLP_ENDPOINT`**. Default no-op (no overhead se non configurato). Quando set, OTLP/HTTP verso collector. Zero assumzioni su topologia (LGTM stack è Phase 5).
- **D-API-21:** Prometheus `/metrics` endpoint: **esposto public** (path NON `include_in_schema=False`, NON in OpenAPI). Filosofia open-data: metrics utili anche a community esterna. Reverse proxy può eventualmente filtrare in produzione (Phase 4-5).
- **D-API-22:** OTel auto-instrumentation: **FastAPI + SQLAlchemy + asyncpg + Redis + httpx** (set completo). Overhead accettato ~5% latency. Custom span manuali per resolution resolver (utile per debug query routing).
- **D-API-23:** structlog config: JSON in prod, console in dev — controllato da env `LOG_FORMAT=json|console`. Default `json` se non set (safer for prod).

### OpenAPI Metadata + Examples
- **D-API-24:** OpenAPI 3.1 `info`:
  - title: `Climate Pulse API`
  - version: `1.0.0` (segue progetto, non FastAPI app version)
  - description: 2-paragraph descrizione + link a docs site
  - contact: `{name: "Federico Calo", email: "fedcal01@gmail.com", url: "https://federicocalo.dev"}`
  - license: `{name: "MIT", identifier: "MIT"}` (SPDX)
  - tags: array per raggruppare endpoint in Swagger UI nav (Stations, Observations, Sources, Meta, Health)
- **D-API-25:** Examples inline per ogni endpoint: **curl + Python httpx + risposta sample**. Tre `code-samples` extensions in OpenAPI (`x-codeSamples`) — Redoc li rende come tabs.
- **D-API-26:** OpenAPI `servers` section: **multipli** — `[{url: "http://localhost:8000", description: "Local dev"}, {url: "https://fedcal.github.io/Climate-Pulse/api", description: "Public (placeholder, Phase 4-5 reverse proxy)"}]`. Configurabile via env `API_PUBLIC_URL` per altri self-hosters.
- **D-API-27:** Pydantic schema: **field descriptions + examples per ogni field** (`Field(..., description="...", examples=[...])`). OpenAPI schema ricco, mkdocstrings genera tabelle complete.

### API Reference Docs (DOC-04)
- **D-API-28:** mkdocstrings: **una pagina per router** sotto `docs/api/` — `stations.md`, `observations.md`, `sources.md`, `meta.md`, `health.md`. Nav su MkDocs sotto sezione "API Reference". Deep-link friendly.
- **D-API-29:** mkdocstrings include: **routers + Pydantic schemas + esempi**. Auto-doc da docstrings + signatures Pydantic + esempi curl/Python (riusati da OpenAPI `x-codeSamples`).
- **D-API-30:** OpenAPI spec sul docs site: pagina `docs/api/spec.md` con **embed Redoc** (cdn) + **bottone download `openapi.json`**. Consumer può generare SDK localmente con `openapi-generator`.
- **D-API-31:** Pagine docs aggiuntive Phase 2 (tutte create):
  - `docs/api/how-to-query.md` — tutorial pratico con esempio "fetch 7 giorni di temperatura da una stazione Arpae"
  - `docs/api/rate-limits.md` — tabella codici errore + comportamento rate-limit + esempio backoff client Python
  - `docs/api/authentication.md` — placeholder che spiega "v1.0 = per-IP, v1.1+ aggiungerà API keys (EXT-07)"
  - `docs/api/changelog.md` — politica breaking changes, deprecation header (`Sunset:` RFC 8594), introduzione `/v2/` futura

### Claude's Discretion
- HTTP cache headers (Cache-Control, ETag, Last-Modified) per `/v1/stations` e `/v1/meta/variables` (rarely change) — planner decide TTL.
- Redis cache layer in API process (separata dal rate-limit) — opzionale, lascia al planner se serve o no.
- Pydantic v2 v1-compat shim — non serve, project Python 3.12 nativo.
- Error code catalog (es. `urn:climatepulse:rate-limited`, `urn:climatepulse:resolution-too-fine`) — planner espande lista durante implementation.
- Cursor encoding scheme dettagliato (HMAC-SHA256 con secret? plain base64?) — planner decide; default HMAC se serve garantire integrità.
- Test fixture layout per FastAPI TestClient — planner discretion.

### Folded Todos
*(none — no pending todos cross-referenced this phase)*

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level (governs every phase)
- `.planning/PROJECT.md` — Core Value, Constraints, Key Decisions
- `.planning/REQUIREMENTS.md` — 67 v1 requirements; Phase 2 owns 14 (API-01..06, 08, 09, 11, 12, 13 + OPS-04, OPS-10, DOC-04)
- `.planning/ROADMAP.md` — Phase 2 section authoritative for scope
- `.planning/STATE.md` — Current position

### Phase 1 (Phase 2 builds on top — locked decisions)
- `.planning/phases/01-foundation-slice-public-docs/01-CONTEXT.md` — 27 decisions incl. D-14 minimal FastAPI skeleton già live (Phase 2 estende), D-23 due hypertable
- `.planning/phases/01-foundation-slice-public-docs/SKELETON.md` — Walking Skeleton lock (uv workspace, package layout)
- `.planning/phases/01-foundation-slice-public-docs/01-VERIFICATION.md` — Phase 1 status: passed
- `.planning/phases/01-foundation-slice-public-docs/01-05-SUMMARY.md` — FastAPI minimal app (`/healthz` + `/readyz`) committed location

### Research (validated)
- `.planning/research/STACK.md` — version pins (FastAPI 0.136, Pydantic 2.9, slowapi 0.1.9+, pyarrow 18+, structlog 24.4, OTel 1.28, prometheus-client 0.21, orjson 3.10)
- `.planning/research/ARCHITECTURE.md` — FastAPI layering, resolution resolver pattern, Redis pub/sub fanout (per Phase 4)
- `.planning/research/PITFALLS.md` — #11 (no rate limit = DoS), #12 (API queries hit CAGGs not raw), #19 (GDPR logs), #11 (no pagination), #21 (cursor encoding integrity)

### External specs
- **RFC 7807** — Problem Details for HTTP APIs (https://datatracker.ietf.org/doc/html/rfc7807) — error response format
- **RFC 8594** — The Sunset HTTP Header Field (deprecation header)
- **RFC 9457** — Updated Problem Details RFC (some tooling prefers this version)
- **OpenAPI 3.1** — https://spec.openapis.org/oas/v3.1.0
- **slowapi** docs — https://slowapi.readthedocs.io/ — Redis storage backend + headers
- **OpenTelemetry Python** — https://opentelemetry.io/docs/languages/python/ — auto-instrumentation set
- **TimescaleDB CAGG query routing** — official docs su `time_bucket_gapfill` per gestire missing data nel resolution resolver

### Existing code (Phase 1 committed)
- `apps/api/climatepulse_api/main.py` — FastAPI app entry (Phase 1 minimal, Phase 2 estende)
- `apps/api/climatepulse_api/routers/health.py` — /healthz + /readyz (Phase 1, leave intact)
- `apps/api/climatepulse_api/settings.py` — pydantic-settings (Phase 1, estendere per CORS_ORIGINS, OTEL_EXPORTER_OTLP_ENDPOINT, LOG_FORMAT, API_PUBLIC_URL)
- `packages/core/climatepulse_core/storage/repos.py` — MetadataRepo (sources/variables/stations cache loaders)
- `packages/core/climatepulse_core/storage/writer.py` — IdempotentWriter (read by API for /v1/sources/status)
- `packages/core/climatepulse_core/observability/health.py` — record_success / is_stale (reused for /v1/sources/status freshness logic)
- `mkdocs.yml` — extend nav per docs/api/ pages

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phase 1 deliverables)
- **FastAPI app skeleton** (`apps/api/climatepulse_api/main.py`): Phase 1 minimal app already wired with structlog, lifespan (DB pool + Redis init/teardown), basic middleware. Phase 2 ADDS routers, doesn't restart from scratch.
- **Settings** (`apps/api/climatepulse_api/settings.py`): pydantic-settings BaseSettings already loaded with DATABASE_URL, REDIS_URL, LOG_LEVEL. Add Phase 2 fields: `CORS_ORIGINS: list[str]`, `OTEL_EXPORTER_OTLP_ENDPOINT: str | None`, `LOG_FORMAT: Literal["json", "console"]`, `API_PUBLIC_URL: str | None`, `RATE_LIMIT_STATIONS: str = "60/minute"`, etc.
- **Health router** (`apps/api/climatepulse_api/routers/health.py`): `/healthz` + `/readyz` keep as-is. Phase 2 adds new routers (do NOT modify health.py).
- **asyncpg pool** (initialized in main.py lifespan): reuse for all read queries. Pool size already tuned for Phase 1.
- **Redis client** (initialized in main.py lifespan): reuse for slowapi storage + cursor HMAC secret + cache layer (if added).
- **MetadataRepo** (`packages/core/.../storage/repos.py`): cache loaders (sources/variables/stations) — API routers use these on startup + via dependency injection.
- **IdempotentWriter health metric** (`packages/core/.../observability/health.py`): `record_success(redis, source_id, ts)` + `is_stale(redis, source_id, cadence)` → reuse for `/v1/sources/status`.
- **Domain models** (`packages/core/.../domain/models.py`): `Source`, `Station`, `Variable`, `Observation`, `RawObservation`, `QcFlag` — reuse as base for Pydantic response models (or wrap in DTOs).

### Established Patterns
- **Logging**: structlog with JSON output (Phase 1 default) — every router log via `structlog.get_logger()`, never `print`/`logging` directly.
- **Settings via pydantic-settings**: env-driven, no hardcoded config in code.
- **Async-only**: asyncpg + httpx + redis.asyncio everywhere — no sync I/O in API path.
- **Idempotency**: writer's `ON CONFLICT DO UPDATE` is the only DB write path — API is read-only (Phase 2 doesn't write).
- **Dependency injection**: FastAPI `Depends()` for `get_db_pool()`, `get_redis()`, `get_metadata_repo()` — pattern established in health.py.

### Integration Points
- **Phase 3 (dashboard)** consumes OpenAPI 3.1 spec to generate typed `ApiClient`. Phase 2's spec stability is critical — every endpoint shape, query param, error format locked here.
- **Phase 4 (WebSocket + more sources)** adds `/v1/ws/observations` to the same FastAPI app. Phase 2 doesn't preempt — but settings already extensible (Phase 2 add WS-related fields opzionalmente).
- **Phase 5 (alerts)** adds `/v1/alerts/*` CRUD endpoints to the same app. Pattern (router per feature area) supports this.

</code_context>

<specifics>
## Specific Ideas

- **Resolution resolver routing log**: ogni query observations emette structlog event `api.observations.routed` con `requested_range, chosen_resolution, chosen_table, row_count, latency_ms` — utile per dashboard interna + debug performance.
- **OpenAPI examples real**: gli esempi nelle x-codeSamples devono usare dati realistici Arpae Emilia-Romagna (station_id reale, variabile `air_temperature`, range ultimi 7 giorni) — non placeholder "string" o "value".
- **Cursor opaque format**: `base64url(json.dumps({last_observed_at, last_station_id, last_variable_id, resolution, filters_sha256, exp_ts}))` + HMAC-SHA256 firma con secret in Redis (rotabile). Expired cursor → 400 con message "regenerate query".
- **Stale freshness format**: response `/v1/sources/status` include `freshness_seconds` come INT (not human "5 minutes ago"). Lato client (dashboard Phase 3) formattazione humanize.
- **OpenAPI servers env override**: `if API_PUBLIC_URL is set, prepend to servers list; localhost remains as second entry for dev.`
- **Versioning header for /v2 readiness**: ogni response include header `API-Version: 1.0` — quando arriva v2 si discrimina via Accept header (non breaking).

</specifics>

<deferred>
## Deferred Ideas

- **API key tier + auth middleware** → v1.1+ (EXT-07). Phase 2 lascia uno hook esplicito nel rate-limit per estensione.
- **`/v2/` versioning execution** → quando si avrà bisogno di breaking change. Politica documentata in `docs/api/changelog.md` Phase 2.
- **GraphQL endpoint** → permanently out of scope (PROJECT.md anti-feature).
- **WebSocket `/v1/ws/observations`** → Phase 4.
- **CRUD alerts API `/v1/alerts/*`** → Phase 5.
- **Bulk archive download (per-station-per-year tarball)** → v1.1+ (EXT-08).
- **SDK auto-generato Python + TypeScript via openapi-generator** → v1.1+ (EXT-09/10).
- **HTTP cache layer Redis (oltre rate-limit)** → planner Phase 2 decide se serve; default no, opt-in se profiling mostra hot endpoint.
- **LGTM observability stack actual Compose profile** → Phase 5 (OPS-03).
- **mike docs versioning per release** → Phase 5 (DOC-08).

### Reviewed Todos (not folded)
*(none — no todos reviewed this phase)*

</deferred>

---

*Phase: 2-Public REST API*
*Context gathered: 2026-05-23*
