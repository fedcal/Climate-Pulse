"""Worker heartbeat — sets a Redis key that /readyz uses to detect live workers.

The committed heartbeat strategy (WARNING 3 resolution) uses exactly TWO components:

1. Startup signal: `worker_ready` signal connected in celery_app.py calls
   `set_heartbeat_sync(redis_url)` once per worker process at startup.

2. Periodic Beat task: `tasks.maintenance.heartbeat_tick` is scheduled every
   30s by Beat. It calls `set_heartbeat_sync` from inside a worker process to
   renew the Redis key before it expires.

REMOVED — DO NOT IMPLEMENT:
- task_postrun signal (too coupled to task throughput — quiet periods let key expire)
- worker_heartbeat signal (broker-internal timing, not a stable refresh source)
- worker_process_init per-process variant (Beat task already covers refresh)

Redis DB: DB 0 (broker DB, so worker can write without a separate connection pool).

Key: celery:worker:heartbeat
TTL:  120s (> 4× the 30s refresh interval for resilience to one missed refresh)
"""

import redis as sync_redis

HEARTBEAT_KEY = "celery:worker:heartbeat"
HEARTBEAT_TTL = 120  # seconds — must exceed beat-scheduled refresh interval by ≥4x
HEARTBEAT_REFRESH_INTERVAL = 30  # seconds — Beat-scheduled cadence


def set_heartbeat_sync(redis_url: str) -> None:
    """Write the worker heartbeat key to Redis (synchronous).

    Uses a short-lived Redis connection — not a persistent pool — since this
    is called from signal handlers and periodic tasks where connection reuse
    would require careful lifecycle management.

    Used by BOTH:
    - `worker_ready` signal (startup half of heartbeat strategy)
    - `tasks.maintenance.heartbeat_tick` Beat task (periodic refresh half)

    Args:
        redis_url: Redis connection URL (e.g. 'redis://redis:6379').
                   Uses DB 0 (broker DB) — no /db suffix override needed
                   since that is the default.

    Raises:
        redis.exceptions.ConnectionError: if Redis is unreachable.
            The caller (signal handler or task) should log but not crash.
    """
    client = sync_redis.from_url(redis_url, db=0, socket_timeout=5)
    try:
        client.setex(HEARTBEAT_KEY, HEARTBEAT_TTL, "ok")
    finally:
        client.close()
