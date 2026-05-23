---
phase: 01-foundation-slice-public-docs
plan: "01"
subsystem: infra
tags: [uv, mkdocs-material, github-pages, github-actions, gitleaks, pre-commit, ruff, pyright, pytest, fastapi, celery, timescaledb, asyncpg, pydantic]

requires: []

provides:
  - uv workspace with 4 members (apps/api, apps/worker, packages/core, packages/migrations)
  - pyproject.toml root with ruff, pyright, pytest-cov config and all dev deps
  - MkDocs Material site config with verbatim footer 'Climate Pulse · MIT License · federicocalo.dev'
  - docs/index.md, docs/quickstart.md, docs/scraping-policy.md (DOC-01/02/03/05 + OPS-09)
  - GitHub Actions CI workflow with ruff + pyright + pytest 80%/70% coverage + gitleaks gates
  - GitHub Actions docs deploy workflow (GitHub-native deploy-pages@v4, NOT peaceiris)
  - pre-commit config with ruff + pyright + gitleaks + pre-commit-hooks
  - .env.example with placeholder values only
  - README with project pitch + beat-scaling WARNING

affects: [01-02, 01-03, 01-04, 01-05, all-future-plans]

tech-stack:
  added:
    - uv 0.11.13 (workspace sync, lock file)
    - mkdocs-material 9.7.6
    - mkdocstrings[python] 1.0.4
    - ruff 0.15.14
    - pyright 1.1.409
    - pre-commit 4.6.0
    - gitleaks v8.21.2 (pre-commit hook + gitleaks-action@v2 in CI)
    - pytest 8.3.x + pytest-asyncio 1.3.x + pytest-cov 7.1.x
    - hypothesis 6.152.x
    - testcontainers 4.14.x
    - fakeredis>=2.23
    - vcrpy 8.1.x + pytest-recording + respx>=0.21
    - climatepulse-core (httpx, tenacity, aiocache, pyrate-limiter, pint, pydantic, sqlalchemy, asyncpg, structlog, redis)
    - climatepulse-api (fastapi 0.136.x, uvicorn 0.47.x)
    - climatepulse-worker (celery 5.6.3, ecmwf-opendata, cfgrib, xarray, numpy)
    - climatepulse-migrations (alembic, sqlalchemy-timescaledb, asyncpg)
  patterns:
    - uv workspace with [build-system] hatchling per-member (required for editable installs)
    - GitHub Pages two-job workflow (build + deploy) via GitHub-native actions
    - gitleaks at both pre-commit and CI level (defense in depth for secrets)
    - coverage gates: 80% global / 70% adapters (D-24)
    - cfgrib/libeccodes isolated to apps/worker only (D-22)

key-files:
  created:
    - pyproject.toml (uv workspace root, ruff/pyright/pytest/coverage config)
    - uv.lock (materialized lockfile, 123 packages)
    - apps/api/pyproject.toml (fastapi, uvicorn, climatepulse-core)
    - apps/worker/pyproject.toml (celery, ecmwf-opendata, cfgrib, xarray, numpy)
    - packages/core/pyproject.toml (httpx, tenacity, aiocache, pyrate-limiter, pint, pydantic, sqlalchemy, asyncpg, structlog, redis)
    - packages/migrations/pyproject.toml (alembic, sqlalchemy-timescaledb, asyncpg)
    - apps/api/climatepulse_api/__init__.py
    - apps/worker/climatepulse_worker/__init__.py
    - packages/core/climatepulse_core/__init__.py
    - packages/migrations/climatepulse_migrations/__init__.py
    - .gitignore
    - .env.example
    - README.md
    - mkdocs.yml (verbatim copyright footer, nav, plugins)
    - docs/index.md
    - docs/quickstart.md
    - docs/scraping-policy.md
    - .pre-commit-config.yaml
    - .github/workflows/ci.yml
    - .github/workflows/docs.yml
  modified: []

key-decisions:
  - "Added [build-system] hatchling to all 4 workspace member pyproject.tomls — required for uv to produce editable installs in the venv; without it only climatepulse-core was importable (Rule 1 auto-fix during Task 1)"
  - "copyright field in mkdocs.yml uses verbatim string with middle-dot U+00B7 per D-05/D-06 — no custom MkDocs partial needed"
  - "docs.yml uses GitHub-native configure-pages@v5 + upload-pages-artifact@v3 + deploy-pages@v4 per D-03 — peaceiris explicitly excluded"
  - "CI coverage gate: --cov-fail-under=80 global + separate --cov-fail-under=70 for adapters per D-24"
  - "gitleaks-action@v2 in CI with GITHUB_TOKEN (free for public repos); gitleaks v8.21.2 in pre-commit for local gate"
  - "fakeredis>=2.23 in root dev deps from Wave 0 — required by Plan 03 PoliteHttpClient tests + Plan 05 heartbeat tests"

