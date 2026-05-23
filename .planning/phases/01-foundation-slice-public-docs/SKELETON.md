# Walking Skeleton — Climate Pulse

**Phase:** 1
**Generated:** 2026-05-23

## Capability Proven End-to-End

A self-hoster runs `docker compose up` on a fresh machine and within 10 minutes has (a) TimescaleDB ingesting real observations from ARPA Emilia-Romagna and ECMWF Open Data into TWO hypertables (`observations` + `gridded_observations`), (b) `/healthz` + `/readyz` returning 200, (c) MkDocs site live at `federicocalo.github.io/climate-pulse` with the footer `Climate Pulse · MIT License · federicocalo.dev`, (d) the quickstart guide leads through `climatepulse backfill arpae --from … --to …` producing non-zero, idempotent rows verifiable via `psql -c "select count(*), source from observations group by source"`.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend language | Python 3.12.7 (CI target) on uv workspace | STACK.md pin; uv is 10-100x faster than pip for Docker layer caching |
| Web framework (Phase 1 only) | FastAPI 0.136.1 — minimal app exposing ONLY `/healthz` + `/readyz` (D-14) | All other API-* endpoints deferred to Phase 2 |
| Time-series store | TimescaleDB 2.17 on PostgreSQL 16, TWO hypertables (`observations` station-based + `gridded_observations` grid-based per D-23) | User-locked deviation from single-hypertable; clean station-vs-grid separation |
| Hot-path DB write | asyncpg 0.31 `copy_records_to_table` + `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE` (ING-12) | Race-condition-safe idempotency; ~3x faster than ORM |
| Metadata ORM | SQLAlchemy 2.0.36 async + sqlalchemy-timescaledb 0.4 + Alembic 1.18.4 with raw `op.execute()` for hypertable/CAGG DDL | ORM for stations/variables/sources; raw SQL for Timescale extension DDL (Pitfall D) |
| Task queue | Celery 5.6.3 + Redis 7.4 broker + `redis<6` Python client; queues `ingest/normalize/alerts/dlq`; dedicated singleton `beat` service (`deploy.replicas: 1`) | Pitfall F enforced; Beat never colocated |
| HTTP client | httpx 0.28.1 async + tenacity 9.1.4 (exponential backoff + jitter) + aiocache 0.12.3 ETag cache + pyrate-limiter 4.1.0 RedisBucket (cross-worker rate limit) | Politeness ING-02 |
| GRIB decoder | cfgrib 0.9.15.1 + system `libeccodes0` in worker container ONLY (D-22) | API container stays slim |
| Unit normalization | Pint 0.25.3 (WMO SI) | Silent multiplication bugs are worst-case (Pitfall ING-09) |
| Snapshot fallback storage | Docker volume `snapshots_data` → `/var/lib/climatepulse/snapshots`; format JSON-LD canonical `<source>/<station>/<timestamp>.jsonld`; 30-day rolling rotation via `tasks.maintenance.rotate_snapshots` daily | D-15/D-16/D-17 |
| Docs site | MkDocs Material 9.7.6 → GitHub Pages via `actions/configure-pages@v5` + `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4` (NOT peaceiris); env `github-pages`; trigger on push to `main` | D-03 |
| Footer (verbatim) | `Climate Pulse · MIT License · federicocalo.dev` rendered via `copyright` field in `mkdocs.yml` on every page; same string reused verbatim by Angular dashboard in Phase 3 | D-05/D-06/D-07 |
| Repo URL | `github.com/federicocalo/climate-pulse` | D-01 |
| Docs URL | `federicocalo.github.io/climate-pulse` (no custom domain in Phase 1) | D-02 |
| Test stack | pytest 8.3 + pytest-asyncio 1.3.0 (auto mode) + pytest-cov 7.1.0 + hypothesis 6.152.9 + testcontainers 4.14.2 + vcrpy 8.1.1 + pytest-recording + respx | D-24/D-25/D-26/D-27 |
| CI coverage gate | GitHub Actions, blocking: 80% global / 70% adapters | D-24 |
| Lint / type / format | ruff 0.15.14 + pyright 1.1.409 + pre-commit 4.6.0 + gitleaks/gitleaks-action@v2 | OPS-07/OPS-08 |
| Deploy target | Self-hosted Docker Compose v2.30+; single default bridge network (Claude's discretion) | OPS-01 |
| Directory layout | uv workspace: `apps/{api,worker}` + `packages/{core,migrations}` + `infra/` + `docs/` + `tests/{unit,integration,fixtures/cassettes}` | RESEARCH.md project structure |
| Adapter contract | `WeatherSourceAdapter` ABC + `@register(source_id)` decorator-registry + `async def fetch(window: FetchWindow) -> AsyncIterator[RawObservation]`; `is_grid_based: bool` routes writer to correct hypertable | Claude's discretion; async generator supports both station-batch + grid-batch shapes |
| Robots.txt | `urllib.robotparser` (stdlib) + aiocache TTL 24h per host | RFC 9309 |

## Stack Touched in Phase 1

- [x] Project scaffold — uv workspace + pyproject + ruff + pyright + pre-commit + GitHub Actions CI
- [x] Routing — FastAPI minimal `/healthz` + `/readyz` (API-10 anticipated to Phase 1 per D-14)
- [x] Database — TimescaleDB BOTH hypertables created via Alembic, real reads (readyz `SELECT 1`) AND real writes (asyncpg COPY of normalized observations from ARPAE + ECMWF)
- [x] UI (docs) — MkDocs Material on GitHub Pages, quickstart page wired to working backfill CLI
- [x] Deployment — `docker compose up` brings the full stack green; CI deploys docs on every push to `main`

## Out of Scope (Deferred to Later Slices)

- All other public API endpoints — `/v1/stations`, `/v1/observations`, `/v1/sources*`, exports, OpenAPI 3.1 spec, rate limit, WebSocket → Phase 2
- Angular dashboard (including the verbatim footer in Angular layout) → Phase 3
- Other ARPA regions (Lombardia, Veneto), NOAA METAR, Copernicus C3S → Phase 4
- Threshold alerts (rules table, evaluator, webhook, email) → Phase 5
- Reverse proxy (Caddy / nginx) + TLS → Phase 3/4
- `mike` docs versioning → Phase 5 (paired with `v1.0.0` tag)
- Optional observability LGTM Compose profile (Grafana/Loki/Tempo/Prometheus) → Phase 5
- Custom domain `climatepulse.federicocalo.dev` → post-v1.0
- Navbar `Author` link / topbar social icon → declined; footer-only attribution
- DLQ CLI (`climatepulse dlq list/replay/drop`) → Phase 5
- Secret rotation runbook → Phase 5 (Phase 1 ships `.env.example` + gitleaks gates only)

## Subsequent Slice Plan

- **Phase 2 — Public REST API:** Layer the full FastAPI surface (`/v1/stations`, `/v1/observations` with resolution resolver routing across BOTH hypertables, `/v1/sources` health, export streaming, OpenAPI 3.1, slowapi rate limit, OTel + structlog + Prometheus, GDPR IP truncation) on top of the Phase 1 ingest+storage spine.
- **Phase 3 — Angular Dashboard MVP:** Consume Phase 2's OpenAPI 3.1 spec via typed `ApiClient`; ship map + station detail chart + source health page. Verbatim footer reused from `mkdocs.yml` copyright string (D-07).
- **Phase 4 — Live Updates + Source Breadth:** Add WebSocket fan-out, multi-station compare, ARPA Lombardia + Veneto + METAR + Copernicus C3S adapters (each adapter is a single file under `packages/core/.../adapters/`), Caddy reverse proxy + TLS.
- **Phase 5 — Alerts + Ops Hardening + v1.0:** Threshold alert rules + webhook (HMAC-SHA256) + email (aiosmtplib), `dlq` CLI, optional observability LGTM Compose profile, secret rotation runbook, `mike` versioned docs, `v1.0.0` tag + release notes.
