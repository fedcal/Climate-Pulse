"""WMO variable catalog and Pint-based unit converter (ING-09).

Supports the 7 canonical WMO variables in SI units:
  - air_temperature       -> K
  - relative_humidity     -> %
  - surface_pressure      -> Pa
  - wind_direction        -> degree
  - wind_speed            -> m / s
  - total_precipitation   -> kg m-2  (water equivalent; 1 mm = 1 kg/m²)
  - cloud_cover           -> %

Unit conversion uses pint.UnitRegistry for lossless, round-trip-safe arithmetic.
Silently wrong multiplication factors are a worst-case bug (PITFALL ING-09) —
Pint catches unit mismatches at runtime.

rh_from_dewpoint: derives relative humidity from 2m temperature and dewpoint
temperature (Magnus formula). Used by Plan 04 EcmwfOpenAdapter for ECMWF IFS
which does not publish 2r directly (RESEARCH Q2 resolution).
"""

import math

import pint

# ---------------------------------------------------------------------------
# Unit registry
# ---------------------------------------------------------------------------

UREG = pint.UnitRegistry()

# Custom unit alias: 1 mm of water = 1 kg/m² (water equivalent)
# Pint knows "kilogram / meter**2" but not the mm-water colloquial unit used in
# meteorology. We define it so adapters can pass "mm" and get "kg m-2" back.
UREG.define("mm_water = kg / m**2 = mmw")


# ---------------------------------------------------------------------------
# WMO variable catalog
# ---------------------------------------------------------------------------

WMO_VARIABLES: dict[str, dict] = {
    "air_temperature": {
        "unit_si": "K",
        "physical_range": (180.0, 340.0),  # Kelvin: absolute zero to ~67°C (extreme hot)
        "bufr_codes": ["B12101"],
    },
    "relative_humidity": {
        "unit_si": "%",
        "physical_range": (0.0, 100.0),
        "bufr_codes": ["B13003", "2r"],
    },
    "surface_pressure": {
        "unit_si": "Pa",
        "physical_range": (87000.0, 109000.0),  # Pa: ~870 hPa to ~1090 hPa
        "bufr_codes": ["B10004", "sp"],
    },
    "wind_direction": {
        "unit_si": "degree",
        "physical_range": (0.0, 360.0),
        "bufr_codes": ["B11001", "10wd"],
    },
    "wind_speed": {
        "unit_si": "m / s",
        "physical_range": (0.0, 120.0),  # m/s: up to category-5 hurricane
        "bufr_codes": ["B11002"],
    },
    "total_precipitation": {
        "unit_si": "kg m-2",
        "physical_range": (0.0, 500.0),  # kg/m²: up to extreme flash flood amounts
        "bufr_codes": ["B13011", "tp"],
    },
    "cloud_cover": {
        "unit_si": "%",
        "physical_range": (0.0, 100.0),
        "bufr_codes": ["B20010"],
    },
}

# Pre-build a reverse lookup: bufr_code -> wmo_code (for BUFR-coded feeds)
_BUFR_TO_WMO: dict[str, str] = {}
for _wmo_code, _meta in WMO_VARIABLES.items():
    for _bufr_code in _meta["bufr_codes"]:
        _BUFR_TO_WMO[_bufr_code] = _wmo_code


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def normalize_to_si(wmo_code: str, value: float, unit: str) -> tuple[float, str]:
    """Convert value from the given unit to the SI unit for wmo_code.

    Returns (value_in_si, si_unit_string).
    Conversion is performed by Pint, which tracks units through arithmetic
    to prevent silent precision loss or wrong-unit bugs.

    Args:
        wmo_code: canonical WMO variable code (must be in WMO_VARIABLES)
        value:    numeric value in the source unit
        unit:     Pint-compatible unit string (e.g. 'degC', 'hPa', 'knot')

    Returns:
        tuple of (converted float, target SI unit string)

    Raises:
        KeyError: if wmo_code is not in WMO_VARIABLES
        pint.errors.DimensionalityError: if unit is incompatible with the SI unit
    """
    if wmo_code not in WMO_VARIABLES:
        raise KeyError(f"Unknown WMO variable: '{wmo_code}'; add to WMO_VARIABLES first")

    target_unit = WMO_VARIABLES[wmo_code]["unit_si"]

    # Handle dimensionless percentage: Pint handles '%' as a unit (= 0.01),
    # which breaks the round-trip for relative_humidity where we want 65 -> 65.
    # For percentage-unit variables, treat % as identity: no conversion needed.
    if target_unit == "%" and unit in ("%", "percent"):
        return (float(value), target_unit)

    # For degree (wind direction): no conversion, just return float
    if target_unit == "degree" and unit in ("degree", "degrees", "deg", "°"):
        return (float(value), target_unit)

    # Use UREG.Quantity constructor to handle offset units (degC, degF) correctly.
    # Pint raises OffsetUnitCalculusError if you do `value * UREG('degC')` because
    # degC is a non-multiplicative (offset) unit — see pint docs on non-multiplicative units.
    converted = UREG.Quantity(value, unit).to(target_unit)
    return (float(converted.magnitude), target_unit)


def bufr_to_wmo_code(bufr_code: str) -> str | None:
    """Reverse lookup: BUFR code / ECMWF shortName -> canonical WMO variable code.

    Returns None if the code is not known.
    """
    return _BUFR_TO_WMO.get(bufr_code)


# ---------------------------------------------------------------------------
# rh_from_dewpoint (Magnus formula)
# ---------------------------------------------------------------------------


def rh_from_dewpoint(t2m_kelvin: float, d2m_kelvin: float) -> float:
    """Derive 2m relative humidity (%) from 2m temperature and dewpoint temperature.

    Uses the Magnus formula (August–Roche–Magnus approximation):
        RH = 100 * exp(17.625 * d_c / (243.04 + d_c)) /
                     exp(17.625 * t_c / (243.04 + t_c))

    where t_c and d_c are in °C.

    Output is clamped to [0.0, 100.0] to handle supersaturation from noisy
    GRIB fields (Td > T is physically impossible but occurs in reanalysis grids).

    Used by Plan 04 EcmwfOpenAdapter for the 6th D-10 variable (2m RH) because
    ECMWF IFS oper does not always publish 2r directly.

    Args:
        t2m_kelvin: 2m air temperature in Kelvin
        d2m_kelvin: 2m dewpoint temperature in Kelvin

    Returns:
        Relative humidity percentage, clamped to [0.0, 100.0]
    """
    # Convert Kelvin to Celsius via Pint for correctness
    t_c = (t2m_kelvin * UREG.kelvin).to("degC").magnitude
    d_c = (d2m_kelvin * UREG.kelvin).to("degC").magnitude

    rh = 100.0 * math.exp((17.625 * d_c) / (243.04 + d_c)) / math.exp(
        (17.625 * t_c) / (243.04 + t_c)
    )

    # Clamp to physical range
    return max(0.0, min(100.0, rh))
