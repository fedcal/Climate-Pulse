"""Maintenance Celery tasks — snapshot rotation (D-17) + worker heartbeat (WARNING 3).

Tasks:
  rotate_snapshots   — delete JSON-LD snapshots older than 30 days (D-17).
                       Scheduled daily at 03:00 UTC by Beat.
  heartbeat_tick     — renew the worker heartbeat Redis key every 30s (WARNING 3).
                       Part of the committed two-component heartbeat strategy.

Both tasks run inside a worker process — dispatched by the singleton Beat service.
"""

import asyncio

import structlog

from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="climatepulse_worker.tasks.maintenance.rotate_snapshots")
def rotate_snapshots() -> int:
    """Delete JSON-LD snapshot files older than 30 days (D-17 retention).

    Uses SnapshotStore.rotate(max_age_days=30) to walk the Docker volume
    and remove stale .jsonld files. Runs daily at 03:00 UTC per the Beat
    schedule in celery_app.py.

    Returns:
        Number of snapshot files deleted.
    """
    from climatepulse_core.http.snapshot import SnapshotStore
    from climatepulse_core.settings import get_settings

    settings = get_settings()
    store = SnapshotStore(settings.snapshot_dir)
    count = asyncio.run(store.rotate(max_age_days=30))

    logger.info("snapshots.rotated", count=count, snapshot_dir=settings.snapshot_dir)
    return count


@shared_task(name="climatepulse_worker.tasks.maintenance.heartbeat_tick")
def heartbeat_tick() -> None:
    """Renew the worker heartbeat Redis key (periodic refresh — WARNING 3).

    This is the periodic-refresh half of the committed two-component heartbeat
    strategy. Beat dispatches this task every 30s; any healthy worker picks it
    up and calls set_heartbeat_sync to extend the Redis key TTL.

    Paired with the worker_ready signal (startup half) in celery_app.py.

    The /readyz endpoint checks Redis key 'celery:worker:heartbeat' — as long
    as at least one worker is alive and picking up this task, the key stays
    fresh and /readyz reports the Celery component as healthy.

    Key: celery:worker:heartbeat (TTL: 120s — see heartbeat.py)
    Schedule: every 30s via beat_schedule["worker-heartbeat-30s"]
    """
    from climatepulse_core.settings import get_settings

    from climatepulse_worker.heartbeat import set_heartbeat_sync

    settings = get_settings()
    try:
        set_heartbeat_sync(settings.redis_url)
        logger.debug("heartbeat.renewed", key="celery:worker:heartbeat")
    except Exception as exc:
        # Do not crash the task — log the failure and let it retry next cycle
        logger.warning("heartbeat.failed", error=str(exc))
