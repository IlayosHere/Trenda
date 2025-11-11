"""Application configuration utilities."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

# Ensure environment variables are available as soon as the package is imported.
load_dotenv()


@dataclass(frozen=True)
class DatabaseConfig:
    """Immutable container for database connection parameters."""

    dbname: str
    user: str
    password: str
    host: str
    port: str
    options: str | None


@dataclass(frozen=True)
class ApiConfig:
    """Immutable container for API specific configuration."""

    allowed_origins: List[str]


@lru_cache(maxsize=1)
def get_database_config() -> DatabaseConfig:
    """Return database configuration from the current environment."""

    from os import getenv

    return DatabaseConfig(
        dbname=getenv("DB_NAME", "trenda"),
        user=getenv("DB_USER", "postgres"),
        password=getenv("DB_PASSWORD", ""),
        host=getenv("DB_HOST", "localhost"),
        port=getenv("DB_PORT", "5432"),
        options=getenv("DB_OPTIONS", "-c search_path=trenda"),
    )


@lru_cache(maxsize=1)
def get_api_config() -> ApiConfig:
    """Return API specific configuration derived from environment variables."""

    from os import getenv

    origins = getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:8080",
    )
    allowed = [origin.strip() for origin in origins.split(",") if origin.strip()]
    return ApiConfig(allowed_origins=allowed)
