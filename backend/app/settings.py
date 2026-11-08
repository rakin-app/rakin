"""Application settings, loaded from the environment (and `.env` if present).

Every field here must be listed in the repo-root `.env.example` with a working
local default; `tests/test_settings.py` enforces that.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root `.env`, shared with Docker Compose. Real environment variables win.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # The API connects as a login user in the `rakin_app` role, which RLS applies to.
    database_url: str = "postgresql+asyncpg://rakin_api:rakin_api@localhost:5432/rakin"
    # Migrations run as the role that owns the tables.
    migration_database_url: str = "postgresql+asyncpg://rakin:rakin@localhost:5432/rakin"
    db_pool_size: int = Field(default=5, ge=1)
    healthz_db_timeout_seconds: float = Field(default=2.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
