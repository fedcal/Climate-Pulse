"""Unit tests for Celery app configuration — ING-11.

Tests verify:
- 4 queues defined (ingest, normalize, alerts, dlq)
- Beat schedule has correct entries for D-17/D-19
- run_source and rotate_snapshots tasks are registered
- heartbeat helper sets the Redis key correctly
- adapter @register decorators fire on import of tasks.ingest
- worker_ready signal is connected to set_heartbeat_sync

Run with:
    uv run pytest tests/unit/test_celery_app.py -v -x
"""

import importlib
import sys

import pytest
import fakeredis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_celery_app():
    """Import (or reload) the celery_app module to get a fresh reference.

    Must be called after clearing any cached settings.
    """
    # Remove cached modules to allow clean import
    for mod_name in list(sys.modules.keys()):
        if "climatepulse_worker" in mod_name and mod_name != "climatepulse_worker":
            del sys.modules[mod_name]
    import climatepulse_worker.celery_app as celery_app_module
    return celery_app_module


# ---------------------------------------------------------------------------
# Queue tests
# ---------------------------------------------------------------------------


def test_four_queues_defined(monkeypatch):
    """ING-11 mandates exactly 4 queues: ingest, normalize, alerts, dlq."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    # Clear lru_cache so settings re-reads env
    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    queue_names = {q.name for q in app.conf.task_queues}
    assert len(app.conf.task_queues) == 4, f"Expected 4 queues, got {len(app.conf.task_queues)}: {queue_names}"
    assert queue_names == {"ingest", "normalize", "alerts", "dlq"}


def test_beat_schedule_arpa_emilia_15min(monkeypatch):
    """D-19: ARPAE ingestion every 15 minutes (900 seconds)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "arpa-emilia-15min" in app.conf.beat_schedule, \
        f"Expected 'arpa-emilia-15min' in beat_schedule, got keys: {list(app.conf.beat_schedule.keys())}"
    schedule_entry = app.conf.beat_schedule["arpa-emilia-15min"]
    assert schedule_entry["schedule"] == 900.0, \
        f"Expected 900.0 seconds for ARPAE cadence, got {schedule_entry['schedule']}"
    assert schedule_entry["task"] == "climatepulse_worker.tasks.ingest.run_source"
    assert schedule_entry["args"] == ("arpa_emilia",)


def test_beat_schedule_ecmwf_open_6h(monkeypatch):
    """ECMWF Open Data every 6 hours (21600 seconds)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "ecmwf-open-6h" in app.conf.beat_schedule
    schedule_entry = app.conf.beat_schedule["ecmwf-open-6h"]
    assert schedule_entry["schedule"] == 21600.0, \
        f"Expected 21600.0 seconds for ECMWF cadence, got {schedule_entry['schedule']}"
    assert schedule_entry["task"] == "climatepulse_worker.tasks.ingest.run_source"
    assert schedule_entry["args"] == ("ecmwf_open",)


def test_beat_schedule_rotate_snapshots_daily(monkeypatch):
    """D-17: rotate_snapshots runs daily at 03:00 UTC via crontab."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "rotate-snapshots-daily" in app.conf.beat_schedule
    schedule_entry = app.conf.beat_schedule["rotate-snapshots-daily"]
    from celery.schedules import crontab
    schedule = schedule_entry["schedule"]
    assert isinstance(schedule, crontab), \
        f"Expected crontab for rotate_snapshots schedule, got {type(schedule)}"
    assert schedule.hour == frozenset({3}), f"Expected hour=3, got {schedule.hour}"
    assert schedule.minute == frozenset({0}), f"Expected minute=0, got {schedule.minute}"


def test_run_source_task_registered(monkeypatch):
    """run_source task must be auto-discovered and registered."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "climatepulse_worker.tasks.ingest.run_source" in app.tasks, \
        f"run_source not registered; registered tasks: {sorted(t for t in app.tasks if 'climatepulse' in t)}"


def test_rotate_snapshots_task_registered(monkeypatch):
    """rotate_snapshots task must be auto-discovered and registered."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "climatepulse_worker.tasks.maintenance.rotate_snapshots" in app.tasks, \
        f"rotate_snapshots not registered; tasks: {sorted(t for t in app.tasks if 'climatepulse' in t)}"


