"""Centralised application settings for Climate Pulse.

Loaded from environment variables or a .env file (pydantic-settings 2.x).
Redis DB allocation is declared as class constants so every module imports
from one place — prevents typos and eases future reconfiguration.

Usage:
    from climatepulse_core.settings import get_settings
    settings = get_settings()
    print(settings.redis_url)
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env file.

    Fields without defaults raise ValidationError at startup if not set,
    which is intentional — loud failure beats silent misconfiguration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------------------
    # Required (no default — fails loudly if missing)
    # ---------------------------------------------------------------------------
    database_url: str  # e.g. postgresql+asyncpg://user:pass@localhost:5432/db

    # ---------------------------------------------------------------------------
    # Optional (sensible defaults for local development)
    # ---------------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379"
    snapshot_dir: str = "/var/lib/climatepulse/snapshots"  # D-15 Docker volume default
    log_level: str = "INFO"
    environment: Literal["development", "production"] = "development"

    # ---------------------------------------------------------------------------
    # Redis DB allocation (class constants — do NOT change without updating
    # all consumers and the compose.yaml / documentation)
    # ---------------------------------------------------------------------------
    # DB 0: Celery broker (task queue)
    REDIS_DB_BROKER: int = 0
    # DB 1: Celery result backend
    REDIS_DB_RESULTS: int = 1
    # DB 2: pyrate-limiter per-host rate limit buckets (PoliteHttpClient)
    REDIS_DB_RATELIMIT: int = 2
    # DB 3: aiocache ETag/Last-Modified cache (PoliteHttpClient)
    REDIS_DB_ETAG: int = 3
    # DB 4: ING-14 per-source health metrics (last_successful_ingest_at)
    REDIS_DB_METRICS: int = 4


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call).

    Use this in application code instead of instantiating Settings() directly
    to ensure all modules share the same configuration state.

    In tests, call `get_settings.cache_clear()` before patching env vars.
    """
    return Settings()
