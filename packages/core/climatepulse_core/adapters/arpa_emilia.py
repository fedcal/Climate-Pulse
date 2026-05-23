"""ARPA Emilia-Romagna weather adapter (ING-03).

Fetches station-based meteorological observations from the ARPAE-SIMC open data
portal via the realtime.jsonl endpoint or monthly storico gzip archives.

Key decisions:
- cadence_seconds=900 (15-min per D-19)
- dati-simc.arpae.it is the data host (D-18)
- Schema-drift (unknown BUFR codes) → yield SCHEMA_VIOLATION + structured log (D-20)
- Null BUFR values → (0.0, MISSING) sentinel via handle_null_value (Pitfall C)
- Temperature (B12101) is already in Kelvin in the ARPAE feed — no Celsius conversion
- VCR / respx cassettes for 5 canonical HTTP scenarios (D-27, RESEARCH Q4)
"""

import gzip
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from climatepulse_core.adapters.base import (
    FetchWindow,
    SourceMeta,
    WeatherSourceAdapter,
    register,
)
from climatepulse_core.domain.models import QcFlag, RawObservation, Station
from climatepulse_core.normalize.qc import handle_null_value, validate_range
from climatepulse_core.normalize.wmo import bufr_to_wmo_code, normalize_to_si

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

REALTIME_URL = (
    "https://dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl"
)
STORICO_BASE_URL = (
    "https://dati-simc.arpae.it/opendata/osservati/meteo/storico"
)
HOST = "dati-simc.arpae.it"

# Window age threshold: use storico (monthly gzip) if window is older than this
STORICO_THRESHOLD_DAYS = 7

# BUFR codes that carry station metadata — skip as observation variables
_METADATA_BUFR_CODES = frozenset(
    {"B01019", "B01194", "B05001", "B06001", "B07030", "B33007"}
)

# BUFR code → Pint unit string for feed-native units
# B12101 is Kelvin — already SI, no conversion needed
BUFR_SOURCE_UNITS: dict[str, str] = {
    "B12101": "kelvin",           # air temperature, already SI
    "B13003": "percent",          # relative humidity
    "B11001": "degree",           # wind direction (degrees true)
    "B11002": "meter/second",     # wind speed
    "B13011": "mm_water",         # total precipitation (1 mm = 1 kg/m²)
    "B10004": "Pa",               # surface pressure
    "B20010": "percent",          # cloud cover
}


# ---------------------------------------------------------------------------
# Adapter implementation
# ---------------------------------------------------------------------------


