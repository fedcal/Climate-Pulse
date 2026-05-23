# Phase 1: Foundation Slice + Public Docs - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the entire architectural spine end-to-end with the thinnest possible vertical slice, and ship public documentation from day one.

**In scope:**
- Adapter ABC + decorator registry + polite HTTP client (User-Agent, robots.txt, Redis-shared rate limit, tenacity backoff, aiocache ETag, snapshot fallback)
- TWO source adapters: ARPA Emilia-Romagna (station-based reference) via `dati.arpae.it` REST/JSON; ECMWF Open Data (grid-based reference) via cfgrib + system libeccodes0
- Normalizer WMO (7 core variables, SI units via Pint, range validation, quality flags)
- Timezone-safe ingestion (Europe/Rome → TIMESTAMPTZ UTC; explicit DST tests for March + October)
- Celery worker + dedicated Beat service (singleton) + queues `ingest/normalize/alerts/dlq` + idempotent writer (`ON CONFLICT … DO UPDATE` via asyncpg `copy_records_to_table`)
- Backfill CLI (`climatepulse backfill <source> --from --to`); split-by-day
- Per-adapter health metric `last_successful_ingest_at` + canary alert on silent break
- TimescaleDB schema: TWO hypertables (station-based `observations` + grid-based `gridded_observations` — see D-23), each with CAGG (`obs_hourly`, `gridded_hourly`), compression policy after 7d, retention configurable per source, policy ordering `refresh_lag < compress_after < retention`
- Alembic migrations + raw SQL pattern for `create_hypertable` / CAGG DDL
- Docker Compose v2.30+ (`compose.yaml`) with `timescale + redis + api + worker + beat` services + healthchecks (`condition: service_healthy`)
- `.env.example` + gitleaks pre-commit + GitHub Actions CI (pytest + ruff + pyright + 80% global / 70% adapters coverage gate)
- `docs/scraping-policy.md` for transparency toward ARPA admins
- **Minimal FastAPI HTTP skeleton** anticipated from Phase 2 to serve `/healthz` + `/readyz` (see D-14)
- MkDocs Material site bootstrapped + GitHub Pages deploy via GitHub-native `actions/deploy-pages`
- **Footer `Climate Pulse · MIT License · federicocalo.dev`** on every docs page (Material `copyright` override)
- Quickstart docs: clone → `docker compose up` → backfill CLI demo on 1 station → verify rows via psql

**Out of scope for Phase 1 (deferred to Phase 2+):**
- All other public API endpoints (stations, observations, sources, exports, OpenAPI spec, rate limit, WebSocket) → Phase 2
- Angular dashboard → Phase 3
- Other ARPA regions (Lombardia, Veneto) + NOAA METAR + Copernicus C3S → Phase 4
- Alert rules, webhook, email → Phase 5
- Reverse proxy (Caddy/nginx) + TLS → Phase 3/4 (when dashboard is added)
- `mike` docs versioning → Phase 5 (v1.0.0 tag)
- Optional observability LGTM Compose profile → Phase 5

</domain>

<decisions>
## Implementation Decisions

### Repo + Docs URL
- **D-01:** Repo lives at `github.com/federicocalo/climate-pulse` (personal account, clean URL).
- **D-02:** MkDocs site published at `federicocalo.github.io/climate-pulse` (default GitHub Pages URL — zero DNS config needed for v0.1; custom domain `climatepulse.federicocalo.dev` deferred to post-v1.0 if traffic justifies it).
- **D-03:** GitHub Pages deploy via GitHub-native `actions/configure-pages` + `actions/upload-pages-artifact` + `actions/deploy-pages` (NOT `peaceiris/actions-gh-pages`); triggered on every push to `main`; uses `environment: github-pages` for protection.
- **D-04:** `mike` docs versioning is deferred to Phase 5 (when `v1.0.0` is tagged) — Phase 1 ships a single un-versioned `main` site.

### Footer / Attribution
- **D-05:** Footer text on every MkDocs page: `Climate Pulse · MIT License · federicocalo.dev` (one line, MIT License explicit, `federicocalo.dev` linked).
- **D-06:** Implementation: override `copyright` field in `mkdocs.yml` (Material native mechanism, ~3 lines of YAML — no custom partial needed for Phase 1).
- **D-07:** Same footer text reused VERBATIM by Angular dashboard layout in Phase 3 (consistency).
- **D-08:** No navbar `Author` link, no social icon in topbar — attribution stays in footer only (discreet).

