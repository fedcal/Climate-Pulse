"""Unit tests for EcmwfOpenAdapter (ING-04, D-10, Pitfall A + B).

All tests run WITHOUT actually calling ECMWF or downloading GRIB files.
Client.retrieve and cfgrib.open_datasets are always mocked/monkeypatched.

Key assertions:
- test_ecmwf_six_variables: exactly 6 wmo_codes per cycle (D-10 commitment)
- test_rh_derived_from_dewpoint_correct_value: Magnus formula accuracy
- test_no_fallback_on_missing_param: no silent 5-variable fallback
- test_no_area_kwarg_used: Pitfall A compliance
- test_eu_bbox_applied_post_download: Pitfall A correct approach
- test_wind_uv_derives_speed_and_direction: u/v → speed/direction derivation
"""

import math
from datetime import date, datetime, time, timezone
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
import xarray as xr

from climatepulse_core.adapters.base import FetchWindow, get_adapter
from climatepulse_core.adapters.ecmwf_open import (
    EU_BBOX,
    REQUIRED_PARAMS,
    EcmwfOpenAdapter,
)
from climatepulse_core.domain.models import QcFlag, RawObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_window(since_date: date = date(2026, 5, 23)) -> FetchWindow:
    """Build a one-day FetchWindow for a single cycle."""
    since = datetime.combine(since_date, time.min, tzinfo=timezone.utc)
    until = datetime.combine(since_date, time(hour=12), tzinfo=timezone.utc)
    return FetchWindow(since=since, until=until)


def _make_adapter() -> EcmwfOpenAdapter:
    return EcmwfOpenAdapter()


def _make_synthetic_dataset(
    lats: list[float] | None = None,
    lons: list[float] | None = None,
    t2m: float = 293.15,
    d2m: float = 283.15,
    sp: float = 101325.0,
    u10: float = 3.0,
    v10: float = 4.0,
    tp: float = 0.001,
    include_step: bool = True,
) -> list[xr.Dataset]:
    """Return a list of synthetic xarray Datasets simulating cfgrib.open_datasets output.

    Creates 2 datasets mimicking the multi-typeOfLevel split (Pitfall B):
    - Dataset 1: heightAboveGround=2 variables (t2m, d2m, sp)
    - Dataset 2: heightAboveGround=10 variables (u10, v10, tp)
    """
    if lats is None:
        lats = [36.0, 36.25]
    if lons is None:
        lons = [-24.75, -24.5]

    lat_arr = np.array(lats, dtype="float32")
    lon_arr = np.array(lons, dtype="float32")
    nlat, nlon = len(lats), len(lons)

    coords: dict = {
        "latitude": ("latitude", lat_arr),
        "longitude": ("longitude", lon_arr),
    }
    if include_step:
        coords["step"] = ("step", np.array([0], dtype="int64"))

    def make_data(val: float) -> np.ndarray:
        return np.full((1, nlat, nlon), val, dtype="float64") if include_step else np.full((nlat, nlon), val, dtype="float64")

    def make_2d(val: float) -> np.ndarray:
        return np.full((nlat, nlon), val, dtype="float64")

    if include_step:
        shape_coords = ["step", "latitude", "longitude"]
    else:
        shape_coords = ["latitude", "longitude"]

    # Dataset 1: 2m temperature, dewpoint, surface pressure
    ds1_vars = {
        "t2m": xr.Variable(
            shape_coords,
            make_data(t2m),
            attrs={"units": "K", "GRIB_shortName": "2t"},
        ),
        "d2m": xr.Variable(
            shape_coords,
            make_data(d2m),
            attrs={"units": "K", "GRIB_shortName": "2d"},
        ),
        "sp": xr.Variable(
            shape_coords,
            make_data(sp),
            attrs={"units": "Pa", "GRIB_shortName": "sp"},
        ),
    }

    # Dataset 2: 10m wind, total precipitation
    ds2_vars = {
        "u10": xr.Variable(
            shape_coords,
            make_data(u10),
            attrs={"units": "m s**-1", "GRIB_shortName": "10u"},
        ),
        "v10": xr.Variable(
            shape_coords,
            make_data(v10),
            attrs={"units": "m s**-1", "GRIB_shortName": "10v"},
        ),
        "tp": xr.Variable(
            shape_coords,
            make_data(tp),
            attrs={"units": "m", "GRIB_shortName": "tp"},
        ),
    }

    ds1 = xr.Dataset(ds1_vars, coords=coords)
    ds2 = xr.Dataset(ds2_vars, coords=coords)
    return [ds1, ds2]


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


def test_source_meta_fields():
    adapter = _make_adapter()
    meta = adapter.source_meta()
    assert meta.source_id == "ecmwf_open"
    assert "ECMWF" in meta.name
    assert "CC-BY" in meta.license or "CC BY" in meta.license
    assert meta.terms_url is not None
    assert "ecmwf.int" in meta.terms_url
    assert meta.default_qc_flag == 0


def test_cadence_is_6h():
    assert EcmwfOpenAdapter.cadence_seconds == 21600


