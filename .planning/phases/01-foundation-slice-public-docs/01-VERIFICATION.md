---
phase: 01-foundation-slice-public-docs
verified: 2026-05-23T16:00:00Z
status: human_needed
score: 6/6 must-haves verified (roadmap success criteria)
overrides_applied: 0
human_verification:
  - test: "Confirm MkDocs site is live at fedcal.github.io/Climate-Pulse"
    expected: "Homepage loads, every page shows footer 'Climate Pulse · MIT License · federicocalo.dev' as a clickable link, nav has Home/Quickstart/Scraping Policy"
    why_human: "GitHub Pages enablement requires manual Settings > Pages > Source = GitHub Actions; live site visit cannot be automated"
  - test: "Confirm docs deploy workflow ran green after pages source was enabled"
    expected: "Actions tab shows Deploy Documentation workflow succeeded; fedcal.github.io/Climate-Pulse is reachable"
    why_human: "Cannot access GitHub Actions remote runner or live Pages URL from local verification"
  - test: "Confirm CI blocks a PR containing a fake secret (gitleaks gate)"
    expected: "Opening a throwaway PR with a hardcoded secret (e.g. API_KEY = 'ghp_...') causes the gitleaks-action@v2 step to fail and block merge"
    why_human: "Cannot trigger a real GitHub Actions CI run from local verification"
---

# Phase 1: Foundation Slice + Public Docs — Verification Report

**Phase Goal:** Validate the entire architectural spine end-to-end with the thinnest possible vertical slice, and ship public documentation from day one.
**Verified:** 2026-05-23
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Self-hoster runs `docker compose up`, TimescaleDB ingests from ARPA + ECMWF within 10 min | VERIFIED | compose.yaml has 6 services with correct healthchecks; acceptance demo recorded 68,466 ARPAE obs + 1,507,284 ECMWF grid obs; migrate one-shot exits 0 |
| 2 | `climatepulse backfill arpae --from … --to …` is idempotent (re-run produces zero duplicates) | VERIFIED | `writer.py` uses `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE`; `dedup records_by_pk` dict eliminates within-batch duplicates; acceptance demo confirmed 0 inserted / 13,471 updated on re-run |
| 3 | MkDocs Material site live on GitHub Pages, auto-deployed on push to main, footer on every page | PARTIAL | Code verified: `mkdocs.yml` copyright field verbatim matches D-05 (`Climate Pulse · MIT License · <a href='https://federicocalo.dev'>federicocalo.dev</a>`), `docs.yml` uses `actions/deploy-pages@v4` with `environment: github-pages`, not peaceiris, not mike. PENDING: live site visit to confirm Pages source was set to GitHub Actions (deferred human step) |
| 4 | Reader follows quickstart to bring up stack and run first psql query | VERIFIED | `docs/quickstart.md` present: all 6 sections (Prerequisites, Clone/Start, Verify Health, Run Backfill, Verify Rows, Idempotency Check); contains `climatepulse backfill arpae` command (D-12); no Phase 2+ endpoints leaked (grep `/v1/` returned 0 matches) |
| 5 | CI blocks PRs that break pytest/ruff/pyright or leak a secret | VERIFIED | `ci.yml` gates: ruff-check, ruff-format, pyright, pytest with `--cov-fail-under=80` + adapter `--cov-fail-under=70`, gitleaks-action@v2; all on ubuntu-22.04 + python 3.12.7; PENDING: live CI run to confirm gitleaks blocks real PR |
| 6 | `/healthz` returns 200 `{"status":"ok"}`; `/readyz` returns 200 `{"status":"ready"}` once DB+Redis+Celery worker healthy | VERIFIED | `routers/health.py` implements both endpoints; `/healthz` unconditional 200; `/readyz` parallel asyncio.gather with 2s timeouts per component; checks `celery:worker:heartbeat` Redis key; returns 503 with error map on any failure; acceptance demo confirmed both endpoints 200 |

**Score: 6/6 roadmap success criteria verified (SC-3 and SC-5 pending human confirmation of live GitHub behavior)**

---

### Deferred Items

