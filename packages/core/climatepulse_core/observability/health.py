"""Per-source health metrics for the ING-14 canary pattern.

Tracks last_successful_ingest_at per source in Redis DB 4 (REDIS_DB_METRICS).
The IdempotentWriter calls record_success() after every successful flush.
A canary Celery task periodically calls is_stale() for each source and flips
the source to 'unhealthy' if no success has been seen within 2×cadence_seconds.

Redis key format: metrics:last_success:{source_id}
Redis TTL: 86400 seconds (24 hours) — matches is_stale threshold of 2×cadence.
"""

from datetime import datetime, timezone


_KEY_PREFIX = "metrics:last_success"
_TTL_SECONDS = 86400  # 24h


async def record_success(redis_client, source_id: str) -> None:
    """Record a successful ingest event for source_id in Redis.

    Writes the current UTC ISO timestamp under `metrics:last_success:{source_id}`
    with a 24-hour TTL. Overwrites any existing entry for the source.

    Args:
        redis_client:  an async Redis client (redis.asyncio or fakeredis.aioredis)
        source_id:     the adapter's source_id string
    """
    key = f"{_KEY_PREFIX}:{source_id}"
    ts = datetime.now(timezone.utc).isoformat()
    await redis_client.setex(key, _TTL_SECONDS, ts)


async def get_last_success(redis_client, source_id: str) -> datetime | None:
    """Return the last successful ingest timestamp for source_id, or None.

    Args:
        redis_client:  an async Redis client
        source_id:     the adapter's source_id string

    Returns:
        UTC-aware datetime of the last recorded success, or None if key is absent.
    """
    key = f"{_KEY_PREFIX}:{source_id}"
    raw = await redis_client.get(key)
    if raw is None:
        return None

    # raw is bytes from redis, or str from fakeredis
    ts_str = raw.decode() if isinstance(raw, bytes) else raw
    return datetime.fromisoformat(ts_str)


async def is_stale(redis_client, source_id: str, cadence_seconds: int) -> bool:
    """Return True if the source has not ingested within 2×cadence_seconds (ING-14).

    The 2× multiplier gives a grace window so a single delayed run does not
    immediately trigger the canary alert. If the key is absent (source never ran
    or TTL expired), the source is considered stale.

    Args:
        redis_client:      an async Redis client
        source_id:         the adapter's source_id string
        cadence_seconds:   expected ingest interval (e.g. 900 for 15-min cadence)

    Returns:
        True  if key absent or last success older than 2×cadence_seconds
        False if last success is within 2×cadence_seconds
    """
    last_success = await get_last_success(redis_client, source_id)
    if last_success is None:
        return True

    now = datetime.now(timezone.utc)
    age_seconds = (now - last_success).total_seconds()
    return age_seconds > (2 * cadence_seconds)
