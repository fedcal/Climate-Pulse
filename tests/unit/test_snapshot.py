"""Tests for SnapshotStore: JSON-LD write/read, path traversal guard, rotation."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from climatepulse_core.http.snapshot import SnapshotStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_observations():
    return [
        {"variable": "air_temperature", "value": 285.65, "unit": "K", "qc_flag": 1},
        {"variable": "relative_humidity", "value": 78.0, "unit": "%", "qc_flag": 1},
    ]


# ---------------------------------------------------------------------------
# Write and read
# ---------------------------------------------------------------------------


async def test_write_and_read_jsonld(tmp_path):
    """Write a snapshot, read latest, assert JSON-LD structure is preserved."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 5, 23, 3, 15, 0, tzinfo=timezone.utc)
    obs = _sample_observations()

    path = await store.write_jsonld(
        source_id="arpa_emilia",
        station_or_grid_id="stn001",
        observed_at=observed_at,
        observations=obs,
        snapshot_reason="source_5xx",
    )

    assert path.exists()
    assert path.suffix == ".jsonld"

    # Read back
    data = await store.read_latest("arpa_emilia", "stn001")
    assert data is not None
    assert "@context" in data
    assert "observations" in data
    assert data["snapshot_reason"] == "source_5xx"
    assert len(data["observations"]) == 2


async def test_write_jsonld_creates_parent_dirs(tmp_path):
    """SnapshotStore creates nested subdirectories as needed."""
    store = SnapshotStore(str(tmp_path / "nested" / "dir"))
    observed_at = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)

    path = await store.write_jsonld(
        source_id="test_src",
        station_or_grid_id="g001",
        observed_at=observed_at,
        observations=[],
        snapshot_reason="test",
    )
    assert path.exists()


async def test_read_latest_no_snapshots(tmp_path):
    """read_latest returns None when no snapshots exist for source/station."""
    store = SnapshotStore(str(tmp_path))
    result = await store.read_latest("nonexistent_src", "stn999")
    assert result is None


# ---------------------------------------------------------------------------
# Path traversal security (T-03-04)
# ---------------------------------------------------------------------------


async def test_path_traversal_source_id_rejected(tmp_path):
    """write_jsonld raises ValueError for source_id with path traversal characters."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="source_id"):
        await store.write_jsonld(
            source_id="../etc",
            station_or_grid_id="stn001",
            observed_at=observed_at,
            observations=[],
            snapshot_reason="test",
        )


async def test_path_traversal_station_id_rejected(tmp_path):
    """write_jsonld raises ValueError for station_or_grid_id with path separators."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="station_or_grid_id"):
        await store.write_jsonld(
            source_id="arpa_emilia",
            station_or_grid_id="/etc/passwd",
            observed_at=observed_at,
            observations=[],
            snapshot_reason="test",
        )


async def test_valid_ids_with_hyphens_accepted(tmp_path):
    """Hyphens and underscores in IDs are allowed."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    path = await store.write_jsonld(
        source_id="arpa-emilia",
        station_or_grid_id="stn_001-A",
        observed_at=observed_at,
        observations=[],
        snapshot_reason="test",
    )
    assert path.exists()


# ---------------------------------------------------------------------------
# Rotation (D-17 30-day retention)
# ---------------------------------------------------------------------------


async def test_rotate_deletes_old_files(tmp_path, monkeypatch):
    """rotate(30) deletes files older than 30 days, keeps newer ones."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)

    # Write 3 snapshots
    paths = []
    for i, station in enumerate(["stn001", "stn002", "stn003"]):
        p = await store.write_jsonld(
            source_id="arpa_emilia",
            station_or_grid_id=station,
            observed_at=observed_at,
            observations=[],
            snapshot_reason="test",
        )
        paths.append(p)

    # Monkey-patch the mtime: set stn001 to 10 days ago, stn002 to 20 days, stn003 to 40 days
    now = time.time()
    days_10 = now - (10 * 86400)
    days_20 = now - (20 * 86400)
    days_40 = now - (40 * 86400)

    import os
    os.utime(paths[0], (days_10, days_10))
    os.utime(paths[1], (days_20, days_20))
    os.utime(paths[2], (days_40, days_40))

    # Rotate with 30-day limit
    deleted_count = await store.rotate(max_age_days=30)

    assert deleted_count == 1
    assert paths[0].exists()   # 10 days old -> kept
    assert paths[1].exists()   # 20 days old -> kept
    assert not paths[2].exists()  # 40 days old -> deleted


async def test_rotate_returns_zero_for_fresh_files(tmp_path):
    """rotate() returns 0 when all files are within the retention window."""
    store = SnapshotStore(str(tmp_path))
    observed_at = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)

    await store.write_jsonld(
        source_id="arpa_emilia",
        station_or_grid_id="stn001",
        observed_at=observed_at,
        observations=[],
        snapshot_reason="test",
    )

    deleted_count = await store.rotate(max_age_days=30)
    assert deleted_count == 0