### Phase 1 Acceptance Demo
- **D-09:** "Done" means: a self-hoster runs `docker compose up` on a fresh machine and within 10 minutes has (a) TimescaleDB ingesting from Arpae + ECMWF, (b) 5–10 representative ARPA stations × 30 days of history persisted, (c) `/healthz` + `/readyz` responding 200, (d) MkDocs site live at `federicocalo.github.io/climate-pulse` with the footer, (e) quickstart works end-to-end including `climatepulse backfill arpae --from … --to …`.
- **D-10:** ECMWF subset scope: **EU bbox, 4 cycles/day, 5+ variables** (T2m, surface pressure, 10m wind u/v, total precipitation, 2m relative humidity).
- **D-11:** ARPA Emilia-Romagna scope: **5–10 representative stations × 30 days of history** at the end of Phase 1 (validates compression policy that kicks in after 7d + retention).
- **D-12:** Quickstart demo includes: clone → `docker compose up` → wait health → `climatepulse backfill arpae --from $(date -d '7 days ago' +%F) --to $(date +%F)` → `psql … -c "select count(*), source from observations group by source"` → expected non-zero rows.
- **D-13:** Quickstart does NOT promise Phase 2+ API endpoints (no roadmap-leak / over-promising in v0.1 docs).
- **D-14:** **SCOPE ADJUSTMENT — API-10 anticipated to Phase 1.** Phase 1 ships a MINIMAL FastAPI app exposing ONLY `/healthz` (liveness) + `/readyz` (checks DB + Redis + Celery worker heartbeat). The rest of API-* requirements stay in Phase 2. ROADMAP.md and REQUIREMENTS.md Traceability must be updated by planner to move API-10 from Phase 2 → Phase 1.

### Snapshot Fallback
- **D-15:** Storage: Docker volume `snapshots/` mounted on worker container; configurable via env var `SNAPSHOT_DIR` (default `/var/lib/climatepulse/snapshots`).
- **D-16:** Format: **JSON-LD canonical** (structured, semantically rich, interoperable; per-snapshot file is `<source>/<station>/<timestamp>.jsonld` with `@context` referencing WMO variables).
- **D-17:** Retention: **30 days rolling** (cleanup periodic Celery task `tasks.maintenance.rotate_snapshots` running daily).

### ARPA Emilia-Romagna Source
- **D-18:** Primary endpoint: **`dati.arpae.it` REST/JSON** (official open-data portal, robots.txt present, documented, polite-friendly).
- **D-19:** Ingestion cadence: **15 minutes** (matches PROJECT.md target production cadence; stress-tests politeness from day 1).
- **D-20:** Schema-drift handling: row marked `quality_flag='schema_violation'` + task routed to `dlq` queue (no auto-replay) + ING-14 canary metric flips source to `unhealthy` so dashboard source health page (Phase 3) shows it. NO fail-loud (other sources keep ingesting); NO silent skip.

### ECMWF GRIB Parsing
- **D-21:** Parser stack: **cfgrib 0.9.14+ + system `libeccodes0`** in the worker Dockerfile (accepted ~300MB image growth; one-time cost, paid in Phase 1 to avoid future surprise).
- **D-22:** `libeccodes0` lives in the **worker container only** — the FastAPI api container stays slim (no eccodes dependency).
- **D-23:** **Storage model — DEVIATION from research recommendation.** Grid-based ECMWF observations go to a **dedicated `gridded_observations` hypertable**, separate from station-based `observations`. User accepted the trade-off: doubled ops complexity (2 CAGGs `obs_hourly` + `gridded_hourly`, 2 compression policies, 2 retention policies, 2 read paths in API) in exchange for clean station-vs-grid separation. Planner: design BOTH hypertables in Phase 1; the resolution resolver in Phase 2 routes by query type (station_id → `observations`, lat/lon → `gridded_observations` with nearest-grid-point lookup).

