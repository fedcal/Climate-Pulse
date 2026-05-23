"""Timezone helper: Europe/Rome naive datetimes -> UTC TIMESTAMPTZ (ING-10).

Provides two exception classes (NonExistentTimeError, AmbiguousTimeError) for
the two DST transition cases:
  - Spring-forward gap  (2026-03-29 02:00-03:00): NonExistentTimeError
  - Fall-back overlap   (2026-10-25 02:00-03:00): AmbiguousTimeError

D-26 requires explicit tests for both cases, covered in tests/unit/test_timezone.py.

The strict wrapper (to_utc_strict) resolves ambiguity deterministically:
  - Gap: advance naive_dt by 1 hour (post-gap time), tag QcFlag.OUT_OF_RANGE
  - Ambiguous: use fold parameter (0 = first occurrence = CEST, 1 = CET)
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from climatepulse_core.domain.models import QcFlag

# Timezone definitions
_ROME_TZ = ZoneInfo("Europe/Rome")
_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class NonExistentTimeError(ValueError):
    """Raised when a naive datetime falls in a DST spring-forward gap.

    Example: 2026-03-29 02:30 Europe/Rome does not exist — clocks jump
    from 02:00 CET directly to 03:00 CEST.
    """


class AmbiguousTimeError(ValueError):
    """Raised when a naive datetime falls in a DST fall-back overlap.

    Example: 2026-10-25 02:30 Europe/Rome occurs twice — once as CEST (UTC+2)
    and once as CET (UTC+1). The caller must decide which occurrence to use.
    """


# ---------------------------------------------------------------------------
# DST transition detection helpers
# ---------------------------------------------------------------------------


def _find_last_sunday(year: int, month: int) -> datetime:
    """Return the last Sunday of the given month at midnight."""
    # Find the last day of the month, then walk back to Sunday (weekday=6)
    if month == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(year, month + 1, 1) - timedelta(days=1)

    days_since_sunday = (last_day.weekday() + 1) % 7  # Monday=0, Sunday=6
    return last_day - timedelta(days=days_since_sunday)


def _is_in_spring_forward_gap(naive_dt: datetime) -> bool:
    """Return True if naive_dt falls in the spring-forward gap (02:00-03:00 on transition day).

    Europe/Rome DST spring-forward: last Sunday of March, clocks advance
    from 02:00 CET (UTC+1) to 03:00 CEST (UTC+2). Times 02:00-02:59:59 do not exist.
    """
    if naive_dt.month != 3:
        return False
    transition_day = _find_last_sunday(naive_dt.year, 3)
    if naive_dt.date() != transition_day.date():
        return False
    # Times from 02:00 (inclusive) to 03:00 (exclusive) are non-existent
    return naive_dt.hour == 2


def _is_in_fall_back_overlap(naive_dt: datetime) -> bool:
    """Return True if naive_dt falls in the fall-back overlap (02:00-03:00 on transition day).

    Europe/Rome DST fall-back: last Sunday of October, clocks move
    from 03:00 CEST (UTC+2) back to 02:00 CET (UTC+1). Times 02:00-02:59:59 occur twice.
    """
    if naive_dt.month != 10:
        return False
    transition_day = _find_last_sunday(naive_dt.year, 10)
    if naive_dt.date() != transition_day.date():
        return False
    # Times from 02:00 (inclusive) to 03:00 (exclusive) are ambiguous
    return naive_dt.hour == 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_utc(naive_dt: datetime, tz_name: str = "Europe/Rome") -> datetime:
    """Convert a naive datetime to UTC, raising for DST ambiguity.

    Args:
        naive_dt: a naive (no tzinfo) datetime in the local timezone
        tz_name:  local timezone name (defaults to 'Europe/Rome')

    Returns:
        A tz-aware datetime in UTC

    Raises:
        ValueError: if naive_dt already has tzinfo (must be naive)
        NonExistentTimeError: if naive_dt falls in a spring-forward gap
        AmbiguousTimeError: if naive_dt falls in a fall-back overlap
    """
    if naive_dt.tzinfo is not None:
        raise ValueError(f"to_utc expects a naive datetime; got tzinfo={naive_dt.tzinfo!r}")

    tz = ZoneInfo(tz_name) if tz_name != "Europe/Rome" else _ROME_TZ

    # For Europe/Rome, detect DST transitions explicitly
    if tz_name == "Europe/Rome":
        if _is_in_spring_forward_gap(naive_dt):
            raise NonExistentTimeError(
                f"{naive_dt.isoformat()} does not exist in Europe/Rome "
                "(spring-forward gap: clocks jump from 02:00 CET to 03:00 CEST)"
            )
        if _is_in_fall_back_overlap(naive_dt):
            raise AmbiguousTimeError(
                f"{naive_dt.isoformat()} is ambiguous in Europe/Rome "
                "(fall-back overlap: occurs as both CEST UTC+2 and CET UTC+1)"
            )

    local_dt = naive_dt.replace(tzinfo=tz)
    return local_dt.astimezone(_UTC)


def to_utc_strict(
    naive_dt: datetime,
    tz_name: str = "Europe/Rome",
    fold: int = 0,
) -> tuple[datetime, QcFlag]:
    """Convert a naive datetime to UTC, resolving DST ambiguity deterministically.

    Gap handling: advance naive_dt by 1 hour (post-gap), convert, tag QcFlag.OUT_OF_RANGE.
    Overlap handling: use `fold` parameter (0 = first occurrence, 1 = second occurrence).

    Args:
        naive_dt: a naive datetime in the local timezone
        tz_name:  local timezone name (defaults to 'Europe/Rome')
        fold:     for ambiguous times: 0 = first occurrence (CEST, UTC+2),
                  1 = second occurrence (CET, UTC+1)

    Returns:
        (utc_datetime, QcFlag) where QcFlag is:
          - GOOD         for unambiguous timestamps
          - OUT_OF_RANGE for gap timestamps (timestamp advanced by 1 hour)
    """
    tz = ZoneInfo(tz_name) if tz_name != "Europe/Rome" else _ROME_TZ

    if tz_name == "Europe/Rome":
        if _is_in_spring_forward_gap(naive_dt):
            # Advance by 1 hour to land in the post-gap window
            advanced = naive_dt + timedelta(hours=1)
            local_dt = advanced.replace(tzinfo=tz)
            utc_dt = local_dt.astimezone(_UTC)
            return (utc_dt, QcFlag.OUT_OF_RANGE)

        if _is_in_fall_back_overlap(naive_dt):
            # Use fold to select first (fold=0) or second (fold=1) occurrence
            local_dt = naive_dt.replace(tzinfo=tz, fold=fold)
            utc_dt = local_dt.astimezone(_UTC)
            return (utc_dt, QcFlag.GOOD)

    local_dt = naive_dt.replace(tzinfo=tz)
    utc_dt = local_dt.astimezone(_UTC)
    return (utc_dt, QcFlag.GOOD)
