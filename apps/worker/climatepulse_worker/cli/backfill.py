"""Backfill CLI — `climatepulse backfill <source> --from --to` (ING-13, D-12).

Usage:
    climatepulse backfill arpae --from 2026-05-01 --to 2026-05-07
    climatepulse backfill ecmwf --from 2026-05-01 --to 2026-05-07

Splits the date window by day; calls adapter.fetch + writer.write_batch per day.
Idempotent: re-running the same command produces 0 new rows (ON CONFLICT DO UPDATE).

Source aliases (D-12 user-facing command shape):
  arpae / arpa / arpa_emilia → arpa_emilia (canonical source_id)
  ecmwf / ecmwf_open        → ecmwf_open  (canonical source_id)

Security (T-04-03): asyncpg errors are caught and printed without echoing
the connection URL to stderr. argparse error formatter does not echo args.
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import structlog

from climatepulse_core.adapters.base import all_source_ids, get_adapter
from climatepulse_core.storage.writer import IdempotentWriter

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Source alias map (D-12 user-facing aliases → canonical source_id)
# ---------------------------------------------------------------------------

SOURCE_ALIASES: dict[str, str] = {
    "arpae": "arpa_emilia",
    "arpa": "arpa_emilia",
    "arpa_emilia": "arpa_emilia",
    "ecmwf": "ecmwf_open",
    "ecmwf_open": "ecmwf_open",
}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse backfill CLI arguments.

    Args:
        argv: argument list (defaults to sys.argv[1:])

    Returns:
        Parsed namespace with:
          .source       str (raw alias or canonical)
          .from_date    date
          .to           date (defaults to today)
          .db_url       str | None
          .redis_url    str | None

    Raises:
        SystemExit(2): on invalid arguments (argparse default)
    """
    parser = argparse.ArgumentParser(
        prog="climatepulse backfill",
        description=(
            "Backfill weather observations from a source adapter.\n"
            "Splits the date window by day; idempotent re-run produces zero new rows.\n"
            "\n"
            f"Registered sources: {', '.join(sorted(SOURCE_ALIASES.keys()))}\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        type=str,
        choices=sorted(SOURCE_ALIASES.keys()),
        metavar="SOURCE",
        help=(
            "Data source to backfill. "
            f"Choices: {', '.join(sorted(SOURCE_ALIASES.keys()))}"
        ),
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=date.fromisoformat,
        required=True,
        metavar="YYYY-MM-DD",
        help="Start date (inclusive, ISO format)",
    )
    parser.add_argument(
        "--to",
        dest="to",
        type=date.fromisoformat,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="End date (inclusive, ISO format). Defaults to today.",
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        type=str,
        default=None,
        help="PostgreSQL connection URL (overrides DATABASE_URL env var)",
    )
    parser.add_argument(
        "--redis-url",
        dest="redis_url",
        type=str,
        default=None,
        help="Redis connection URL (overrides REDIS_URL env var)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Metadata bootstrap
# ---------------------------------------------------------------------------


async def _ensure_metadata(
    source_id: str,
    adapter: Any,
    db_pool: Any,
    redis_client: Any,
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    """Upsert source metadata and return surrogate caches for the IdempotentWriter.

    Registers the source + WMO variables + stations (via discover_stations)
    into the metadata tables so the writer can resolve surrogate PKs.

    Returns:
        (sources_cache, variables_cache, stations_cache)
    """
    from climatepulse_core.domain.models import Source, Variable
    from climatepulse_core.normalize.wmo import WMO_VARIABLES
    from climatepulse_core.storage.repos import MetadataRepo

    meta = adapter.source_meta()
    repo = MetadataRepo(db_pool)

    # Upsert source
    source = Source(
        source_id=meta.source_id,
        name=meta.name,
        license=meta.license,
        attribution=meta.attribution,
        terms_url=meta.terms_url,
        enabled=True,
    )
    source_pk = await repo.upsert_source(source)

    # Upsert all WMO variables
    for wmo_code, var_meta in WMO_VARIABLES.items():
        bufr_codes = var_meta.get("bufr_codes", [])
        bufr_code = bufr_codes[0] if bufr_codes else None
        variable = Variable(
            wmo_code=wmo_code,
            bufr_code=bufr_code,
            unit_si=var_meta["unit_si"],
        )
        await repo.upsert_variable(variable)

    # Discover + upsert stations (grid-based adapters return empty list)
    try:
        stations = await adapter.discover_stations()
    except Exception as exc:
        logger.warning("backfill.discover_stations_failed", error=str(exc))
        stations = []

    for station in stations:
        await repo.upsert_station(station, source_pk)

    # Load caches
    sources_cache = await repo.load_sources_cache()
    variables_cache = await repo.load_variables_cache()
    stations_cache = {
        source_id: await repo.load_stations_cache(sources_cache[source_id])
        for source_id in sources_cache
    }

    return sources_cache, variables_cache, stations_cache


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


async def run_backfill(
    source_id: str,
    since: date,
    until: date,
    db_pool: Any,
    redis_client: Any,
) -> int:
    """Execute the backfill for a date range.

    Splits the range by day; calls adapter.fetch + writer.write_batch per day.
    Prints per-day row counts to stdout.

    Args:
        source_id:    canonical source identifier (e.g. 'arpa_emilia')
        since:        start date (inclusive)
        until:        end date (inclusive)
        db_pool:      asyncpg.Pool or compatible
        redis_client: async Redis client for ING-14 health metrics

    Returns:
        Total rows written across all days.
    """
    # Trigger adapter registration via import
    import importlib

    for module_name in [
        "climatepulse_core.adapters.arpa_emilia",
        "climatepulse_core.adapters.ecmwf_open",
    ]:
        try:
            importlib.import_module(module_name)
        except Exception:
            pass  # Adapter may not be installed in this environment

    adapter = get_adapter(source_id)

    # Ensure metadata tables are populated; load surrogate caches
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

    total_rows = 0
    current_day = since

    while current_day <= until:
        # Build daily FetchWindow
        day_since = datetime.combine(current_day, time.min, tzinfo=timezone.utc)
        day_until = datetime.combine(
            current_day + timedelta(days=1), time.min, tzinfo=timezone.utc
        )

        from climatepulse_core.adapters.base import FetchWindow
        window = FetchWindow(since=day_since, until=day_until)

        try:
            obs_list = [o async for o in adapter.fetch(window)]
            rows_written = await writer.write_batch(adapter, obs_list)
        except Exception as exc:
            logger.error(
                "backfill.day_failed",
                source=source_id,
                day=current_day.isoformat(),
                error=str(exc),
            )
            print(
                f"{current_day}: ERROR — {exc!s}",
                file=sys.stderr,
            )
            current_day += timedelta(days=1)
            continue

        total_rows += rows_written
        logger.info(
            "backfill.day",
            source=source_id,
            day=current_day.isoformat(),
            observations=len(obs_list),
            rows_written=rows_written,
        )
        print(f"{current_day.isoformat()}: {rows_written} rows persisted")
        current_day += timedelta(days=1)

    return total_rows


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for `climatepulse backfill`.

    Returns:
        0 on success, 1 on error, 2 on argument error (argparse).
    """
    args = parse_args(argv)
    source_id = SOURCE_ALIASES[args.source]

    # Validate date range
    if args.from_date > args.to:
        print(
            f"Error: --from {args.from_date} is after --to {args.to}",
            file=sys.stderr,
        )
        return 2

    # Build connection URLs
    import os

    db_url = args.db_url or os.environ.get("DATABASE_URL", "")
    redis_url = args.redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")

    if not db_url:
        print(
            "Error: DATABASE_URL not set. Use --db-url or set DATABASE_URL env var.",
            file=sys.stderr,
        )
        return 1

    async def _run() -> int:
        import asyncpg
        import redis.asyncio as aioredis

        db_pool = None
        redis_client = None
        try:
            # Strip +asyncpg driver prefix that asyncpg.create_pool doesn't accept
            # (SQLAlchemy uses "postgresql+asyncpg://" but asyncpg wants "postgresql://")
            asyncpg_url = (
                "postgresql://" + db_url[len("postgresql+asyncpg://") :]
                if db_url.startswith("postgresql+asyncpg://")
                else db_url
            )
            db_pool = await asyncpg.create_pool(asyncpg_url)
            redis_client = aioredis.Redis.from_url(redis_url)

            total = await run_backfill(
                source_id=source_id,
                since=args.from_date,
                until=args.to,
                db_pool=db_pool,
                redis_client=redis_client,
            )
            print(f"\nTotal rows persisted: {total}")
            return 0

        except KeyError as exc:
            # T-04-03: Do NOT echo db_url/credentials in error messages
            print(f"Error: Unknown source '{source_id}'", file=sys.stderr)
            logger.error("backfill.unknown_source", source=source_id, error=str(exc))
            return 1
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            # T-04-03: sanitize error — never echo connection strings
            error_msg = str(exc)
            if db_url in error_msg:
                error_msg = error_msg.replace(db_url, "<redacted>")
            print(f"Error: {error_msg}", file=sys.stderr)
            logger.error("backfill.failed", error=str(exc))
            return 1
        finally:
            if redis_client:
                await redis_client.aclose()
            if db_pool:
                await db_pool.close()

    return asyncio.run(_run())