### Testing Strategy + Coverage Gate
- **D-24:** CI coverage gate (GitHub Actions, blocking): **80% global / 70% adapters** (lower bar for adapters acknowledges scraping/mocking difficulty).
- **D-25:** **testcontainers (TimescaleDB) is MANDATORY** in CI — every PR runs integration tests against real TimescaleDB instance (validates `create_hypertable` DDL, `ON CONFLICT` semantics, CAGG refresh, compression). Slower CI accepted.
- **D-26:** Property-based testing (`hypothesis`): mandatory for (a) **Normalizer** (unit conversion round-trips: °C↔K, hPa↔Pa, knots↔m/s — no silent loss), (b) **Timezone** (round-trip `Europe/Rome` naive → UTC → back; explicit cases for DST transitions March + October).
- **D-27:** HTTP mocking for ARPA: **VCR.py cassettes** for 5+ scenarios (200 OK happy path, 304 Not Modified ETag, 404, 500, timeout) — recorded once from live endpoint, replayed in CI. respx allowed for edge-case error injection.

### Claude's Discretion
- Compose network topology (single network vs separated) — planner chooses based on simplicity.
- CI matrix strategy (single OS/Python vs matrix) — planner chooses; default `ubuntu-22.04` + `python 3.12.7`.
- Adapter ABC interface contract (sync iterator vs async generator vs return batch) — planner researches and decides during plan-phase; constraint: must support both station-batch (Arpae) and grid-batch (ECMWF) shapes.
- Logging library config (structlog handlers, formatters) — planner picks sensible defaults (JSON in production, console in dev).
- Test fixture organization, helper layout — planner discretion.

### Folded Todos
*(none — no pending todos cross-referenced this phase)*

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level (governs every phase)
- `.planning/PROJECT.md` — Core Value, Active requirements, Constraints, Key Decisions (incl. GitHub Pages + footer hard requirements)
- `.planning/REQUIREMENTS.md` — 67 v1 requirements with REQ-IDs (Phase 1 owns 24+1 after D-14 anticipation)
- `.planning/ROADMAP.md` — 5-phase Vertical MVP structure; Phase 1 section is authoritative for scope (subject to D-14 update)
- `.planning/STATE.md` — Current position; updated after this discussion

### Research (validated by gsd-project-researcher, locks key technical choices)
- `.planning/research/STACK.md` — version pins (FastAPI 0.136 / Python 3.12.7 / TimescaleDB 2.17 on PG16 / Celery 5.6.3 / Redis 7.4 + redis<6 client / cfgrib 0.9.14 + libeccodes0 / Pint 0.24 / asyncpg 0.30 / SQLAlchemy 2.0.36 + sqlalchemy-timescaledb 0.4 + Alembic 1.13 / structlog 24.4 + OTel 1.28 + prometheus-client 0.21 / pytest 8.3 + testcontainers 4.14 + hypothesis + vcrpy / uv + ruff + pyright + pre-commit 4.0); explicit do-not-use list; MkDocs Material 9.5+ + mkdocstrings 0.27+
- `.planning/research/ARCHITECTURE.md` — adapter ABC + decorator registry pattern; hypertable schema sketch; Celery topology (queues, Beat singleton, DLQ); polite HTTP client design; project layout (`apps/{api,worker,dashboard}` + `packages/{core,migrations}`)
- `.planning/research/PITFALLS.md` — critical pitfalls for Phase 1: #1 hypertable PK + chunk_time_interval, #2 PK includes time, #3 policy ordering, #4 scraping politeness, #5 Celery idempotency, #6 Beat singleton, #7 timezone Europe/Rome DST, #8 unit conversion via Pint, #14 Compose healthchecks, #15 secrets, #16 CI gate, #20 silent adapter break
- `.planning/research/FEATURES.md` — feature priority categories (table stakes vs differentiators vs anti-features); Phase 1 ships table-stakes ingestion+storage primitives
- `.planning/research/SUMMARY.md` — executive synthesis with phase-by-phase research flags; flags Phase 1 needs deeper research on empirical `chunk_time_interval` validation + adapter ABC contract

