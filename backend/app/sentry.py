"""Error reporting to Sentry, on only when `SENTRY_DSN` is set.

Sentry's logging integration turns every `ERROR` log record into an event, so code
reports a failure by logging it (`logger.exception`), and the same line reaches stdout
whether Sentry is configured or not.

An event leaves the country (#373), so it carries no personal data: no request body,
query string (the request's or a breadcrumb's) or cookies, no local variables, and no
message from the database driver, whose text holds row values (a unique violation's
`Key (rut)=(…)`, the statement's parameters). Those messages become their SQLSTATE and
constraint name.
"""

import re
from typing import Any, Protocol, cast

import asyncpg
import sentry_sdk
from sentry_sdk.types import Event, Hint


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
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        # `send_default_pii=False`, in the form that replaces it (it warns since 2.74).
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "url_query_params": {"mode": "off"},
            "http_bodies": [],
            "stack_frame_variables": False,
            "database_query_data": False,
        },
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub,
        **options,
    )
    return True


def scrub(event: Event, hint: Hint) -> Event:
    """`before_send`: drop what can name a person from `event`."""
    fields = cast(dict[str, Any], event)
    request = fields.get("request")
    if request is not None:
        for key in ("data", "query_string", "cookies"):
            request.pop(key, None)
        headers = request.get("headers")
        if headers is not None:
            for name in [n for n in headers if n.lower() == "cookie"]:
                del headers[name]
    # Outgoing requests (httpx, the stdlib) leave breadcrumbs with their query string, in
    # the crumb's data and in httpx's own log line ("HTTP Request: POST https://…?…").
    for crumb in fields.get("breadcrumbs", {}).get("values", []):
        if isinstance(crumb.get("message"), str):
            crumb["message"] = URL_QUERY.sub(r"\1", crumb["message"])
        data = crumb.get("data")
        if data is not None:
            data.pop("http.query", None)
            data.pop("http.fragment", None)
    exc_info = hint.get("exc_info")
    withhold_driver_messages(
        fields.get("exception", {}).get("values", []), exc_info[1] if exc_info else None
    )
    return event


def withhold_driver_messages(values: list[dict[str, Any]], exc: BaseException | None) -> None:
    """Replace the text of each database error in `values` with its SQLSTATE and constraint.

    The SDK reports `exc`'s whole chain (cause or context), one value per exception;
    each is matched to the exception it came from by module and qualified type name, in
    order. A value from asyncpg or SQLAlchemy left unmatched loses its text all the same.
    """
    replacements: list[tuple[str, str, str]] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        kind = type(exc)
        if kind.__module__.startswith(DRIVER_MODULES):
            replacements.append((kind.__module__, kind.__qualname__, summary(exc)))
        exc = exc.__cause__ or exc.__context__
    for value in values:
        if not str(value.get("module")).startswith(DRIVER_MODULES):
            continue
        value["value"] = WITHHELD
        for i, (module, name, text) in enumerate(replacements):
            if value.get("module") == module and value.get("type") == name:
                value["value"] = text
                del replacements[i]
                break


URL_QUERY = re.compile(r"(\w+://[^\s?#\"']*)[?#][^\s\"']*")
DRIVER_MODULES = ("asyncpg", "sqlalchemy")
WITHHELD = "(message withheld)"


def summary(exc: BaseException) -> str:
    """`exc`'s SQLSTATE and constraint name, the parts of a database error that name no one."""
    while not isinstance(exc, asyncpg.PostgresError):
        inner = getattr(exc, "orig", None) or exc.__cause__
        if inner is None:
            sqlstate = getattr(exc, "sqlstate", None)
            return f"sqlstate={sqlstate} {WITHHELD}" if sqlstate else WITHHELD
        exc = inner
    return f"sqlstate={exc.sqlstate} constraint={exc.constraint_name} {WITHHELD}"