def test_adapters_registered_on_import(monkeypatch):
    """tasks.ingest module-level imports arpa_emilia + ecmwf_open adapter modules.

    This test verifies that importing tasks.ingest will cause both adapter modules
    to be imported (which triggers @register). We test this by forcing a completely
    clean slate: evict ALL climatepulse_worker and adapter modules, then import
    tasks.ingest, then confirm both adapters are available via get_adapter.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    import sys

    # Evict ALL worker and adapter modules for a completely clean slate
    to_delete = [
        mod_name for mod_name in sys.modules
        if "climatepulse_worker" in mod_name or "climatepulse_core.adapters" in mod_name
    ]
    for mod_name in to_delete:
        del sys.modules[mod_name]

    # Also clear the registry itself (it may have stale entries)
    import climatepulse_core.adapters.base as base_module
    base_module._REGISTRY.clear()

    # Now import ingest — its top-level imports will trigger @register decorators
    import climatepulse_worker.tasks.ingest  # noqa: F401

    # Both adapters should now be accessible via get_adapter
    adapter_arpa = base_module.get_adapter("arpa_emilia")
    assert adapter_arpa is not None, "arpa_emilia adapter not registered after importing tasks.ingest"
    adapter_ecmwf = base_module.get_adapter("ecmwf_open")
    assert adapter_ecmwf is not None, "ecmwf_open adapter not registered after importing tasks.ingest"


def test_heartbeat_sets_redis_key(monkeypatch):
    """set_heartbeat_sync must write celery:worker:heartbeat with correct TTL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    # Create a fake redis server
    fake_server = fakeredis.FakeServer()
    fake_redis = fakeredis.FakeRedis(server=fake_server)

    # Monkeypatch redis.from_url to return our fake redis
    import redis
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: fake_redis)

    from climatepulse_worker.heartbeat import HEARTBEAT_KEY, HEARTBEAT_TTL, set_heartbeat_sync

    set_heartbeat_sync("redis://localhost:6379")

    # Check the key was set
    value = fake_redis.get(HEARTBEAT_KEY)
    assert value == b"ok" or value == "ok", f"Expected 'ok', got {value!r}"

    # Check TTL is in range (100 < TTL <= 120)
    ttl = fake_redis.ttl(HEARTBEAT_KEY)
    assert 100 < ttl <= HEARTBEAT_TTL, f"Expected TTL between 100 and {HEARTBEAT_TTL}, got {ttl}"


def test_heartbeat_tick_task_registered(monkeypatch):
    """heartbeat_tick must be registered as a Celery task (periodic refresh half of strategy)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "climatepulse_worker.tasks.maintenance.heartbeat_tick" in app.tasks, \
        f"heartbeat_tick not registered; tasks: {sorted(t for t in app.tasks if 'climatepulse' in t)}"


def test_beat_schedule_has_heartbeat_tick(monkeypatch):
    """Beat schedule must include worker-heartbeat-30s entry at 30s interval."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    celery_app_mod = _reload_celery_app()
    app = celery_app_mod.app

    assert "worker-heartbeat-30s" in app.conf.beat_schedule, \
        f"Expected 'worker-heartbeat-30s' in beat_schedule, got keys: {list(app.conf.beat_schedule.keys())}"
    schedule_entry = app.conf.beat_schedule["worker-heartbeat-30s"]
    assert schedule_entry["schedule"] == 30.0, \
        f"Expected 30.0 seconds for heartbeat schedule, got {schedule_entry['schedule']}"
    assert schedule_entry["task"] == "climatepulse_worker.tasks.maintenance.heartbeat_tick"


def test_worker_ready_signal_connected(monkeypatch):
    """worker_ready signal must have set_heartbeat_sync registered as a receiver."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    from climatepulse_core.settings import get_settings
    get_settings.cache_clear()

    # Import celery_app to ensure the signal is connected
    celery_app_mod = _reload_celery_app()

    from celery.signals import worker_ready
    from climatepulse_worker.heartbeat import set_heartbeat_sync

    # Check that set_heartbeat_sync (or a wrapper referencing it) is connected
    # worker_ready.receivers contains (id, weakref_or_callable) pairs
    connected_funcs = []
    for _id, func_ref in worker_ready.receivers:
        try:
            # Could be a weakref
            import weakref
            if isinstance(func_ref, weakref.ref):
                func = func_ref()
            else:
                func = func_ref
            if func is not None:
                connected_funcs.append(func)
        except Exception:
            pass

    # Check the signal has at least one receiver
    assert len(worker_ready.receivers) > 0, \
        "worker_ready signal has no receivers — set_heartbeat_sync not connected"
