"""Unit tests for FastAPI health endpoints — /healthz + /readyz (API-10, D-14).

Tests verify:
- /healthz returns 200 unconditionally (liveness)
- /readyz checks DB + Redis + Celery heartbeat; returns 200 or 503
- /docs, /redoc, /openapi.json all return 404 (D-13 enforcement)
- No /v1/* routes registered (Phase 2 leak prevention)

Run with:
    uv run pytest tests/unit/test_healthz.py -v -x
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# App import — defer to avoid settings validation errors
# ---------------------------------------------------------------------------


def _make_mock_pool(fetchval_return=1, fetchval_error=None):
    """Helper: build a mock asyncpg pool."""
    mock_conn = AsyncMock()
    if fetchval_error is not None:
        mock_conn.fetchval = AsyncMock(side_effect=fetchval_error)
    else:
        mock_conn.fetchval = AsyncMock(return_value=fetchval_return)

    mock_acquire_ctx = AsyncMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_acquire_ctx)
    mock_pool.close = AsyncMock()
    return mock_pool


def _make_mock_redis(ping_ok=True, heartbeat=b"ok"):
    """Helper: build a mock redis client."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True if ping_ok else None)
    mock_redis.get = AsyncMock(return_value=heartbeat)
    mock_redis.close = AsyncMock()
    return mock_redis


@pytest.fixture
def api_app(monkeypatch):
    """Provide a FastAPI app with mocked settings and mocked lifespan dependencies."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    # Clear any cached settings
    from climatepulse_api.settings import get_api_settings
    get_api_settings.cache_clear()

    # Mock asyncpg.create_pool and Redis.from_url to prevent real connections during lifespan
    mock_pool = _make_mock_pool()
    mock_redis = _make_mock_redis()

    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=mock_pool))
    monkeypatch.setattr("redis.asyncio.Redis.from_url", MagicMock(return_value=mock_redis))

    from climatepulse_api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client_with_healthy_deps(api_app):
    """TestClient with healthy DB + Redis + Celery heartbeat in app.state."""
    mock_pool = _make_mock_pool()
    mock_redis = _make_mock_redis(heartbeat=b"ok")

    with TestClient(api_app, raise_server_exceptions=True) as client:
        # Override app.state after lifespan startup
        client.app.state.db_pool = mock_pool
        client.app.state.redis_client = mock_redis
        yield client


# ---------------------------------------------------------------------------
# /healthz tests
# ---------------------------------------------------------------------------


def test_healthz_returns_200_with_status_ok(api_app, monkeypatch):
    """GET /healthz must return 200 with {status: ok} unconditionally."""
    with TestClient(api_app, raise_server_exceptions=False) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_works_without_dependencies(api_app, monkeypatch):
    """GET /healthz must succeed even if db_pool + redis_client are None (liveness)."""
    with TestClient(api_app, raise_server_exceptions=False) as client:
        response = client.get("/healthz")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /readyz tests
# ---------------------------------------------------------------------------


def test_readyz_all_healthy_returns_200(client_with_healthy_deps):
    """GET /readyz returns 200 when DB + Redis + Celery heartbeat are all OK."""
    response = client_with_healthy_deps.get("/readyz")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.json() == {"status": "ready"}


def test_readyz_db_down_returns_503_with_db_error(api_app):
    """GET /readyz returns 503 when DB is unreachable; detail.db is non-empty."""
    mock_pool = _make_mock_pool(fetchval_error=ConnectionError("DB connection refused"))
    mock_redis = _make_mock_redis(heartbeat=b"ok")

    with TestClient(api_app, raise_server_exceptions=False) as client:
        client.app.state.db_pool = mock_pool
        client.app.state.redis_client = mock_redis
        response = client.get("/readyz")

    assert response.status_code == 503, f"Expected 503, got {response.status_code}: {response.text}"
    detail = response.json().get("detail", {})
    assert "db" in detail, f"Expected 'db' in detail, got {detail}"
    assert detail["db"], "detail.db should be non-empty error description"


def test_readyz_no_celery_heartbeat_returns_503(api_app):
    """GET /readyz returns 503 when Celery heartbeat key is missing."""
    mock_pool = _make_mock_pool()
    mock_redis = _make_mock_redis(heartbeat=None)  # key missing

    with TestClient(api_app, raise_server_exceptions=False) as client:
        client.app.state.db_pool = mock_pool
        client.app.state.redis_client = mock_redis
        response = client.get("/readyz")

    assert response.status_code == 503, f"Expected 503, got {response.status_code}: {response.text}"
    detail = response.json().get("detail", {})
    assert "celery" in detail, f"Expected 'celery' in detail, got {detail}"
    assert "no worker heartbeat" in detail["celery"], \
        f"Expected 'no worker heartbeat' in celery detail, got {detail['celery']!r}"


# ---------------------------------------------------------------------------
# D-13 enforcement: /docs, /redoc, /openapi.json must be disabled
# ---------------------------------------------------------------------------


def test_redoc_and_docs_are_disabled(api_app):
    """Verify D-13: /docs, /redoc, /openapi.json all return 404 (no Phase 2 leak)."""
    with TestClient(api_app, raise_server_exceptions=False) as client:
        docs_resp = client.get("/docs", follow_redirects=False)
        redoc_resp = client.get("/redoc", follow_redirects=False)
        openapi_resp = client.get("/openapi.json", follow_redirects=False)

    assert docs_resp.status_code == 404, \
        f"Expected /docs to return 404, got {docs_resp.status_code}"
    assert redoc_resp.status_code == 404, \
        f"Expected /redoc to return 404, got {redoc_resp.status_code}"
    assert openapi_resp.status_code == 404, \
        f"Expected /openapi.json to return 404, got {openapi_resp.status_code}"


def test_no_v1_routes_registered(api_app):
    """Guard: no /v1/* routes should exist in Phase 1 (D-14 Phase 2 leak prevention)."""
    v1_routes = [
        route for route in api_app.routes
        if hasattr(route, "path") and route.path.startswith("/v1")
    ]
    assert not v1_routes, \
        f"Unexpected /v1 routes registered: {[r.path for r in v1_routes]}"
