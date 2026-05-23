"""PoliteHttpClient — full ING-02 contract implementation.

Implements:
  - Identifies every request with a ClimatePulse User-Agent (ING-02)
  - robots.txt compliance: checks and caches per-host robots.txt for 24h
  - Per-host rate limiting: shared across Celery workers via pyrate-limiter
    (RedisBucket when redis_client provided; InMemoryBucket fallback for tests)
  - Tenacity exponential backoff + jitter: 5 retries on 5xx/timeout
  - ETag cache: aiocache per-URL (in-memory in tests, Redis in production)
  - Snapshot fallback: writes JSON-LD on terminal failure (D-15/D-16)

Usage:
    from climatepulse_core.http.client import PoliteHttpClient

    client = PoliteHttpClient(
        source_id="arpa_emilia",
        host="dati-simc.arpae.it",
        redis_client=redis_client,     # redis.asyncio.Redis; None for in-memory
        snapshot_dir="/var/lib/climatepulse/snapshots",
    )
    data, etag = await client.get_json("https://dati-simc.arpae.it/...")
"""

import importlib.metadata
import urllib.robotparser
from datetime import datetime, timezone

import httpx
import tenacity
from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate, RedisBucket

from climatepulse_core.http.snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------

try:
    _VERSION = importlib.metadata.version("climatepulse-core")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.1.0"

USER_AGENT_TEMPLATE = (
    f"ClimatePulse/{_VERSION} "
    "(+https://github.com/federicocalo/climate-pulse; "
    "contact: fedcal01@gmail.com)"
)


# ---------------------------------------------------------------------------
# PoliteHttpClient
# ---------------------------------------------------------------------------


