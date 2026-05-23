"""Integration tests: ON CONFLICT DO UPDATE idempotency on the observations table.

Tests the ING-12 contract: inserting the same (station_id, variable_id,
observed_at, source_id) tuple multiple times must produce exactly ONE row,
with the latest value taking effect (upsert semantics).

This verifies:
1. Duplicate insert is silently handled (no IntegrityError)
2. The row count remains 1 after N inserts with the same PK
3. The upsert updates the value when re-inserted with a different value
"""

from datetime import datetime, timezone

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

OBSERVED_AT = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)

INSERT_SQL = """
    INSERT INTO observations
        (station_id, variable_id, observed_at, source_id, value, qc_flag)
    VALUES
        ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (station_id, variable_id, observed_at, source_id)
    DO UPDATE SET
        value    = EXCLUDED.value,
        qc_flag  = EXCLUDED.qc_flag
"""

COUNT_SQL = """
    SELECT count(*)::int FROM observations
    WHERE station_id = $1
      AND variable_id = $2
      AND observed_at = $3
      AND source_id   = $4
"""

VALUE_SQL = """
    SELECT value FROM observations
    WHERE station_id = $1
      AND variable_id = $2
      AND observed_at = $3
      AND source_id   = $4
"""


@pytest.mark.asyncio
async def test_on_conflict_do_nothing_via_pk(db_pool, seed_metadata):
    """Re-inserting the same PK tuple must produce exactly 1 row (ING-12).

    Phase 1:  Insert with value=285.5 twice → row count must be 1.
    Phase 2:  Insert with value=999.0 → row count still 1; value updated.
    """
    sid = seed_metadata["station_id"]
    vid = seed_metadata["variable_id"]
    src = seed_metadata["source_id"]

    async with db_pool.acquire() as conn:
        # --- Phase 1: insert same tuple twice ---
        await conn.execute(INSERT_SQL, sid, vid, OBSERVED_AT, src, 285.5, 0)
        await conn.execute(INSERT_SQL, sid, vid, OBSERVED_AT, src, 285.5, 0)

        count = await conn.fetchval(COUNT_SQL, sid, vid, OBSERVED_AT, src)
        assert count == 1, (
            f"Expected 1 row after 2 identical inserts, got {count}"
        )

        # --- Phase 2: insert with different value ---
        await conn.execute(INSERT_SQL, sid, vid, OBSERVED_AT, src, 999.0, 0)

        count = await conn.fetchval(COUNT_SQL, sid, vid, OBSERVED_AT, src)
        assert count == 1, (
            f"Expected 1 row after 3rd insert (upsert), got {count}"
        )

        value = await conn.fetchval(VALUE_SQL, sid, vid, OBSERVED_AT, src)
        assert value == pytest.approx(999.0), (
            f"Expected value=999.0 after upsert, got {value}"
        )

        # --- Cleanup: remove test row so it doesn't pollute CAGG tests ---
        await conn.execute(
            "DELETE FROM observations"
            " WHERE station_id=$1 AND variable_id=$2"
            " AND observed_at=$3 AND source_id=$4",
            sid, vid, OBSERVED_AT, src,
        )
