"""Ingestion Celery tasks — run_source + dlq_route (ING-11, D-19, D-20).

Tasks:
  run_source(source_id) — fetch observations for source_id for a recent
                          overlap window; route SCHEMA_VIOLATION rows to dlq.
                          Retries up to 3 times with exponential backoff.
  dlq_route(source_id, observations) — receive DLQ-routed observations;
                                        log + persist to Redis sorted set
                                        for Phase 5 visibility.

Adapter imports at module top level so @register decorators fire when this
module is imported (which happens when Celery auto-discovers tasks).
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task
from celery.utils.log import get_task_logger

# Import adapter modules to trigger @register decorators — required so
# get_adapter("arpa_emilia") and get_adapter("ecmwf_open") work in run_source.
# The noqa F401 suppresses "imported but unused" linter warning.
from climatepulse_core.adapters import arpa_emilia  # noqa: F401
from climatepulse_core.adapters import ecmwf_open  # noqa: F401
from climatepulse_core.adapters.base import get_adapter
from climatepulse_core.domain.models import QcFlag

logger = get_task_logger(__name__)
structlog_logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    name="climatepulse_worker.tasks.ingest.run_source",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def run_source(self, source_id: str) -> int:
    """Fetch and persist observations for a given source_id (ING-11).

    Builds a time window of [now - 2*cadence_seconds, now] to catch any
    missed runs in the previous cycle (overlap window strategy). Delegates
    to run_backfill_window for the actual fetch + write.

    On any SCHEMA_VIOLATION rows discovered during write, routes them to
    the DLQ queue via dlq_route.apply_async(queue='dlq') (D-20).

    Args:
        source_id: canonical source identifier (e.g. 'arpa_emilia').

    Returns:
        Total rows written to the hypertable.

    Raises:
        Exception: re-raised after recording the error; triggers Celery retry.
    """
    adapter = get_adapter(source_id)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=2 * adapter.cadence_seconds)

    structlog_logger.info(
        "ingest.run_source.start",
        source=source_id,
        window_start=window_start.isoformat(),
        window_end=now.isoformat(),
    )

    async def _run() -> int:
        import asyncpg
        import redis.asyncio as aioredis

        from climatepulse_core.adapters.base import FetchWindow
        from climatepulse_core.storage.writer import IdempotentWriter
        from climatepulse_worker.cli.backfill import _ensure_metadata

        from climatepulse_core.settings import get_settings
        settings = get_settings()

        # Strip +asyncpg driver prefix that asyncpg.create_pool doesn't accept
        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

        db_pool = None
        redis_client = None
        try:
            db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
            redis_client = aioredis.Redis.from_url(settings.redis_url)

            sources_cache, variables_cache, stations_cache = await _ensure_metadata(
                source_id, adapter, db_pool, redis_client
            )

            writer = IdempotentWriter(
                db_pool=db_pool,
                redis_client=redis_client,
                sources_cache=sources_cache,
                variables_cache=variables_cache,
                stations_cache=stations_cache,
            )

            window = FetchWindow(since=window_start, until=now)
            obs_list = [o async for o in adapter.fetch(window)]

            # Separate schema-violation rows from normal rows
            normal_obs = []
            schema_violations = []
            for obs in obs_list:
                if obs.qc_flag == QcFlag.SCHEMA_VIOLATION:
                    schema_violations.append(obs)
                else:
                    normal_obs.append(obs)

            # Route schema violations to DLQ (D-20)
            if schema_violations:
                violation_dicts = [
                    {
                        "source_id": obs.source_id,
                        "observed_at": obs.observed_at.isoformat(),
                        "station_external_id": obs.station_external_id,
                        "wmo_code": obs.wmo_code,
                        "value": obs.value,
                        "qc_flag": int(obs.qc_flag),
                    }
                    for obs in schema_violations
                ]
                dlq_route.apply_async(
                    args=(source_id, violation_dicts),
                    queue="dlq",
                )
                structlog_logger.warning(
                    "ingest.schema_violations_routed",
                    source=source_id,
                    count=len(schema_violations),
                )

            rows_written = await writer.write_batch(adapter, normal_obs)

            structlog_logger.info(
                "ingest.run_source.complete",
                source=source_id,
                observations=len(obs_list),
                rows_written=rows_written,
                schema_violations=len(schema_violations),
            )
            return rows_written

        finally:
            if redis_client:
                await redis_client.aclose()
            if db_pool:
                await db_pool.close()

    return asyncio.run(_run())


@shared_task(name="climatepulse_worker.tasks.ingest.dlq_route")
def dlq_route(source_id: str, observations: list) -> None:
    """Receive DLQ-routed observations (D-20 schema-violation handling).

    Logs the violation and persists to a Redis list keyed by source_id for
    Phase 5 DLQ CLI visibility. Trims to the last 1000 entries to bound memory.

    Args:
        source_id:     canonical source identifier for the violating rows.
        observations:  list of observation dicts (serialized RawObservation).
    """
    import redis as sync_redis

    from climatepulse_core.settings import get_settings

    settings = get_settings()

    structlog_logger.warning(
        "dlq.received",
        source=source_id,
        count=len(observations),
    )

    # Persist to Redis for Phase 5 visibility
    now_iso = datetime.now(timezone.utc).isoformat()
    entry = json.dumps({"observations": observations, "received_at": now_iso})
    dlq_key = f"dlq:{source_id}"

    client = sync_redis.from_url(settings.redis_url, db=0, socket_timeout=5)
    try:
        pipe = client.pipeline()
        pipe.lpush(dlq_key, entry)
        pipe.ltrim(dlq_key, 0, 999)  # keep last 1000 entries
        pipe.execute()
    except Exception as exc:
        structlog_logger.error("dlq.persist_failed", source=source_id, error=str(exc))
    finally:
        client.close()
