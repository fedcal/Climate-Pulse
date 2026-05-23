# Phase 2: Public REST API - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 02-public-rest-api
**Areas discussed:** Resolution resolver + range limits, Pagination + error envelope, CORS + API key readiness, Source health + export format, WMO variable dictionary + ARPAE coverage, Observability OTel exporters, OpenAPI metadata + examples, mkdocstrings API reference structure (DOC-04)

---

## Resolution Resolver + Range Limits

### Q1: Comportamento resolution resolver?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-route fisso | Server decide, no override, contratto API semplice e prevedibile | ✓ |
| Auto + override `?resolution=` | Default auto, ma utente esperto può forzare | |
| Required esplicito | Utente DEVE specificare, zero magia | |

### Q2: Max range per query observations?

| Option | Description | Selected |
|--------|-------------|----------|
| raw: 7d / hourly: 90d / daily: 5y | Scalato per resolution, bilanciato | ✓ |
| raw: 24h / hourly: 30d / daily: 1y | Conservativo, protegge infrastruttura | |
| raw: 30d / hourly: 1y / daily: nessun limite | Generoso, rischia query 200MB+ | |
| Nessun limite | Solo rate-limit, sconsigliato | |

### Q3: Default period se start/end omessi?

| Option | Description | Selected |
|--------|-------------|----------|
| Last 24h | Sicuro e utile, raw resolution leggera | ✓ |
| Last 7d | Più dati ma forza hourly | |
| Errore 400 | Zero magia ma frustra esplorazione | |

### Q4: Boundaries time range?

| Option | Description | Selected |
|--------|-------------|----------|
| [start, end) half-open | Standard Python/TimescaleDB, concatenazione banale | ✓ |
| [start, end] closed | Più intuitivo non-dev ma overlap di 1 punto | |

---

## Pagination + Error Envelope

### Q1: Pagination cursor format?

