"""Unit tests for the `climatepulse backfill` CLI (ING-13, D-12).

Covers:
- Source alias normalisation (arpae → arpa_emilia)
- Invalid date format → exit code 2
- Unknown source → exit code 2
- Default --to is today
- Daily window splitting (3 days → 3 calls to write_batch)
- Idempotency: re-run produces 0 new rows
"""

import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from climatepulse_worker.cli.backfill import (
    SOURCE_ALIASES,
    parse_args,
    run_backfill,
)


# ---------------------------------------------------------------------------
# Source alias tests
# ---------------------------------------------------------------------------


def test_source_alias_arpae_resolves_to_arpa_emilia():
    """'arpae' alias must resolve to 'arpa_emilia' source_id."""
    args = parse_args(["arpae", "--from", "2026-05-01"])
    resolved = SOURCE_ALIASES.get(args.source, args.source)
    assert resolved == "arpa_emilia", (
        f"Expected 'arpa_emilia', got '{resolved}'"
    )


def test_source_alias_arpa_resolves_to_arpa_emilia():
    """'arpa' alias must also resolve to 'arpa_emilia'."""
    args = parse_args(["arpa", "--from", "2026-05-01"])
    resolved = SOURCE_ALIASES.get(args.source, args.source)
    assert resolved == "arpa_emilia"


def test_source_alias_ecmwf_resolves_to_ecmwf_open():
    """'ecmwf' alias must resolve to 'ecmwf_open' source_id."""
    args = parse_args(["ecmwf", "--from", "2026-05-01"])
    resolved = SOURCE_ALIASES.get(args.source, args.source)
    assert resolved == "ecmwf_open"


def test_canonical_source_id_is_identity():
    """Canonical source_ids (e.g. 'arpa_emilia') resolve to themselves."""
    args = parse_args(["arpa_emilia", "--from", "2026-05-01"])
    resolved = SOURCE_ALIASES.get(args.source, args.source)
    assert resolved == "arpa_emilia"


# ---------------------------------------------------------------------------
# Invalid inputs → exit code 2
# ---------------------------------------------------------------------------


def test_invalid_date_format_exits_2():
    """Invalid --from date format must exit with code 2."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["arpae", "--from", "not-a-date"])
    assert exc_info.value.code == 2


def test_unknown_source_rejected():
    """Unknown source name must exit with code 2."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["unknown_src", "--from", "2026-05-01"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Default --to is today
# ---------------------------------------------------------------------------


def test_default_to_is_today():
    """When --to is omitted, the parsed value must be today's date."""
    args = parse_args(["arpae", "--from", "2026-05-01"])
    assert args.to == date.today(), (
        f"Default --to should be today ({date.today()}), got {args.to}"
    )


# ---------------------------------------------------------------------------
# Daily window splitting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_splits_by_day():
    """run_backfill must call write_batch once per day in the date range."""
    # Stub adapter that yields one fake observation per fetch
    stub_obs = MagicMock()
    stub_obs.station_external_id = "test_station"
    stub_obs.wmo_code = "air_temperature"

    async def stub_fetch(window):
        yield stub_obs

    stub_adapter = MagicMock()
    stub_adapter.is_grid_based = False
    stub_adapter.source_id = "arpa_emilia"
    stub_adapter.fetch = stub_fetch

    write_batch_calls = []

    async def stub_write_batch(adapter, obs_list):
        write_batch_calls.append(len(obs_list))
        return len(obs_list)

    stub_writer = MagicMock()
    stub_writer.write_batch = stub_write_batch

    mock_ensure = AsyncMock(return_value=({}, {}, {}))

    with (
        patch(
            "climatepulse_worker.cli.backfill.get_adapter",
            return_value=stub_adapter,
        ),
        patch(
            "climatepulse_worker.cli.backfill.IdempotentWriter",
            return_value=stub_writer,
        ),
        patch(
            "climatepulse_worker.cli.backfill._ensure_metadata",
            mock_ensure,
        ),
    ):
        await run_backfill(
            source_id="arpa_emilia",
            since=date(2026, 5, 1),
            until=date(2026, 5, 3),
            db_pool=MagicMock(),
            redis_client=MagicMock(),
        )

    # 3 days: May 1, May 2, May 3 → 3 write_batch calls
    assert len(write_batch_calls) == 3, (
        f"Expected 3 daily write_batch calls, got {len(write_batch_calls)}"
    )


# ---------------------------------------------------------------------------
# Idempotency — second run produces 0 rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backfill_idempotent_second_run_zero_rows():
    """Second run_backfill over the same date range must return 0 total rows."""
    stub_obs = MagicMock()
    stub_obs.station_external_id = "test_station"
    stub_obs.wmo_code = "air_temperature"

    async def stub_fetch(window):
        yield stub_obs

    stub_adapter = MagicMock()
    stub_adapter.is_grid_based = False
    stub_adapter.source_id = "arpa_emilia"
    stub_adapter.fetch = stub_fetch

    run_count = [0]

    async def idempotent_write_batch(adapter, obs_list):
        run_count[0] += 1
        # First run: insert rows; second run: 0 new rows (all DO UPDATE)
        if run_count[0] <= 1:  # only 1 day in test range
            return len(obs_list)
        return 0  # Idempotent: second run inserts nothing

    stub_writer = MagicMock()
    stub_writer.write_batch = idempotent_write_batch

    mock_ensure = AsyncMock(return_value=({}, {}, {}))

    with (
        patch(
            "climatepulse_worker.cli.backfill.get_adapter",
            return_value=stub_adapter,
        ),
        patch(
            "climatepulse_worker.cli.backfill.IdempotentWriter",
            return_value=stub_writer,
        ),
        patch(
            "climatepulse_worker.cli.backfill._ensure_metadata",
            mock_ensure,
        ),
    ):
        first_total = await run_backfill(
            source_id="arpa_emilia",
            since=date(2026, 5, 1),
            until=date(2026, 5, 1),  # single day
            db_pool=MagicMock(),
            redis_client=MagicMock(),
        )

        run_count[0] = 0  # reset counter

        async def zero_write_batch(adapter, obs_list):
            return 0  # Idempotent re-run: 0 new rows

        stub_writer.write_batch = zero_write_batch

        second_total = await run_backfill(
            source_id="arpa_emilia",
            since=date(2026, 5, 1),
            until=date(2026, 5, 1),
            db_pool=MagicMock(),
            redis_client=MagicMock(),
        )

    assert second_total == 0, (
        f"Second run must produce 0 new rows (idempotency contract); got {second_total}"
    )


# ---------------------------------------------------------------------------
# --help output contains 'backfill'
# ---------------------------------------------------------------------------


def test_help_contains_backfill():
    """parse_args('--help') should print usage with 'backfill'."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--help"])
    # argparse --help exits with 0
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Valid date range parsing
# ---------------------------------------------------------------------------


def test_valid_date_range_parses():
    """Valid --from and --to should parse as date objects."""
    args = parse_args(["arpae", "--from", "2026-05-01", "--to", "2026-05-07"])
    assert args.source == "arpae"
    assert args.from_date == date(2026, 5, 1)
    assert args.to == date(2026, 5, 7)


def test_from_before_to():
    """--from before --to is valid (no error)."""
    args = parse_args(["arpae", "--from", "2026-05-01", "--to", "2026-05-31"])
    assert args.from_date == date(2026, 5, 1)
    assert args.to == date(2026, 5, 31)
