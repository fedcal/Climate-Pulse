"""Shared pytest fixtures for unit tests.

Clears the adapter registry between tests to avoid pollution from
one test's registered adapters leaking into another test.
"""

import pytest

import climatepulse_core.adapters.base as _base_module


@pytest.fixture(autouse=True)
def clear_adapter_registry():
    """Reset the global adapter registry before and after each test."""
    original = dict(_base_module._REGISTRY)
    _base_module._REGISTRY.clear()
    yield
    _base_module._REGISTRY.clear()
    _base_module._REGISTRY.update(original)
