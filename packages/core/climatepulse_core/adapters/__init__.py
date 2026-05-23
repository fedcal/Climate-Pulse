"""Adapter package — re-exports everything adapters need from one import.

Usage:
    from climatepulse_core.adapters import (
        WeatherSourceAdapter, register, get_adapter, all_source_ids,
        FetchWindow, SourceMeta, RawObservation, Station, Source, Variable, QcFlag,
    )
"""

from climatepulse_core.adapters.base import (
    FetchWindow,
    SourceMeta,
    WeatherSourceAdapter,
    all_source_ids,
    get_adapter,
    register,
)
from climatepulse_core.domain.models import (
    QcFlag,
    RawObservation,
    Source,
    Station,
    Variable,
)

__all__ = [
    "FetchWindow",
    "SourceMeta",
    "WeatherSourceAdapter",
    "all_source_ids",
    "get_adapter",
    "register",
    "QcFlag",
    "RawObservation",
    "Source",
    "Station",
    "Variable",
]