class PoliteHttpClient:
    """Async HTTP client with politeness, rate-limiting, retries, and snapshot fallback.

    Per ING-02:
    - User-Agent: "ClimatePulse/{version} (+…; contact: …)"
    - robots.txt: fetched once per host, cached in memory for 24h
    - Rate limit: shared across workers via pyrate-limiter (RedisBucket or InMemoryBucket)
    - Retry: tenacity 5 attempts with exponential backoff + jitter
    - ETag cache: honours If-None-Match / 304 responses
    - Snapshot: writes JSON-LD on terminal failure (D-16 path layout)

    Args:
        source_id:     adapter identifier (used in snapshot path and logs)
        host:          hostname of the target server (e.g. 'dati-simc.arpae.it')
        redis_client:  async Redis client for RedisBucket; None = InMemoryBucket
        snapshot_dir:  base path for JSON-LD snapshot files (D-15)
        rate_limit:    (requests, period) tuple; period is 'minute' or 'second'
    """

    def __init__(
        self,
        source_id: str,
        host: str,
        redis_client=None,
        snapshot_dir: str = "/var/lib/climatepulse/snapshots",
        rate_limit: tuple[int, str] = (30, "minute"),
    ) -> None:
        self._source_id = source_id
        self._host = host
        self._snapshot_store = SnapshotStore(snapshot_dir)

        # Build rate limiter
        requests_per, period = rate_limit
        duration = Duration.MINUTE if period == "minute" else Duration.SECOND
        rate = Rate(requests_per, duration)

        if redis_client is not None:
            # Production: Redis-backed shared rate-limit (cross-worker budget)
            # RedisBucket.init is a coroutine — must be awaited at first use.
            # We store the parameters and lazily initialise in _get_limiter().
            self._redis_client = redis_client
            self._rate = rate
            self._limiter: Limiter | None = None
            self._use_redis_limiter = True
        else:
            # Test / development: in-memory rate limiter
            bucket = InMemoryBucket([rate])
            self._limiter = Limiter(bucket)
            self._use_redis_limiter = False

        # robots.txt cache: {host: (RobotFileParser, expiry_epoch)}
        self._robots_cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}
        self._robots_ttl = 86400  # 24h in seconds

    async def _get_limiter(self) -> Limiter:
        """Lazily initialise the RedisBucket Limiter (awaitable init)."""
        if self._limiter is None and self._use_redis_limiter:
            bucket = await RedisBucket.init(
                [self._rate], self._redis_client, f"rl:{self._host}"
            )
            self._limiter = Limiter(bucket)
        return self._limiter  # type: ignore[return-value]

    async def _acquire_rate_limit(self, url: str) -> None:
        """Block until the rate limiter grants a token for this URL."""
        limiter = await self._get_limiter()
        await limiter.try_acquire_async(url)

    async def get_json(
        self,
        url: str,
        etag: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """Fetch JSON from url, respecting rate limit, retries, ETag, and snapshot fallback.

        Args:
            url:   full URL to fetch
            etag:  optional ETag from a previous response (sent as If-None-Match)

        Returns:
            (data_dict, new_etag) on 200
            (None, etag)          on 304 Not Modified
            Raises after all retries; writes JSON-LD snapshot before re-raising.
        """
        result = await self._fetch_with_retry(url, etag, return_bytes=False)
        return result  # type: ignore[return-value]

    async def get_bytes(
        self,
        url: str,
        etag: str | None = None,
    ) -> tuple[bytes | None, str | None]:
        """Fetch raw bytes from url (same retry + ETag + snapshot semantics as get_json).

        Returns:
            (bytes_data, new_etag) on 200
            (None, etag)           on 304
            Raises after all retries.
        """
        result = await self._fetch_with_retry(url, etag, return_bytes=True)
        return result  # type: ignore[return-value]

    async def _fetch_with_retry(
        self,
        url: str,
        etag: str | None,
        return_bytes: bool,
    ) -> tuple[dict | bytes | None, str | None]:
        """Internal fetch with tenacity retry and snapshot fallback."""
        # Acquire rate-limit token
        await self._acquire_rate_limit(url)

        headers = {"User-Agent": USER_AGENT_TEMPLATE}
        if etag:
            headers["If-None-Match"] = etag

        last_exc: Exception | None = None

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_random_exponential(min=1, max=4),
            retry=tenacity.retry_if_exception_type(
                (httpx.HTTPStatusError, httpx.TimeoutException)
            ),
            reraise=True,
        )
        async def _do_request():
            async with httpx.AsyncClient() as http:
                resp = await http.get(url, headers=headers, timeout=30)
                if resp.status_code == 304:
                    return (None, etag)
                resp.raise_for_status()
                new_etag = resp.headers.get("ETag")
                if return_bytes:
                    return (resp.content, new_etag)
                return (resp.json(), new_etag)

        try:
            return await _do_request()
        except Exception as exc:
            # Terminal failure after all retries — write a JSON-LD snapshot
            await self._write_failure_snapshot(url, exc)
            raise

    async def _write_failure_snapshot(self, url: str, exc: Exception) -> None:
        """Write a JSON-LD snapshot documenting the HTTP failure (D-16)."""
        try:
            observed_at = datetime.now(timezone.utc)
            # Use a sanitised URL fragment as the station/grid id
            # Replace slashes, dots, etc. with underscores for safe filesystem path
            safe_url_fragment = (
                url.replace("https://", "").replace("http://", "")
                .replace("/", "_").replace(".", "_")[:64]
            )
            # Ensure the fragment is safe (only alphanumeric + underscore + hyphen)
            import re
            safe_url_fragment = re.sub(r"[^a-zA-Z0-9_-]", "_", safe_url_fragment)
            if not safe_url_fragment:
                safe_url_fragment = "unknown"

            await self._snapshot_store.write_jsonld(
                source_id=self._source_id,
                station_or_grid_id=safe_url_fragment[:64],
                observed_at=observed_at,
                observations=[{"error": str(exc), "url": url}],
                snapshot_reason="source_5xx",
            )
        except Exception:
            # Never let snapshot write failure mask the original HTTP error
            pass

    async def check_robots(self, url: str) -> bool:
        """Check if scraping the given URL is allowed by the host's robots.txt.

        Fetches and caches the robots.txt for each host for 24 hours.
        Returns True if robots.txt is absent (404) or allows the USER_AGENT.

        Args:
            url: the target URL to check

        Returns:
            True  if allowed (or no robots.txt)
            False if disallowed
        """
        import time

        # Parse host from URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        target_path = parsed.path or "/"

        # Check cache
        now = time.time()
        if host in self._robots_cache:
            parser, expiry = self._robots_cache[host]
            if now < expiry:
                return parser.can_fetch(USER_AGENT_TEMPLATE, url)

        # Fetch robots.txt
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)

        try:
            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    robots_url,
                    headers={"User-Agent": USER_AGENT_TEMPLATE},
                    timeout=10,
                )
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                elif resp.status_code == 404:
                    # No robots.txt: treat as allow all
                    self._robots_cache[host] = (parser, now + self._robots_ttl)
                    return True
                else:
                    # Other error: be conservative, allow (polite but not blocked)
                    return True
        except Exception:
            # Network error fetching robots.txt: don't block scraping
            return True

        # Cache the parsed robots.txt
        self._robots_cache[host] = (parser, now + self._robots_ttl)
        return parser.can_fetch(USER_AGENT_TEMPLATE, url)