def test_is_grid_based():
    assert EcmwfOpenAdapter.is_grid_based is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_adapter_registered():
    import importlib

    import climatepulse_core.adapters.ecmwf_open

    importlib.reload(climatepulse_core.adapters.ecmwf_open)
    adapter = get_adapter("ecmwf_open")
    assert adapter.__class__.__name__ == "EcmwfOpenAdapter"
    assert adapter.source_id == "ecmwf_open"


# ---------------------------------------------------------------------------
# discover_stations returns empty list (grid-based)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_stations_returns_empty():
    adapter = _make_adapter()
    stations = await adapter.discover_stations()
    assert stations == [], "Grid-based adapter must return empty station list"


# ---------------------------------------------------------------------------
# Pitfall A: NO area= kwarg in Client.retrieve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_area_kwarg_used():
    """Client.retrieve must NOT be called with area= kwarg (Pitfall A)."""
    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            _ = [o async for o in adapter.fetch(window)]

    # Assert retrieve was called and 'area' was NOT in any kwargs
    assert mock_client.retrieve.called, "Client.retrieve must be called"
    for actual_call in mock_client.retrieve.call_args_list:
        assert "area" not in actual_call.kwargs, (
            f"Pitfall A: 'area=' kwarg must NOT be passed to Client.retrieve; "
            f"got call: {actual_call}"
        )


# ---------------------------------------------------------------------------
# EU bbox applied post-download via xarray.sel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eu_bbox_applied_post_download():
    """EU bbox must be applied via .sel() on the xarray Dataset, not via Client.retrieve area=."""
    adapter = _make_adapter()
    window = _make_window()

    # Build a dataset with global-ish coordinates to verify sel is called
    global_lats = [80.0, 50.0, 10.0]  # includes out-of-EU lats
    global_lons = [-30.0, 0.0, 50.0]  # includes out-of-EU lons
    datasets = _make_synthetic_dataset(lats=global_lats, lons=global_lons)

    # Spy: wrap Dataset.sel to track calls
    sel_was_called = []
    original_sel = xr.Dataset.sel

    def spy_sel(self, *args, **kwargs):
        sel_was_called.append(kwargs)
        return original_sel(self, *args, **kwargs)

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            with patch.object(xr.Dataset, "sel", spy_sel):
                _ = [o async for o in adapter.fetch(window)]

    assert len(sel_was_called) > 0, "xarray Dataset.sel must be called for EU bbox subsetting"
    # Verify that sel was called with latitude/longitude slices
    found_bbox_sel = any(
        "latitude" in call_kwargs and "longitude" in call_kwargs
        for call_kwargs in sel_was_called
    )
    assert found_bbox_sel, (
        "EU bbox must be applied via ds.sel(latitude=..., longitude=...) after download"
    )


# ---------------------------------------------------------------------------
# Grid observations have lat/lon/lat_idx/lon_idx populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grid_observations_have_grid_fields():
    """Yielded RawObservation must have lat, lon, lat_idx, lon_idx, init_time, step_h."""
    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    assert len(obs_list) > 0, "Expected at least one grid observation"
    for obs in obs_list:
        assert obs.lat is not None, f"lat must be set for grid obs; got {obs!r}"
        assert obs.lon is not None, f"lon must be set for grid obs; got {obs!r}"
        assert obs.lat_idx is not None, f"lat_idx must be set for grid obs; got {obs!r}"
        assert obs.lon_idx is not None, f"lon_idx must be set for grid obs; got {obs!r}"
        assert obs.init_time is not None, f"init_time must be set for grid obs; got {obs!r}"
        assert obs.step_h is not None, f"step_h must be set for grid obs; got {obs!r}"
        assert obs.station_external_id is None, (
            f"station_external_id must be None for grid obs; got {obs!r}"
        )


# ---------------------------------------------------------------------------
# Exactly 6 variables per cycle — D-10 commitment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ecmwf_six_variables():
    """Exactly 6 canonical wmo_codes must be yielded per fetch cycle (D-10)."""
    expected_wmo_codes = frozenset({
        "air_temperature",
        "surface_pressure",
        "wind_speed",
        "wind_direction",
        "total_precipitation",
        "relative_humidity",
    })

    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    actual_wmo_codes = frozenset(o.wmo_code for o in obs_list)
    assert actual_wmo_codes == expected_wmo_codes, (
        f"D-10: expected exactly {expected_wmo_codes}, got {actual_wmo_codes}"
    )


# ---------------------------------------------------------------------------
# RH derived from dewpoint — Magnus formula accuracy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rh_derived_from_dewpoint_correct_value():
    """RH must be derived from t2m + d2m via Magnus formula (RESEARCH Q2).

    Reference: t2m=293.15 K (20°C), d2m=283.15 K (10°C) → RH ≈ 52.5%
    """
    adapter = _make_adapter()
    window = _make_window()
    # t2m=293.15 K, d2m=283.15 K (10°C dewpoint with 20°C air)
    datasets = _make_synthetic_dataset(t2m=293.15, d2m=283.15)

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    rh_obs = [o for o in obs_list if o.wmo_code == "relative_humidity"]
    assert len(rh_obs) >= 1, "Expected at least one relative_humidity observation"
    rh_val = rh_obs[0].value
    assert abs(rh_val - 52.5) < 1.0, (
        f"RH from Magnus formula for t2m=293.15 K, d2m=283.15 K should be ~52.5%, "
        f"got {rh_val:.2f}%"
    )


