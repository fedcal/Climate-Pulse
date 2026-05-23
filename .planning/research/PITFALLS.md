# Pitfalls Research

**Domain:** Multi-source weather/time-series aggregation pipeline (ARPA scraping + ECMWF + NOAA METAR + Copernicus → TimescaleDB → FastAPI + Angular SSR, Docker Compose, solo dev)
**Researched:** 2026-05-23
**Confidence:** HIGH (TimescaleDB ops, Celery, scraping politeness — verified via official docs and post-mortems); MEDIUM (Angular SSR + Leaflet/Plotly hydration specifics, ARPA-specific behaviors)

---

## Critical Pitfalls

### Pitfall 1: Wrong `chunk_time_interval` on hypertable (irreversible at scale)

**What goes wrong:**
TimescaleDB hypertable is created with a chunk interval that is too large (e.g. 1 month / 1 year) or too small (1 minute) relative to ingestion rate. Once data is ingested, you cannot shrink an existing chunk — you must create a new hypertable and migrate.

**Why it happens:**
Default examples in tutorials use `INTERVAL '1 day'` regardless of workload. With Climate Pulse cardinality (stations × variables × sources every 15min), a wrong choice silently destroys query performance and compression efficiency.

**How to avoid:**
- Estimate ingestion rate per chunk BEFORE `create_hypertable`. Target: indexes for currently-ingested chunks fit in ~25% of RAM. For Climate Pulse expected scale (hundreds of ARPA stations × ~10 variables × 15min → ~10M rows/day max), use `chunk_time_interval => INTERVAL '7 days'` initially, validated empirically.
- Run `chunks_detailed_size('hypertable_name')` after a week to verify chunk sizes (target: 25%–100% of `shared_buffers`).
- Document the value in a migration so it's not lost.

**Warning signs:**
- Query plans show "Scanning N chunks" with N > 100 for typical 7-day queries → chunks too small
- Single-chunk size > 50% of `shared_buffers` → chunks too large
- Compression ratio < 5× on old chunks → likely chunks too small (overhead dominates)

**Phase to address:** Storage phase (hypertable design). Severity: **CRITICAL**

---

### Pitfall 2: Hypertable primary key omits the time column

**What goes wrong:**
Defining `PRIMARY KEY (station_id, variable)` on a hypertable fails or breaks partitioning, because TimescaleDB requires the time partition column to be part of every UNIQUE/PRIMARY KEY constraint. Developers then drop the PK entirely, losing dedup guarantees on ingestion.

**Why it happens:**
Coming from OLTP Postgres habits — "natural key" thinking. TimescaleDB error message is cryptic.

**How to avoid:**
- Always include `time` in PK: `PRIMARY KEY (station_id, variable, source, time)`.
- Use `INSERT … ON CONFLICT (station_id, variable, source, time) DO UPDATE` for idempotent ingestion (Celery may re-run a task — see Pitfall 5).
- For deduplication across overlapping sources for the same station, add a `source` discriminator column and let consumers pick the preferred source per `(station, variable, time)` via a view or continuous aggregate.

**Warning signs:** Duplicate rows in raw table for the same `(station, variable, time)` after a Celery retry storm.

**Phase to address:** Storage phase (schema design). Severity: **CRITICAL**

---

### Pitfall 3: Continuous aggregate / compression / retention policies in wrong order

**What goes wrong:**
Compression policy fires before continuous aggregate refresh, so the aggregate refresh tries to UPDATE a compressed chunk and fails (or silently skips). Retention drops a chunk before the aggregate has materialized it, losing data permanently.

**Why it happens:**
Each policy is configured independently in tutorials; their temporal interaction isn't obvious.

**How to avoid:**
- **Ordering rule:** `refresh_lag < compression_after < retention_after`.
- Recommended starting values for Climate Pulse: refresh CAGGs with 1h lag, compress after 7 days, retain raw 90 days (configurable per source).
- Continuous aggregates have their own retention — compressed CAGGs can replace raw data for long-horizon queries.
- Monitor `timescaledb_information.job_errors` and alert on consecutive failures (e.g. 3 in a row).

**Warning signs:** `job_errors` table fills up; CAGG queries return NULL for recent buckets; disk usage growing despite retention policy.

**Phase to address:** Storage phase + Ops phase. Severity: **CRITICAL**

---

### Pitfall 4: Scraping ARPA endpoints without politeness controls

**What goes wrong:**
Scraper hammers ARPA regional endpoint (no `User-Agent`, no rate limit, no backoff) → IP banned, contact from agency, or project shut down. ARPA endpoints are public but rate-limited at the network edge by some regions.

**Why it happens:**
`requests.get(url)` is the obvious first draft. Default Python `requests` UA is `python-requests/X.Y.Z` which many ops teams alert on as bot traffic.

