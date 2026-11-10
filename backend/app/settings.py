"""Application settings, loaded from the environment (and `.env` if present).

Every field here must be listed in the repo-root `.env.example` with a working
local default; `tests/test_settings.py` enforces that.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root `.env`, shared with Docker Compose. Real environment variables win.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Signs local-disk upload URLs (and, later, magic links). Fine on a laptop, refused in
# production.
LOCAL_SECRET_KEY = "local-only-secret-change-me"
# Encrypts sensitive custom-field values at rest. Its own key, not `SECRET_KEY`, so
# rotating that after a leak never destroys them; refused in production too.
LOCAL_FIELD_ENCRYPTION_KEY = "local-only-field-key-change-me"
# Dot-separated DNS labels: a bare host name, no scheme, port or path.
HOST_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # The API connects as a login user in the `rakin_app` role, which RLS applies to.
    database_url: str = "postgresql+asyncpg://rakin_api:rakin_api@localhost:5432/rakin"
    # Migrations run as the role that owns the tables. Both users are created by
    # `python -m app.db_bootstrap`.
    migration_database_url: str = (
        "postgresql+asyncpg://rakin_owner:rakin_owner@localhost:5432/rakin"
    )
    db_pool_size: int = Field(default=5, ge=1)
    healthz_db_timeout_seconds: float = Field(default=2.0, gt=0)
    secret_key: str = Field(default=LOCAL_SECRET_KEY, min_length=16)
    field_encryption_key: str = Field(default=LOCAL_FIELD_ENCRYPTION_KEY, min_length=16)
    # Where the browser reaches the app (Caddy), for absolute links the API hands out.
    public_base_url: str = "http://localhost:8080"
    # Each gym is served at `<slug>.<BASE_DOMAIN>` (`app.hosts`), on PUBLIC_BASE_URL's
    # scheme and port: `staging.rakin.app` serves `meta.staging.rakin.app`. Empty
    # serves every gym on PUBLIC_BASE_URL alone.
    base_domain: str = ""

    # Integrations (`app/integrations`): each picks an implementation by name. The
    # defaults need no network and no account, so a fresh instance works offline.
    mailer: Literal["console", "smtp"] = "console"
    mail_from: str = "Rakin <no-reply@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    # starttls on 587, tls (implicit) on 465, none only for a local relay.
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_timeout_seconds: float = Field(default=10.0, gt=0)

    messenger: Literal["wame"] = "wame"

    blob_store: Literal["local", "s3"] = "local"
    # Relative paths resolve against the working directory (`/srv` in Compose).
    blob_local_dir: Path = Path("var/blobs")
    blob_url_ttl_seconds: int = Field(default=900, ge=60, le=7 * 24 * 3600)
    s3_endpoint_url: str = "http://garage:3900"
    s3_public_endpoint_url: str = "http://localhost:3900"
    s3_region: str = "garage"
    s3_bucket: str = "rakin"
    s3_access_key_id: str = "GKd06e218c3fa3bb3f69e9d09e"
    s3_secret_access_key: str = "af635cf10ca8d78993f886624767e63600cb52fa8e7730c15d026ace93a3f341"

    payment_rail: Literal["none"] = "none"
    bank_feed: Literal["none"] = "none"
    # The join link's public form (`app.integrations.humancheck`): `turnstile` checks
    # each submission with Cloudflare Turnstile, with these keys.
    human_check: Literal["none", "turnstile"] = "none"
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # The nightly jobs (`app/jobs`): a day's run starts once the day has begun here.
    jobs_timezone: str = "America/Santiago"
    # Failed jobs are reported to Sentry when set (`app.sentry`); empty sends nothing.
    sentry_dsn: str = ""

    @field_validator("jobs_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r}") from None
        return value

    @field_validator("base_domain")
    @classmethod
    def _host_name(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if value and not HOST_NAME.fullmatch(value):
            raise ValueError(f"not a host name: {value!r} (no scheme, port or path)")
        return value

    @model_validator(mode="after")
    def _turnstile_has_its_keys(self) -> "Settings":
        if self.human_check == "turnstile" and not (
            self.turnstile_site_key.strip() and self.turnstile_secret_key.strip()
        ):
            raise ValueError(
                "human_check=turnstile needs TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY"
            )
        return self

    @model_validator(mode="after")
    def _no_local_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key == LOCAL_SECRET_KEY:
            raise ValueError("secret_key: set SECRET_KEY; the local default is public")
        if (
            self.environment == "production"
            and self.field_encryption_key == LOCAL_FIELD_ENCRYPTION_KEY
        ):
            raise ValueError(
                "field_encryption_key: set FIELD_ENCRYPTION_KEY; the local default is public"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