# ---------------------------------------------------------------------------
# No silent fallback on missing param (D-10 non-negotiable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_fallback_on_missing_param():
    """If Client.retrieve raises, the adapter must propagate (not silently drop a variable)."""
    adapter = _make_adapter()
    window = _make_window()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Simulate downstream API change that drops a param
        mock_client.retrieve.side_effect = RuntimeError(
            "Parameter '2d' not available in this cycle"
        )

        with pytest.raises((RuntimeError, Exception)):
            _ = [o async for o in adapter.fetch(window)]

    # The adapter must NOT have returned any partial observations
    # (The exception is raised before any yield)


# ---------------------------------------------------------------------------
# Wind u/v → speed/direction derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wind_uv_derives_speed_and_direction():
    """u10=3.0, v10=4.0 → wind_speed≈5.0 m/s, wind_direction≈217°.

    wind_speed = sqrt(u² + v²) = sqrt(9 + 16) = 5.0
    wind_direction = (atan2(-u, -v) * 180/pi) % 360
                   = (atan2(-3, -4) * 180/pi) % 360
                   = (≈ -143.13°) % 360 ≈ 216.87° ≈ 217°
    """
    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset(u10=3.0, v10=4.0)

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    speed_obs = [o for o in obs_list if o.wmo_code == "wind_speed"]
    dir_obs = [o for o in obs_list if o.wmo_code == "wind_direction"]

    assert len(speed_obs) >= 1, "Expected wind_speed observations"
    assert len(dir_obs) >= 1, "Expected wind_direction observations"

    for obs in speed_obs:
        assert abs(obs.value - 5.0) < 0.01, (
            f"wind_speed for u=3, v=4 should be ~5.0 m/s; got {obs.value}"
        )

    expected_dir = (math.atan2(-3.0, -4.0) * 180 / math.pi) % 360
    for obs in dir_obs:
        assert abs(obs.value - expected_dir) < 0.1, (
            f"wind_direction for u=3, v=4 should be ~{expected_dir:.1f}°; got {obs.value:.2f}°"
        )


# ---------------------------------------------------------------------------
# No raw u/v observations yielded (they are intermediate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_uv_not_yielded():
    """u10, v10 are intermediate — must NOT appear as raw RawObservation wmo_codes."""
    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    all_codes = {o.wmo_code for o in obs_list}
    assert "wind_u_component" not in all_codes, "Intermediate u10 must not be yielded"
    assert "wind_v_component" not in all_codes, "Intermediate v10 must not be yielded"
    assert "dewpoint_temperature_intermediate" not in all_codes, (
        "Intermediate d2m must not be yielded"
    )


# ---------------------------------------------------------------------------
# No raw d2m observation yielded (intermediate for RH derivation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_d2m_not_yielded():
    """2d (dewpoint) is intermediate — must NOT appear as wmo_code in output."""
    adapter = _make_adapter()
    window = _make_window()
    datasets = _make_synthetic_dataset()

    with patch("climatepulse_core.adapters.ecmwf_open.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve = MagicMock()

        with patch("climatepulse_core.adapters.ecmwf_open.cfgrib") as mock_cfgrib:
            mock_cfgrib.open_datasets.return_value = datasets

            obs_list: list[RawObservation] = [o async for o in adapter.fetch(window)]

    d2m_codes = {o.wmo_code for o in obs_list if "dewpoint" in o.wmo_code}
    assert len(d2m_codes) == 0, (
        f"d2m (dewpoint) must not be yielded as a raw observation; got {d2m_codes}"
    )


# ---------------------------------------------------------------------------
# REQUIRED_PARAMS must include '2d' and have exactly 6 elements
# ---------------------------------------------------------------------------


def test_required_params_include_2d():
    """REQUIRED_PARAMS must include '2d' for RH derivation (RESEARCH Q2)."""
    assert "2d" in REQUIRED_PARAMS, (
        "REQUIRED_PARAMS must include '2d' for dewpoint-to-RH derivation"
    )


def test_required_params_count_six():
    """REQUIRED_PARAMS must have exactly 6 params (D-10)."""
    assert len(REQUIRED_PARAMS) == 6, (
        f"D-10 requires exactly 6 params; got {len(REQUIRED_PARAMS)}: {REQUIRED_PARAMS}"
    )


def test_eu_bbox_constants():
    """EU_BBOX constants must match research specification."""
    assert EU_BBOX["lat_max"] == 72.0
    assert EU_BBOX["lat_min"] == 35.0
    assert EU_BBOX["lon_min"] == -25.0
    assert EU_BBOX["lon_max"] == 45.0