**How to avoid:**
- **Identifying User-Agent**: `ClimatePulse/0.x (+https://github.com/<owner>/climate-pulse; contact: <email>)`. Configurable via env var so self-hosters set their own.
- Parse and respect `robots.txt` per-host via `urllib.robotparser` or `reppy`; cache the parsed result per host for 24h.
- Enforce **per-host rate limit** (start at 1 req / 2s, configurable per adapter). Use `aiolimiter` or `pyrate-limiter` with Redis backend so all Celery workers share the budget.
- HTTP cache with `Cache-Control` / `ETag` / `If-Modified-Since` via `requests-cache` or `httpx` + `hishel` — avoids re-downloading unchanged pages.
- **Exponential backoff with jitter** on 429/5xx via `tenacity` (`wait_random_exponential(min=2, max=60)`, `stop_after_attempt(5)`).
- **Snapshot fallback**: if source returns 5xx/timeout, serve last successful snapshot from object storage (or filesystem volume) and flag observations with `quality_flag = 'stale_snapshot'`.
- Compliance documented in `docs/scraping-policy.md` so regional ARPA admins (or curious users) can audit.

**Warning signs:** HTTP 429 in logs; sudden drop to 0 rows for a region; bounced contact email from agency.

**Phase to address:** Ingestion phase (foundation). Severity: **CRITICAL** (legal/community risk)

---

### Pitfall 5: Celery task not idempotent → duplicates on retry / visibility-timeout

**What goes wrong:**
A Celery task scrapes ARPA and writes 5000 rows, then crashes before ack. Redis visibility timeout (default 1h) expires → another worker picks it up → 10000 rows in DB (5000 duplicates). With unique constraints missing (see Pitfall 2), data is corrupted.

**Why it happens:**
Celery + Redis broker semantics are "at-least-once" by design; tutorials don't emphasize this. With `acks_late=True` (recommended for reliability), duplicates are even more likely if task runtime > visibility_timeout.

**How to avoid:**
- **Idempotent ingest by construction**: use `ON CONFLICT (station_id, variable, source, time) DO UPDATE SET value = EXCLUDED.value, quality_flag = EXCLUDED.quality_flag, ingested_at = NOW()`.
- Set `visibility_timeout` > max expected task runtime × 2 (e.g. `transport_options={'visibility_timeout': 7200}` for 1h-max tasks).
- `acks_late = True` + `task_reject_on_worker_lost = True` for all ingestion tasks.
- Retry with exponential backoff + max retries: `@task(autoretry_for=(RequestException,), retry_backoff=True, retry_kwargs={'max_retries': 5})`.
- Use task `task_id` derived from `(source, region, time_bucket)` to dedupe at queue level via `result_backend` check.

**Warning signs:** Same `ingested_at` minute showing 2× expected row count; Celery logs show "task X received" twice with different worker IDs.

**Phase to address:** Ingestion phase. Severity: **CRITICAL**

---

### Pitfall 6: Celery Beat running on multiple worker containers → duplicate schedules

**What goes wrong:**
`docker-compose scale worker=3` and each worker container runs `celery worker --beat` → each Beat instance independently fires the cron, so `ingest_arpa_lombardia` runs 3× every 15min. Floods sources, fills DLQ, hits Pitfall 4.

**Why it happens:**
`--beat` is convenient flag in single-node setups; the warning that Beat must be a singleton is buried in docs.

**How to avoid:**
- Beat runs in a **dedicated, separate `beat` service** in `docker-compose.yml`, never colocated with workers. Workers run `celery worker` only.
- Document explicitly in `README.md`: "Do NOT scale the `beat` service > 1".
- For belt-and-suspenders, use `celery-redbeat` (Redis-backed scheduler with built-in lock) — survives container restarts and prevents schedule drift.
- For long-running ingest jobs, wrap task body in a Redis distributed lock with timeout (`redlock` or `redis.lock`) keyed by `(task_name, time_bucket)` so even concurrent triggers serialize.

**Warning signs:** Same scheduled task appears N times in `flower` per period; DB shows 3× expected rows for same `(source, time)`.

**Phase to address:** Ingestion phase / Deploy phase. Severity: **HIGH**

---

### Pitfall 7: Timezone handling — DST and naive timestamps from ARPA feeds

**What goes wrong:**
ARPA Lombardia returns timestamps in `Europe/Rome` (CET/CEST) as naive ISO strings. On DST transition night, two rows have the same local timestamp (e.g. 02:30 in October appears twice). Stored as-is, query results are wrong for ~1 week / year.

**Why it happens:**
`datetime.fromisoformat()` returns naive datetime; nobody catches it. `Europe/Rome` is rarely tested.

**How to avoid:**
- **Storage rule**: ALL timestamps in DB are `TIMESTAMPTZ` and stored in UTC. Period.
- At adapter boundary, attach IANA timezone explicitly (`zoneinfo.ZoneInfo("Europe/Rome")`), then `.astimezone(UTC)`. Never store naive.
- For DST-ambiguous times, use `fold=0/1` discriminator or skip the ambiguous hour and flag with `quality_flag = 'dst_ambiguous'`.
- Document per-source timezone assumptions in adapter config: `ARPA_LOMBARDIA_TZ = "Europe/Rome"`, `METAR_TZ = "UTC"`, `ECMWF_TZ = "UTC"`.
- API output in UTC by default; client may pass `?tz=Europe/Rome` for display conversion.
- **Test**: include a parametrized test for DST spring-forward (March) and fall-back (October) hours.

**Warning signs:** Continuous aggregate buckets show 2× value for 02:00 local in October; missing data for 02:00 local in March.

**Phase to address:** Ingestion phase (adapter contract). Severity: **CRITICAL**

---