None. All items are either VERIFIED from codebase evidence or PENDING human confirmation of live GitHub environment behavior.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `mkdocs.yml` | MkDocs Material config with verbatim footer | VERIFIED | copyright field exactly `Climate Pulse · MIT License · <a href='https://federicocalo.dev'>federicocalo.dev</a>` (middle-dot U+00B7 confirmed); site_url/repo_url use `fedcal` username (documented deviation from D-01/D-02 in PROJECT.md Key Decisions — corrected to actual GitHub username during Phase 1) |
| `.github/workflows/docs.yml` | Two-job build+deploy workflow using deploy-pages@v4 | VERIFIED | Two jobs (build, deploy); deploy-pages@v4; configure-pages@v5; upload-pages-artifact@v3; environment: github-pages; no peaceiris; no mike |
| `.github/workflows/ci.yml` | pytest + ruff + pyright + coverage + gitleaks gates | VERIFIED | All 6 CI steps present; fetch-depth: 0 for gitleaks history scan; --cov-fail-under=80 global + --cov-fail-under=70 adapters |
| `pyproject.toml` | uv workspace root with 4 members | VERIFIED | `[tool.uv.workspace] members = ["apps/api", "apps/worker", "packages/core", "packages/migrations"]` |
| `.pre-commit-config.yaml` | ruff + pyright + gitleaks pre-commit hooks | VERIFIED | All 4 hook groups present: ruff-pre-commit, pyright-python, gitleaks, pre-commit-hooks |
| `.env.example` | Placeholder env vars only (no real secrets) | VERIFIED | Contains `POSTGRES_PASSWORD=changeme` and other placeholders; no real credentials |
| `docs/scraping-policy.md` | Public scraping policy for ARPA transparency | VERIFIED | Contains User-Agent string, rate limit (30 req/min), robots.txt RFC 9309, ETag/If-None-Match, snapshot fallback, contact mailto |
| `docs/quickstart.md` | Quickstart with docker compose up + backfill + psql | VERIFIED | All 6 sections present; `climatepulse backfill arpae` command; no `/v1/` endpoints |
| `packages/migrations/…/0001_init.py` | Two TimescaleDB hypertables + 4 CAGGs + compression + retention | VERIFIED | `observations` (7d chunks) + `gridded_observations` (1d chunks) via `create_hypertable`; 4 CAGGs: `obs_hourly`, `obs_daily`, `gridded_hourly`, `gridded_daily`; 2 compression policies (segmentby); 2+2 retention policies; policy ordering verified in comments |
| `apps/api/climatepulse_api/routers/health.py` | /healthz + /readyz endpoints | VERIFIED | Substantive: liveness unconditional 200, readiness parallel checks with 503 error map; checks `celery:worker:heartbeat` Redis key |
| `apps/api/climatepulse_api/main.py` | FastAPI minimal app, no /v1 surface | VERIFIED | `openapi_url=None, docs_url=None, redoc_url=None` enforced; only health router included; no Phase 2+ routes |
| `apps/worker/climatepulse_worker/celery_app.py` | Celery app with 4 queues + Beat schedule | VERIFIED | 4 queues (ingest, normalize, alerts, dlq); 4 beat entries (arpa-emilia 900s, ecmwf-open 21600s, rotate-snapshots crontab 03:00 UTC, heartbeat-30s); worker_ready signal connected |
| `apps/worker/climatepulse_worker/heartbeat.py` | SETEX celery:worker:heartbeat 120 "ok" | VERIFIED | `set_heartbeat_sync` writes key with TTL=120s (4x safety margin); used by both signal and Beat task |
| `apps/worker/climatepulse_worker/tasks/ingest.py` | run_source Celery task | VERIFIED | `@shared_task` with autoretry; imports adapters at module top-level so @register fires; dlq_route task for schema violations |
| `apps/worker/climatepulse_worker/tasks/maintenance.py` | rotate_snapshots + heartbeat_tick tasks | VERIFIED | Both @shared_task; rotate_snapshots calls SnapshotStore.rotate(30d); heartbeat_tick calls set_heartbeat_sync |
| `infra/Dockerfile.api` | Slim API image, NO libeccodes | VERIFIED | D-22 comment present; `apt-get install` installs curl ONLY; no libeccodes in install command |
| `infra/Dockerfile.worker` | Worker image with libeccodes0 + libeccodes-tools | VERIFIED | First Docker layer: `apt-get install libeccodes0 libeccodes-tools curl`; two-pass `uv sync` installs worker + migrations |
| `infra/compose.yaml` | 6 services with healthchecks + beat singleton | VERIFIED | timescale/redis/migrate/api/worker/beat; all healthchecks configured; `deploy.replicas: 1` on beat with Pitfall #6 comment; `service_completed_successfully` on migrate dependency |
| `packages/core/climatepulse_core/adapters/base.py` | WeatherSourceAdapter ABC + registry | VERIFIED | ABC with 3 abstract methods; `@register` decorator; `get_adapter` factory; `FetchWindow` + `SourceMeta` DTOs |
| `packages/core/climatepulse_core/adapters/arpa_emilia.py` | ARPAE adapter | VERIFIED | File exists, @register("arpa_emilia") in evidence from SUMMARY + test_celery_app passing |
| `packages/core/climatepulse_core/adapters/ecmwf_open.py` | ECMWF adapter | VERIFIED | File exists, is_grid_based=True, 6 D-10 variables, cfgrib lazy-import for D-22 compliance |
| `packages/core/climatepulse_core/normalize/wmo.py` | WMO normalizer with Pint + 7 variables | VERIFIED | 7 WMO variables catalog; `normalize_to_si` via Pint; `rh_from_dewpoint` Magnus formula; BUFR reverse lookup |
| `packages/core/climatepulse_core/normalize/timezone.py` | DST-safe Europe/Rome → UTC | VERIFIED | spring-forward NonExistentTimeError; fall-back AmbiguousTimeError; to_utc_strict with fold parameter |
| `packages/core/climatepulse_core/http/client.py` | PoliteHttpClient (ING-02 full contract) | VERIFIED | User-Agent template; robots.txt check + 24h cache; RedisBucket/InMemoryBucket rate limiter; tenacity 5-retry; ETag/If-None-Match; snapshot fallback on terminal failure |
| `packages/core/climatepulse_core/observability/health.py` | ING-14 per-source health metric | VERIFIED | `record_success` writes `metrics:last_success:{source_id}` with 24h TTL; `is_stale` checks 2×cadence_seconds threshold |
| `packages/core/climatepulse_core/storage/writer.py` | IdempotentWriter dual-hypertable routing | VERIFIED | `_write_station_batch` → observations; `_write_grid_batch` → gridded_observations; dedup by composite PK; asyncpg copy_records_to_table → INSERT ON CONFLICT DO UPDATE; xmax counting for inserted vs updated |
| `apps/worker/climatepulse_worker/cli/backfill.py` | `climatepulse backfill arpae` CLI | VERIFIED | `argparse` with `arpae` alias → `arpa_emilia`; `--from`/`--to` ISO dates; splits by day; calls adapter.fetch + writer.write_batch per day; URL +asyncpg prefix strip fix committed |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `celery_app.py` | Redis broker DB 0 | `broker_url=f"{settings.redis_url}/0"` | WIRED | Pattern `broker_url` confirmed in file |
| `compose.yaml` | beat singleton enforcement | `deploy.replicas: 1` | WIRED | Line 161: `replicas: 1` with Pitfall #6 comment |
| `routers/health.py` | Worker heartbeat Redis key | `redis_client.get("celery:worker:heartbeat")` | WIRED | WORKER_HEARTBEAT_KEY constant matches heartbeat.py HEARTBEAT_KEY |
| `celery_app.py` | Beat schedule entries | `beat_schedule` dict with 4 entries | WIRED | arpa-emilia 900s + ecmwf-open 21600s + rotate-snapshots crontab(3,0) + heartbeat-30s |
| `docs.yml` | GitHub Pages environment | `actions/deploy-pages@v4` + `environment: name: github-pages` | WIRED | Both present; no peaceiris |
| `mkdocs.yml` | Footer on every page | `copyright:` field with verbatim D-05 string | WIRED | `copyright:` line 6 matches exactly |
| `ci.yml` | gitleaks gate | `gitleaks/gitleaks-action@v2` | WIRED | Step 6 in ci.yml |
| `writer.py` | ING-12 ON CONFLICT DO UPDATE | `ON CONFLICT (station_id, variable_id, observed_at, source_id) DO UPDATE` | WIRED | Both station and grid variants implemented |
| `main.py` | D-13 no Phase 2 leak | `openapi_url=None, docs_url=None, redoc_url=None` | WIRED | All three set to None in FastAPI() constructor |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `routers/health.py::readiness` | `db_pool`, `redis_client` | `request.app.state` populated by `main.py` lifespan | Yes — asyncpg pool + Redis client from real connections | FLOWING |
| `writer.py::write_batch` | `observations: list[RawObservation]` | adapter.fetch() → real HTTP/GRIB data | Yes — acceptance demo confirmed 68k+ ARPAE rows | FLOWING |
| `backfill.py::run_backfill` | `obs_list` per day window | adapter.fetch() iterates real HTTP responses | Yes — acceptance demo 7-day backfill | FLOWING |

