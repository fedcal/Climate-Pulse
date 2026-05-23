"""JSON-LD snapshot store for polite HTTP client fallback (D-15/D-16/D-17).

When PoliteHttpClient exhausts all tenacity retries, it writes a JSON-LD
canonical snapshot to the Docker volume so the data is not lost entirely.

File layout (D-16):
    {snapshot_dir}/{source_id}/{station_or_grid_id}/{ISO8601_UTC}.jsonld

Format: JSON-LD with @context referencing WMO variables + schema.org + cp vocab.

Retention: SnapshotStore.rotate(max_age_days=30) deletes files older than
    30 days (D-17); called daily by Celery task tasks.maintenance.rotate_snapshots.

Security (T-03-04): source_id and station_or_grid_id are validated against
    ^[a-zA-Z0-9_-]+$ before being used to construct filesystem paths.
    Any input containing path separators or '..' raises ValueError.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# Regex for safe IDs: alphanumeric, underscore, hyphen only (no slashes, dots, or ..)
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# JSON-LD @context (per RESEARCH.md lines 898-922 design)
_JSONLD_CONTEXT = {
    "wmo": "https://codes.wmo.int/common/",
    "schema": "https://schema.org/",
    "cp": "https://github.com/federicocalo/climate-pulse/vocab#",
    "observed_at": {"@id": "schema:dateObserved", "@type": "@datetime"},
    "air_temperature": {"@id": "wmo:unit/degK"},
    "relative_humidity": {"@id": "wmo:unit/percent"},
    "surface_pressure": {"@id": "wmo:unit/Pa"},
    "wind_direction": {"@id": "wmo:unit/degree"},
    "wind_speed": {"@id": "wmo:unit/m-s-1"},
    "total_precipitation": {"@id": "wmo:unit/kg-m-2"},
    "cloud_cover": {"@id": "wmo:unit/percent"},
    "station_id": {"@id": "cp:stationId"},
    "source_id": {"@id": "cp:sourceId"},
    "qc_flag": {"@id": "cp:qualityFlag"},
    "snapshot_reason": {"@id": "cp:snapshotReason"},
    "snapshot_captured_at": {"@id": "cp:snapshotCapturedAt"},
}


def _validate_id(id_value: str, field_name: str) -> None:
    """Validate that id_value contains only safe filesystem characters.

    Raises:
        ValueError: if id_value contains path separators, '..', or other
            characters that could be used for path traversal (T-03-04).
    """
    if not _SAFE_ID_RE.match(id_value):
        raise ValueError(
            f"Invalid {field_name}: '{id_value}' — must match ^[a-zA-Z0-9_-]+$ "
            f"(path traversal prevention T-03-04)"
        )


class SnapshotStore:
    """Write, read, and rotate JSON-LD snapshots on the Docker volume.

    One instance per PoliteHttpClient; the snapshot_dir is the Docker volume
    mount point (D-15, default: /var/lib/climatepulse/snapshots).
    """

    def __init__(self, snapshot_dir: str) -> None:
        self._base = Path(snapshot_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    async def write_jsonld(
        self,
        source_id: str,
        station_or_grid_id: str,
        observed_at: datetime,
        observations: list[dict],
        snapshot_reason: str,
    ) -> Path:
        """Write a JSON-LD snapshot file to the Docker volume.

        Path layout: {base}/{source_id}/{station_or_grid_id}/{iso_timestamp}.jsonld

        Args:
            source_id:           adapter source identifier (e.g. 'arpa_emilia')
            station_or_grid_id:  station or grid-point identifier
            observed_at:         UTC datetime of the observation batch
            observations:        list of observation dicts (variable, value, unit, qc_flag)
            snapshot_reason:     reason for the snapshot (e.g. 'source_5xx', 'timeout')

        Returns:
            Path to the written snapshot file.

        Raises:
            ValueError: if source_id or station_or_grid_id contain path traversal chars
        """
        _validate_id(source_id, "source_id")
        _validate_id(station_or_grid_id, "station_or_grid_id")

        # Build file path per D-16
        ts_str = observed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        file_path = self._base / source_id / station_or_grid_id / f"{ts_str}.jsonld"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Construct JSON-LD document
        doc = {
            "@context": _JSONLD_CONTEXT,
            "@type": "cp:WeatherObservation",
            "station_id": f"{source_id}__{station_or_grid_id}",
            "source_id": source_id,
            "observed_at": ts_str,
            "observations": observations,
            "snapshot_reason": snapshot_reason,
            "snapshot_captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        file_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        return file_path

    async def read_latest(
        self,
        source_id: str,
        station_or_grid_id: str,
    ) -> dict | None:
        """Return the most recent snapshot for a source/station, or None.

        Scans the directory for .jsonld files and returns the one with the
        lexicographically latest name (ISO timestamps sort correctly).

        Args:
            source_id:          adapter source identifier
            station_or_grid_id: station or grid-point identifier

        Returns:
            Parsed JSON dict from the latest snapshot file, or None if none found.
        """
        _validate_id(source_id, "source_id")
        _validate_id(station_or_grid_id, "station_or_grid_id")

        snap_dir = self._base / source_id / station_or_grid_id
        if not snap_dir.exists():
            return None

        jsonld_files = sorted(snap_dir.glob("*.jsonld"))
        if not jsonld_files:
            return None

        # Latest file has the largest ISO-formatted name
        latest = jsonld_files[-1]
        return json.loads(latest.read_text())

    async def rotate(self, max_age_days: int = 30) -> int:
        """Delete snapshot files older than max_age_days.

        Implements D-17 30-day rolling retention. Called daily by the Celery
        maintenance task `tasks.maintenance.rotate_snapshots`.

        Args:
            max_age_days: files with mtime older than this are deleted (default: 30)

        Returns:
            Number of files deleted.
        """
        cutoff = time.time() - (max_age_days * 86400)
        deleted_count = 0

        for jsonld_file in self._base.rglob("*.jsonld"):
            try:
                file_mtime = jsonld_file.stat().st_mtime
                if file_mtime < cutoff:
                    jsonld_file.unlink()
                    deleted_count += 1
            except FileNotFoundError:
                # Race condition: file already deleted (e.g. parallel worker)
                pass

        return deleted_count
