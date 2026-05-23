"""Quality control functions for WMO observations.

validate_range: returns QcFlag based on whether a value falls within the
    physical bounds defined in WMO_VARIABLES.

handle_null_value: implements Pitfall C (RESEARCH.md lines 1262-1265) —
    None values from BUFR feeds (e.g. B13011 = null) are stored as (0.0, MISSING)
    rather than being skipped. This keeps the row in the DB (schema integrity)
    while flagging it for downstream consumers.
"""

from climatepulse_core.domain.models import QcFlag
from climatepulse_core.normalize.wmo import WMO_VARIABLES


def validate_range(wmo_code: str, value_si: float | None) -> QcFlag:
    """Return a QcFlag based on the physical plausibility of value_si.

    Args:
        wmo_code:  canonical WMO variable code (must be in WMO_VARIABLES)
        value_si:  value in SI units, or None for missing observations

    Returns:
        QcFlag.MISSING     if value_si is None
        QcFlag.OUT_OF_RANGE if value_si is outside the physical bounds
        QcFlag.GOOD        otherwise

    Raises:
        KeyError: if wmo_code is not in WMO_VARIABLES
    """
    if value_si is None:
        return QcFlag.MISSING

    if wmo_code not in WMO_VARIABLES:
        raise KeyError(f"Unknown WMO variable: '{wmo_code}'")

    lo, hi = WMO_VARIABLES[wmo_code]["physical_range"]
    if value_si < lo or value_si > hi:
        return QcFlag.OUT_OF_RANGE

    return QcFlag.GOOD


def handle_null_value(wmo_code: str, value: float | None) -> tuple[float, QcFlag]:
    """Handle null/None values from BUFR feeds (Pitfall C).

    Per RESEARCH.md lines 1262-1265: BUFR null values (e.g. B13011 = null for
    no rain) must NOT be silently dropped. Instead, insert a sentinel (0.0) with
    QcFlag.MISSING so the row stays in the DB and downstream consumers know data
    was expected but absent.

    For non-None values, applies validate_range to determine the QcFlag.

    Args:
        wmo_code: canonical WMO variable code
        value:    raw value from the adapter, or None if missing in source

    Returns:
        (float_value, QcFlag) where float_value is 0.0 for None inputs
    """
    if value is None:
        return (0.0, QcFlag.MISSING)

    flag = validate_range(wmo_code, value)
    return (float(value), flag)
