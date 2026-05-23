"""Celery application configuration for Climate Pulse worker (ING-11).

Queue topology (ING-11):
  ingest    — adapter fetch + write tasks (run_source, rotate_snapshots)
  normalize — reserved for Phase 5 normalization pipeline
  alerts    — reserved for Phase 5 alert evaluation
  dlq       — dead letter queue for schema-violation rows (D-20)

Beat schedule:
  arpa-emilia-15min      — run_source("arpa_emilia") every 15 min (D-19)
  ecmwf-open-6h          — run_source("ecmwf_open") every 6 hours
  rotate-snapshots-daily — rotate_snapshots() daily at 03:00 UTC (D-17)
  worker-heartbeat-30s   — heartbeat_tick() every 30s (WARNING 3 — periodic refresh)

Heartbeat strategy (WARNING 3 — committed, no alternatives):
  1. Startup: worker_ready signal → set_heartbeat_sync(redis_url)
  2. Periodic: Beat dispatches heartbeat_tick every 30s → set_heartbeat_sync(redis_url)

The /readyz endpoint (Plan 05 Task 2) checks Redis key 'celery:worker:heartbeat'
(TTL 120s) to verify at least one worker is alive. The key must be renewed faster
than the TTL — 30s cadence gives a 4x safety margin.
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready
from kombu import Queue

from climatepulse_core.settings import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = Celery("climatepulse_worker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

app.conf.update(
    # Broker + backend (DB 0 = broker, DB 1 = results — see settings.py allocation)
    broker_url=f"{settings.redis_url}/0",
    result_backend=f"{settings.redis_url}/1",

    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Reliability settings
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# ---------------------------------------------------------------------------
# Queue definitions — ING-11 mandates exactly 4 queues
# ---------------------------------------------------------------------------

app.conf.task_queues = [
    Queue("ingest"),
    Queue("normalize"),
    Queue("alerts"),
    Queue("dlq"),
]

app.conf.task_default_queue = "ingest"

# Route tasks to their appropriate queues
app.conf.task_routes = {
    "climatepulse_worker.tasks.ingest.*": {"queue": "ingest"},
    "climatepulse_worker.tasks.maintenance.*": {"queue": "ingest"},
    # dlq tasks are explicitly dispatched to "dlq" queue via apply_async(queue='dlq')
}

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {
    # D-19: ARPA Emilia-Romagna every 15 minutes
    "arpa-emilia-15min": {
        "task": "climatepulse_worker.tasks.ingest.run_source",
        "schedule": 900.0,
        "args": ("arpa_emilia",),
    },

    # ECMWF Open Data every 6 hours (4 forecast cycles per day)
    "ecmwf-open-6h": {
        "task": "climatepulse_worker.tasks.ingest.run_source",
        "schedule": 21600.0,
        "args": ("ecmwf_open",),
    },

    # D-17: rotate JSON-LD snapshots daily at 03:00 UTC
    "rotate-snapshots-daily": {
        "task": "climatepulse_worker.tasks.maintenance.rotate_snapshots",
        "schedule": crontab(hour=3, minute=0),
    },

    # WARNING 3 — committed heartbeat strategy (periodic refresh component)
    # Beat dispatches this every 30s; a worker renews the Redis key so /readyz
    # sees the Celery component as alive. TTL=120s gives 4x safety margin.
    "worker-heartbeat-30s": {
        "task": "climatepulse_worker.tasks.maintenance.heartbeat_tick",
        "schedule": 30.0,
    },
}

# ---------------------------------------------------------------------------
# Explicitly import task modules so @shared_task decorators register tasks.
# autodiscover_tasks is left as a belt-and-suspenders call for worker startup,
# but explicit imports guarantee registration at module-import time (needed
# for tests and for `celery inspect registered`).
# ---------------------------------------------------------------------------

import climatepulse_worker.tasks.ingest  # noqa: E402, F401
import climatepulse_worker.tasks.maintenance  # noqa: E402, F401

app.autodiscover_tasks(["climatepulse_worker.tasks"])

# ---------------------------------------------------------------------------
# Startup signal — worker_ready (startup half of committed heartbeat strategy)
# ---------------------------------------------------------------------------


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Write the worker heartbeat key on process startup (WARNING 3 — startup half).

    Called once per worker process when Celery signals the worker is ready to
    accept tasks. Sets Redis key 'celery:worker:heartbeat' with SETEX 120 'ok'.

    The periodic half (Beat task every 30s) renews the key so /readyz stays
    green as long as the worker is alive and picking up tasks.
    """
    from climatepulse_worker.heartbeat import set_heartbeat_sync

    try:
        set_heartbeat_sync(settings.redis_url)
    except Exception as exc:
        # Non-fatal — log and continue. Beat will renew the key within 30s.
        import logging
        logging.getLogger(__name__).warning(
            "worker_ready: heartbeat set failed: %s", exc
        )
