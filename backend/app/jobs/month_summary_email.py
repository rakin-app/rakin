"""`python -m app.jobs.month_summary_email`: send one gym's Resumen del mes for a closed
month now, to check a real inbox (#507), outside the job's first 7 days of the month.

    uv run python -m app.jobs.month_summary_email --slug sur --month 2026-10-01 \\
        [--to someone@example.cl]

It sends exactly the email `month_summary_email` would (`app.jobs.month_summary.
month_notice`), from what was kept of the month, through the normal mail path, so
staging's `MAIL_ALLOW` still applies, and records it in `message_log` as the job does.

Without `--to` it goes to the titular, and counts as the month's send: the job will not
send it again. It is refused when the gym turned the email off in Ajustes, or when the
month already went to the titular. With `--to` a copy goes to that address instead,
addressed as to the titular (their name, their unsubscribe link), and does not count:
the job still sends the titular theirs. Either way an unsubscribed titular's email is
recorded as `suppressed`, as the job's would be.

It exits 0 once the email is sent, 1 when it was refused, suppressed or failed, and
2 for no such gym or a malformed month.
"""

import argparse
import asyncio
import dataclasses
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import asyncpg

from app.db_bootstrap import to_dsn
from app.jobs.daily import mailing
from app.jobs.month_summary import emailed, gym_settings, month_notice
from app.notices import Notice, Notices, Outcome
from app.schemas.gym import summary_email_on
from app.settings import get_settings

NO_SUCH_GYM = "no gym has that slug"
TURNED_OFF = "the gym turned it off in Ajustes; send a copy with --to"
ALREADY_SENT = "it already went to the titular; send a copy with --to"


@dataclass(frozen=True)
class Request:
    slug: str
    # The month's first day.
    month: date
    # Where a copy goes instead of the titular.
    to: str | None = None


async def prepare(conn: asyncpg.Connection, request: Request) -> Notice | str:
    """The email `request` asks for, or why it is refused. As the owner: RLS holds it to
    the gym it names."""
    async with conn.transaction():
        found = await conn.fetchrow("SELECT id FROM auth_gym_by_slug($1)", request.slug)
        if found is None:
            return NO_SUCH_GYM
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(found["id"]))
        notice = await month_notice(conn, request.month)
        if isinstance(notice, str):
            return notice
        if request.to is not None:
            return dataclasses.replace(notice, to=request.to)
        if not summary_email_on(await gym_settings(conn)):
            return TURNED_OFF
        if await emailed(conn, request.month, notice.to):
            return ALREADY_SENT
        return notice


async def send(conn: asyncpg.Connection, notices: Notices, request: Request) -> Outcome | str:
    """Send the email `request` asks for: its outcome, or why it was refused."""
    notice = await prepare(conn, request)
    if isinstance(notice, str):
        return notice
    return await notices.send(notice)


def first_day(value: str) -> date:
    day = date.fromisoformat(value)
    if day.day != 1:
        raise ValueError("not a month's first day")
    return day


def parse(argv: Sequence[str] | None = None) -> Request:
    parser = argparse.ArgumentParser(
        description="Send one gym's Resumen del mes for a closed month now."
    )
    parser.add_argument("--slug", required=True, help="the gym's slug")
    parser.add_argument(
        "--month", required=True, type=first_day, help="the month's first day, YYYY-MM-01"
    )
    parser.add_argument("--to", help="send a copy here instead of to the titular")
    args = parser.parse_args(argv)
    return Request(slug=args.slug, month=args.month, to=args.to)


def main(argv: Sequence[str] | None = None) -> int:
    request = parse(argv)
    settings = get_settings()

    async def go() -> Outcome | str:
        conn = await asyncpg.connect(to_dsn(settings.migration_database_url))
        try:
            async with mailing(settings) as notices:
                return await send(conn, notices, request)
        finally:
            await conn.close()

    outcome = asyncio.run(go())
    if isinstance(outcome, Outcome):
        print(f"{outcome.value}: see message_log for {request.slug}, {request.month:%Y-%m}")
        return 0 if outcome is Outcome.SENT else 1
    print(f"not sent: {outcome}", file=sys.stderr)
    return 2 if outcome == NO_SUCH_GYM else 1


if __name__ == "__main__":
    raise SystemExit(main())
