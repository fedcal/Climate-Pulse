---
phase: 01-foundation-slice-public-docs
plan: "05"
subsystem: worker-api-compose
tags: [celery, fastapi, docker-compose, healthcheck, beat, ingestion, ops]
dependency_graph:
  requires: [01-01, 01-02, 01-03, 01-04]
  provides: [celery-worker, beat-singleton, healthz-readyz, compose-stack]
  affects: [REQUIREMENTS.md, ROADMAP.md]
tech_stack:
  added:
    - "Celery 5.6.3 with 4 queues (ingest/normalize/alerts/dlq)"
    - "celery.signals.worker_ready for startup heartbeat"
    - "kombu.Queue for explicit queue definition"
    - "FastAPI 0.136.1 minimal app (openapi_url=None)"
    - "asyncpg.create_pool for /readyz DB check"
    - "redis.asyncio.Redis for /readyz Redis check"
    - "pydantic-settings ApiSettings for API config"
    - "Docker Compose v2 with 6 services"
    - "TimescaleDB 2.17.2-pg16 (pinned)"
    - "Redis 7.4-alpine"
  patterns:
    - "Two-component heartbeat strategy: worker_ready signal + Beat periodic task"
    - "Parallel asyncio.gather for /readyz checks with 2s timeouts each"
    - "lifespan context manager for asyncpg pool + Redis client lifecycle"
    - "Beat singleton enforced via deploy.replicas: 1 + inline comment"
    - "migrate service with condition: service_completed_successfully"
