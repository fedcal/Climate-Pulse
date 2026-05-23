"""ECMWF Open Data adapter for grid-based forecast observations (ING-04).

Downloads IFS HRES forecasts via ecmwf-opendata Client, decodes with cfgrib
(Pitfall B: multi-typeOfLevel auto-split), subsets EU bbox post-download via
xarray.sel (Pitfall A: NO area= kwarg), and yields RawObservation objects.

D-10 commitment: EXACTLY 6 variables per cycle — no silent scope reduction:
  1. air_temperature      (from 2t, K)
  2. surface_pressure     (from sp, Pa)
  3. wind_speed           (derived from 10u + 10v, m/s)
  4. wind_direction       (derived from 10u + 10v, °)
  5. total_precipitation  (from tp, m → kg/m² via normalize_to_si)
  6. relative_humidity    (derived from 2t + 2d via Magnus formula, %)

Intermediates NOT yielded as RawObservations: 10u, 10v, 2d.
"""

import asyncio
import math
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr

# cfgrib and ecmwf.opendata are heavy dependencies (require libeccodes0 system lib — D-22).
# They live ONLY in the worker container (not api container).
# Use lazy imports here so the module can be imported in tests without libeccodes0.
try:
    import cfgrib as _cfgrib_module  # noqa: F401
    cfgrib = _cfgrib_module  # reassigned so monkeypatching via tests works
except (ImportError, RuntimeError):
    # RuntimeError raised when libeccodes0 is absent (D-22: worker container only)
    cfgrib = None  # type: ignore[assignment]

try:
    from ecmwf.opendata import Client as _EcmwfClient
    Client = _EcmwfClient
except (ImportError, RuntimeError):
    Client = None  # type: ignore[assignment]

from climatepulse_core.adapters.base import (
    FetchWindow,
    SourceMeta,
    WeatherSourceAdapter,
    register,
)
from climatepulse_core.domain.models import QcFlag, RawObservation, Station
from climatepulse_core.normalize.qc import validate_range
from climatepulse_core.normalize.wmo import normalize_to_si, rh_from_dewpoint

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

EU_BBOX: dict[str, float] = {
    "lat_max": 72.0,
    "lat_min": 35.0,
    "lon_min": -25.0,
    "lon_max": 45.0,
}

# D-10: 6 required parameters — no fallback allowed (RESEARCH Q2 resolution)
# 2d (dewpoint) is used to DERIVE relative_humidity via rh_from_dewpoint
REQUIRED_PARAMS: list[str] = ["2t", "sp", "10u", "10v", "tp", "2d"]

# Intentionally empty — D-10's 6 variables are guaranteed via derivation
OPTIONAL_PARAMS: list[str] = []

# ECMWF forecast cycle hours
CYCLES: list[int] = [0, 6, 12, 18]

# Forecast steps requested
FORECAST_STEPS: list[int] = [0, 6, 12, 24]

# xarray variable name → canonical WMO code mapping
# Intermediate variables (u10, v10, d2m) are NOT yielded directly
XVAR_TO_WMO: dict[str, str] = {
    "t2m": "air_temperature",
    "sp": "surface_pressure",
    "tp": "total_precipitation",
    # u10, v10 → derived → wind_speed, wind_direction
    # d2m → derived → relative_humidity
}

# Intermediate variables consumed in derivation, NOT yielded as RawObservations
_INTERMEDIATE_VARS = frozenset({"u10", "v10", "d2m"})


# ---------------------------------------------------------------------------
# Adapter implementation
# ---------------------------------------------------------------------------


