"""Tests for WeatherSourceAdapter ABC, decorator registry, FetchWindow, and SourceMeta.

All tests use unique source_ids (suffixed with the test function name) to avoid
any cross-test pollution in the module-level registry, in addition to the
autouse fixture in conftest.py that clears the registry between tests.
"""

from datetime import datetime, timezone

import pytest

from climatepulse_core.adapters import (
    FetchWindow,
    RawObservation,
    SourceMeta,
    Station,
    WeatherSourceAdapter,
    all_source_ids,
    get_adapter,
    register,
)


# ---------------------------------------------------------------------------
# Helper: minimal concrete subclass for testing
# ---------------------------------------------------------------------------

def make_adapter_class(source_id_str: str):
    """Create a minimal concrete WeatherSourceAdapter subclass."""

    @register(source_id_str)
    class _MinimalAdapter(WeatherSourceAdapter):
        cadence_seconds = 900

        async def discover_stations(self):
            return []

        async def fetch(self, window):
            return
            yield  # make it an async generator

        def source_meta(self):
            return SourceMeta(
                source_id=source_id_str,
                name="Test",
                license="MIT",
                attribution="Test",
                terms_url=None,
                default_qc_flag=0,
            )

    return _MinimalAdapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_assigns_source_id_attribute():
    """@register sets class.source_id to the registered string."""
    cls = make_adapter_class("test_src_1")
    assert cls.source_id == "test_src_1"


def test_duplicate_registration_raises():
    """Registering the same source_id twice raises ValueError containing 'Duplicate'."""
    make_adapter_class("test_src_2")

    with pytest.raises(ValueError, match="Duplicate"):

        @register("test_src_2")
        class _Dup(WeatherSourceAdapter):
            cadence_seconds = 900

            async def discover_stations(self):
                return []

            async def fetch(self, window):
                return
                yield

            def source_meta(self):
                return SourceMeta(
                    source_id="test_src_2",
                    name="Dup",
                    license="MIT",
                    attribution="Dup",
                    terms_url=None,
                    default_qc_flag=0,
                )


def test_get_adapter_returns_fresh_instance():
    """Two calls to get_adapter for the same source_id return distinct objects."""
    make_adapter_class("test_src_3")
    instance_a = get_adapter("test_src_3")
    instance_b = get_adapter("test_src_3")
    assert instance_a is not instance_b


def test_unknown_source_raises_keyerror():
    """get_adapter with an unregistered source_id raises KeyError."""
    with pytest.raises(KeyError):
        get_adapter("nonexistent_source_xyz")


def test_all_source_ids_sorted():
    """all_source_ids() returns a sorted list of registered source ids."""
    make_adapter_class("zzz_source")
    make_adapter_class("aaa_source")
    make_adapter_class("mmm_source")

    ids = all_source_ids()
    assert ids == sorted(ids)
    assert "zzz_source" in ids
    assert "aaa_source" in ids
    assert "mmm_source" in ids


def test_abstract_cannot_instantiate():
    """WeatherSourceAdapter cannot be instantiated directly (ABC)."""
    with pytest.raises(TypeError):
        WeatherSourceAdapter()  # type: ignore[abstract]


def test_fetchwindow_rejects_naive_datetime():
    """FetchWindow raises ValueError when since or until has no tzinfo."""
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValueError):
        FetchWindow(since=naive, until=naive)


def test_fetchwindow_rejects_inverted_range():
    """FetchWindow raises ValueError when until < since."""
    t1 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        FetchWindow(since=t1, until=t2)


def test_fetchwindow_accepts_utc():
    """Valid tz-aware UTC FetchWindow constructs without error."""
    since = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    window = FetchWindow(since=since, until=until)
    assert window.since == since
    assert window.until == until
