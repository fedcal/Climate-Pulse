# Scraping Policy

Climate Pulse aggregates data from public European meteorological portals, including ARPA
Emilia-Romagna's `dati-simc.arpae.it` open-data endpoint. We are committed to behaving as a
respectful, well-identified crawler that does not impose unnecessary load on public data portals.

## User-Agent Identification

Every HTTP request made by Climate Pulse includes a descriptive `User-Agent` header:

```
ClimatePulse/{version} (+https://github.com/federicocalo/climate-pulse; contact: fedcal01@gmail.com)
```

This string identifies the crawler, links to the public source repository, and provides a
contact address so administrators can reach us if the crawler misbehaves.

## Rate Limiting

Climate Pulse enforces a conservative rate limit of **30 requests per minute per host** using
`pyrate-limiter` with a Redis-backed shared bucket. This limit is enforced globally across all
Celery workers — not just per process — so scaling the `worker` service does not multiply the
request rate toward any single host.

The Beat scheduler triggers ARPA ingestion every 15 minutes. Combined with the 30 req/min cap
and the per-day split strategy in the backfill CLI, Climate Pulse never generates a burst that
would impact portal availability.

## robots.txt Compliance

Climate Pulse fetches and caches the `robots.txt` file for every data source host (RFC 9309
standard). The cache TTL is 24 hours. If `robots.txt` disallows access to the data endpoints,
Climate Pulse will refuse to scrape and will flip the source's health metric to `unhealthy`
rather than violating the directive.

## ETag / If-None-Match Caching

Requests to endpoints that support HTTP caching (ETag or Last-Modified headers) use
`If-None-Match` / `If-Modified-Since` headers via `aiocache` with a Redis backend. A `304 Not
Modified` response is treated as a cache hit — no data transfer, no processing, minimal load on
the server.

## Snapshot Fallback

When a data source returns a 5xx error or times out after retries, Climate Pulse writes the last
successful response to a local JSON-LD snapshot file and serves stale data tagged with
`qc_flag = stale_snapshot`. It does **not** retry in a tight loop or hammer the endpoint until
it recovers. Retries use exponential backoff with jitter via `tenacity` (maximum 5 attempts,
random backoff 4–60 seconds).

## Contact Us

If you are an ARPA administrator and our crawler is causing problems — even if it appears within
policy — please contact us at **[fedcal01@gmail.com](mailto:fedcal01@gmail.com)**. We will
investigate and adjust the rate limit or schedule immediately.

You can also open an issue at
[github.com/federicocalo/climate-pulse/issues](https://github.com/federicocalo/climate-pulse/issues).
