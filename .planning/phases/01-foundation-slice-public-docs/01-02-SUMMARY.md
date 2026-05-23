---
phase: 01-foundation-slice-public-docs
plan: "02"
subsystem: storage
tags: [timescaledb, hypertable, alembic, migrations, testcontainers, cagg, compression, retention]
dependency_graph:
  requires:
    - "01-01-PLAN.md (workspace scaffold, pyproject.toml, uv setup)"
  provides:
    - "climatepulse_core.domain.models (RawObservation, Observation, Station, Variable, Source, QcFlag)"
    - "climatepulse_core.storage.models (Base, SourceRow, VariableRow, StationRow)"
    - "Alembic migration 0001_init: sources/variables/stations + observations + gridded_observations hypertables"
    - "4 CAGGs: obs_hourly, obs_daily (hierarchical), gridded_hourly, gridded_daily (hierarchical)"
    - "Compression + retention policies on both hypertables and both daily CAGGs"
    - "9 integration tests via testcontainers TimescaleDB 2.17.2-pg16"
  affects:
    - "01-03-PLAN.md (adapter ABC, normalizer, writer — imports from domain.models and storage)"
    - "01-05-PLAN.md (Docker Compose — runs this migration on startup)"
tech_stack:
  added:
    - "asyncpg 0.31.0"
    - "SQLAlchemy[asyncio] 2.0.49"
    - "sqlalchemy-timescaledb 0.4.1"
    - "Alembic 1.18.4"
    - "testcontainers 4.14.x (DockerContainer pattern)"
    - "pytest-asyncio 1.3.0"
  patterns:
    - "Frozen dataclasses for domain models (immutability per coding-style.md)"
    - "ORM for metadata tables only; hypertables managed via op.execute() raw SQL"
    - "sync _run_migrations session fixture + per-test asyncpg pool (avoids asyncio loop scope conflicts)"
    - "include_name callback with prefix matching for _timescaledb*/_hyper_* (Q5 resolution)"
key_files:
  created:
    - "packages/core/climatepulse_core/domain/models.py"
    - "packages/core/climatepulse_core/domain/__init__.py"
    - "packages/core/climatepulse_core/storage/models.py"
    - "packages/core/climatepulse_core/storage/__init__.py"
    - "packages/core/climatepulse_core/__init__.py"
    - "packages/core/pyproject.toml"
    - "packages/migrations/alembic.ini"
    - "packages/migrations/climatepulse_migrations/env.py"
    - "packages/migrations/climatepulse_migrations/versions/0001_init.py"
    - "packages/migrations/pyproject.toml"
    - "tests/integration/conftest.py"
    - "tests/integration/test_hypertable.py"
    - "tests/integration/test_idempotency.py"
    - "tests/integration/test_cagg.py"
    - "pyproject.toml (workspace root)"
    - "uv.lock"
    - ".gitignore"
  modified:
    - "packages/migrations/alembic.ini (script_location fix: %(here)s prefix)"
    - "packages/migrations/climatepulse_migrations/versions/0001_init.py (sa.REAL fix)"
decisions:
  - "Use sync _run_migrations session fixture + per-test asyncpg pool (function-scoped) to avoid asyncpg event loop scope conflicts in pytest-asyncio 1.x"
  - "time_interval (INTERVAL) not integer_interval (NULL for TIMESTAMPTZ hypertables) used for chunk interval assertion"
  - "alembic.ini script_location = %(here)s/climatepulse_migrations so migration runs from any CWD"
metrics:
  duration: "~45 minutes"
  completed: "2026-05-23"
  tasks_completed: 3
  files_created: 16
  tests_added: 9
---

# Phase 01 Plan 02: Storage Layer (Hypertables + CAGGs + Integration Tests) Summary

**One-liner:** Two TimescaleDB hypertables (observations + gridded_observations) with 4 hierarchical CAGGs, compression+retention policies, and 9 passing integration tests via testcontainers 2.17.2-pg16.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Domain dataclasses + SQLAlchemy metadata models | 9a016d0 | domain/models.py, storage/models.py, pyproject.toml |
| 2 | Alembic env + initial migration | ce8d20c | alembic.ini, env.py, versions/0001_init.py |
| 3 | testcontainers fixture + 9 integration tests | 4d3289f | conftest.py, test_hypertable.py, test_idempotency.py, test_cagg.py |

## Requirements Delivered

| Requirement | Status | Evidence |
|-------------|--------|----------|
| STO-01 | DONE | observations hypertable, PK(station_id,variable_id,observed_at,source_id), chunk 7d |
| STO-02 | DONE | sources/variables/stations ORM models + DDL in migration |
| STO-03 | DONE | 4 CAGGs: obs_hourly(raw→1h) + obs_daily(obs_hourly→1d) + gridded_hourly(raw→6h) + gridded_daily(gridded_hourly→1d) |
| STO-04 | DONE | Compression: segmentby station_id+variable_id (obs) / lat_idx+lon_idx+variable_id (gridded) |
| STO-05 | DONE | Retention: 5y raw obs, 90d raw gridded, 20y both daily CAGGs |
| STO-06 | DONE | Alembic op.execute() pattern, include_name exclusion (Pitfall D + Q5 resolution) |
| D-23 | DONE | TWO hypertables: observations (station-based) + gridded_observations (grid-based) |

