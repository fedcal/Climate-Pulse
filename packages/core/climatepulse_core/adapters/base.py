"""WeatherSourceAdapter ABC, decorator-based registry, FetchWindow, and SourceMeta.

This module defines the contract every data-source adapter must implement.
Plan 04 will add concrete adapters (ArpaeAdapter, EcmwfOpenAdapter) that
subclass WeatherSourceAdapter. This module is the single source of truth
for the adapter interface.

Usage:
    from climatepulse_core.adapters.base import (
        register, get_adapter, all_source_ids,
        WeatherSourceAdapter, FetchWindow, SourceMeta,
    )
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator, Callable

if TYPE_CHECKING:
    from climatepulse_core.domain.models import RawObservation, Station

# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type["WeatherSourceAdapter"]] = {}


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def register(source_id: str) -> Callable:
    """Class decorator that registers a WeatherSourceAdapter subclass.

    Sets cls.source_id = source_id and adds cls to the module-level _REGISTRY.
    Raises ValueError if the source_id is already registered (duplicate guard).

    Example:
        @register("arpa_emilia")
        class ArpaeAdapter(WeatherSourceAdapter):
            ...
    """

    def decorator(cls: type["WeatherSourceAdapter"]) -> type["WeatherSourceAdapter"]:
        if source_id in _REGISTRY:
            raise ValueError(
                f"Duplicate source_id: '{source_id}' is already registered by "
                f"{_REGISTRY[source_id].__qualname__}"
            )
        cls.source_id = source_id  # type: ignore[assignment]
        _REGISTRY[source_id] = cls
        return cls

    return decorator


def get_adapter(source_id: str) -> "WeatherSourceAdapter":
    """Return a NEW instance of the adapter registered for source_id.

    Raises KeyError if source_id is not registered.
    Returns a fresh instance each call (not cached) so callers can configure
    per-task state independently.
    """
    if source_id not in _REGISTRY:
        raise KeyError(f"Unknown source_id: '{source_id}' — is the adapter imported?")
    return _REGISTRY[source_id]()


def all_source_ids() -> list[str]:
    """Return a sorted list of all registered source identifiers."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchWindow:
    """Closed time window for an ingestion request.

    Both `since` and `until` must be timezone-aware UTC datetimes.
    Raises ValueError if:
      - either datetime is naive (no tzinfo)
      - since > until (inverted range)
    """

    since: datetime  # tz-aware UTC inclusive start
    until: datetime  # tz-aware UTC inclusive end

    def __post_init__(self) -> None:
        if self.since.tzinfo is None or self.until.tzinfo is None:
            raise ValueError(
                "FetchWindow requires tz-aware datetimes; "
                f"got since={self.since!r}, until={self.until!r}"
            )
        if self.since > self.until:
            raise ValueError(
                f"FetchWindow.since must be <= until; "
                f"got since={self.since.isoformat()}, until={self.until.isoformat()}"
            )


@dataclass(frozen=True)
class SourceMeta:
    """Licensing and attribution metadata for a data source.

    Stored alongside every ingested batch so downstream consumers know
    the provenance and license obligations of each observation.
    """

    source_id: str           # 'arpa_emilia', 'ecmwf_open'
    name: str                # human-readable display name
    license: str             # SPDX identifier or URL
    attribution: str         # required attribution text
    terms_url: str | None    # URL to terms of service, or None
    default_qc_flag: int     # QcFlag value applied to observations absent explicit QC


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class WeatherSourceAdapter(ABC):
    """Abstract base for all weather data source adapters.

    Concrete adapters MUST:
      1. Be decorated with @register("<source_id>")
      2. Declare a class-level `cadence_seconds: int`
      3. Implement the three abstract methods below

    The adapter's `is_grid_based` flag determines which hypertable the
    IdempotentWriter routes observations to:
      - False (default): station-based `observations` table (ARPAE)
      - True: grid-based `gridded_observations` table (ECMWF)
    """

    source_id: str             # set by @register decorator
    cadence_seconds: int       # seconds between normal ingest cycles; must be set on subclass
    polite_delay_ms: int = 1000  # minimum inter-request delay in ms
    is_grid_based: bool = False  # True for ECMWF-style grid sources

    @abstractmethod
    async def discover_stations(self) -> list["Station"]:
        """Return the full station / grid-point catalog for this source.

        Called once per cadence cycle (or daily for slowly-changing catalogs).
        For grid-based adapters, returns grid-point metadata instead.
        """
        ...

    @abstractmethod
    async def fetch(self, window: FetchWindow) -> AsyncIterator["RawObservation"]:
        """Yield RawObservation objects for all observations in [window.since, window.until].

        MUST be idempotent: fetching the same window twice produces the same
        observations (no side effects). The Writer handles deduplication via
        ON CONFLICT DO UPDATE, but callers should not rely on that for business logic.

        Yields RawObservation with:
          - observed_at: tz-aware UTC datetime
          - source_id: matches self.source_id
          - wmo_code: one of the 7 canonical WMO codes (from normalize.wmo)
          - value: raw value in the adapter's native unit (normalizer converts to SI)
        """
        ...

    @abstractmethod
    def source_meta(self) -> SourceMeta:
        """Return licensing and attribution metadata for this source.

        Called once at adapter construction; result is cached by the caller.
        """
        ...
