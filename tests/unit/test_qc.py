"""Tests for QC range validation and null-value handling."""

import pytest

from climatepulse_core.domain.models import QcFlag
from climatepulse_core.normalize.qc import handle_null_value, validate_range


# ---------------------------------------------------------------------------
# validate_range tests
# ---------------------------------------------------------------------------


def test_out_of_range_temperature_high():
    """500 K is above the physical range for air temperature -> OUT_OF_RANGE."""
    assert validate_range("air_temperature", 500.0) == QcFlag.OUT_OF_RANGE


def test_out_of_range_temperature_low():
    """100 K is below the physical minimum for air temperature -> OUT_OF_RANGE."""
    assert validate_range("air_temperature", 100.0) == QcFlag.OUT_OF_RANGE


def test_good_temperature():
    """285 K is within the valid physical range -> GOOD."""
    assert validate_range("air_temperature", 285.0) == QcFlag.GOOD


def test_out_of_range_humidity():
    """110% relative humidity is outside the physical range -> OUT_OF_RANGE."""
    assert validate_range("relative_humidity", 110.0) == QcFlag.OUT_OF_RANGE


def test_good_humidity():
    """65% relative humidity is within range -> GOOD."""
    assert validate_range("relative_humidity", 65.0) == QcFlag.GOOD


def test_out_of_range_pressure_high():
    """150000 Pa is above the surface pressure range -> OUT_OF_RANGE."""
    assert validate_range("surface_pressure", 150000.0) == QcFlag.OUT_OF_RANGE


def test_missing_value():
    """None input returns QcFlag.MISSING."""
    assert validate_range("air_temperature", None) == QcFlag.MISSING  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# handle_null_value tests (Pitfall C)
# ---------------------------------------------------------------------------


def test_handle_null_value_none():
    """None value returns (0.0, QcFlag.MISSING) per Pitfall C."""
    value, flag = handle_null_value("total_precipitation", None)
    assert value == 0.0
    assert flag == QcFlag.MISSING


def test_handle_null_value_in_range():
    """Non-None in-range value returns (value, GOOD)."""
    value, flag = handle_null_value("air_temperature", 293.15)
    assert value == 293.15
    assert flag == QcFlag.GOOD


def test_handle_null_value_out_of_range():
    """Non-None out-of-range value returns (value, OUT_OF_RANGE)."""
    value, flag = handle_null_value("air_temperature", 500.0)
    assert value == 500.0
    assert flag == QcFlag.OUT_OF_RANGE