### External specs / docs (referenced by adapters)
- TimescaleDB docs — `create_hypertable`, continuous aggregates, compression policy, retention policy, `add_compression_policy`, `add_retention_policy`, `add_continuous_aggregate_policy` (verify ordering)
- Arpae open data — `https://dati.arpae.it/` portal endpoints (researcher must enumerate exact REST schema during plan-phase research)
- ECMWF Open Data — `ecmwf-opendata` Python package + GRIB2 message schema for IFS
- Robots.txt RFC 9309 — for polite client compliance
- WMO Codes Registry — variable code dictionary (TEMP, HUM, PRES, WND_DIR, WND_SPD, PCP, RAD, CLD) and SI unit definitions

### CI / Deploy
- GitHub Pages: `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4` (latest stable)
- gitleaks: `gitleaks/gitleaks-action@v2` for pre-commit + CI

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- *(none — greenfield repo, only `.git/` and `.planning/` exist)*

### Established Patterns
- *(none — Phase 1 establishes them. Planner sets the pattern that Phases 2-5 reuse.)*

### Integration Points
- *(none — first phase. Downstream phases will integrate via the adapter registry, OpenAPI 3.1 spec from Phase 2's FastAPI app, and the typed `ApiClient` in Phase 3.)*

**Note for planner:** Project layout to be created in Phase 1 (per ARCHITECTURE.md):
```
climate-pulse/
├── apps/
│   ├── api/             # FastAPI minimal (just /healthz + /readyz in Phase 1)
│   └── worker/          # Celery worker + Beat
├── packages/
│   ├── core/            # WeatherSourceAdapter ABC + registry + polite HTTP client + normalizer + writer
│   └── migrations/      # Alembic + raw SQL for hypertable/CAGG DDL
├── infra/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker     # includes libeccodes0
│   └── compose.yaml
├── docs/                # MkDocs Material content
├── mkdocs.yml
├── tests/
│   ├── unit/
│   ├── integration/     # testcontainers
│   └── fixtures/cassettes/  # VCR.py
├── .github/
│   └── workflows/
│       ├── ci.yml       # pytest + ruff + pyright + coverage + gitleaks
│       └── docs.yml     # MkDocs build + deploy-pages
├── .env.example
├── .gitignore
├── pyproject.toml       # uv workspace root
└── README.md
```

</code_context>

<specifics>
## Specific Ideas

- Footer string is locked verbatim: `Climate Pulse · MIT License · federicocalo.dev` — same characters, same separators (middle-dot `·`), same casing across MkDocs and (later) Angular dashboard.
- Quickstart command shape: `climatepulse backfill arpae --from YYYY-MM-DD --to YYYY-MM-DD` (positional source name, ISO dates, idempotent re-run).
- Test expectation phrasing in docs: "Re-running the backfill command produces zero duplicate rows" (idempotency contract is user-facing, not just internal).
- CI badge in README: build + coverage + docs (deployed status) — symbolize that docs ship with code.
- `docs/scraping-policy.md` should be linked from the MkDocs site nav so ARPA admins can find it easily if they ever check (transparency builds trust).

</specifics>

<deferred>
## Deferred Ideas

- **Custom domain `climatepulse.federicocalo.dev`** — re-evaluate post-v1.0 if traffic justifies DNS setup; CNAME on the gh-pages site enables it without code change.
- **`mike` docs versioning** — Phase 5, paired with `v1.0.0` tag (DOC-08).
- **Navbar `Author` link / social icon to `federicocalo.dev`** — declined for v0.1 (footer-only attribution); revisit if community asks for it.
- **VCR cassette for non-200 ARPA scenarios beyond 5** — extend test corpus in Phase 4 when adding Lombardia + Veneto adapters.
- **MinIO snapshot storage profile** — only if local volume becomes unmanageable; reconsider in Phase 5 ops hardening.
- **`/v1/sources/status` UI endpoint** — Phase 3 (dashboard source health page), but the backend metric `last_successful_ingest_at` is collected in Phase 1 (ING-14).
- **CI matrix multi-OS / multi-Python** — defer to Phase 5; Phase 1 single target (ubuntu-22.04 + python 3.12.7) is sufficient.

### Reviewed Todos (not folded)
*(none — no todos reviewed this phase)*

</deferred>

---

*Phase: 1-Foundation Slice + Public Docs*
*Context gathered: 2026-05-23*
