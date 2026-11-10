"""Error reporting to Sentry, on only when `SENTRY_DSN` is set.

Sentry's logging integration turns every `ERROR` log record into an event, so code
reports a failure by logging it (`logger.exception`), and the same line reaches stdout
whether Sentry is configured or not.
"""

from typing import Any, Protocol

import sentry_sdk


class SentryConfig(Protocol):
    """What Sentry needs from a service's settings (`Settings`, `BackupSettings`)."""

    @property
    def sentry_dsn(self) -> str: ...

    @property
    def environment(self) -> str: ...


def init_sentry(settings: SentryConfig, **options: Any) -> bool:
    """Start the Sentry client if a DSN is configured; whether it did."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, **options)
    return True