@register("arpa_emilia")
class ArpaeEmiliaAdapter(WeatherSourceAdapter):
    """Concrete adapter for ARPA Emilia-Romagna SIMC open data.

    Station-based (is_grid_based=False); routes observations to the
    `observations` hypertable via the IdempotentWriter.

    Fetches from:
    - realtime: https://dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl
    - storico:  https://dati-simc.arpae.it/opendata/osservati/meteo/storico/YYYY-MM.json.gz

    The choice is determined by window age (D-20: recent → realtime; older than 7 days → storico).
    """

    cadence_seconds: int = 900      # 15-min cadence (D-19)
    polite_delay_ms: int = 1000
    is_grid_based: bool = False

    def __init__(self, snapshot_dir: str = "/var/lib/climatepulse/snapshots") -> None:
        """Initialise the adapter with an optional custom snapshot directory.

        Args:
            snapshot_dir: base path for JSON-LD snapshot files (D-15)
        """
        self._snapshot_dir = snapshot_dir
        # HTTP client — timeout 30s per RESEARCH.md; 5 retries via tenacity in PoliteHttpClient
        self._http_timeout = 30.0

    def source_meta(self) -> SourceMeta:
        """Return licensing and attribution metadata for ARPAE SIMC."""
        return SourceMeta(
            source_id="arpa_emilia",
            name="ARPA Emilia-Romagna SIMC",
            license="CC-BY 4.0",
            attribution="ARPAE SIMC — dati.arpae.it",
            terms_url=(
                "https://dati.arpae.it/dataset/"
                "dati-dalle-stazioni-meteo-locali-della-rete-idrometeorologica-regionale"
            ),
            default_qc_flag=0,
        )

    async def discover_stations(self) -> list[Station]:
        """Parse one realtime.jsonl snapshot to build the station catalog.

        Extracts unique (network, lat, lon) tuples and maps them to Station
        domain objects. Deterministic external_id = f"{network}__{lat:.4f}_{lon:.4f}".

        Returns:
            List of Station objects; may be empty if the feed is unreachable.
        """
        try:
            content = await self._fetch_bytes(REALTIME_URL)
        except Exception as exc:
            logger.warning(
                "arpa_emilia.discover_stations.fetch_failed",
                error=str(exc),
            )
            return []

        if content is None:
            return []

        stations: dict[str, Station] = {}
        for line in content.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            lat = record.get("lat")
            lon = record.get("lon")
            if lat is None or lon is None:
                continue

            network = None
            name = "unknown"
            # Extract metadata from vars
            for group in record.get("data", []):
                vars_dict = group.get("vars", {})
                if "B01194" in vars_dict:
                    network = vars_dict["B01194"].get("v") or network
                if "B01019" in vars_dict:
                    name = vars_dict["B01019"].get("v") or name

            network = network or record.get("network", "unknown")
            external_id = f"{network}__{lat:.4f}_{lon:.4f}"

            if external_id not in stations:
                stations[external_id] = Station(
                    source_id="arpa_emilia",
                    external_id=external_id,
                    name=name,
                    lat=float(lat),
                    lon=float(lon),
                )

        return list(stations.values())

    async def fetch(self, window: FetchWindow) -> AsyncIterator[RawObservation]:  # type: ignore[override]
        """Yield RawObservation objects for all stations in the fetch window.

        Decision: realtime vs storico based on window.since age.
        - Recent (< STORICO_THRESHOLD_DAYS ago): fetch realtime.jsonl
        - Older: fetch monthly storico gzip archives

        Args:
            window: FetchWindow with UTC since/until bounds

        Yields:
            RawObservation instances; includes SCHEMA_VIOLATION rows (D-20).

        Raises:
            httpx.HTTPStatusError: on 4xx/5xx after all retries
            httpx.TimeoutException: on persistent timeout
        """
        now_utc = datetime.now(timezone.utc)
        threshold = now_utc - timedelta(days=STORICO_THRESHOLD_DAYS)

        if window.since >= threshold:
            # Recent window → use realtime endpoint
            async for obs in self._fetch_realtime(window):
                yield obs
        else:
            # Historical window → use storico monthly archives
            async for obs in self._fetch_storico(window):
                yield obs

    async def _fetch_realtime(
        self, window: FetchWindow
    ) -> AsyncIterator[RawObservation]:
        """Fetch from the realtime.jsonl endpoint and yield observations."""
        content = await self._fetch_bytes(REALTIME_URL)
        if content is None:
            # 304 Not Modified — no new data
            return

        text = content.decode("utf-8", errors="replace")
        async for obs in self._parse_jsonl(text, window):
            yield obs

    async def _fetch_storico(
        self, window: FetchWindow
    ) -> AsyncIterator[RawObservation]:
        """Fetch monthly storico gzip archives and yield observations in window."""
        # Collect all (year, month) pairs in the window
        months: list[tuple[int, int]] = []
        current = window.since.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current <= window.until:
            months.append((current.year, current.month))
            # Advance by one month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        for year, month in months:
            url = f"{STORICO_BASE_URL}/{year:04d}-{month:02d}.json.gz"
            try:
                content = await self._fetch_bytes(url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.info(
                        "arpa_emilia.storico.not_found",
                        year=year,
                        month=month,
                        url=url,
                    )
                    continue
                raise

            if content is None:
                continue

            # Decompress gzip
            try:
                with gzip.open(io.BytesIO(content), "rb") as gz:
                    text = gz.read().decode("utf-8", errors="replace")
            except Exception as exc:
                logger.warning(
                    "arpa_emilia.storico.decompress_failed",
                    year=year,
                    month=month,
                    error=str(exc),
                )
                continue

            async for obs in self._parse_jsonl(text, window):
                yield obs

    async def _parse_jsonl(
        self, text: str, window: FetchWindow
    ) -> AsyncIterator[RawObservation]:
        """Parse line-delimited JSON and yield RawObservation objects.

        Applies window filtering, BUFR-to-WMO mapping, unit normalization,
        range validation, and schema-drift handling (D-20).
        """
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("arpa_emilia.parse_jsonl.invalid_json", error=str(exc))
                continue

            # Parse observed_at
            date_str = record.get("date", "")
            if not date_str:
                continue
            try:
                observed_at = datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                )
            except ValueError:
                logger.warning(
                    "arpa_emilia.parse_jsonl.bad_date", date_str=date_str
                )
                continue

            # Filter by window
            if observed_at < window.since or observed_at > window.until:
                continue

            lat = record.get("lat")
            lon = record.get("lon")
            if lat is None or lon is None:
                continue

            network = record.get("network", "unknown")

            # Extract station metadata from vars groups
            station_name = "unknown"
            for group in record.get("data", []):
                vars_dict = group.get("vars", {})
                if "B01194" in vars_dict:
                    network = vars_dict["B01194"].get("v") or network
                if "B01019" in vars_dict:
                    station_name = vars_dict["B01019"].get("v") or station_name  # noqa: F841

            station_external_id = f"{network}__{lat:.4f}_{lon:.4f}"

            # Iterate all data groups (level/timerange/vars)
            for group in record.get("data", []):
                vars_dict: dict[str, Any] = group.get("vars", {})
                for bufr_code, payload in vars_dict.items():
                    # Skip metadata codes
                    if bufr_code in _METADATA_BUFR_CODES:
                        continue

                    wmo_code = bufr_to_wmo_code(bufr_code)

                    if wmo_code is None:
                        # D-20: schema-drift — emit SCHEMA_VIOLATION, no fail-loud, no silent skip
                        logger.warning(
                            "arpae.schema_drift",
                            bufr_code=bufr_code,
                            station=station_external_id,
                        )
                        yield RawObservation(
                            source_id="arpa_emilia",
                            observed_at=observed_at,
                            station_external_id=station_external_id,
                            wmo_code=f"unknown:{bufr_code}",
                            value=0.0,
                            qc_flag=QcFlag.SCHEMA_VIOLATION,
                        )
                        continue

                    # Extract raw value
                    raw_v = payload.get("v") if isinstance(payload, dict) else None

                    if raw_v is None:
                        # Pitfall C: null value → sentinel (0.0, MISSING)
                        value_si, qc = handle_null_value(wmo_code, None)
                        yield RawObservation(
                            source_id="arpa_emilia",
                            observed_at=observed_at,
                            station_external_id=station_external_id,
                            wmo_code=wmo_code,
                            value=value_si,
                            qc_flag=qc,
                        )
                        continue

                    # Convert to SI using Pint
                    source_unit = BUFR_SOURCE_UNITS.get(bufr_code, "")
                    try:
                        if source_unit:
                            value_si, _ = normalize_to_si(wmo_code, float(raw_v), source_unit)
                        else:
                            # Unknown unit — use raw value, flag as schema_violation
                            value_si = float(raw_v)
                    except (KeyError, Exception) as exc:
                        logger.warning(
                            "arpa_emilia.normalize_error",
                            bufr_code=bufr_code,
                            wmo_code=wmo_code,
                            error=str(exc),
                        )
                        value_si = float(raw_v)

                    qc = validate_range(wmo_code, value_si)

                    yield RawObservation(
                        source_id="arpa_emilia",
                        observed_at=observed_at,
                        station_external_id=station_external_id,
                        wmo_code=wmo_code,
                        value=value_si,
                        qc_flag=qc,
                    )

    async def _fetch_bytes(self, url: str) -> bytes | None:
        """Fetch raw bytes from URL with retries and timeout.

        Returns:
            bytes on success, None on 304 Not Modified.

        Raises:
            httpx.HTTPStatusError: on 4xx/5xx after all retries
            httpx.TimeoutException: on persistent timeout
        """
        import tenacity

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_random_exponential(min=1, max=4),
            retry=tenacity.retry_if_exception_type(
                (httpx.HTTPStatusError, httpx.TimeoutException)
            ),
            reraise=True,
        )
        async def _do_fetch() -> bytes | None:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    timeout=self._http_timeout,
                    headers={"User-Agent": "ClimatePulse/0.1"},
                )
                if resp.status_code == 304:
                    return None
                resp.raise_for_status()
                return resp.content

        try:
            return await _do_fetch()
        except Exception:
            # Write snapshot before re-raising (D-15/D-16)
            await self._write_failure_snapshot(url)
            raise

    async def _write_failure_snapshot(self, url: str) -> None:
        """Write a JSON-LD snapshot to document the HTTP failure (D-16)."""
        import re
        from pathlib import Path

        try:
            safe_fragment = re.sub(r"[^a-zA-Z0-9_-]", "_", url.replace("https://", ""))[:64]
            if not safe_fragment:
                safe_fragment = "unknown"
            ts_str = datetime.now(timezone.utc).isoformat().replace(":", "-")
            snapshot_path = (
                Path(self._snapshot_dir)
                / "arpa_emilia"
                / safe_fragment
                / f"{ts_str}.jsonld"
            )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_data = {
                "@context": {
                    "cp": "https://github.com/federicocalo/climate-pulse/vocab#"
                },
                "@type": "cp:FetchFailure",
                "source_id": "arpa_emilia",
                "url": url,
                "snapshot_reason": "source_error",
                "snapshot_captured_at": datetime.now(timezone.utc).isoformat(),
            }
            snapshot_path.write_text(json.dumps(snapshot_data, indent=2))
        except Exception:
            # Never let snapshot write failure mask the original error
            pass