### Pitfall 8: Unit conversion silently wrong across sources

**What goes wrong:**
ARPA returns temperature in °C, METAR in °C but pressure in hPa or inHg depending on station, ECMWF GRIB returns K (Kelvin) and m/s, NOAA METAR wind in knots. A single missed conversion → "Milano had 287°C on Tuesday" headline.

**Why it happens:**
Source-specific docs assume their unit; cross-source aggregation forgets to normalize.

**How to avoid:**
- Define **canonical WMO/SI units** at the storage layer: temperature in K (or °C — pick one and enforce), wind in m/s, pressure in Pa, precipitation in kg/m² (= mm), radiation in W/m².
- Conversion happens **inside the adapter**, never in the API layer. Adapter contract: `Observation(variable: WMOVariable, value: float, unit: SIUnit)`.
- Use `pint` library for typed unit conversion — never multiply by magic numbers in code.
- Range validation per variable at ingest: temperature −90°C to +60°C, wind 0–120 m/s, pressure 870–1085 hPa. Outliers flagged `quality_flag = 'range_violation'`, not silently dropped.
- Property-based tests (`hypothesis`) for adapter round-trips: `parse(serialize(obs)) == obs`.

**Warning signs:** Plotly dashboard shows temperature spike to 287; min/max metrics show pressure of 0.00010 (someone normalized to bar instead of Pa).

**Phase to address:** Ingestion phase. Severity: **CRITICAL**

---

### Pitfall 9: ECMWF/Copernicus CDS request exceeds quota → entire pipeline blocks

**What goes wrong:**
CDS API enforces per-user concurrent request limits and queue priorities. Naive code does `client.retrieve(...)` synchronously inside a Celery task, blocking a worker for 30min while the request queues, then 30min more to download a 2GB GRIB. Worker pool exhausted, ARPA ingest stalls.

**Why it happens:**
The `cdsapi` client looks synchronous; queue semantics aren't visible until your account hits the cap.

**How to avoid:**
- Use `ecmwf-opendata` for open-data dissemination (no auth, faster, smaller subset) — preferred for routine ingestion.
- For CDS (Copernicus C3S deep history): submit request, capture request ID, return immediately. Separate poll-task checks status every 5min; downloader task fires only when ready.
- Split large GRIB requests by variable / date range (CDS recommends < 4 GiB per file due to netCDF3 limits).
- Stream GRIB to disk, never load fully in memory. Parse with `cfgrib` + `xarray.open_dataset(..., engine='cfgrib', backend_kwargs={'indexpath': ''})` (avoid `.idx` pollution).
- Dedicated low-concurrency Celery queue for CDS tasks (`-Q ecmwf -c 1`) so they don't starve fast scrapers.
- Cache GRIB files locally with content hash — re-runs don't re-download.

**Warning signs:** Celery `flower` shows worker stuck for >30min in `cdsapi`; CDS dashboard shows "queue full" errors.

**Phase to address:** Ingestion phase. Severity: **HIGH**

---

### Pitfall 10: METAR parser breaks on real-world variants (CAVOK, VRB, RVR, NIL, AUTO)

**What goes wrong:**
Custom regex parser handles 90% of METARs from `KJFK 121651Z 27015KT...` examples but fails on:
- `VRB03KT` (variable wind direction at low speed)
- `CAVOK` (replaces visibility, cloud, weather → keys missing in result)
- `R24L/0800N` (RVR with trend indicator)
- `NIL` (no observation available)
- `AUTO` flag (automated, may lack human-only fields)
- `////` placeholders for unmeasured fields
- AMD/COR/RTD amendment indicators

Result: silent KeyErrors caught by overly-broad `except`, observations dropped without log.

**Why it happens:**
METAR is a printable but irregular format; the WMO spec has many optional groups and national variants.

**How to avoid:**
- **Do not write a custom METAR parser**. Use `python-metar` (mature, handles VRB, CAVOK, RVR, AUTO).
- For TAF, use `python-metar` (supports TAF) or `aeroapi`/`avwx-engine`.
- Wrap in adapter that converts parser output → canonical `Observation` objects with explicit `is_cavok`, `is_auto`, `amendment_type` flags preserved as metadata.
- Test corpus: include 100+ real METARs from NOAA archive covering edge cases (VRB, CAVOK, RVR, NIL, BECMG, TEMPO, AMD).
- On parse failure, **store raw METAR string + error** in a `parse_errors` table; never silently drop.

**Warning signs:** `quality_flag = 'parse_error'` count growing; specific airports (often non-US ICAO) show 0 observations.

**Phase to address:** Ingestion phase. Severity: **HIGH**

---

### Pitfall 11: Public API has no rate limiting → abused into DoS

**What goes wrong:**
Open API endpoints (no auth — per project decision) are scraped by a single client at 1000 req/s downloading every station's history. Postgres connection pool exhausted, all users get 500.

**Why it happens:**
"It's behind a CDN" / "no one knows about us yet" / "we'll add it later".

