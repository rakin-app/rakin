"""Error reporting to Sentry, on only when `SENTRY_DSN` is set.

Sentry's logging integration turns every `ERROR` log record into an event, so code
reports a failure by logging it (`logger.exception`), and the same line reaches stdout
whether Sentry is configured or not.

An event leaves the country (#373), so it carries no personal data: no request body,
query string (the request's or a breadcrumb's) or cookies, no local variables, and no
message from the database driver, whose text holds row values (a unique violation's
`Key (rut)=(…)`, the statement's parameters), nor from pydantic, whose text quotes the
`input_value`. Those messages become their SQLSTATE and constraint name, or the fields
that failed validation, wherever they appear: an exception's value, or a log message
that quotes the exception.
"""

import logging
import re
from collections.abc import Callable
from typing import Any, Protocol, cast

import asyncpg
import pydantic_core
import sentry_sdk
from sentry_sdk.types import Breadcrumb, BreadcrumbHint, Event, Hint


class SentryConfig(Protocol):
    """What Sentry needs from a service's settings (`Settings`, `BackupSettings`)."""

    @property
    def sentry_dsn(self) -> str: ...

    @property
    def environment(self) -> str: ...

    @property
    def sentry_environment(self) -> str: ...


def init_sentry(settings: SentryConfig, **options: Any) -> bool:
    """Start the Sentry client if a DSN is configured; whether it did.

    A `before_send` or `before_breadcrumb` in `options` runs after this module's own, on
    what it already scrubbed.
    """
    if not settings.sentry_dsn:
        return False
    before_send = then(scrub, options.pop("before_send", None))
    before_breadcrumb = then(scrub_breadcrumb, options.pop("before_breadcrumb", None))
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        # `SENTRY_ENVIRONMENT` tells staging from production, both `production` here.
        environment=settings.sentry_environment or settings.environment,
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
        before_send=before_send,
        before_breadcrumb=before_breadcrumb,
        **options,
    )
    return True


def then[T](
    first: Callable[[T, Hint], T], after: Callable[[T, Hint], T | None] | None
) -> Callable[[T, Hint], T | None]:
    """`first`, followed by `after` when there is one."""
    if after is None:
        return first
    return lambda item, hint: after(first(item, hint), hint)


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
    exc = exc_info[1] if exc_info else None
    withhold_messages(fields.get("exception", {}).get("values", []), exc)
    logentry = fields.get("logentry")
    if logentry is not None:
        clean = unquote(quoted_by(hint.get("log_record"), exc))
        for key in ("message", "formatted"):
            logentry[key] = clean(logentry.get(key))
        params = logentry.get("params")
        if isinstance(params, dict):
            logentry["params"] = {k: clean(v) for k, v in params.items()}
        elif isinstance(params, list | tuple):
            logentry["params"] = [clean(p) for p in params]
    return event


def scrub_breadcrumb(crumb: Breadcrumb, hint: BreadcrumbHint) -> Breadcrumb:
    """`before_breadcrumb`: a log record kept as a breadcrumb, which every later event
    carries, quotes no exception's withheld text either."""
    record = hint.get("log_record")
    if isinstance(record, logging.LogRecord):
        exc = record.exc_info[1] if record.exc_info else None
        crumb["message"] = unquote(quoted_by(record, exc))(crumb.get("message"))
    return crumb


def withhold_messages(values: list[dict[str, Any]], exc: BaseException | None) -> None:
    """Replace the text of each withheld exception in `values` with its `summary`.

    The SDK reports `exc`'s whole chain (cause or context), one value per exception;
    each is matched to the exception it came from by module and qualified type name, in
    order. A value from a withheld module left unmatched loses its text all the same.
    """
    replacements = [(type(e).__module__, type(e).__qualname__, text) for e, text in withheld(exc)]
    for value in values:
        if not str(value.get("module")).startswith(WITHHELD_MODULES):
            continue
        value["value"] = WITHHELD
        for i, (module, name, text) in enumerate(replacements):
            if value.get("module") == module and value.get("type") == name:
                value["value"] = text
                del replacements[i]
                break


def quoted_by(record: object, exc: BaseException | None) -> list[BaseException]:
    """The exceptions a log record can quote: its own (`exc`) and those passed as a
    parameter, to `%s` them."""
    args = getattr(record, "args", None) or ()
    args = args.values() if isinstance(args, dict) else args
    return [e for e in (exc, *args) if isinstance(e, BaseException)]


def unquote(quoted: list[BaseException]) -> Callable[[Any], Any]:
    """What turns the text of each withheld exception in `quoted`'s chains, as `str` or
    `repr`, into its `summary` wherever a string quotes it: a log message written with
    `%s` or an f-string, or a parameter the SDK has already turned into a string."""
    found = [pair for exc in quoted for pair in withheld(exc)]
    texts = sorted(
        {original: text for e, text in found for original in (repr(e), str(e)) if original}.items(),
        key=lambda pair: -len(pair[0]),
    )

    def clean(item: Any) -> Any:
        if not isinstance(item, str):
            return item
        for original, text in texts:
            item = item.replace(original, text)
        return item

    return clean


def withheld(exc: BaseException | None) -> list[tuple[BaseException, str]]:
    """Each exception in `exc`'s chain from a withheld module, with its `summary`."""
    found: list[tuple[BaseException, str]] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__module__.startswith(WITHHELD_MODULES):
            found.append((exc, summary(exc)))
        exc = exc.__cause__ or exc.__context__
    return found


URL_QUERY = re.compile(r"(\w+://[^\s?#\"']*)[?#][^\s\"']*")
# The database driver and its wrapper quote row values; pydantic quotes `input_value`.
WITHHELD_MODULES = ("asyncpg", "sqlalchemy", "pydantic", "pydantic_core")
WITHHELD = "(message withheld)"


def summary(exc: BaseException) -> str:
    """What of `exc` names no one: a database error's SQLSTATE and constraint name, or
    which fields failed validation and why."""
    if isinstance(exc, pydantic_core.ValidationError):
        failed = ", ".join(
            f"{'.'.join(map(str, error['loc'])) or '(root)'} {error['type']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        return f"{exc.title}: {failed} {WITHHELD}"
    while not isinstance(exc, asyncpg.PostgresError):
        inner = getattr(exc, "orig", None) or exc.__cause__
        if inner is None:
            sqlstate = getattr(exc, "sqlstate", None)
            return f"sqlstate={sqlstate} {WITHHELD}" if sqlstate else WITHHELD
        exc = inner
    return f"sqlstate={exc.sqlstate} constraint={exc.constraint_name} {WITHHELD}"