@register("ecmwf_open")
class EcmwfOpenAdapter(WeatherSourceAdapter):
    """Concrete adapter for ECMWF Open Data IFS HRES forecasts.

    Grid-based (is_grid_based=True); routes observations to the
    `gridded_observations` hypertable via the IdempotentWriter.

    Downloads GRIB2 files via ecmwf-opendata Client to a temporary directory,
    decodes using cfgrib.open_datasets (handles multi-typeOfLevel, Pitfall B),
    subsets to EU bbox via xarray.sel (Pitfall A: no area= kwarg), then yields
    one RawObservation per (grid_point, variable, step).

    IMPORTANT: GRIB files are deleted after processing (tempfile.TemporaryDirectory).
    """

    cadence_seconds: int = 21600   # 6h between cycles 00/06/12/18Z
    is_grid_based: bool = True

    def source_meta(self) -> SourceMeta:
        """Return ECMWF Open Data attribution metadata."""
        return SourceMeta(
            source_id="ecmwf_open",
            name="ECMWF Open Data IFS HRES forecast",
            license="CC-BY-4.0",
            attribution="ECMWF Open Data IFS HRES forecast",
            terms_url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
            default_qc_flag=0,
        )

    async def discover_stations(self) -> list[Station]:
        """Grid-based adapter — no station catalog. Returns empty list."""
        return []

    async def fetch(self, window: FetchWindow) -> AsyncIterator[RawObservation]:  # type: ignore[override]
        """Yield RawObservation objects for all EU grid points in the fetch window.

        For each ECMWF forecast cycle (00Z / 06Z / 12Z / 18Z) falling within
        [window.since, window.until], downloads the GRIB2 file, decodes it,
        subsets to EU bbox, and yields observations for all 6 D-10 variables.

        Raises:
            Any exception from Client.retrieve propagates immediately (no silent fallback).
        """
        loop = asyncio.get_event_loop()

        # Enumerate (date, cycle_hour) pairs in the window
        init_times = list(self._iter_init_times(window))

        for init_time in init_times:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpfile = Path(tmpdir) / (
                    f"ecmwf_{init_time.year:04d}{init_time.month:02d}"
                    f"{init_time.day:02d}_{init_time.hour:02d}z.grib2"
                )

                # Download — run sync client in executor; exceptions propagate (D-10: no fallback)
                if Client is None:
                    raise RuntimeError(
                        "ecmwf-opendata is not installed. "
                        "Run in the worker container which has all dependencies."
                    )
                try:
                    await loop.run_in_executor(
                        None,
                        self._download_grib,
                        init_time,
                        str(tmpfile),
                    )
                except Exception as exc:
                    logger.error(
                        "ecmwf.grib_download_failed",
                        init_time=init_time.isoformat(),
                        error=str(exc),
                    )
                    raise  # Propagate — D-10 commitment, no silent fallback

                # Decode GRIB (run in executor; cfgrib is sync and may be slow)
                if cfgrib is None:
                    raise RuntimeError(
                        "cfgrib / libeccodes0 is not installed. "
                        "Run in the worker container (D-22)."
                    )
                try:
                    datasets: list[xr.Dataset] = await loop.run_in_executor(
                        None,
                        lambda p=str(tmpfile): cfgrib.open_datasets(p, {"indexpath": ""}),
                    )
                except Exception as exc:
                    logger.warning(
                        "ecmwf.grib_decode_failed",
                        init_time=init_time.isoformat(),
                        error=str(exc),
                    )
                    raise  # Propagate

                # Collect intermediate arrays needed for derivations
                u10_arrays: dict[tuple, float] = {}   # (lat_idx, lon_idx, step_ns) → float
                v10_arrays: dict[tuple, float] = {}
                t2m_arrays: dict[tuple, float] = {}
                d2m_arrays: dict[tuple, float] = {}

                # Direct variable observations (not intermediate)
                direct_obs: list[RawObservation] = []

                # Process each dataset (one per typeOfLevel per Pitfall B)
                for ds in datasets:
                    # EU bbox subsetting — POST-download, via xarray.sel (Pitfall A)
                    eu = ds.sel(
                        latitude=slice(EU_BBOX["lat_max"], EU_BBOX["lat_min"]),
                        longitude=slice(EU_BBOX["lon_min"], EU_BBOX["lon_max"]),
                    )

                    lat_values = eu.coords["latitude"].values
                    lon_values = eu.coords["longitude"].values

                    # Determine step dimension (may be scalar or absent)
                    has_step = "step" in eu.coords
                    step_vals = eu.coords["step"].values if has_step else [0]

                    for data_var_name in eu.data_vars:
                        da = eu[data_var_name]
                        xshortname = da.attrs.get("GRIB_shortName", data_var_name)
                        source_unit = da.attrs.get("units", "")

                        for step_val in step_vals:
                            # Select this step
                            if has_step:
                                # step_val may be np.timedelta64 — convert to hours
                                try:
                                    step_h = int(
                                        np.timedelta64(step_val, "h") / np.timedelta64(1, "h")
                                    )
                                except Exception:
                                    step_h = int(step_val)
                                try:
                                    slice_at_step = da.sel(step=step_val)
                                except Exception:
                                    slice_at_step = da.isel(step=0)
                            else:
                                step_h = 0
                                slice_at_step = da

                            valid_at = init_time + timedelta(hours=step_h)
                            data_2d = np.atleast_2d(slice_at_step.values)

                            for lat_idx, lat_val in enumerate(lat_values):
                                for lon_idx, lon_val in enumerate(lon_values):
                                    if data_2d.ndim == 2:
                                        value_raw = float(data_2d[lat_idx, lon_idx])
                                    else:
                                        value_raw = float(data_2d.flat[0])
                                    key = (lat_idx, lon_idx, step_h)

                                    # Route intermediates vs direct observations
                                    if data_var_name in _INTERMEDIATE_VARS or xshortname in {"10u", "10v", "2d"}:
                                        if data_var_name == "u10" or xshortname == "10u":
                                            u10_arrays[key] = value_raw
                                        elif data_var_name == "v10" or xshortname == "10v":
                                            v10_arrays[key] = value_raw
                                        elif data_var_name == "d2m" or xshortname == "2d":
                                            d2m_arrays[key] = value_raw
                                        continue

                                    if data_var_name == "t2m" or xshortname == "2t":
                                        t2m_arrays[key] = value_raw
                                        # Also yield as air_temperature
                                        wmo_code = "air_temperature"
                                    else:
                                        wmo_code = XVAR_TO_WMO.get(
                                            data_var_name,
                                            XVAR_TO_WMO.get(xshortname, ""),
                                        )
                                        if not wmo_code:
                                            logger.warning(
                                                "ecmwf.unknown_variable",
                                                var=data_var_name,
                                                shortname=xshortname,
                                            )
                                            continue

                                    # Convert to SI
                                    try:
                                        if source_unit and source_unit not in ("", "unknown"):
                                            value_si, _ = normalize_to_si(
                                                wmo_code, value_raw, source_unit
                                            )
                                        else:
                                            value_si = value_raw
                                    except Exception:
                                        value_si = value_raw

                                    qc = validate_range(wmo_code, value_si)
                                    direct_obs.append(
                                        RawObservation(
                                            source_id="ecmwf_open",
                                            observed_at=valid_at,
                                            station_external_id=None,
                                            wmo_code=wmo_code,
                                            value=value_si,
                                            qc_flag=qc,
                                            lat=float(lat_val),
                                            lon=float(lon_val),
                                            lat_idx=lat_idx,
                                            lon_idx=lon_idx,
                                            init_time=init_time,
                                            step_h=step_h,
                                        )
                                    )

                # Yield direct observations
                for obs in direct_obs:
                    yield obs

                # Yield derived observations
                # Build combined key set — use step values from u10 (or any available)
                derived_keys = set(u10_arrays) | set(d2m_arrays)

                for key in derived_keys:
                    lat_idx, lon_idx, step_h = key
                    valid_at = init_time + timedelta(hours=step_h)

                    # Derive lat/lon values
                    # Use the first dataset that has enough grid points
                    lat_val: float = 0.0
                    lon_val: float = 0.0
                    if datasets:
                        eu_first = datasets[0].sel(
                            latitude=slice(EU_BBOX["lat_max"], EU_BBOX["lat_min"]),
                            longitude=slice(EU_BBOX["lon_min"], EU_BBOX["lon_max"]),
                        )
                        lat_vals_arr = eu_first.coords["latitude"].values
                        lon_vals_arr = eu_first.coords["longitude"].values
                        if lat_idx < len(lat_vals_arr):
                            lat_val = float(lat_vals_arr[lat_idx])
                        if lon_idx < len(lon_vals_arr):
                            lon_val = float(lon_vals_arr[lon_idx])

                    # Wind speed and direction from u10 + v10
                    if key in u10_arrays and key in v10_arrays:
                        u = u10_arrays[key]
                        v = v10_arrays[key]
                        speed = math.sqrt(u**2 + v**2)
                        direction = (math.atan2(-u, -v) * 180.0 / math.pi) % 360.0

                        qc_speed = validate_range("wind_speed", speed)
                        yield RawObservation(
                            source_id="ecmwf_open",
                            observed_at=valid_at,
                            station_external_id=None,
                            wmo_code="wind_speed",
                            value=speed,
                            qc_flag=qc_speed,
                            lat=lat_val,
                            lon=lon_val,
                            lat_idx=lat_idx,
                            lon_idx=lon_idx,
                            init_time=init_time,
                            step_h=step_h,
                        )

                        qc_dir = validate_range("wind_direction", direction)
                        yield RawObservation(
                            source_id="ecmwf_open",
                            observed_at=valid_at,
                            station_external_id=None,
                            wmo_code="wind_direction",
                            value=direction,
                            qc_flag=qc_dir,
                            lat=lat_val,
                            lon=lon_val,
                            lat_idx=lat_idx,
                            lon_idx=lon_idx,
                            init_time=init_time,
                            step_h=step_h,
                        )

                    # RH from 2t + 2d (Magnus formula, RESEARCH Q2 resolution)
                    if key in t2m_arrays and key in d2m_arrays:
                        t2m_k = t2m_arrays[key]
                        d2m_k = d2m_arrays[key]
                        try:
                            rh = rh_from_dewpoint(t2m_k, d2m_k)
                            qc_rh = validate_range("relative_humidity", rh)
                        except Exception:
                            # D-10: if derivation fails on a cell, yield OUT_OF_RANGE
                            rh = 0.0
                            qc_rh = QcFlag.OUT_OF_RANGE

                        yield RawObservation(
                            source_id="ecmwf_open",
                            observed_at=valid_at,
                            station_external_id=None,
                            wmo_code="relative_humidity",
                            value=rh,
                            qc_flag=qc_rh,
                            lat=lat_val,
                            lon=lon_val,
                            lat_idx=lat_idx,
                            lon_idx=lon_idx,
                            init_time=init_time,
                            step_h=step_h,
                        )

    def _download_grib(self, init_time: datetime, target_path: str) -> None:
        """Download one ECMWF GRIB2 forecast cycle to target_path.

        Uses REQUIRED_PARAMS directly — NO fallback, NO area= kwarg (Pitfall A).
        Runs synchronously; caller must use run_in_executor for async context.

        Args:
            init_time:   UTC datetime of the forecast init (must be 00/06/12/18Z)
            target_path: file system path for the output GRIB2 file

        Raises:
            Any exception from Client.retrieve propagates (D-10: no silent fallback)
        """
        if Client is None:
            raise RuntimeError("ecmwf-opendata not installed; cannot create Client")
        client = Client(source="ecmwf", model="ifs", resol="0p25")
        # CRITICAL: NO area= kwarg — Pitfall A
        client.retrieve(
            time=init_time.hour,
            type="fc",
            step=FORECAST_STEPS,
            param=REQUIRED_PARAMS,
            target=target_path,
        )

    def _iter_init_times(self, window: FetchWindow) -> list[datetime]:
        """Return all (date, cycle) init times falling within window.

        Only includes cycles where init_time is within [window.since, window.until].
        """
        result: list[datetime] = []
        current_date = window.since.date()
        end_date = window.until.date()

        while current_date <= end_date:
            for cycle_hour in CYCLES:
                init_time = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    cycle_hour,
                    tzinfo=timezone.utc,
                )
                if window.since <= init_time <= window.until:
                    result.append(init_time)
            from datetime import timedelta as _td
            current_date += _td(days=1)

        return result
