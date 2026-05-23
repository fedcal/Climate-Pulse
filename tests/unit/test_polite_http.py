"""Tests for PoliteHttpClient (ING-02) and health metric helpers (ING-14).

Uses respx for httpx mocking (RESEARCH.md D-27 allows respx for edge-case injection).
Uses fakeredis.aioredis for Redis-backed rate-limiter and health metrics.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest
import respx
from httpx import Response

from climatepulse_core.http.client import PoliteHttpClient
from climatepulse_core.observability.health import (
    get_last_success,
    is_stale,
    record_success,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_redis():
    """Provide a fakeredis.aioredis instance for testing."""
    r = await fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def snapshot_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def make_client(snapshot_dir):
    """Factory that returns a PoliteHttpClient configured with in-memory rate limiter.

    Note: In tests we pass redis_client=None so that InMemoryBucket is used
    (RedisBucket requires Redis SCRIPT command which fakeredis does not support).
    The health metric functions are tested separately with fake_redis.
    """
    async def _factory(source_id="test_src", host="example.com"):
        client = PoliteHttpClient(
            source_id=source_id,
            host=host,
            redis_client=None,           # InMemoryBucket — no Redis scripting needed
            snapshot_dir=snapshot_dir,
            rate_limit=(100, "minute"),  # high limit so tests don't block
        )
        return client
    return _factory


# ---------------------------------------------------------------------------
# User-Agent header
# ---------------------------------------------------------------------------


@respx.mock
async def test_user_agent_header_correct(make_client):
    """Every request must carry the ClimatePulse User-Agent (ING-02)."""
    respx.get("https://example.com/data").mock(return_value=Response(200, json={"x": 1}))

    client = await make_client()
    ua_seen = []

    respx.get("https://example.com/data").side_effect = lambda req: (
        ua_seen.append(req.headers.get("user-agent", "")),
        Response(200, json={"x": 1}),
    )[-1]

    await client.get_json("https://example.com/data")

    assert len(ua_seen) == 1
    assert "ClimatePulse/" in ua_seen[0]
    assert "github.com/federicocalo/climate-pulse" in ua_seen[0]
    assert "fedcal01@gmail.com" in ua_seen[0]


# ---------------------------------------------------------------------------
# get_json: 200, 304
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_json_returns_data_on_200(make_client):
    """200 response returns (data_dict, etag)."""
    respx.get("https://example.com/api").mock(
        return_value=Response(200, json={"key": "value"}, headers={"ETag": '"abc123"'})
    )

    client = await make_client()
    data, etag = await client.get_json("https://example.com/api")
    assert data == {"key": "value"}
    assert etag == '"abc123"'


@respx.mock
async def test_get_json_304_returns_none_data(make_client):
    """304 Not Modified returns (None, original_etag)."""
    respx.get("https://example.com/api").mock(return_value=Response(304))

    client = await make_client()
    data, etag = await client.get_json("https://example.com/api", etag='"abc123"')
    assert data is None
    assert etag == '"abc123"'


# ---------------------------------------------------------------------------
# get_json: 500 retry + snapshot fallback
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_json_500_writes_snapshot_on_terminal_failure(make_client, snapshot_dir):
    """After all tenacity retries on 5xx, a JSON-LD snapshot is written."""
    respx.get("https://example.com/fail").mock(return_value=Response(500))

    client = await make_client(source_id="test_src", host="example.com")

    with pytest.raises(Exception):
        await client.get_json("https://example.com/fail")

    # At least one .jsonld file should have been created
    jsonld_files = list(Path(snapshot_dir).rglob("*.jsonld"))
    assert len(jsonld_files) >= 1, "Expected at least 1 snapshot file after terminal failure"


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


@respx.mock
async def test_check_robots_disallowed_returns_false(make_client):
    """A disallowed path in robots.txt causes check_robots() to return False."""
    robots_body = "User-agent: *\nDisallow: /private\n"
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text=robots_body)
    )

    client = await make_client(host="example.com")
    allowed = await client.check_robots("https://example.com/private/data")
    assert allowed is False


@respx.mock
async def test_check_robots_allowed_returns_true(make_client):
    """A non-disallowed path in robots.txt returns True."""
    robots_body = "User-agent: *\nDisallow: /private\n"
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text=robots_body)
    )

    client = await make_client(host="example.com")
    allowed = await client.check_robots("https://example.com/public/data")
    assert allowed is True


@respx.mock
async def test_check_robots_no_robots_txt_returns_true(make_client):
    """A 404 robots.txt (no file) is treated as 'allow all'."""
    respx.get("https://example.com/robots.txt").mock(return_value=Response(404))

    client = await make_client(host="example.com")
    allowed = await client.check_robots("https://example.com/data")
    assert allowed is True


# ---------------------------------------------------------------------------
# Health metric: record_success + is_stale (ING-14)
# ---------------------------------------------------------------------------


async def test_record_success_sets_redis_key(fake_redis):
    """record_success() stores ISO timestamp in Redis with 24h TTL."""
    await record_success(fake_redis, "arpa_emilia")

    key = "metrics:last_success:arpa_emilia"
    value = await fake_redis.get(key)
    assert value is not None

    # Verify it's a parseable ISO datetime
    dt = datetime.fromisoformat(value.decode())
    assert dt.tzinfo is not None


async def test_get_last_success_returns_none_when_missing(fake_redis):
    """get_last_success() returns None when key not set."""
    result = await get_last_success(fake_redis, "unknown_source")
    assert result is None


async def test_get_last_success_returns_datetime(fake_redis):
    """get_last_success() returns a UTC datetime after recording."""
    await record_success(fake_redis, "test_source")
    result = await get_last_success(fake_redis, "test_source")
    assert result is not None
    assert result.tzinfo is not None


async def test_is_stale_true_when_no_key(fake_redis):
    """is_stale() returns True when key is missing (source never ran)."""
    assert await is_stale(fake_redis, "new_source", cadence_seconds=900) is True


async def test_is_stale_false_when_fresh(fake_redis):
    """is_stale() returns False when last success is within 2×cadence."""
    await record_success(fake_redis, "fresh_source")
    # cadence=900s => threshold=1800s; just recorded so definitely fresh
    assert await is_stale(fake_redis, "fresh_source", cadence_seconds=900) is False


async def test_is_stale_true_when_old(fake_redis):
    """is_stale() returns True when last success is older than 2×cadence."""
    # Set a very old timestamp manually
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await fake_redis.setex("metrics:last_success:slow_source", 86400, old_ts)

    # cadence=60s => 2×cadence = 120s; 2 hours old >> 120s
    assert await is_stale(fake_redis, "slow_source", cadence_seconds=60) is True