| Option | Description | Selected |
|--------|-------------|----------|
| Opaque base64 (encoded last_row PK) | Stateless, scopre PK minimi, standard Stripe-style | ✓ |
| Next-page URL completo nel response | HATEOAS-ish, zero parsing client | |
| Offset/limit semplice | Familiare ma breaks at scale (PITFALL #11) | |

### Q2: Page size default/max?

| Option | Description | Selected |
|--------|-------------|----------|
| default 1000, max 10000 | Bilancia round-trip e payload, ~100KB-1MB/page | ✓ |
| default 100, max 1000 | Conservativo | |
| default 500, max 5000 | Mediano | |

### Q3: Error response format?

| Option | Description | Selected |
|--------|-------------|----------|
| RFC 7807 Problem Details | Standard IETF, OpenAPI-friendly, tooling generico | ✓ |
| Custom envelope | Flessibile ma non standard | |
| FastAPI default | Minimal, no metadata | |

### Q4: Include request_id + OTel trace link?

| Option | Description | Selected |
|--------|-------------|----------|
| X-Request-ID header + body + OTel link | Debug nightmare-proof, trace ritrovabile in Tempo | ✓ |
| Solo header | Più pulito ma meno visibile | |
| Niente request_id | Solo timestamp, debug difficile | |

---

## CORS + API Key Readiness

### Q1: CORS allowlist?

| Option | Description | Selected |
|--------|-------------|----------|
| Configurabile via env CORS_ORIGINS | Default localhost, prod imposti via env | ✓ |
| Allow any origin * | Apertura massima ma niente protezione | |
| Solo Angular hardcoded | Limitato, blocca altri client legittimi | |

### Q2: Skeleton API keys (v1.1+)?

| Option | Description | Selected |
|--------|-------------|----------|
| Solo per-IP rate-limit in v1.0 | Niente skeleton, scalerò rate per IP quando aggiungerò keys | ✓ |
| Skeleton API key opzionale | Più codice ora, facilita v1.1 | |
| Skeleton + UnboundLimit | Massima developer-friendliness ma più lavoro | |

### Q3: Rate-limit key scheme?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-IP + per-route | Default slowapi, budget separati per route | ✓ |
| Per-IP globale | Più stringente | |
| Per-IP + sliding window | Più fair ma più costoso su Redis | |

### Q4: Behavior 429 superato?

| Option | Description | Selected |
|--------|-------------|----------|
| 429 + Retry-After + Problem Details body | Standard, client robusti già implementano backoff | ✓ |
| 429 senza Retry-After | Solo X-RateLimit-Reset, client deve calcolare | |
| Soft rate-limit (200 + warning) | Sconsigliato, DB comunque hammered | |

---

## Source Health + Export Format

### Q1: Definizione 'stale'?

| Option | Description | Selected |
|--------|-------------|----------|
| stale_after = 2× cadence | Per-source threshold, Arpae 30min, ECMWF 12h, METAR 2h | ✓ |
| stale_after = 1.5× cadence | Più sensibile, rischio falsi positivi | |
| stale_after fisso 1h | Semplice ma non rispetta realtà multi-source | |

### Q2: HTTP status se source stale?

| Option | Description | Selected |
|--------|-------------|----------|
| Sempre 200, status nel body | Endpoint monitoring, deve sempre rispondere | ✓ |
| 503 se down, 200 con flag se stale | Mix | |
| 503 anche per stale | Aggressivo, breaks monitoring | |

### Q3: Parquet schema?

| Option | Description | Selected |
|--------|-------------|----------|
| Long format (1 row per station/var/time) | SQL-friendly, supporta filter, mantiene quality_flag | ✓ |
| Wide format (col per variable) | Compatto dashboard ma richiede pivot | |
| Configurabile ?format=parquet-wide/long | Best of both ma raddoppia logica | |

### Q4: CSV compression + chunk?

| Option | Description | Selected |
|--------|-------------|----------|
| Gzip on-the-fly + chunk 10k row | Bandwidth-friendly + RAM cap ~10MB | ✓ |
| No compression + chunk 1k | Max compatibilità, bandwidth maggiore | |
| Optional ?compress=gzip | Opt-in, più esplicito ma complica logica | |

---

## WMO Variable Dictionary + ARPAE Coverage

### Q1: Codici BUFR oltre i 7 core (97k row/day skipped)?

| Option | Description | Selected |
|--------|-------------|----------|
| Sì, mappa B04001-B04006 + B13215 + B07031 | Zero perdita dati: date→drop, B13215→qc_flag, B07031→station.elevation | ✓ |
| Solo le 7 core fissate | Stato Phase 1, 97k warning/day | |
| Mappa tutto come WMO_OTHER:Bxxxx | Massima copertura ma sporca catalogo | |

### Q2: Campi /v1/meta/variables?

| Option | Description | Selected |
|--------|-------------|----------|
| wmo_code, name, si_unit, description, valid_range | valid_range utile per outlier detection client-side | ✓ |
| wmo_code, name, si_unit, description | Minimal | |
| Tutto + provenance per-source | Più ricco ma join costoso | |

### Q3: Filtro ?variable= accetta WMO code o nome?

| Option | Description | Selected |
|--------|-------------|----------|
| Entrambi | B12101 o air_temperature, alias supportati | ✓ |
| Solo nome human-readable | Self-documenting | |
| Solo WMO code | Standard-aderente ma frustrante | |

---

## Observability OTel Exporters

### Q1: OTel exporter default?

| Option | Description | Selected |
|--------|-------------|----------|
| OTLP/HTTP configurabile via env | No-op se non set, zero overhead, zero assumzioni topologia | ✓ |
| OTLP/HTTP fisso localhost:4318 | Plug-and-play se attivi profile observability | |
| Console exporter | Solo dev, prod manual config | |

### Q2: Prometheus /metrics endpoint?

| Option | Description | Selected |
|--------|-------------|----------|
| Esposto public a /metrics | Standard Prometheus, filosofia open-data | ✓ |
| Solo internal network | Più sicuro ma meno utile self-hosters | |
| Behind basic-auth env token | Compromesso, più codice | |

### Q3: OTel auto-instrumentation set?

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI + SQLAlchemy + asyncpg + Redis + httpx | Coverage completa request-to-DB, ~5% overhead | ✓ |
| Solo FastAPI + manual span | Più leggero ma perde DB tracing | |
| Solo FastAPI | Minimo | |

### Q4: structlog format?

| Option | Description | Selected |
|--------|-------------|----------|
| JSON prod, console dev (env LOG_FORMAT) | Loki/Promtail friendly + DX dev | ✓ |
| Sempre JSON | Uniforme ma DX peggiore | |
| Sempre console | DX migliore ma Loki ingest difficile | |

---

## OpenAPI Metadata + Examples

### Q1: OpenAPI info section?

| Option | Description | Selected |
|--------|-------------|----------|
| title + version + description + contact + license + tags | Set completo, tags raggruppano endpoint Swagger nav | ✓ |
| title + version + description + license | Più leggero, sacrifica contact/tags | |
| FastAPI defaults | Zero customization | |

### Q2: Examples inline per endpoint?

| Option | Description | Selected |
|--------|-------------|----------|
| Sì, curl + Python httpx + risposta sample | Swagger UI = quickstart, adoption più veloce | ✓ |
| Solo curl | Più leggero | |
| Niente examples | Solo schema | |

### Q3: OpenAPI servers section?

| Option | Description | Selected |
|--------|-------------|----------|
| Multiple: localhost + fedcal.github.io/Climate-Pulse/api | Swagger switch tra prod/dev, env-configurable | ✓ |
| Solo localhost:8000 | Dev only Phase 2 | |
| Single env API_PUBLIC_URL | Più semplice, niente switch | |

### Q4: Pydantic schema descriptions detail?

| Option | Description | Selected |
|--------|-------------|----------|
| Field descriptions + examples per field | OpenAPI ricco, mkdocstrings tabelle complete | ✓ |
| Solo descriptions | Più leggero | |
| Defaults Pydantic | Schema bare-bones | |

---

## mkdocstrings API Reference Structure (DOC-04)

### Q1: Layout pagina API reference?

| Option | Description | Selected |
|--------|-------------|----------|
| Una pagina per router | Nav docs/api/, deep-link friendly | ✓ |
| Pagina unica | Ctrl+F facile | |
| Solo Redoc embed | Pierde integrazione MkDocs | |

### Q2: mkdocstrings include cosa?

| Option | Description | Selected |
|--------|-------------|----------|
| Routers + Pydantic schemas + esempi | Auto-doc da docstrings + signatures + x-codeSamples riusati | ✓ |
| Solo Pydantic schemas | Endpoint summary manuale | |
| Tutto + private helpers | Massima copertura ma rumore | |

### Q3: OpenAPI spec sul docs site?

| Option | Description | Selected |
|--------|-------------|----------|
| Download openapi.json + embed Redoc | Auto-contenuto, SDK localmente | ✓ |
| Solo embed Redoc | Più sintetico | |
| Solo link Swagger esterno | Niente embed/download | |

### Q4: Pagine docs aggiuntive Phase 2 (multi-select)?

| Option | Description | Selected |
|--------|-------------|----------|
| How to query (tutorial pratico) | Walkthrough con esempi | ✓ |
| Rate limit + error codes reference | Tabella codici + backoff example | ✓ |
| Authentication (placeholder v1.1) | Spiega v1.0 per-IP, v1.1+ API keys | ✓ |
| Changelog API (versioning policy) | Politica breaking changes, deprecation | ✓ |

---

## Claude's Discretion

Aree dove il planner ha flessibilità (non richiedono decisione utente):
- HTTP cache headers (Cache-Control, ETag) — planner decide TTL.
- Redis cache layer interno API process — opzionale.
- Pydantic v2 compat shim — non serve.
- Error code catalog completo (urns) — espande durante implementation.
- Cursor encoding HMAC vs plain — planner decide.
- Test fixture layout FastAPI TestClient — discretion.

---

## Deferred Ideas

- **API key tier + auth middleware** → v1.1+ (EXT-07). Skeleton hook nel rate-limit.
- **/v2/ versioning execution** → quando serve breaking change. Politica in docs/api/changelog.md.
- **GraphQL endpoint** → permanently out of scope.
- **WebSocket /v1/ws/observations** → Phase 4.
- **CRUD alerts /v1/alerts/*** → Phase 5.
- **Bulk archive download** → v1.1+ (EXT-08).
- **SDK auto-gen Python/TypeScript** → v1.1+ (EXT-09/10).
- **HTTP cache layer Redis** → planner decide.
- **LGTM Compose profile** → Phase 5 (OPS-03).
- **mike docs versioning per release** → Phase 5 (DOC-08).