key_files:
  created:
    - apps/worker/climatepulse_worker/celery_app.py
    - apps/worker/climatepulse_worker/heartbeat.py
    - apps/worker/climatepulse_worker/tasks/__init__.py
    - apps/worker/climatepulse_worker/tasks/ingest.py
    - apps/worker/climatepulse_worker/tasks/maintenance.py
    - apps/api/climatepulse_api/settings.py
    - apps/api/climatepulse_api/routers/__init__.py
    - apps/api/climatepulse_api/routers/health.py
    - apps/api/climatepulse_api/main.py
    - infra/Dockerfile.api
    - infra/Dockerfile.worker
    - infra/compose.yaml
    - tests/unit/test_celery_app.py
    - tests/unit/test_healthz.py
  modified:
    - apps/api/pyproject.toml (added asyncpg, redis, pydantic-settings deps)
    - .planning/REQUIREMENTS.md (API-10 moved Phase 2 → Phase 1)
    - .planning/ROADMAP.md (Phase 1 requirements + Success Criteria #6)
    - uv.lock (synced after api deps update)
decisions:
  - "Two-component heartbeat strategy (WARNING 3): worker_ready signal (startup) + heartbeat_tick Beat task (every 30s periodic). No alternatives considered."
  - "autodiscover_tasks(force=True) not sufficient in test isolation — used explicit module imports instead to guarantee task registration at module-load time"
  - "TestClient lifespan patching: monkeypatched asyncpg.create_pool + Redis.from_url to prevent real connection attempts in unit tests"
  - "Dockerfile.api contains D-22 comment mentioning libeccodes — the grep check was adjusted to target apt-get install, not any string mention"
metrics:
  duration: "16 minutes"
  completed_date: "2026-05-23"
  tasks_completed: 4
  tasks_total: 5
  files_created: 14
  files_modified: 4
---

# Phase 1 Plan 5: Celery + FastAPI Minimal API + Docker Compose Summary

**One-liner:** Celery 5.6.3 worker with 4 queues + singleton Beat + FastAPI minimal /healthz + /readyz + compose.yaml stack with healthchecks; API-10 moved Phase 2 → Phase 1 per D-14 mandate.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Celery app + 4 queues + Beat + heartbeat | 90960f5 | celery_app.py, heartbeat.py, tasks/ingest.py, tasks/maintenance.py |
| 2 | FastAPI minimal /healthz + /readyz | cbe4dc7 | main.py, routers/health.py, settings.py |
| 3 | Dockerfiles + compose.yaml | 15a6cd0 | Dockerfile.api, Dockerfile.worker, compose.yaml |
| 4 | REQUIREMENTS.md + ROADMAP.md (API-10 migration) | 4522ae6 | REQUIREMENTS.md, ROADMAP.md |
| 5 | Acceptance demo checkpoint | - | Awaiting human verification |

## What Was Built

### Task 1: Celery App + Worker Infrastructure (ING-11)

**celery_app.py** configures:
- Broker: `{redis_url}/0` (DB 0 per settings allocation)
- Results: `{redis_url}/1` (DB 1)
- 4 queues: `ingest`, `normalize`, `alerts`, `dlq`
- Beat schedule: arpa_emilia 900s (D-19), ecmwf_open 21600s, rotate_snapshots crontab(hour=3, minute=0) (D-17), heartbeat_tick 30s (WARNING 3)

**Heartbeat strategy** (WARNING 3 committed — two components, no alternatives):
1. `worker_ready` signal → `set_heartbeat_sync(redis_url)` on process startup
2. `heartbeat_tick` Beat task every 30s → `set_heartbeat_sync(redis_url)` periodic renewal
- Redis key: `celery:worker:heartbeat` with TTL=120s (4x safety margin over 30s cadence)

**tasks/ingest.py** (`run_source`):
- Autoretry for any exception, max 3 retries, exponential backoff up to 300s
- Adapter imported at module top-level (so @register fires on Celery autodiscovery)
- Schema violations routed to `dlq` queue via `dlq_route.apply_async(queue='dlq')`
- `dlq_route` persists to Redis list `dlq:{source_id}` (trimmed to 1000 entries)

**tasks/maintenance.py**:
- `rotate_snapshots`: calls `SnapshotStore.rotate(max_age_days=30)` (D-17)
- `heartbeat_tick`: calls `set_heartbeat_sync` from heartbeat module

**Test coverage: 11/11 tests pass** — queue count, beat schedule cadences, task registration, heartbeat TTL, signal connection.

### Task 2: FastAPI Minimal API (D-14, API-10)

**GET /healthz**: Returns `{"status":"ok"}` unconditionally (no deps).

**GET /readyz**: Parallel asyncio.gather checks with 2s timeouts:
- DB: asyncpg `SELECT 1`
- Redis: `redis_client.ping()`
- Celery: `redis_client.get("celery:worker:heartbeat")` == b"ok"
- Returns 503 with `{"detail": {"component": "error message"}}` if any fail

**D-13 enforcement**: `openapi_url=None, docs_url=None, redoc_url=None` — /docs, /redoc, /openapi.json all return 404.

**ApiSettings** (separate from core Settings): `database_url`, `redis_url`, `environment` — no `snapshot_dir` (D-22, API container doesn't need it).

**Test coverage: 7/7 tests pass** — healthz unconditional, readyz healthy/db-down/no-heartbeat, docs disabled, no v1 routes.

### Task 3: Docker Infrastructure (OPS-01)

**Dockerfile.api**:
- Base: `python:3.12.7-slim-bookworm`
- D-22 compliance: `curl` only system dep; NO libeccodes
- HEALTHCHECK: `curl -fsS http://localhost:8000/healthz`
- CMD: `uv run uvicorn climatepulse_api.main:app --host 0.0.0.0 --port 8000`

**Dockerfile.worker**:
- Base: `python:3.12.7-slim-bookworm`
- D-21 compliance: `libeccodes0 libeccodes-tools` in first Docker layer
- HEALTHCHECK: `celery -A climatepulse_worker.celery_app inspect ping -t 5`
- CMD: 4 worker concurrency consuming all 4 queues
- Used for BOTH worker and beat services (command override in compose.yaml)

**compose.yaml** (6 services):
- `timescale`: image pinned `2.17.2-pg16`, healthcheck `pg_isready`, NOT port-exposed
- `redis`: image `7.4-alpine`, healthcheck `redis-cli ping`, NOT port-exposed
- `migrate`: one-shot Alembic runner with `restart: "no"`, exits 0 on success
- `api`: depends_on `migrate: service_completed_successfully` (schema before connections)
- `worker`: depends_on `migrate: service_completed_successfully`, snapshots_data volume (D-15)
- `beat`: `deploy.replicas: 1` with `DO NOT scale beat > 1` comment (Pitfall #6)
- Only `api` exposes port 8000 (T-05-04/T-05-05 mitigations)

### Task 4: Documentation Updates (D-14)

**REQUIREMENTS.md**:
- API-10 Traceability: Phase 2 → Phase 1
- Per-phase distribution: Phase 1 = 25 (added API(1)), Phase 2 = 14 (removed API(1))
- D-14 update note added

**ROADMAP.md**:
- Phase 1 Requirements line: `, API-10` appended
- Phase 2 Requirements: `API-10, ` removed
- Phase 1 Success Criteria #6 added: `/healthz + /readyz` specification

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] autodiscover_tasks insufficient for test isolation**
- **Found during:** Task 1 (test_run_source_task_registered failing)
- **Issue:** `app.autodiscover_tasks(["climatepulse_worker.tasks"])` does not force module import at celery_app.py load time; tasks only register when the module is explicitly imported. In test isolation where modules are cleared/reloaded, autodiscovery finds nothing.
- **Fix:** Added explicit `import climatepulse_worker.tasks.ingest` and `import climatepulse_worker.tasks.maintenance` before `autodiscover_tasks()` call. Tasks register at module-import time. autodiscover_tasks kept as belt-and-suspenders for production startup.
- **Files modified:** `apps/worker/climatepulse_worker/celery_app.py`
- **Commit:** 90960f5

**2. [Rule 1 - Bug] asyncpg version mismatch in api pyproject.toml**
- **Found during:** Task 2 (uv sync failed)
- **Issue:** api/pyproject.toml specified `asyncpg==0.30.*` but climatepulse-core requires `asyncpg==0.31.*`; workspace resolution failure.
- **Fix:** Changed api dep to `asyncpg==0.31.*` to match core.
- **Files modified:** `apps/api/pyproject.toml`
- **Commit:** cbe4dc7

**3. [Rule 1 - Bug] TestClient lifespan executes real asyncpg.create_pool**
- **Found during:** Task 2 (test_healthz_returns_200_with_status_ok failing with InvalidPasswordError)
- **Issue:** TestClient with `with TestClient(app)` context manager triggers the `lifespan` which calls `asyncpg.create_pool(test_url)` — this tries to connect to a real PostgreSQL server.
- **Fix:** Monkeypatched `asyncpg.create_pool` and `redis.asyncio.Redis.from_url` in the `api_app` fixture to return AsyncMock objects. Tests operate on mock connections, not real ones.
- **Files modified:** `tests/unit/test_healthz.py`
- **Commit:** cbe4dc7

**4. [Rule 1 - Bug] clear_adapter_registry fixture conflicts with test_adapters_registered_on_import**
- **Found during:** Task 1 (test_adapters_registered_on_import failing in full test suite, passing in isolation)
- **Issue:** The autouse `clear_adapter_registry` fixture (conftest.py) clears the `_REGISTRY` before each test. When `test_adapters_registered_on_import` runs after `test_four_queues_defined`, the adapter modules are cached in sys.modules (already imported) but `_REGISTRY` is cleared. Re-importing the ingest module doesn't trigger `@register` again because Python module cache skips re-execution.
- **Fix:** The test now explicitly deletes ALL climatepulse_core.adapters.* and climatepulse_worker modules from sys.modules AND clears `_REGISTRY` directly before reimporting. This forces `@register` to fire fresh.
- **Files modified:** `tests/unit/test_celery_app.py`
- **Commit:** 90960f5

## Known Stubs

None — all functionality is wired. The `dlq_route` task persists to Redis and logs, which is the complete Phase 1 behavior (Phase 5 DLQ CLI is the planned extension).

## Threat Surface Scan

New surface introduced this plan:

| Flag | File | Description |
|------|------|-------------|
| threat_flag: public_endpoint | apps/api/climatepulse_api/routers/health.py | GET /healthz + GET /readyz are publicly exposed on port 8000. T-05-01 (accept) and T-05-06 (accept with 2s timeout) mitigations documented in PLAN.md threat model. |
| threat_flag: env_secrets | infra/compose.yaml | POSTGRES_PASSWORD interpolated from .env at runtime. T-05-08 mitigation: .env gitignored (Plan 01), .env.example has placeholders only. |

## Self-Check

### Files Exist
- [x] apps/worker/climatepulse_worker/celery_app.py
- [x] apps/worker/climatepulse_worker/heartbeat.py
- [x] apps/worker/climatepulse_worker/tasks/__init__.py
- [x] apps/worker/climatepulse_worker/tasks/ingest.py
- [x] apps/worker/climatepulse_worker/tasks/maintenance.py
- [x] apps/api/climatepulse_api/settings.py
- [x] apps/api/climatepulse_api/routers/__init__.py
- [x] apps/api/climatepulse_api/routers/health.py
- [x] apps/api/climatepulse_api/main.py
- [x] infra/Dockerfile.api
- [x] infra/Dockerfile.worker
- [x] infra/compose.yaml
- [x] tests/unit/test_celery_app.py
- [x] tests/unit/test_healthz.py
- [x] .planning/phases/01-foundation-slice-public-docs/01-05-SUMMARY.md

### Commits Exist
- [x] 90960f5 — Task 1 (Celery + heartbeat + tasks)
- [x] cbe4dc7 — Task 2 (FastAPI health endpoints)
- [x] 15a6cd0 — Task 3 (Dockerfiles + compose.yaml)
- [x] 4522ae6 — Task 4 (REQUIREMENTS.md + ROADMAP.md)

### Test Results
- 11/11 test_celery_app.py — PASS
- 7/7 test_healthz.py — PASS
- Total: 18/18 unit tests PASS

## Self-Check: PASSED

All files created, all commits exist, all 18 unit tests pass.

---

## Pending: Task 5 — Acceptance Demo Checkpoint

Task 5 is a `checkpoint:human-verify` requiring the user to run the full D-9 acceptance demo on a fresh `docker compose up`. The checkpoint details are returned in the agent's final message.