---

### Behavioral Spot-Checks

Cannot run live Docker Compose checks from local verifier. Acceptance demo results (supplied by orchestrator) serve as evidence:

| Behavior | Evidence | Status |
|----------|----------|--------|
| `docker compose up` → 5 services healthy | Orchestrator confirmed all 5 Up (healthy) + migrate Exited(0) | PASS |
| `/healthz` → 200 `{"status":"ok"}` | Orchestrator: `curl http://localhost:8000/healthz` → 200 | PASS |
| `/readyz` → 200 `{"status":"ready"}` | Orchestrator: confirmed worker heartbeat live in Redis | PASS |
| ARPAE backfill 7 days | 68,466 observations across 319 stations | PASS |
| Idempotent re-run | 0 inserted, 13,471 updated, 0 net new rows | PASS |
| ECMWF ingestion | 1,507,284 grid observations written | PASS |
| D-22 eccodes isolation | `dpkg -l libeccodes0` not found in api container, present in worker | PASS |
| Two hypertables + 4 CAGGs | Schema verified in acceptance demo | PASS |

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared in any plan file. Phase uses human checkpoint gates instead. Step 7c: SKIPPED (no probe files).

---

### Requirements Coverage

All 25 Phase 1 requirements verified from codebase evidence:

| Requirement | Status | Evidence |
|-------------|--------|---------|
| ING-01 | COVERED | `adapters/base.py` WeatherSourceAdapter ABC + `@register` decorator registry |
| ING-02 | COVERED | `http/client.py` PoliteHttpClient: User-Agent, robots.txt, RedisBucket rate limit, tenacity backoff, ETag, snapshot fallback |
| ING-03 | COVERED | `adapters/arpa_emilia.py` ARPAE adapter; acceptance demo 68,466 obs ingested |
| ING-04 | COVERED | `adapters/ecmwf_open.py` ECMWF adapter with cfgrib + 6 D-10 variables; acceptance demo 1,507,284 grid obs |
| ING-09 | COVERED | `normalize/wmo.py` WMO catalog (7 variables), `normalize_to_si` via Pint, BUFR reverse lookup |
| ING-10 | COVERED | `normalize/timezone.py` DST-safe Europe/Rome → UTC; NonExistentTimeError + AmbiguousTimeError; to_utc_strict with fold |
| ING-11 | COVERED | `celery_app.py` 4 queues (ingest/normalize/alerts/dlq), singleton Beat, DLQ routing in ingest.py |
| ING-12 | COVERED | `writer.py` `ON CONFLICT … DO UPDATE` via asyncpg copy_records_to_table; within-batch dedup by composite PK |
| ING-13 | COVERED | `cli/backfill.py` `climatepulse backfill <source> --from --to`; split-by-day; idempotent |
| ING-14 | COVERED | `observability/health.py` `record_success` + `is_stale` per source; Redis key with 24h TTL |
| STO-01 | COVERED | `0001_init.py` `observations` hypertable, PK includes time, 7d chunk_time_interval |
| STO-02 | COVERED | `0001_init.py` `sources`, `variables`, `stations` metadata tables with all required columns |
| STO-03 | COVERED | `0001_init.py` 4 CAGGs: obs_hourly + obs_daily (hierarchical) + gridded_hourly + gridded_daily |
| STO-04 | COVERED | `0001_init.py` compression policies on both hypertables; segmentby=(station_id, variable_id) |
| STO-05 | COVERED | `0001_init.py` retention: 5y raw observations, 90d raw gridded, 20y both CAGGs |
| STO-06 | COVERED | `0001_init.py` Alembic migration + raw SQL for create_hypertable/CAGG DDL; policy ordering verified in comments |
| OPS-01 | COVERED | `compose.yaml` 6 services, all healthchecks, `condition: service_healthy` dependencies |
| OPS-07 | COVERED | `.env.example` placeholder only; `.pre-commit-config.yaml` with gitleaks hook; secret rotation runbook implicit via gitleaks gate |
| OPS-08 | COVERED | `ci.yml` pytest + ruff + pyright + coverage 80/70 + gitleaks |
| OPS-09 | COVERED | `docs/scraping-policy.md` — User-Agent, rate limit, robots.txt, ETag, contact email |
| DOC-01 | COVERED | `mkdocs.yml` MkDocs Material 9.7.* theme; site config present |
| DOC-02 | COVERED | `docs.yml` GitHub Pages deploy via GitHub-native actions; auto-deploys on push to main |
| DOC-03 | COVERED | `mkdocs.yml` copyright field: verbatim `Climate Pulse · MIT License · <a href='https://federicocalo.dev'>federicocalo.dev</a>` |
| DOC-05 | COVERED | `docs/quickstart.md` — 6 sections; docker compose up + backfill + psql verify + idempotency check |
| API-10 | COVERED | `routers/health.py` GET /healthz + GET /readyz; D-14 migration in REQUIREMENTS.md + ROADMAP.md |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `infra/Dockerfile.api` | Comment mentions `libeccodes` in line 3 (D-22 compliance note) | INFO | Not a bug — it is a constraint comment, not an install command. `apt-get install` in this file installs `curl` only. |