**How to avoid:**
- **Day 1**: `slowapi` with Redis backend (shared across API replicas). Per-IP defaults: 60 req/min for `/stations`, 30 req/min for `/observations`, 10 req/min for `/export`. Configurable per env.
- For long exports (CSV/Parquet), require **async job pattern**: POST creates job, GET polls; rate limit on job creation, not on result poll.
- Always paginate: max `limit=1000`, default `limit=100`, cursor-based for time-series (`?after=<timestamp>`) not offset (offset breaks at scale).
- Set `statement_timeout` per role in Postgres (e.g. 30s for `api_user`) so a runaway query can't camp on a connection.
- **Optional API key** (project decision) for higher limits — soft trust, not auth.
- Reverse proxy (Caddy/Traefik in Compose) provides a second rate-limit layer + connection limits per IP.

**Warning signs:** Postgres `pg_stat_activity` shows many long-running SELECTs from same IP; FastAPI 429 spike.

**Phase to address:** API phase. Severity: **CRITICAL**

---

### Pitfall 12: API queries hit raw hypertable instead of continuous aggregates → slow + DB hammer

**What goes wrong:**
Dashboard requests "last 5 years daily mean temperature for Milano" → API runs `SELECT time_bucket('1 day', time), avg(value) FROM observations WHERE ... GROUP BY 1`. Scans ~50M rows. 10 dashboard users = DB on fire.

**Why it happens:**
Easy to forget CAGGs exist; query writers default to the raw table.

**How to avoid:**
- Create CAGGs for canonical buckets: `1h`, `1d`, `1mo` per `(station_id, variable)`. Refresh policy: 1h lag.
- API layer **routes by requested resolution**: bucket >= 1d → CAGG `obs_daily`; 1h–1d → CAGG `obs_hourly`; <1h → raw `observations`.
- Add Redis response cache for popular queries (TTL 5min for "today", 1h for historical). Use `fastapi-cache` with a per-key lock (`single-flight`) to prevent thundering herd on cache miss.
- `EXPLAIN ANALYZE` representative queries in CI; fail if any plan touches > 10 chunks for a non-export endpoint.

**Warning signs:** P95 API latency > 2s; Postgres CPU sustained > 70%; `pg_stat_statements` top query is on raw hypertable.

**Phase to address:** Storage phase (CAGG design) + API phase (routing). Severity: **HIGH**

---

### Pitfall 13: Angular SSR hydration breaks on Leaflet / Plotly mount

**What goes wrong:**
Leaflet calls `window.L` and creates DOM nodes on mount. Plotly does direct DOM manipulation. Server-rendered HTML has empty `<div>`; client renders chart inside it → hydration mismatch → Angular warns + entire component re-renders (FOUC, lost interactivity).

**Why it happens:**
Both libraries are imperative DOM-touchers, antithetical to SSR's "render once on server, hydrate on client" assumption.

**How to avoid:**
- Wrap map/chart components with `ngSkipHydration` — explicit opt-out, documented in code comments.
- Or: use `afterNextRender` lifecycle hook (Angular 16+) so Leaflet/Plotly init only runs in browser; render a server-friendly placeholder server-side (skeleton or static SVG preview).
- Lazy-load Leaflet/Plotly bundles with dynamic `import()` inside `afterNextRender` — keeps SSR bundle small.
- Guard every `window`/`document`/`navigator` access with `isPlatformBrowser(this.platformId)` injection.
- SSR build test in CI: render every route headless, assert no `NG0500/NG0501` hydration errors in console.

**Warning signs:** Browser console: `NG0500: Hydration node mismatch`; map flickers on load; SEO crawl shows empty map div (acceptable if intentional).

**Phase to address:** Dashboard phase. Severity: **HIGH**

---

### Pitfall 14: Docker Compose `depends_on` without `condition: service_healthy`

**What goes wrong:**
`api` container starts as soon as `timescaledb` container is "running" (process started, not ready). API's first DB connection fails, container crashes, Compose marks it failed. With restart policy, eventually starts; without, stack is broken on first `up`.

**Why it happens:**
Plain `depends_on: [timescaledb]` only waits for container creation, not readiness. Tutorials show this as "the simple way".

