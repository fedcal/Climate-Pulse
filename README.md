# Climate Pulse

[![CI](https://github.com/federicocalo/climate-pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/federicocalo/climate-pulse/actions/workflows/ci.yml)
[![Docs](https://github.com/federicocalo/climate-pulse/actions/workflows/docs.yml/badge.svg)](https://federicocalo.github.io/climate-pulse)
[![Coverage](https://img.shields.io/badge/coverage-80%25-brightgreen)](https://github.com/federicocalo/climate-pulse)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Climate Pulse is an open-source pipeline that aggregates meteorological data from European public
sources (Italian regional ARPA stations, ECMWF Open Data, NOAA METAR/TAF, Copernicus C3S) into
a single time-series store queryable via a public REST/WebSocket API and visualised through an
Angular dashboard with an interactive map. It is designed for researchers, data journalists,
open-data communities, and SMEs (agriculture, renewable energy) who need structured access to
historical weather data without paying commercial API fees.

**Documentation:** [https://federicocalo.github.io/climate-pulse](https://federicocalo.github.io/climate-pulse)

## Quickstart

See the [Quickstart Guide](https://federicocalo.github.io/climate-pulse/quickstart/) for full
instructions including `docker compose up`, backfill CLI, and data verification via psql.

```bash
git clone https://github.com/federicocalo/climate-pulse
cd climate-pulse
cp .env.example .env
docker compose up -d
```

## Architecture

- **Ingestion layer:** Celery workers poll ARPA Emilia-Romagna (15 min cadence) and ECMWF Open
  Data (4 cycles/day) via a polite HTTP client with rate limiting, ETag caching, and snapshot
  fallback.
- **Storage:** TimescaleDB on PostgreSQL 16 with TWO hypertables — `observations` (station-based)
  and `gridded_observations` (ECMWF grid-based) — each with continuous aggregates, compression
  after 7 days, and configurable retention.
- **API (Phase 1):** Minimal FastAPI exposing only `/healthz` (liveness) and `/readyz`
  (checks DB + Redis + Celery worker heartbeat).
- **Docs:** MkDocs Material deployed to GitHub Pages on every push to `main`.

## WARNING: Do NOT scale the `beat` service

The Celery Beat scheduler **must run as exactly ONE instance at all times**. Scaling the `beat`
service to more than one replica will cause every scheduled task to fire multiple times per
interval — resulting in doubled ARPA requests (politeness violation), duplicate rows in both
hypertables, and a flooded Dead Letter Queue.

The `compose.yaml` enforces `deploy.replicas: 1` on the `beat` service. Do not override this
with `docker compose up --scale beat=2` or equivalent.

If you need more ingest throughput, scale the `worker` service instead:
```bash
docker compose up --scale worker=4  # safe: workers are stateless
# NEVER: docker compose up --scale beat=2
```

## License

MIT License — see [LICENSE](LICENSE) for details.

Copyright 2026 Federico Calo — [federicocalo.dev](https://federicocalo.dev)