patterns-established:
  - "uv workspace: all members need [build-system] hatchling for editable installs"
  - "cfgrib/ecmwf isolation: apps/worker/pyproject.toml ONLY; never add to api or core"
  - "gitleaks dual-gate: pre-commit (local) + CI (remote); .env.example must use placeholders only"
  - "CI jobs always use ubuntu-22.04 + python 3.12.7 (single matrix target per CONTEXT.md)"
  - "docs workflow: lightweight pip install (not full workspace sync) for docs-only CI speed"

requirements-completed: [DOC-01, DOC-02, DOC-03, DOC-05, OPS-07, OPS-08, OPS-09]

duration: 8min
completed: 2026-05-23
---

# Phase 1 Plan 01: Foundation Slice — uv workspace skeleton + MkDocs Material live on GitHub Pages with verbatim footer + CI gates

**uv workspace with 4 packages, MkDocs Material site publishing `Climate Pulse · MIT License · federicocalo.dev` footer, and GitHub Actions CI enforcing ruff + pyright + pytest 80/70% coverage + gitleaks gates**

## Performance

- **Duration:** ~8 minutes
- **Started:** 2026-05-23T10:24:56Z
- **Completed:** 2026-05-23T10:32:52Z
- **Tasks:** 3 auto + 1 checkpoint (human-verify for GitHub Pages source setting)
- **Files created:** 20

## Accomplishments

- uv workspace root + 4 per-package pyprojects fully resolved (123 packages in uv.lock); all 4 workspace packages import successfully
- MkDocs Material 9.7.6 site config with VERBATIM copyright footer `Climate Pulse · MIT License · <a href='https://federicocalo.dev'>federicocalo.dev</a>` (middle-dot U+00B7 per D-05); `mkdocs build --strict` passes with zero warnings
- docs/index.md + docs/quickstart.md (7-section guide with exact `climatepulse backfill arpae` command + idempotency check) + docs/scraping-policy.md (User-Agent, 30 req/min, robots.txt, ETag, snapshot fallback, contact email)
- .github/workflows/docs.yml: GitHub-native two-job (build + deploy) workflow with configure-pages@v5 + upload-pages-artifact@v3 + deploy-pages@v4 and `environment: github-pages`; peaceiris explicitly not used per D-03
- .github/workflows/ci.yml: ubuntu-22.04 + python 3.12.7; ruff check + ruff format --check + pyright + pytest --cov-fail-under=80 + adapters --cov-fail-under=70 + gitleaks-action@v2; fetch-depth:0 for gitleaks history
- .pre-commit-config.yaml: ruff v0.15.14 + pyright v1.1.409 + gitleaks v8.21.2 + pre-commit-hooks v5.0.0; `pre-commit run --all-files` passes all hooks

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold uv workspace + package skeletons + .gitignore + .env.example** - `f018222` (chore)
2. **Task 2: MkDocs Material config + docs pages + verbatim footer** - `0928865` (feat)
3. **Task 3: Pre-commit config + GitHub Actions CI + Docs deploy workflow** - `a9fc374` (chore)
4. **Task 4: GitHub Pages source enablement checkpoint** - awaiting human verify

## Files Created/Modified

- `pyproject.toml` — uv workspace root, ruff/pyright/pytest/coverage config, dev deps (fakeredis>=2.23 included)
- `uv.lock` — 123 packages resolved
- `apps/api/pyproject.toml` — fastapi 0.136.x, uvicorn 0.47.x, climatepulse-core (workspace dep)
- `apps/worker/pyproject.toml` — celery 5.6.3, ecmwf-opendata, cfgrib, xarray, numpy (cfgrib isolated here per D-22)
- `packages/core/pyproject.toml` — httpx, tenacity, aiocache, pyrate-limiter, pint, pydantic, sqlalchemy, asyncpg, structlog, redis
- `packages/migrations/pyproject.toml` — alembic, sqlalchemy-timescaledb, asyncpg
- `apps/api/climatepulse_api/__init__.py` — package marker
- `apps/worker/climatepulse_worker/__init__.py` — package marker
- `packages/core/climatepulse_core/__init__.py` — package marker
- `packages/migrations/climatepulse_migrations/__init__.py` — package marker
- `.gitignore` — Python, uv, pytest, mkdocs, .env, GRIB, snapshots, IDE, OS
- `.env.example` — placeholder values only (no real secrets; gitleaks-clean)
- `README.md` — project pitch, badge placeholders, beat scaling WARNING paragraph
- `mkdocs.yml` — verbatim copyright footer, nav (3 pages), Material theme, mkdocstrings plugin
- `docs/index.md` — overview, architecture diagram, Phase 1 API scope, quickstart link
- `docs/quickstart.md` — 7-section guide: prereqs → clone → health → backfill → verify → idempotency → next
- `docs/scraping-policy.md` — User-Agent, 30 req/min, robots.txt RFC 9309, ETag, snapshot fallback, contact mailto
- `.pre-commit-config.yaml` — ruff + pyright + gitleaks + pre-commit-hooks
- `.github/workflows/ci.yml` — CI gates (ruff, pyright, pytest 80/70, gitleaks-action@v2)
- `.github/workflows/docs.yml` — GitHub-native Pages deploy (two-job, configure-pages@v5 + deploy-pages@v4)

