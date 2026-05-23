# Quickstart

This guide walks you through running Climate Pulse locally with Docker Compose, ingesting your
first 7 days of ARPA Emilia-Romagna data, and verifying that rows landed in TimescaleDB.

## Prerequisites

- **Docker Engine 25+** — [install Docker](https://docs.docker.com/engine/install/)
- **Docker Compose v2.30+** — included with Docker Desktop; on Linux install the `docker-compose-plugin`
- Linux or macOS (Windows with WSL2 is supported but not tested)

## Clone and Start

```bash
git clone https://github.com/federicocalo/climate-pulse
cd climate-pulse
cp .env.example .env
docker compose up -d
```

Docker Compose will pull the TimescaleDB, Redis, API, worker, and beat images and start all
services in the background.

## Verify Health

Wait approximately 60 seconds for TimescaleDB to initialise, then check service health:

```bash
# Liveness — should return {"status":"ok"} immediately
curl http://localhost:8000/healthz

# Readiness — returns 200 once DB + Redis + worker are up (may take up to 60s)
curl http://localhost:8000/readyz
```

`/readyz` returns `{"status":"ready"}` when all dependencies are up, or HTTP 503 with a JSON
error body if any dependency is not yet available.

## Run the Backfill

Once `/readyz` returns 200, ingest the past 7 days of ARPA Emilia-Romagna observations:

```bash
docker compose exec worker climatepulse backfill arpae \
  --from $(date -d '7 days ago' +%F) \
  --to $(date +%F)
```

- `arpae` is the source identifier for ARPA Emilia-Romagna.
- `--from` and `--to` accept ISO 8601 dates (`YYYY-MM-DD`).
- The backfill is **split by day** internally to respect ARPA's rate limits.

## Verify Rows

Confirm that observations landed in TimescaleDB:

```bash
docker compose exec timescale psql -U climatepulse -d climatepulse \
  -c "select count(*), source_id from observations group by source_id"
```

You should see a non-zero row count for `source_id = 'arpae'`. A typical 7-day backfill across
5–10 stations produces tens of thousands of rows.

## Idempotency Check

Re-run the exact same backfill command from the step above:

```bash
docker compose exec worker climatepulse backfill arpae \
  --from $(date -d '7 days ago' +%F) \
  --to $(date +%F)
```

Then re-run the psql count query. **The row count must not change.** Climate Pulse uses
`ON CONFLICT … DO UPDATE` semantics — re-ingesting the same observations is safe and produces
zero duplicate rows. This idempotency guarantee is load-bearing: the Beat scheduler may fire a
task twice in edge cases, and the backfill CLI is designed to be re-runnable without side effects.

## What's Next

- Read the [Scraping Policy](scraping-policy.md) to understand how Climate Pulse behaves toward
  ARPA data portals.
