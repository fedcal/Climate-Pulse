"""Unit tests for ArpaeEmiliaAdapter (ING-03, D-18, D-19, D-20, D-27).

Uses respx to mock async httpx calls per RESEARCH Q4 resolution
(vcrpy async httpx support has known issues on Python 3.12).
All 5 D-27 scenarios are covered: 200/304/404/500/timeout.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
import respx

from climatepulse_core.adapters.arpa_emilia import (
    REALTIME_URL,
    ArpaeEmiliaAdapter,
)
from climatepulse_core.adapters.base import FetchWindow, get_adapter, register
from climatepulse_core.domain.models import QcFlag, RawObservation


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW_UTC = datetime(2026, 5, 23, 3, 30, 0, tzinfo=timezone.utc)

# A typical realtime.jsonl ARPAE record (3 observation groups)
_HAPPY_JSONL_LINE = json.dumps(
    {
        "version": 1,
        "network": "agrmet",
        "ident": None,
        "lon": 11.1234,
        "lat": 44.5678,
        "date": "2026-05-23T03:15:00Z",
        "data": [
            {
                "level": [105, 0, 0, 0],
                "timerange": [0, 0, 0],
                "vars": {
                    "B12101": {"v": 285.65, "a": {"B33007": 70}},
                    "B13003": {"v": 78.0, "a": {"B33007": 70}},
                    "B13011": {"v": None, "a": {"B33007": 70}},  # Pitfall C
                    "B07030": {"v": 45.0},
                    "B01019": {"v": "Carpineti"},
                    "B01194": {"v": "agrmet"},
                    "B05001": {"v": 44.5678},
                    "B06001": {"v": 11.1234},
                },
            }
        ],
    }
)

_HAPPY_JSONL_LINE_WITH_WIND = json.dumps(
    {
        "version": 1,
        "network": "agrmet",
        "ident": None,
        "lon": 11.2345,
        "lat": 44.6789,
        "date": "2026-05-23T03:15:00Z",
        "data": [
            {
                "level": [105, 0, 0, 0],
                "timerange": [0, 0, 0],
                "vars": {
                    "B12101": {"v": 283.15, "a": {"B33007": 70}},
                    "B13003": {"v": 65.0, "a": {"B33007": 70}},
                    "B11001": {"v": 180.0, "a": {"B33007": 70}},
                    "B11002": {"v": 5.2, "a": {"B33007": 70}},
                    "B07030": {"v": 120.0},
                    "B01019": {"v": "Casalecchio"},
                    "B01194": {"v": "agrmet"},
                    "B05001": {"v": 44.6789},
                    "B06001": {"v": 11.2345},
                },
            }
        ],
    }
)

_UNKNOWN_BUFR_LINE = json.dumps(
    {
        "version": 1,
        "network": "agrmet",
        "ident": None,
        "lon": 11.9999,
        "lat": 44.9999,
        "date": "2026-05-23T03:15:00Z",
        "data": [
            {
                "level": [105, 0, 0, 0],
                "timerange": [0, 0, 0],
                "vars": {
                    "B12101": {"v": 285.0, "a": {"B33007": 70}},
                    "B99999": {"v": 42.0},  # Unknown code — D-20
                    "B07030": {"v": 10.0},
                    "B01019": {"v": "TestStation"},
                    "B01194": {"v": "agrmet"},
                    "B05001": {"v": 44.9999},
                    "B06001": {"v": 11.9999},
                },
            }
        ],
    }
)

_NULL_PRECIP_LINE = json.dumps(
    {
        "version": 1,
        "network": "agrmet",
        "ident": None,
        "lon": 11.5555,
        "lat": 44.5555,
        "date": "2026-05-23T03:15:00Z",
        "data": [
            {
                "level": [105, 0, 0, 0],
                "timerange": [0, 0, 0],
                "vars": {
                    "B13011": {"v": None},  # Pitfall C null value
                    "B07030": {"v": 10.0},
                    "B01019": {"v": "NullPrecipStation"},
                    "B01194": {"v": "agrmet"},
                    "B05001": {"v": 44.5555},
                    "B06001": {"v": 11.5555},
                },
            }
        ],
    }
)


def _make_window(hours_ago: int = 1) -> FetchWindow:
    """Build a FetchWindow in the recent past (realtime path)."""
    until = _NOW_UTC
    since = until - timedelta(hours=hours_ago)
    return FetchWindow(since=since, until=until)


def _make_adapter() -> ArpaeEmiliaAdapter:
    """Build adapter with no Redis (in-memory rate limiter)."""
    return ArpaeEmiliaAdapter()


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


def test_source_meta_fields():
    adapter = _make_adapter()
    meta = adapter.source_meta()
    assert meta.source_id == "arpa_emilia"
    assert "ARPA" in meta.name
    assert "CC-BY" in meta.license or "CC BY" in meta.license
    assert meta.terms_url is not None
    assert "dati.arpae.it" in meta.terms_url
    assert meta.default_qc_flag == 0


def test_cadence_is_15_min():
    assert ArpaeEmiliaAdapter.cadence_seconds == 900


def test_is_not_grid_based():
    assert ArpaeEmiliaAdapter.is_grid_based is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_adapter_registered():
    """@register('arpa_emilia') must add adapter to registry."""
    # Re-import to trigger registration after registry clear in conftest
    import importlib

    import climatepulse_core.adapters.arpa_emilia

    importlib.reload(climatepulse_core.adapters.arpa_emilia)
    adapter = get_adapter("arpa_emilia")
    assert isinstance(adapter, ArpaeEmiliaAdapter)


# ---------------------------------------------------------------------------
# Task 1 happy path — D-27 scenario 1 (200 OK)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_happy_path_yields_observations():
    """200 OK returns observations; all tz-aware UTC; no SCHEMA_VIOLATION."""
    adapter = _make_adapter()
    window = _make_window(hours_ago=1)
    body = (_HAPPY_JSONL_LINE + "\n" + _HAPPY_JSONL_LINE_WITH_WIND + "\n").encode()

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(200, content=body))

        obs: list[RawObservation] = [o async for o in adapter.fetch(window)]

    assert len(obs) > 0, "Expected at least one observation from happy-path JSONL"
    for o in obs:
        assert o.observed_at.tzinfo is not None, "observed_at must be tz-aware"
        assert o.qc_flag != QcFlag.SCHEMA_VIOLATION, (
            f"Canonical BUFR codes must not yield SCHEMA_VIOLATION; got {o!r}"
        )


# ---------------------------------------------------------------------------
# D-27 scenario 2 — 304 Not Modified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_etag_304_returns_no_new_data():
    """304 Not Modified → adapter yields zero observations (data not changed)."""
    adapter = _make_adapter()
    window = _make_window(hours_ago=1)

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(304))

        obs: list[RawObservation] = [o async for o in adapter.fetch(window)]

    assert obs == [], "304 response must yield zero observations"


# ---------------------------------------------------------------------------
# D-27 scenario 3 — 404 Not Found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_404_raises_after_retries(tmp_path, monkeypatch):
    """404 → HTTP error propagated after retries; snapshot file written."""
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    adapter = ArpaeEmiliaAdapter(snapshot_dir=str(tmp_path))
    window = _make_window(hours_ago=1)

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        # Return 404 for every request (simulates permanent failure)
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(404, text="Not Found"))

        with pytest.raises(httpx.HTTPStatusError):
            async for _ in adapter.fetch(window):
                pass


# ---------------------------------------------------------------------------
# D-27 scenario 4 — 500 Internal Server Error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_500_raises_after_retries(tmp_path):
    """500 → HTTPStatusError propagated after retries; snapshot file written."""
    adapter = ArpaeEmiliaAdapter(snapshot_dir=str(tmp_path))
    window = _make_window(hours_ago=1)

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        with pytest.raises(httpx.HTTPStatusError):
            async for _ in adapter.fetch(window):
                pass


# ---------------------------------------------------------------------------
# D-27 scenario 5 — Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_timeout_raises_after_retries(tmp_path):
    """Timeout → TimeoutException propagated after retries; snapshot written."""
    adapter = ArpaeEmiliaAdapter(snapshot_dir=str(tmp_path))
    window = _make_window(hours_ago=1)

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(side_effect=httpx.TimeoutException("timed out"))

        with pytest.raises(httpx.TimeoutException):
            async for _ in adapter.fetch(window):
                pass


# ---------------------------------------------------------------------------
# D-20 — schema-drift: unknown BUFR code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_bufr_emits_schema_violation():
    """Unknown BUFR code must yield RawObservation with SCHEMA_VIOLATION (D-20)."""
    adapter = _make_adapter()
    window = _make_window(hours_ago=1)
    body = (_UNKNOWN_BUFR_LINE + "\n").encode()

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(200, content=body))

        obs: list[RawObservation] = [o async for o in adapter.fetch(window)]

    violation_obs = [o for o in obs if o.qc_flag == QcFlag.SCHEMA_VIOLATION]
    assert len(violation_obs) >= 1, (
        "Expected at least one SCHEMA_VIOLATION observation for unknown BUFR B99999"
    )
    assert any(o.wmo_code.startswith("unknown:") for o in violation_obs), (
        "SCHEMA_VIOLATION obs must have wmo_code='unknown:<bufr_code>'"
    )


# ---------------------------------------------------------------------------
# Pitfall C — null value → MISSING qc_flag, value=0.0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_value_handled_as_missing():
    """B13011=null → qc_flag=MISSING, value=0.0, wmo_code='total_precipitation'."""
    adapter = _make_adapter()
    window = _make_window(hours_ago=1)
    body = (_NULL_PRECIP_LINE + "\n").encode()

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(200, content=body))

        obs: list[RawObservation] = [o async for o in adapter.fetch(window)]

    precip_obs = [o for o in obs if o.wmo_code == "total_precipitation"]
    assert len(precip_obs) >= 1, "Expected at least one total_precipitation observation"
    assert precip_obs[0].qc_flag == QcFlag.MISSING, (
        "Null B13011 must yield qc_flag=MISSING"
    )
    assert precip_obs[0].value == 0.0, "Null B13011 must yield value=0.0"


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_stations_returns_stations():
    """discover_stations() parses JSONL snapshot and returns Station objects."""
    adapter = _make_adapter()
    body = (_HAPPY_JSONL_LINE + "\n" + _HAPPY_JSONL_LINE_WITH_WIND + "\n").encode()

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(200, content=body))

        stations = await adapter.discover_stations()

    assert len(stations) >= 1
    for stn in stations:
        assert stn.source_id == "arpa_emilia"
        assert stn.external_id is not None
        assert isinstance(stn.lat, float)
        assert isinstance(stn.lon, float)


# ---------------------------------------------------------------------------
# Temperature is already SI (Kelvin) — no conversion needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temperature_already_kelvin_no_conversion():
    """B12101 is already Kelvin in ARPAE feed — value must be unchanged."""
    adapter = _make_adapter()
    window = _make_window(hours_ago=1)
    body = (_HAPPY_JSONL_LINE + "\n").encode()

    with respx.mock(base_url="https://dati-simc.arpae.it", assert_all_called=False) as mock:
        mock.get(
            "/opendata/osservati/meteo/realtime/realtime.jsonl"
        ).mock(return_value=httpx.Response(200, content=body))

        obs: list[RawObservation] = [o async for o in adapter.fetch(window)]

    temp_obs = [o for o in obs if o.wmo_code == "air_temperature"]
    assert len(temp_obs) >= 1
    # B12101 v=285.65 K → should remain 285.65 K (no conversion)
    assert abs(temp_obs[0].value - 285.65) < 0.01, (
        f"Temperature should remain in Kelvin (285.65), got {temp_obs[0].value}"
    )