## Decisions Made

- Added `[build-system] hatchling` to all 4 workspace member pyproject.tomls — uv requires this for editable installs; without it, only `climatepulse_core` (which had a pre-existing build-system from the skeleton) was importable from the shared venv. This is a standard uv workspace pattern and not a plan deviation, but it needed to be applied to all members.
- `copyright` field in `mkdocs.yml` uses the verbatim string with middle-dot `·` (U+00B7) per D-05/D-06. No custom MkDocs partial needed.
- GitHub Pages docs deploy uses GitHub-native actions only (configure-pages@v5, upload-pages-artifact@v3, deploy-pages@v4) — peaceiris explicitly not used per D-03.
- CI coverage gate: `--cov-fail-under=80` global + separate pytest run for adapters with `--cov-fail-under=70` per D-24. Both steps use `continue-on-error: false`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added [build-system] hatchling to all 4 workspace member pyproject.tomls**
- **Found during:** Task 1 (post-sync verification)
- **Issue:** After `uv sync --all-packages --all-groups`, only `climatepulse_core` was importable. The other 3 packages (api, worker, migrations) were missing from site-packages because they lacked a `[build-system]` declaration — uv cannot create editable installs without one.
- **Fix:** Added `[build-system] requires = ["hatchling"] build-backend = "hatchling.build"` to all 4 member pyproject.tomls.
- **Files modified:** `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`, `packages/core/pyproject.toml`, `packages/migrations/pyproject.toml`
- **Verification:** `uv run python -c "import climatepulse_core, climatepulse_api, climatepulse_worker, climatepulse_migrations"` succeeds.
- **Committed in:** `f018222` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug: missing build-system declaration preventing workspace package imports)
**Impact on plan:** Required for correctness — the plan explicitly requires all 4 packages to be importable. Fix is standard uv workspace pattern.

## Issues Encountered

- `uv sync --all-packages --all-groups` reported success but `--package X` variants uninstalled other packages — this is expected uv behavior (package-specific sync switches venv context). The correct invocation is always `--all-packages --all-groups` for the shared workspace venv.

## User Setup Required

**GitHub Pages source must be set to "GitHub Actions" before the docs deploy workflow will succeed.**

1. Go to https://github.com/federicocalo/climate-pulse/settings/pages
2. Under "Build and deployment" > "Source", select **"GitHub Actions"**
3. Click Save
4. Push changes to `main` and observe `Deploy Documentation` workflow on the Actions tab
5. Verify footer text at https://federicocalo.github.io/climate-pulse (must read literally: `Climate Pulse · MIT License · federicocalo.dev` with clickable link)
6. Verify gitleaks CI gate blocks a PR with `API_KEY = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"`

## Next Phase Readiness

- uv workspace skeleton is ready for all subsequent plans in Phase 1 (Plans 02-05)
- CI gates are in place: ruff, pyright, pytest 80%/70% coverage, gitleaks
- Pre-commit hooks installed and tested locally (`pre-commit run --all-files` passes)
- fakeredis>=2.23 is in dev deps — Plan 03 (PoliteHttpClient) and Plan 05 (heartbeat) can use it immediately
- cfgrib/libeccodes is isolated to apps/worker per D-22 — no API container contamination risk

## Known Stubs

None — this plan creates configuration, documentation, and package scaffolding only. No data-flow stubs.

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model:
- T-01-01: .env.example verified to contain only placeholder values (grep clean)
- T-01-02: docs.yml uses `environment: github-pages` protection
- T-01-03: quickstart.md verified to contain no Phase 2+ API endpoints (grep clean)

## Self-Check

### Files exist:

- [x] `pyproject.toml`
- [x] `uv.lock`
- [x] `apps/api/pyproject.toml`
- [x] `apps/worker/pyproject.toml`
- [x] `packages/core/pyproject.toml`
- [x] `packages/migrations/pyproject.toml`
- [x] `apps/api/climatepulse_api/__init__.py`
- [x] `apps/worker/climatepulse_worker/__init__.py`
- [x] `packages/core/climatepulse_core/__init__.py`
- [x] `packages/migrations/climatepulse_migrations/__init__.py`
- [x] `.gitignore`
- [x] `.env.example`
- [x] `README.md`
- [x] `mkdocs.yml`
- [x] `docs/index.md`
- [x] `docs/quickstart.md`
- [x] `docs/scraping-policy.md`
- [x] `.pre-commit-config.yaml`
- [x] `.github/workflows/ci.yml`
- [x] `.github/workflows/docs.yml`

### Commits exist:

- [x] `f018222` — Task 1: scaffold workspace
- [x] `0928865` — Task 2: MkDocs config + docs pages
- [x] `a9fc374` — Task 3: CI + docs workflow

## Self-Check: PASSED

---
*Phase: 01-foundation-slice-public-docs*
*Completed: 2026-05-23*
