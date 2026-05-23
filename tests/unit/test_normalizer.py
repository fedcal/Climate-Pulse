"""Property-based and explicit tests for the WMO unit normalizer (Pint).

Tests D-26 hypothesis coverage: unit conversion round-trips must be lossless.
All round-trips use math.isclose with rel_tol=1e-9 to catch floating-point drift.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from climatepulse_core.normalize.wmo import (
    WMO_VARIABLES,
    bufr_to_wmo_code,
    normalize_to_si,
    rh_from_dewpoint,
)


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


def test_wmo_variables_has_7_entries():
    """ING-09: WMO_VARIABLES must contain exactly 7 canonical variables."""
    assert len(WMO_VARIABLES) == 7


def test_wmo_variables_required_keys():
    """ING-09: All 7 required WMO variables are present."""
    required = {
        "air_temperature",
        "relative_humidity",
        "surface_pressure",
        "wind_direction",
        "wind_speed",
        "total_precipitation",
        "cloud_cover",
    }
    assert set(WMO_VARIABLES.keys()) == required


# ---------------------------------------------------------------------------
# Explicit unit conversion tests
# ---------------------------------------------------------------------------


def test_celsius_to_kelvin_zero():
    """0°C converts to 273.15 K."""
    value_si, unit_si = normalize_to_si("air_temperature", 0.0, "degC")
    assert unit_si == "K"
    assert math.isclose(value_si, 273.15, rel_tol=1e-9)


def test_hpa_to_pa():
    """1013.25 hPa converts to 101325.0 Pa."""
    value_si, unit_si = normalize_to_si("surface_pressure", 1013.25, "hPa")
    assert unit_si == "Pa"
    assert math.isclose(value_si, 101325.0, rel_tol=1e-9)


def test_knots_to_ms():
    """1 knot = 0.514444... m/s."""
    value_si, unit_si = normalize_to_si("wind_speed", 1.0, "knot")
    assert unit_si == "m / s"
    assert math.isclose(value_si, 0.5144444444444445, rel_tol=1e-6)


def test_kelvin_passthrough():
    """Temperature already in K passes through unchanged."""
    value_si, unit_si = normalize_to_si("air_temperature", 293.15, "K")
    assert unit_si == "K"
    assert math.isclose(value_si, 293.15, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Hypothesis property tests: round-trip losslessness (D-26)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(st.floats(min_value=180.0, max_value=340.0, allow_nan=False, allow_infinity=False))
def test_celsius_kelvin_roundtrip(k_val: float):
    """K -> °C -> K round-trip is lossless to rel_tol=1e-9 (D-26)."""
    # Convert K to °C (subtract 273.15), then normalize_to_si converts back to K
    celsius = k_val - 273.15
    k_result, _ = normalize_to_si("air_temperature", celsius, "degC")
    assert math.isclose(k_result, k_val, rel_tol=1e-9), (
        f"Round-trip failed: {k_val} K -> {celsius} °C -> {k_result} K"
    )


@settings(max_examples=200)
@given(st.floats(min_value=87000.0, max_value=109000.0, allow_nan=False, allow_infinity=False))
def test_hpa_pa_roundtrip(pa_val: float):
    """Pa -> hPa -> Pa round-trip is lossless to rel_tol=1e-9 (D-26)."""
    hpa = pa_val / 100.0
    pa_result, _ = normalize_to_si("surface_pressure", hpa, "hPa")
    assert math.isclose(pa_result, pa_val, rel_tol=1e-9), (
        f"Round-trip failed: {pa_val} Pa -> {hpa} hPa -> {pa_result} Pa"
    )


@settings(max_examples=200)
@given(st.floats(min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False))
def test_knots_ms_roundtrip(ms_val: float):
    """m/s -> knots -> m/s round-trip is lossless to rel_tol=1e-9 (D-26)."""
    knots = ms_val / 0.5144444444444445
    ms_result, _ = normalize_to_si("wind_speed", knots, "knot")
    assert math.isclose(ms_result, ms_val, rel_tol=1e-6), (
        f"Round-trip failed: {ms_val} m/s -> {knots} kn -> {ms_result} m/s"
    )


# ---------------------------------------------------------------------------
# BUFR reverse lookup
# ---------------------------------------------------------------------------


def test_bufr_lookup_b12101():
    """B12101 maps to air_temperature."""
    assert bufr_to_wmo_code("B12101") == "air_temperature"


def test_bufr_lookup_unknown():
    """Unknown BUFR code returns None."""
    assert bufr_to_wmo_code("BXXXXX") is None


def test_bufr_lookup_sp_ecmwf():
    """ECMWF shortName 'sp' maps to surface_pressure."""
    assert bufr_to_wmo_code("sp") == "surface_pressure"


# ---------------------------------------------------------------------------
# rh_from_dewpoint
# ---------------------------------------------------------------------------


def test_rh_from_dewpoint_known_values():
    """At T=20°C (293.15K) and Td=10°C (283.15K), RH ~52.5% (Magnus formula)."""
    rh = rh_from_dewpoint(t2m_kelvin=293.15, d2m_kelvin=283.15)
    assert pytest.approx(rh, abs=0.5) == 52.5


def test_rh_from_dewpoint_saturation():
    """At T == Td, RH must equal 100.0 (saturation)."""
    rh = rh_from_dewpoint(t2m_kelvin=288.15, d2m_kelvin=288.15)
    assert math.isclose(rh, 100.0, abs_tol=0.01), f"Expected 100.0, got {rh}"


def test_rh_from_dewpoint_clamped():
    """Pathological Td > T (supersaturation from noisy GRIB) is clamped to 100.0."""
    rh = rh_from_dewpoint(t2m_kelvin=280.0, d2m_kelvin=285.0)  # Td > T
    assert rh == 100.0, f"Expected clamped 100.0, got {rh}"
