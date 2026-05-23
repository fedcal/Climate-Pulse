"""API-specific settings for the Climate Pulse FastAPI application.

Separate from climatepulse_core.settings because the API container does not
need snapshot_dir (D-22) or other worker-specific config.

Usage:
    from climatepulse_api.settings import get_api_settings
    settings = get_api_settings()
    print(settings.database_url)
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """API application settings loaded from environment / .env file.

    Fields without defaults raise ValidationError at startup if not set.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------------------
    # Required
    # ---------------------------------------------------------------------------
    database_url: str  # e.g. postgresql+asyncpg://user:pass@host:5432/db

    # ---------------------------------------------------------------------------
    # Optional
    # ---------------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379"
    environment: Literal["development", "production"] = "development"


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Return the singleton ApiSettings instance (cached after first call).

    In tests, call `get_api_settings.cache_clear()` before patching env vars.
    """
    return ApiSettings()
