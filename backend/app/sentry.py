"""Error reporting to Sentry, on only when `SENTRY_DSN` is set.

Sentry's logging integration turns every `ERROR` log record into an event, so code
reports a failure by logging it (`logger.exception`), and the same line reaches stdout
whether Sentry is configured or not.
"""

from typing import Any

import sentry_sdk

from app.settings import Settings


def init_sentry(settings: Settings, **options: Any) -> bool:
    """Start the Sentry client if a DSN is configured; whether it did."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, **options)
    return True
