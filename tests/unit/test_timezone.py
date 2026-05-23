"""Tests for the timezone helper (Europe/Rome naive -> UTC).

D-26 requires:
  - Explicit DST spring-forward gap test for 2026-03-29 02:30
  - Explicit DST fall-back overlap test for 2026-10-25 02:30
  - hypothesis property test for round-trip UTC preservation
"""

from datetime import datetime, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from climatepulse_core.domain.models import QcFlag
from climatepulse_core.normalize.timezone import (
    AmbiguousTimeError,
    NonExistentTimeError,
    to_utc,
    to_utc_strict,
)


# ---------------------------------------------------------------------------
# Normal conversion
# ---------------------------------------------------------------------------


def test_normal_date_converts_to_utc():
    """A normal summer date in Europe/Rome (CEST = UTC+2) -> UTC."""
    # 14:30 CEST = 12:30 UTC
    result = to_utc(datetime(2026, 6, 15, 14, 30))
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc or str(result.tzinfo) == "UTC"
    assert result.hour == 12
    assert result.minute == 30


def test_winter_date_converts_to_utc():
    """A normal winter date in Europe/Rome (CET = UTC+1) -> UTC."""
    # 14:30 CET = 13:30 UTC
    result = to_utc(datetime(2026, 1, 15, 14, 30))
    assert result.hour == 13
    assert result.minute == 30


# ---------------------------------------------------------------------------
# DST edge cases (D-26 explicit)
# ---------------------------------------------------------------------------


def test_dst_spring_forward_gap_raises():
    """2026-03-29 02:30 is in the spring-forward gap — raises NonExistentTimeError (D-26)."""
    with pytest.raises(NonExistentTimeError):
        to_utc(datetime(2026, 3, 29, 2, 30))


def test_dst_fall_back_overlap_raises():
    """2026-10-25 02:30 is in the fall-back overlap — raises AmbiguousTimeError (D-26)."""
    with pytest.raises(AmbiguousTimeError):
        to_utc(datetime(2026, 10, 25, 2, 30))


# ---------------------------------------------------------------------------
# to_utc_strict
# ---------------------------------------------------------------------------


def test_to_utc_strict_gap_advances():
    """Spring-forward gap: advance by 1 hour, return QcFlag.OUT_OF_RANGE.

    2026-03-29 02:30 CEST gap -> 03:30 CEST = 01:30 UTC + OUT_OF_RANGE.
    """
    result_dt, flag = to_utc_strict(datetime(2026, 3, 29, 2, 30))
    assert result_dt.tzinfo is not None
    assert flag == QcFlag.OUT_OF_RANGE
    # 03:30 CEST (UTC+2) = 01:30 UTC
    assert result_dt.hour == 1
    assert result_dt.minute == 30


def test_to_utc_strict_fold_first():
    """Fall-back overlap with fold=0 returns first occurrence (CEST UTC+2 = 00:30Z)."""
    result_dt, flag = to_utc_strict(datetime(2026, 10, 25, 2, 30), fold=0)
    assert result_dt.tzinfo is not None
    # fold=0 -> first occurrence: CEST (UTC+2) -> 02:30 - 2h = 00:30 UTC
    assert result_dt.hour == 0
    assert result_dt.minute == 30


def test_to_utc_strict_fold_second():
    """Fall-back overlap with fold=1 returns second occurrence (CET UTC+1 = 01:30Z)."""
    result_dt, flag = to_utc_strict(datetime(2026, 10, 25, 2, 30), fold=1)
    assert result_dt.tzinfo is not None
    # fold=1 -> second occurrence: CET (UTC+1) -> 02:30 - 1h = 01:30 UTC
    assert result_dt.hour == 1
    assert result_dt.minute == 30


def test_to_utc_strict_normal_is_good():
    """Normal (non-ambiguous) timestamp returns (utc_dt, QcFlag.GOOD)."""
    result_dt, flag = to_utc_strict(datetime(2026, 6, 15, 14, 30))
    assert result_dt.tzinfo is not None
    assert flag == QcFlag.GOOD


# ---------------------------------------------------------------------------
# Hypothesis property test (D-26)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2027, 12, 31),
    )
)
def test_roundtrip_property(naive_dt: datetime):
    """For any naive datetime (outside DST transition windows), to_utc_strict
    returns a UTC datetime with UTC tzinfo.

    The hypothesis engine will generate many datetimes; we use assume() to skip
    the two 2-hour transition windows each year to avoid NonExistentTimeError /
    AmbiguousTimeError cases, which are tested explicitly above.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Rome")

    # Skip datetimes that fall in any spring-forward 02:00-03:00 window
    # (last Sunday of March) or fall-back 02:00-03:00 window (last Sunday Oct)
    # We do a simple check: skip any 02:xx naive datetime in March or October
    # to be conservative (some of those hours are safe, but we skip all to
    # keep the test clean).
    if naive_dt.month in (3, 10) and naive_dt.hour == 2:
        assume(False)

    result_dt, flag = to_utc_strict(naive_dt)

    # Result must be UTC
    assert result_dt.tzinfo is not None

    # For non-gap datetimes, flag should be GOOD (no QC degradation)
    if flag == QcFlag.GOOD:
        # Round-trip: UTC -> Europe/Rome naive -> UTC must give same instant
        rome_dt = result_dt.astimezone(tz)
        naive_back = rome_dt.replace(tzinfo=None)
        back_utc, _ = to_utc_strict(naive_back, fold=rome_dt.fold)
        # Allow 1-second tolerance for edge cases near DST boundaries
        diff = abs((back_utc - result_dt).total_seconds())
        assert diff < 1, (
            f"Round-trip mismatch: {naive_dt} -> {result_dt} -> {naive_back} -> {back_utc}"
        )
