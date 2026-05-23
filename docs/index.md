# Climate Pulse

Climate Pulse is an open-source pipeline that aggregates meteorological data from European public
sources — Italian regional ARPA stations, ECMWF Open Data, NOAA METAR/TAF, and Copernicus C3S — into
a single time-series store queryable via a public REST/WebSocket API and visualised through an
Angular dashboard with an interactive map. It is designed for researchers, data journalists,
open-data communities, and SMEs (agriculture, renewable energy) who need structured access to
historical weather data without paying commercial API fees.

**Current status:** v0.1 — Walking Skeleton. The ingestion pipeline, TimescaleDB storage, and
this documentation site are live. The public REST API and dashboard are coming in Phase 2 and
Phase 3 respectively.

## Architecture at a Glance

Data flows through Climate Pulse in a straightforward pipeline:

```
[ARPA Emilia-Romagna]          [ECMWF Open Data]
  REST/JSON feed                   GRIB2 files
       |                               |
       v                               v
  Celery Worker (ingest queue) ←── Redis broker
       |                               |
       v                               v
  WMO Normalizer (Pint SI units, quality flags)
       |                               |
       v                               v
  TimescaleDB (PostgreSQL 16)
    ├── observations          (station-based: ARPA)
    │   └── obs_hourly CAGG
    └── gridded_observations  (grid-based: ECMWF)
        └── gridded_hourly CAGG
       |
       v
  FastAPI (Phase 1: /healthz + /readyz only)
```

**Two hypertables** keep station-based and grid-based data cleanly separated:

- `observations` — ARPA Emilia-Romagna station measurements (air temperature, humidity,
  precipitation, wind direction, wind speed), partitioned by 7-day chunks, compressed after 7 days,
  retained for 5 years by default.
- `gridded_observations` — ECMWF IFS forecast grid points (EU bounding box, 0.25° resolution),
  partitioned by 1-day chunks, compressed after 7 days, retained for 90 days by default.

Each hypertable has its own continuous aggregate (CAGG), compression policy, and retention policy.

**Phase 1 API** exposes only two endpoints:

- `GET /healthz` — liveness check (process alive, always returns `{"status": "ok"}`)
- `GET /readyz` — readiness check (verifies DB + Redis + Celery worker heartbeat, returns 503 if
  any dependency is down)

Get started with the [Quickstart guide](quickstart.md).
