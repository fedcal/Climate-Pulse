"""FastAPI minimal application for Climate Pulse Phase 1 (D-14, API-10).

This module exposes ONLY two endpoints per D-14 (Phase 1 minimal API):
  GET /healthz  — liveness (process up)
  GET /readyz   — readiness (DB + Redis + Celery worker all healthy)

All other API-* endpoints (stations, observations, OpenAPI spec, etc.) are
deferred to Phase 2. Their absence is enforced in tests (test_no_v1_routes_registered,
test_redoc_and_docs_are_disabled).

D-13 enforcement:
  openapi_url=None, docs_url=None, redoc_url=None
  These are set to None so no Phase 2 API surface leaks from this Phase 1 app.
  Requests to /docs, /redoc, /openapi.json all return 404.

Lifespan:
  - Startup: create asyncpg pool + redis.asyncio.Redis client
  - Shutdown: close both connections
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from fastapi import FastAPI
from redis.asyncio import Redis

from climatepulse_api.routers import health
from climatepulse_api.settings import get_api_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database and Redis connection lifecycle.

    Creates connection pool on startup, closes them on shutdown.
    Both are stored on app.state for dependency injection in routers.
    """
    settings = get_api_settings()

    # asyncpg expects 'postgresql://' not 'postgresql+asyncpg://'
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    app.state.db_pool = await asyncpg.create_pool(
        db_url,
        min_size=1,
        max_size=5,
    )
    app.state.redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=False,  # keep bytes for heartbeat key comparison
    )

    yield

    # Teardown
    await app.state.db_pool.close()
    await app.state.redis_client.close()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Climate Pulse",
    version="0.1.0",
    description="Multi-source EU weather aggregation pipeline — Phase 1 minimal API",
    lifespan=lifespan,
    # D-13: Disable all OpenAPI docs in Phase 1. Phase 2 will add API-09 (OpenAPI 3.1 spec).
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# Routers — Phase 1: health only
# ---------------------------------------------------------------------------

app.include_router(health.router)


# ---------------------------------------------------------------------------
# Root endpoint — friendly redirect-equivalent (no /v1 surface exposed)
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root() -> dict:
    """Root endpoint — friendly message for direct access.

    Returns a minimal JSON response without exposing the absent /v1 surface.
    The docs URL (GitHub Pages) is public information from PROJECT.md.
    """
    return {
        "status": "Climate Pulse minimal API",
        "docs": "https://federicocalo.github.io/climate-pulse",
        "health": "/healthz",
        "readiness": "/readyz",
    }