## Testcontainer Image

**Image used:** `timescale/timescaledb:2.17.2-pg16` (pinned per Pitfall E — NOT latest-pg16)

The tag was available on Docker Hub and downloaded successfully. All 9 integration tests run against this exact version.

## Policy Ordering Matrix (Pitfall #3 Compliance)

| Hypertable / CAGG | refresh_end_offset | compress_after | retention_after | Verified |
|---|---|---|---|---|
| observations | 1 hour | 7 days | 5 years | end_offset(1h) < compress(7d) < retention(5y) ✓ |
| obs_daily | 1 day | — | 20 years | end_offset(1d) < retention(20y) ✓ |
| gridded_observations | 6 hours | 7 days | 90 days | end_offset(6h) < compress(7d) < retention(90d) ✓ |
| gridded_daily | 1 day | — | 20 years | end_offset(1d) < retention(20y) ✓ |

## Integration Tests Added

| Test File | Tests | What Proven |
|-----------|-------|-------------|
| test_hypertable.py | 4 | Both hypertables in timescaledb_information.hypertables; num_dimensions=1; chunk intervals 7d and 1d via time_interval INTERVAL |
| test_idempotency.py | 1 | ON CONFLICT DO UPDATE upsert: duplicate inserts produce 1 row; re-insert with new value updates correctly (ING-12) |
| test_cagg.py | 4 | obs_hourly avg+count after refresh; obs_daily hierarchical (view_definition references obs_hourly); gridded_hourly avg+count; gridded_daily hierarchical (view_definition references gridded_hourly) |

**Total: 9/9 tests pass** against timescale/timescaledb:2.17.2-pg16.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sa.Real() does not exist in SQLAlchemy 2.0**
- **Found during:** Task 3 (Alembic migration failed with AttributeError)
- **Issue:** SQLAlchemy 2.0 exports `sa.REAL` not `sa.Real`; 3 occurrences in 0001_init.py
- **Fix:** Replaced all `sa.Real()` with `sa.REAL()` in the migration
- **Files modified:** packages/migrations/climatepulse_migrations/versions/0001_init.py
- **Commit:** 4d3289f

**2. [Rule 3 - Blocking] alembic.ini script_location was relative to CWD, not ini file**
- **Found during:** Task 3 (Alembic upgrade head failed with "Path doesn't exist: climatepulse_migrations")
- **Issue:** `script_location = climatepulse_migrations` resolves relative to CWD, not the ini file directory, breaking the subprocess invocation from conftest.py
- **Fix:** Changed to `script_location = %(here)s/climatepulse_migrations` (Alembic `%(here)s` = ini file directory)
- **Files modified:** packages/migrations/alembic.ini
- **Commit:** 4d3289f

**3. [Rule 1 - Bug] integer_interval is NULL for TIMESTAMPTZ hypertables**
- **Found during:** Task 3 (test_hypertable.py chunk interval tests failed)
- **Issue:** TimescaleDB stores chunk_time_interval in `time_interval` (INTERVAL type) for timestamp-based hypertables; `integer_interval` is only populated for integer time columns (NULL for TIMESTAMPTZ)
- **Fix:** Changed assertions to use `time_interval` and compare against `timedelta` objects
- **Files modified:** tests/integration/test_hypertable.py
- **Commit:** 4d3289f

**4. [Rule 3 - Blocking] asyncpg pool event loop scope conflict with pytest-asyncio 1.x**
- **Found during:** Task 3 (all tests failed with "Future attached to a different loop")
- **Issue:** Session-scoped asyncpg pools are bound to the event loop they were created in; pytest-asyncio 1.x uses function-scoped loops by default for async tests, causing cross-loop access errors
- **Fix:** Restructured conftest.py: (a) migration and seeding in sync `_run_migrations` fixture using `asyncio.run()`, (b) per-test function-scoped `db_pool` fixture that creates a fresh asyncpg pool in the test's own event loop
- **Files modified:** tests/integration/conftest.py
- **Commit:** 4d3289f

## Threat Flags

No new security-relevant surfaces beyond those in the plan's threat model.

## Known Stubs

None — all planned functionality is wired and verified by integration tests.

## Self-Check: PASSED

- packages/core/climatepulse_core/domain/models.py: FOUND
- packages/core/climatepulse_core/storage/models.py: FOUND
- packages/migrations/climatepulse_migrations/versions/0001_init.py: FOUND
- packages/migrations/climatepulse_migrations/env.py: FOUND
- tests/integration/conftest.py: FOUND
- tests/integration/test_hypertable.py: FOUND
- tests/integration/test_idempotency.py: FOUND
- tests/integration/test_cagg.py: FOUND
- Commits: 9a016d0, ce8d20c, 4d3289f — all verified in git log