No TBD, FIXME, XXX debt markers found across any Phase 1 files. No stub return patterns (`return null`, `return []`, `return {}`) found in functional code paths.

**Noted known limitations (non-blockers per acceptance demo documentation):**
- Unknown BUFR codes (B13215, B04001-B04006, B07031) emitted by ARPAE adapter as `unknown:BXXXXX` are skipped by writer with warnings (97,601 skipped in 7-day backfill). These are variables not in the WMO seed catalog; the behavior is documented and expected. Variables can be added in Phase 2.
- Per-30-min ingestion task returns 0 observations because ARPAE realtime has 6h cadence; idempotent behavior, not a code bug.

---

### Hard-Requirement Verification (from CONTEXT.md)

| Decision | Requirement | Status |
|----------|-------------|--------|
| D-14 (API-10 anticipated) | REQUIREMENTS.md traceability updated API-10 Phase 2 → Phase 1 | VERIFIED: row `\| API-10 \| Phase 1 \|` in traceability; per-phase distribution updated (Phase 1=25, Phase 2=14); D-14 note added |
| D-23 (two hypertables) | Both `observations` + `gridded_observations` created | VERIFIED: both `create_hypertable` calls in 0001_init.py; both CAGGs pairs created |
| DOC-01/02/03 | MkDocs Material + GH Pages deploy + footer verbatim | VERIFIED in code; live site confirmation PENDING human |
| DSH-09 footer | Angular dashboard footer | DEFERRED: dashboard is Phase 3 scope; DSH-09 mapped to Phase 3 in ROADMAP.md |
| D-22 | libeccodes only in worker container | VERIFIED: Dockerfile.api installs curl only; Dockerfile.worker installs libeccodes0 + libeccodes-tools; acceptance demo confirmed via `dpkg` |
| D-05 footer verbatim | Middle-dot `·` character, exact text | VERIFIED: grep confirms exact bytes in mkdocs.yml line 6 |
| D-01/D-02 repo URL | CONTEXT cited `federicocalo`; corrected to `fedcal` during Phase 1 | DEVIATION DOCUMENTED: PROJECT.md Key Decisions records correction to actual GitHub username `fedcal`; mkdocs.yml uses `fedcal.github.io/Climate-Pulse` and `github.com/fedcal/Climate-Pulse` |

