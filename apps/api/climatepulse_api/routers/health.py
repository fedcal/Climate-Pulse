"""Health check endpoints — /healthz (liveness) + /readyz (readiness) (API-10, D-14).

/healthz: liveness endpoint — process is up. Returns 200 always.
          Must NOT check any dependencies (true liveness per Kubernetes convention).

/readyz:  readiness endpoint — all dependencies are healthy.
          Checks DB (asyncpg SELECT 1) + Redis (ping) + Celery worker heartbeat.
          Returns 200 {"status":"ready"} or 503 {"detail": {component: error}}.

The readyz Celery check uses a lightweight Redis key check (not inspect().ping()
which is synchronous and slow). The worker sets SETEX celery:worker:heartbeat 120 "ok"
on startup and every 30s via Beat (see climatepulse_worker.heartbeat).

Security (T-05-02): Error detail in 503 reveals only component names (db, redis,
celery). These are already public-knowledge architectural choices in PROJECT.md;
they do not aid an attacker.
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException

router = APIRouter(tags=["health"])

# Redis key set by the worker heartbeat strategy (see climatepulse_worker.heartbeat)
WORKER_HEARTBEAT_KEY = "celery:worker:heartbeat"


@router.get("/healthz", status_code=200)
async def liveness() -> dict:
    """Liveness probe: process is alive.

    Returns 200 {"status":"ok"} unconditionally. Does NOT check any external
    dependency — a failed DB or Redis connection must not report the process
    as dead (that would trigger unnecessary pod restarts in a future Kubernetes
    deployment or restart loops in Docker Compose).
    """
    return {"status": "ok"}


@router.get("/readyz", status_code=200)
async def readiness(request: Request) -> dict:
    """Readiness probe: all dependencies are reachable.

    Checks in parallel:
    1. DB: asyncpg SELECT 1 (2s timeout)
    2. Redis: Redis.ping() (2s timeout)
    3. Celery: Redis.get("celery:worker:heartbeat") == "ok" (2s timeout)

    Returns:
        200 {"status":"ready"} if all checks pass.
        503 {"detail": {component: error_message}} listing each failing component.

    Raises:
        HTTPException(503): if any dependency is unhealthy.
    """
    db_pool = request.app.state.db_pool
    redis_client = request.app.state.redis_client
    errors: dict[str, str] = {}

    # DB check
    async def check_db() -> None:
        async with db_pool.acquire() as conn:
            await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=2.0)

    # Redis check
    async def check_redis() -> None:
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)

    # Celery worker heartbeat check
    async def check_celery() -> None:
        pong = await asyncio.wait_for(
            redis_client.get(WORKER_HEARTBEAT_KEY),
            timeout=2.0,
        )
        if pong not in (b"ok", "ok"):
            raise ValueError("no worker heartbeat")

    checks = [
        ("db", check_db),
        ("redis", check_redis),
        ("celery", check_celery),
    ]

    results = await asyncio.gather(
        *[coro() for _, coro in checks],
        return_exceptions=True,
    )

    for (component, _), result in zip(checks, results):
        if isinstance(result, Exception):
            errors[component] = str(result) if str(result) else type(result).__name__

    if errors:
        raise HTTPException(status_code=503, detail=errors)

    return {"status": "ready"}