**How to avoid:**
- Healthcheck on every stateful service:
  - TimescaleDB: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`
  - Redis: `redis-cli ping | grep PONG`
- Dependents use `depends_on: { timescaledb: { condition: service_healthy } }`.
- API/worker entrypoint runs migrations idempotently (Alembic `upgrade head`) — handles fresh DB and existing DB.
- TimescaleDB volume permissions: bind-mount with `user: "1000:1000"` matching image's `postgres` UID, or use named volume (Docker handles perms). Document the pitfall in README — bind-mounts on host with different UID are a common day-1 trap.
- `init` container (Alpine + chown) for bind-mount setups.

**Warning signs:** `docker compose up` first run shows API in restart loop for ~30s; `permission denied` in TimescaleDB logs.

**Phase to address:** Deploy phase. Severity: **HIGH**

---

### Pitfall 15: Secrets committed to repo / hardcoded in compose file

**What goes wrong:**
`POSTGRES_PASSWORD: changeme` hardcoded in `docker-compose.yml`, CDS API key in `cdsapi.config` checked into git. Open-source repo → secrets immediately scraped.

**Why it happens:**
"It's only for local dev" → ships to default deploy → never rotated.

**How to avoid:**
- `docker-compose.yml` reads all secrets from `.env` (gitignored). Provide `.env.example` with placeholders + comments.
- `git-secrets` or `gitleaks` pre-commit hook to block accidental commits.
- CDS API key per-user (each self-hoster registers their own); document in setup guide. Never ship a shared key.
- Postgres password: generate on first `docker compose up` via `init` script if `.env` missing — fail loudly rather than default to `postgres`.
- For Docker Compose v2.5+, prefer `secrets:` block (file-backed) over env vars where the consuming app supports it.

**Warning signs:** `gitleaks detect` shows any non-test match; `.env` in `git ls-files` output.

**Phase to address:** Deploy phase. Severity: **CRITICAL**

---

## Moderate Pitfalls

### Pitfall 16: No CI gate on a solo-dev project → silent regressions

**What goes wrong:** Solo dev pushes "small fix", breaks ingestion for ARPA Veneto, notices 3 weeks later in dashboard.

**How to avoid:** GitHub Actions running pytest + ruff + mypy on PR. Smoke test against test Compose stack. Aim for 70% coverage on adapters (highest-risk surface).

**Phase to address:** Foundation phase (do this in week 1, not "later"). Severity: **MEDIUM**

---

### Pitfall 17: Over-engineering early — premature K8s/Kafka/microservices

**What goes wrong:** Solo dev spends 2 months on Kafka + microservices "for scalability" before having a single working adapter. Project dies.

**How to avoid:** Stick to declared stack (Compose + Celery, no Kafka, no K8s — already in Out of Scope). Resist refactoring temptation until v1.0 ships.

**Phase to address:** All phases (discipline). Severity: **MEDIUM**

---

### Pitfall 18: Plotly bundle bloats Angular dashboard (1MB+ JS)

**What goes wrong:** `plotly.js-dist` is ~3MB minified. Lighthouse score tanks, mobile users wait 10s.

**How to avoid:** Use `plotly.js-basic-dist` or `plotly.js-cartesian-dist` (subset bundles for line/bar charts only). Lazy-load via dynamic import on chart-containing routes.

**Phase to address:** Dashboard phase. Severity: **MEDIUM**

---

### Pitfall 19: GDPR-relevant API access logs

**What goes wrong:** Despite "no PII" claim, API logs `client_ip + query + timestamp` indefinitely → IP is personal data under GDPR. Retention policy missing.

**How to avoke:** Document retention (e.g. logs 30 days), truncate IP to /24 (IPv4) or /48 (IPv6) before persisting, mention in privacy notice. Don't log query parameters that could correlate to specific researcher work (use sampling).

**Phase to address:** API phase + Ops phase. Severity: **MEDIUM**

---

### Pitfall 20: ARPA selector / endpoint changes silently → adapter returns empty

**What goes wrong:** ARPA Lombardia changes HTML structure or JSON schema → BeautifulSoup selector returns `None` → adapter writes 0 rows daily, no error.

**How to avoid:** Schema validation with `pydantic` at adapter output. Per-adapter health metric `last_successful_ingest_at`; alert if > 2× expected frequency without success. "Canary observation" assertion: e.g. ARPA Milano station X must have at least 1 obs/day; if not, page.

**Phase to address:** Ingestion phase + Ops phase. Severity: **HIGH**

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip `ON CONFLICT` on first ingestion task | Faster to ship one adapter | Duplicates on every retry; can't easily clean up later | Never |
| Default `chunk_time_interval` (1 day) | "Just works" demo | Compression ratio cratered, query plans slow at 6 months | OK for first 2 weeks of dev with `<1M` test rows |
| Single beat colocated with worker | One fewer container | Duplicate scheduling at any scaling event | Never in v1.0 |
| Custom regex METAR parser | Avoid extra dep | Spec coverage holes, silent data loss | Never |
| Synchronous CDS download in API request | Simpler code | API blocks 30min, requests time out | Never (always background) |
| `ngSkipHydration` on entire dashboard | Hydration "fixed" overnight | Lose SSR benefit (SEO, FCP) | Only on map/chart components, never on full route |
| No rate limit "for v0.1" | Ship faster | First abusive user takes down the API | Only with private/IP-allowlisted preview |
| Compose `depends_on` without healthcheck | One line shorter | Flaky cold-start, support burden | Single-container dev only |
| Log full client IP indefinitely | Easier debugging | GDPR violation, privacy complaint | Never in prod (truncate or hash) |
| Skip CAGGs, query raw hypertable | One less object to maintain | DB melts at 5+ concurrent dashboard users | Only for variables with <1M rows total |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| ARPA regional endpoints | Assume uniform schema across regions | One adapter per region; share only base contract (`BaseAdapter` ABC) |
| ECMWF Open Data | Fetch full global grid | Use bbox subset for EU only; specify `param`, `levtype`, `step` precisely |
| Copernicus CDS | Synchronous `.retrieve()` in worker | Async submit + poll + download in separate tasks; dedicated low-conc queue |
| NOAA METAR (TGFTP/aviationweather.gov) | Hard-code one URL | Both endpoints have intermittent outages — implement multi-source failover |
| TimescaleDB (compressed chunks) | Try to UPDATE/DELETE compressed chunk | Decompress chunk first, or design ingestion to be append-only past compression threshold |
| Redis (Celery broker) | Share Redis DB with Celery + cache + rate-limit | Use separate Redis logical DBs (broker = DB 0, cache = DB 1, rate-limit = DB 2) |
| Leaflet tile providers | Use OSM tiles in production without attribution / heavy traffic | Add proper attribution; consider self-hosting tiles or commercial provider if traffic high; cache tile responses |
| Angular SSR fetch | Use `fetch`/`HttpClient` with absolute external URL → SSR pre-renders, leaks IP of server | Use `TransferState` to pass data server→client; cache server-side responses |
| Docker Compose volumes (TimescaleDB) | Bind mount with wrong host UID | Named volume OR explicit `user: 1000:1000` + init chown container |
| Plotly + SSR | Render server-side as image (`kaleido`) | Don't — render placeholder server-side; hydrate to interactive client-side |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Query raw hypertable for multi-year aggregates | API P95 > 5s | Continuous aggregates + API routing by resolution | ~6 months ingestion data |
| Missing index on `(station_id, time DESC)` | Latest-value queries slow | Composite index; TimescaleDB auto-creates time index but station_id needs explicit | First "show latest" endpoint |
| Compression never enabled | Disk fills, queries on old data slow | `add_compression_policy('observations', INTERVAL '7 days')` | ~3 months ingestion |
| N+1 in `/stations/{id}/observations` | Each station fetched in loop | Eager-load with `selectinload` (SQLAlchemy) or single JOIN query | First multi-station dashboard render |
| Plotly client-side render of 50k points | Browser freezes 5s | Server-side downsample with `time_bucket` to ≤500 points before serialization | First multi-year chart view |
| Redis as Celery broker memory bloat (result backend) | Redis RSS climbs unbounded | `result_expires=3600`; separate result backend (Postgres) for long-retention results; periodic `flushdb` of broker if appropriate | Few thousand tasks queued/completed |
| FastAPI sync route hitting DB | Workers blocked, low throughput | Use `async def` + `asyncpg`/`SQLAlchemy 2.0 async` consistently | First concurrent user spike |
| No HTTP caching headers | Dashboard re-fetches every nav | `Cache-Control: max-age=N` + `ETag` on read endpoints | First repeat-visit user |
| GRIB file loaded fully into memory | OOM on worker | Stream + `cfgrib` lazy load; subset before materializing | First ECMWF full-grid request |
| Pagination by `OFFSET` for time-series | Slow at deep pages | Cursor pagination keyed on `time` | First export > 10k rows |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| SQL injection via raw query interpolation in adapters | DB compromise | SQLAlchemy parameterized queries everywhere; never `text(f"... {user_input}")` |
| Open Redis port in Compose default network | Anyone with host access can wipe broker/cache | Don't `ports:` Redis to host; only expose API + dashboard |
| Default Postgres password unchanged | DB compromise | Fail loudly on missing `.env`; generate strong random in init script |
| Expose internal numeric station IDs in URLs | Enumeration mapping internal data model | Use stable external slugs (`milano-citta-studi`) over `/stations/4271` |
| Server-side request forgery via user-supplied URL in webhook alerts | Internal network probing | Allow-list scheme `http/https`; deny private IP ranges (RFC1918, link-local, 127/8); use `httpx` with `transport` that blocks redirects to private IPs |
| Verbose error messages leak stack traces | Information disclosure | FastAPI: in prod, custom exception handler returns generic message; full trace to logs only |
| Webhook secret signing absent | Webhook spoofing | HMAC-SHA256 signing of webhook payloads with per-recipient secret |
| Logging API keys in request logs | Key compromise via log access | Middleware redacts `Authorization`, `X-API-Key` headers before logging |
| robots.txt non-compliance | Project reputation damage; legal exposure (EU AI/data protection) | Programmatic robots.txt check before every request; document in scraping policy |
| Plotly/Leaflet from CDN without SRI | Supply-chain attack | Self-host or use Subresource Integrity hashes |
| OpenAPI spec exposes internal endpoints | Attack surface mapping | Tag internal endpoints `include_in_schema=False` |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Dashboard shows "loading..." indefinitely on slow query | User abandons | Skeleton + 5s timeout + "still loading, try narrower range" UX |
| Map shows 5000 station markers, browser dies | Crash | Cluster markers (`Leaflet.markercluster`); load only viewport bounds |
| Charts show no units / source attribution | Researcher can't cite, journalist misreports | Every chart: variable name, unit, source, quality flag breakdown |
| Mixing observations from different sources in same line | Implies continuity that doesn't exist | Per-source series with distinct color + legend; option to "show preferred source only" |
| No way to see data freshness / staleness | User shares stale chart | Per-station "last updated X minutes ago" badge; warn if > expected cadence |
| Time axis in user's local time without indicator | Misreads UTC chart as local | Always show "UTC" or "Europe/Rome" on axis; let user toggle |
| Export gives only JSON | Researchers want CSV; data scientists want Parquet | Offer all three; document column schema |
| No deep-linkable URLs for chart state | User can't share specific view | Sync chart state (station, vars, time range) to URL query params |
| Public API docs hidden / not generated | Researchers can't self-serve | OpenAPI 3.1 auto-published; ReDoc/Swagger UI deployed at `/docs` |
| No "how to cite this data" guidance | Researchers don't cite project / source | Footer + API response `_meta` with citation snippet + DOI (when available) |

---

## "Looks Done But Isn't" Checklist

- [ ] **Adapter:** runs once successfully → verify: idempotency on re-run (no duplicates), handles 5xx/timeout, parses real production payload (not just example fixture), timezone correct
- [ ] **TimescaleDB schema:** hypertable created → verify: PK includes time, compression policy enabled, CAGGs defined with valid refresh+compression+retention ordering, indexes present for hot queries
- [ ] **Celery task:** "works locally" → verify: `acks_late=True`, idempotent, visibility_timeout > runtime×2, registered in beat schedule, DLQ destination configured, max_retries set, dedicated queue if long-running
- [ ] **API endpoint:** returns data → verify: rate-limited, paginated with cursor, uses CAGG for aggregates, response < 1s P95, OpenAPI schema correct, error responses follow envelope
- [ ] **Dashboard component:** renders → verify: works under SSR without hydration warnings, handles loading/error/empty states, units + source displayed, no `window` access without guard
- [ ] **Docker Compose stack:** `up -d` works → verify: healthchecks on all stateful services, `depends_on` uses `condition: service_healthy`, named volumes (no surprise UID), secrets via `.env`, restart policy set, logs rotated
- [ ] **Scraping adapter:** fetches data → verify: identifying User-Agent, respects robots.txt, rate limit per-host (shared across workers via Redis), HTTP cache, snapshot fallback, exponential backoff
- [ ] **METAR/GRIB parser:** decodes happy-path → verify: handles VRB/CAVOK/RVR/NIL/AUTO (METAR), streams not loads (GRIB), parse errors stored not dropped
- [ ] **Public API "open access":** works → verify: rate limit configured, optional API key path for higher limits, GDPR-compliant logging, OpenAPI spec published, terms of use linked
- [ ] **Deploy guide:** "follow README" → verify: works on a fresh VM with only Docker installed, secrets generation documented, default ports / firewall guidance, backup/restore procedure
- [ ] **Continuous aggregate:** created → verify: refresh policy fires (`job_stats`), no errors in `job_errors`, query plan uses CAGG (`EXPLAIN`), CAGG is refreshed before its data window is compressed/dropped
- [ ] **Tests pass:** CI green → verify: tests actually assert behavior (not just `assert True`), include DST edge case, include adapter against recorded fixture, coverage on ingestion/parsing > 80%

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong `chunk_time_interval` set early | MEDIUM (if < 100M rows) — HIGH (later) | Create new hypertable with correct interval; `INSERT INTO new SELECT FROM old`; swap names; drop old. Test on staging first. |
| Missing PK on hypertable → duplicates exist | MEDIUM | Backfill: `DELETE … WHERE ctid NOT IN (SELECT MIN(ctid) GROUP BY station, var, source, time)` per chunk; add PK; add `ON CONFLICT` to ingest |
| Scraping ban from ARPA | HIGH (reputation) | Stop ingestion immediately; reach out to ARPA contact, apologize, share politeness controls now in place; switch to longer rate limit + backup snapshots until trust rebuilt |
| Celery beat duplicates fired N times | LOW (if PK + ON CONFLICT) — HIGH (if not) | If idempotent: no action; clean DLQ. If not: re-derupe affected time window per Pitfall 2 recovery; deploy fix |
| Timezone bug discovered in production data | HIGH | Identify affected time ranges; backfill: re-fetch raw from source, reconvert with correct TZ, INSERT … ON CONFLICT (the bug becomes the fix) |
| GRIB OOM kills worker | LOW | Switch to streaming + bbox subset; restart worker with mem-limit |
| API DoS by single client | LOW (once rate limit added) | Add rate limit + reverse proxy IP ban; ban offending IP at firewall; communicate via API status page |
| SSR hydration error in prod | LOW | Add `ngSkipHydration` to broken component as hotfix; ticket proper afterRender refactor |
| Compose volume perms broken on user install | LOW | Document init container; provide `make reset-volume` recipe |
| Secret leaked to public repo | HIGH | Rotate immediately; assume compromised; force-push not enough (use BFG / git filter-repo); audit access logs since leak time |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| #1 chunk_time_interval | Storage (Phase 2) | `chunks_detailed_size` benchmark in test stack with synthetic load |
| #2 hypertable PK | Storage (Phase 2) | Schema migration includes time in PK; test inserts duplicate → ON CONFLICT triggers |
| #3 policy ordering | Storage (Phase 2) + Ops | `job_errors` empty after 7-day soak; CAGG query returns latest bucket |
| #4 scraping politeness | Ingestion (Phase 3) | robots.txt check unit test; rate limit integration test; UA assertion |
| #5 Celery idempotency | Ingestion (Phase 3) | Replay test: run task twice, assert row count unchanged |
| #6 beat singleton | Ingestion (Phase 3) / Deploy (Phase 6) | Compose review; integration test scales workers, asserts no dup |
| #7 timezone | Ingestion (Phase 3) | DST round-trip test (March + October); all DB timestamps `TIMESTAMPTZ` |
| #8 unit conversion | Ingestion (Phase 3) | Round-trip property test per adapter; range-validation test |
| #9 ECMWF/CDS quota | Ingestion (Phase 3) | Dedicated queue config; async pattern in code review |
| #10 METAR edge cases | Ingestion (Phase 3) | Corpus test of 100+ real METARs including VRB/CAVOK/RVR/NIL |
| #11 API rate limit | API (Phase 4) | Load test exceeds limit → 429 returned; per-IP key sharded |
| #12 API uses CAGGs | Storage (Phase 2) + API (Phase 4) | `EXPLAIN ANALYZE` in CI for aggregate endpoints |
| #13 SSR hydration | Dashboard (Phase 5) | CI runs headless SSR for each route, asserts no NG0500/NG0501 |
| #14 compose healthchecks | Deploy (Phase 6) | Fresh `docker compose up` succeeds on first try in CI |
| #15 secrets | Foundation (Phase 1) + Deploy (Phase 6) | `gitleaks` pre-commit; `.env.example` only template |
| #16 CI gate | Foundation (Phase 1) | GH Actions on every PR |
| #17 over-engineering | All phases | Discipline / PROJECT.md Out of Scope review |
| #18 Plotly bundle | Dashboard (Phase 5) | Lighthouse perf budget in CI; bundle analyzer |
| #19 GDPR logs | API (Phase 4) + Deploy (Phase 6) | Privacy notice; log retention config; IP truncation middleware |
| #20 silent adapter break | Ingestion (Phase 3) + Ops | `last_successful_ingest_at` metric; canary assertion; alert |

---

## Sources

- [TimescaleDB: Improve hypertable and query performance](https://docs.timescale.com/use-timescale/latest/hypertables/change-chunk-intervals/)
- [TigerData forum: choosing chunk_time_interval](https://forum.tigerdata.com/forum/t/choosing-the-right-chunk-time-interval-value-for-timescaledb-hypertables/116)
- [TigerData: testing your chunk size](https://www.tigerdata.com/blog/timescale-cloud-tips-testing-your-chunk-size)
- [Mindful Chase: Troubleshooting TimescaleDB at scale (chunks, compression, CAGGs, WAL)](https://mindfulchase.com/explore/troubleshooting-tips/databases/troubleshooting-timescaledb-at-scale-chunk-design,-compression,-continuous-aggregates,-and-wal-resilience.html)
- [TigerData: About continuous aggregates](https://www.tigerdata.com/docs/use-timescale/latest/continuous-aggregates/about-continuous-aggregates)
- [Celery 5.6 Tasks documentation](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery Periodic Tasks documentation](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
- [Optimizing Celery retries & visibility timeouts at scale (Bhagya Rana)](https://medium.com/@bhagyarana80/optimizing-celery-retries-and-visibility-timeouts-at-high-scale-aa79f923d880)
- [GitGuardian: Celery task resilience](https://blog.gitguardian.com/celery-tasks-retries-errors/)
- [Distributed scheduling gone wrong: the Celery Beat trap](https://medium.com/@sudarshaana/distributed-scheduling-gone-wrong-the-celery-beat-trap-and-how-we-escaped-85c7e53828f6)
- [django-celery-beat duplicate executions issue #558](https://github.com/celery/django-celery-beat/issues/558)
- [Web scraping ethics, legality, robots.txt (Medium)](https://medium.com/@ridhopujiono.work/web-scraping-2-ethics-legality-robots-txt-how-to-stay-out-of-trouble-39052f7dc63f)
- [Bright Data: robots.txt for web scraping guide](https://brightdata.com/blog/how-tos/robots-txt-for-web-scraping-guide)
- [CDSAPI setup (Copernicus)](https://cds.climate.copernicus.eu/how-to-api)
- [ECMWF Open Data Python package](https://pypi.org/project/ecmwf-opendata/)
- [python-metar source (handles VRB, CAVOK, RVR)](https://github.com/python-metar/python-metar)
- [Wikipedia: METAR specification](https://en.wikipedia.org/wiki/METAR)
- [Tinybird: best practices for timestamps and time zones in databases](https://www.tinybird.co/blog/database-timestamps-timezones)
- [Avoiding time zone pitfalls in time series analysis](https://www.linkedin.com/pulse/avoiding-time-zone-pitfalls-series-analysis-gadi-eichhorn-7m2pf)
- [SlowAPI FastAPI rate limiting tutorial](https://shiladityamajumder.medium.com/using-slowapi-in-fastapi-mastering-rate-limiting-like-a-pro-19044cb6062b)
- [FastAPI mistakes that kill performance](https://dev.to/igorbenav/fastapi-mistakes-that-kill-your-performance-2b8k)
- [Angular Hydration guide (angular.dev)](https://angular.dev/guide/hydration)
- [Angular SSR hydration constraints (Piyali Das)](https://medium.com/@piyalidas.it/angular-hydration-the-constraints-1e1d7ce7dded)
- [TimescaleDB Docker volume permissions issue #620](https://github.com/timescale/timescaledb-docker-ha/issues/620)
- [Docker Compose depends_on with health checks](https://oneuptime.com/blog/post/2026-01-16-docker-compose-depends-on-healthcheck/view)
- [HESS: open-source QC algorithms for weather station data](https://hess.copernicus.org/articles/28/4715/2024/)
- [ARPALData: R package for ARPA Lombardia (academic reference for ARPA data structure)](https://link.springer.com/article/10.1007/s10651-024-00599-6)

---
*Pitfalls research for: Climate Pulse weather aggregation pipeline*
*Researched: 2026-05-23*