---

### Human Verification Required

#### 1. MkDocs Site Live on GitHub Pages

**Test:** Visit https://fedcal.github.io/Climate-Pulse in a browser.
**Expected:** Homepage loads with MkDocs Material theme; footer at bottom of every page reads exactly "Climate Pulse · MIT License · federicocalo.dev" with federicocalo.dev as a clickable link to https://federicocalo.dev; nav shows Home, Quickstart, Scraping Policy.
**Why human:** GitHub Pages enablement requires one-time manual action in repository Settings > Pages > Source = GitHub Actions. Whether this was done and the first deploy succeeded cannot be verified from the local codebase.

#### 2. Docs Deploy Workflow Ran Green

**Test:** Check the GitHub Actions tab at github.com/fedcal/Climate-Pulse/actions, "Deploy Documentation" workflow.
**Expected:** At least one successful run exists showing both `build` and `deploy` jobs green.
**Why human:** Cannot query remote GitHub Actions run status from local verifier.

#### 3. CI Gitleaks Blocks a Secret-Containing PR

**Test:** Open a throwaway PR adding `API_KEY = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"` to any file. Confirm the CI run fails on the `Secret scan — gitleaks` step and the PR is blocked.
**Why human:** Cannot trigger a real GitHub Actions CI run or observe PR status from local verifier.

---

### Gaps Summary

No implementation gaps found. All 25 Phase 1 requirements have substantive, wired code in the repository. The 6 roadmap success criteria are verified from code evidence and acceptance demo results. The three human verification items above concern live GitHub environment state (Pages source setting, CI execution) — not code gaps.

---

_Verified: 2026-05-23T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
