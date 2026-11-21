"""The `month_summary` job: each gym's month, once it has closed, is kept as numbers
only, so Resumen del mes still reads it after the log purges (#506).

On the 1st, for every gym, it counts the month that just closed by #505's rules
(`app.month_figures`) and writes each `Figure` to `gym_month_figure` (migration 0082),
with `RULES_VERSION` and no person in any of it. It also writes the debt the month
closed with: what Active memberships owe on overdue periods (`v_overdue`), read on that
run, since the view only knows today. It runs before `billing` and `lapse`, so the
debt is read before the new month bills or lapses anyone.

The debt is written only when the run's day is the gym's real today, the 1st on its
own clock. The runner replays owed days and retries failed ones (`app.jobs.runner`), so
the run for the 1st can happen on the 3rd; that run keeps the figures, which are
counted from rows, but not the debt, which would be the 3rd's and not the month's
close.

A month is written once. A gym with any figure of the month already kept is left
alone, so a second run on the 1st writes nothing, and nor does any later day: the page
reads what was kept, under the rules it was counted under. A gym the 1st did not reach,
one suspended then, is kept on its first run of the month, without the closing debt,
which by then would be another day's. A month before the gym's first is not written.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do. The
run date is the runner's, in `JOBS_TIMEZONE`, as for billing, but whether a gym's month
has ended is asked of the gym's own clock (`gym.timezone`): a gym still in the closed
month, one west of the runner, is left for the next day's run, which keeps it then.
That run's day is no longer the gym's 1st, so such a gym keeps no closing debt that
month; for Chile's gyms, on the runner's timezone, the two clocks agree.

The `month_summary_email` job (#507) emails each gym's titular the month kept, from
the figures stored, the page's own (`app.schemas.summary.month_summary`), so the email
and the page never disagree. It runs after the statements and the overdue emails, on
the first `EMAIL_WITHIN_DAYS` days of the month: the 1st for a gym kept then, the day it
is kept for one the 1st did not reach, and never weeks late. A gym's month is emailed
once: one with a `monthly_summary` row in `message_log` to the titular's address that
was sent, or suppressed by an unsubscribe, is left alone, and one that failed is tried
again on the next run. An operator can send one gym's month now, to check a real inbox
(`app.jobs.month_summary_email`).
No email goes for a month with nothing in it (`has_news`), to a gym with it turned off
in Ajustes (`summary_email`), or to a titular with no address. As for the statements,
each gym is read in its savepoint and the emails go once every gym has been read.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import asyncpg

from app.domain.dates import add_months, local_date
from app.domain.value_summary import REQUIRED_FIGURES, RULES_VERSION, Figure
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.month_figures import asyncpg_rows, count_month, overdue_now
from app.notices import MONTHLY_SUMMARY, Notice, Notices
from app.schemas.gym import Channels, summary_email_on
from app.schemas.summary import has_news, month_summary, partial_since

logger = logging.getLogger(__name__)

NAME = "month_summary"

# RLS holds `gym` and `gym_month_figure` to the gym in `app.gym_id`.
GYM = """
SELECT date_trunc('month', created_at AT TIME ZONE timezone)::date AS first_month, timezone
FROM gym
"""
KEPT = "SELECT EXISTS (SELECT FROM gym_month_figure WHERE month = $1)"
INSERT = """
INSERT INTO gym_month_figure (gym_id, month, figure, value, rules_version)
SELECT current_setting('app.gym_id')::uuid, $1, f.figure, f.value, $4
FROM unnest($2::text[], $3::bigint[]) AS f (figure, value)
ON CONFLICT (gym_id, month, figure) DO NOTHING
"""


def closed_month(day: date) -> date:
    """The first day of the month before `day`'s."""
    return add_months(day.replace(day=1), -1)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def keep_gym(conn: asyncpg.Connection, day: date, now: datetime) -> int:
    """Keep the month before `day`'s of the gym in `app.gym_id`, unless it is kept
    already, the gym is newer than it, or the month has not ended on the gym's clock at
    `now`; the number of figures written."""
    month = closed_month(day)
    gym = await conn.fetchrow(GYM)
    gym_today = local_date(now, gym["timezone"])
    if gym_today < add_months(month, 1) or month < gym["first_month"]:
        return 0
    if await conn.fetchval(KEPT, month):
        return 0
    rows = asyncpg_rows(conn)
    figures: dict[Figure, int] = dict(await count_month(rows, month))
    if day.day == 1 and day == gym_today:
        figures[Figure.OVERDUE_CLP] = await overdue_now(rows)
    names = sorted(figures)
    await conn.execute(INSERT, month, names, [figures[n] for n in names], RULES_VERSION)
    return len(names)


async def keep_months(
    conn: asyncpg.Connection, day: date, clock: Callable[[], datetime] = utc_now
) -> bool:
    """Keep the closed month in every gym, each by its own clock, read from `clock` as
    the job reaches it; `False` if any failed, whose work alone is rolled back."""

    async def work(gym_conn: asyncpg.Connection, on: date) -> int:
        return await keep_gym(gym_conn, on, clock())

    return await each_gym(
        conn,
        day,
        work,
        job=NAME,
        logger=logger,
        failure="keeping a gym's closed month failed",
    )


JOB = Job(NAME, keep_months)


# --- the email (#507) ------------------------------------------------------------------

EMAIL_NAME = "month_summary_email"

# The first days of a month the one before it is emailed on: a gym the 1st did not
# reach is emailed the day its month is kept, unless that is weeks later.
EMAIL_WITHIN_DAYS = 7

# RLS holds `gym`, `gym_month_figure`, `staff`, `gym_person` and `message_log` to the
# gym in `app.gym_id`.
GYM_FOR_EMAIL = """
SELECT g.id, g.name, g.settings, (g.created_at AT TIME ZONE g.timezone)::date AS since
FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
"""
KEPT_FIGURES = "SELECT figure, value FROM gym_month_figure WHERE month = $1"
TITULAR = """
SELECT gp.person_id, gp.name, gp.email
FROM staff s JOIN gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
WHERE s.account_holder
LIMIT 1
"""
# Sent to the titular's address, or suppressed by an unsubscribe: either way, done for
# the month. A copy an operator sent elsewhere to check it (`app.jobs.month_summary_email`)
# does not count.
EMAILED = """
SELECT EXISTS (
    SELECT FROM message_log
    WHERE channel = 'email' AND template = $1 AND status IN ('sent', 'suppressed')
      AND payload ->> 'month' = $2 AND lower(to_address) = lower($3)
)
"""


# Why a month has no email (`month_notice`).
NOT_KEPT = "the month is not kept"
NO_NEWS = "nothing happened in the month"
NO_TITULAR_EMAIL = "the titular has no email"


def _json(value: str | dict[str, Any] | None) -> Any:
    # asyncpg hands `jsonb` over as its text, unless the connection has a codec for it.
    if value is None:
        return {}
    return json.loads(value) if isinstance(value, str) else value


async def gym_settings(conn: asyncpg.Connection) -> Any:
    """The `gym.settings` of the gym in `app.gym_id`."""
    gym = await conn.fetchrow(GYM_FOR_EMAIL)
    return _json(gym["settings"])


async def emailed(conn: asyncpg.Connection, month: date, to: str) -> bool:
    """Whether `month`'s email has gone to `to`, or been suppressed, in the gym in
    `app.gym_id`."""
    return bool(await conn.fetchval(EMAILED, MONTHLY_SUMMARY.name, month.isoformat(), to))


async def month_notice(conn: asyncpg.Connection, month: date) -> Notice | str:
    """The email of `month` to the titular of the gym in `app.gym_id`, from what was
    kept of it, whether or not it went already or the gym turned it off; else why there
    is none."""
    gym = await conn.fetchrow(GYM_FOR_EMAIL)
    settings = _json(gym["settings"])
    rows = await conn.fetch(KEPT_FIGURES, month)
    kept = {Figure(r["figure"]): r["value"] for r in rows if r["figure"] in Figure}
    # Not kept yet, or kept without a figure the page would count again for.
    if not kept.keys() >= REQUIRED_FIGURES:
        return NOT_KEPT
    summary = month_summary(
        kept,
        month=month,
        months=[month],
        since=partial_since(gym["since"], month),
        whatsapp=Channels.model_validate(settings.get("channels", {})).whatsapp,
        kept=None,
    )
    if not has_news(summary):
        return NO_NEWS
    titular = await conn.fetchrow(TITULAR)
    if titular is None or not titular["email"]:
        return NO_TITULAR_EMAIL
    return Notice(
        MONTHLY_SUMMARY,
        to=titular["email"],
        person_id=titular["person_id"],
        gym_id=gym["id"],
        context={
            "name": titular["name"],
            "gym": gym["name"],
            "month": month,
            "summary": summary.model_dump(exclude={"month", "months", "kept"}),
        },
    )


async def summary_notice(conn: asyncpg.Connection, day: date) -> Notice | None:
    """The email of the month before `day`'s to the titular of the gym in `app.gym_id`,
    from what was kept of it; `None` when there is none to send."""
    month = closed_month(day)
    if not summary_email_on(await gym_settings(conn)):
        return None
    notice = await month_notice(conn, month)
    if isinstance(notice, str):
        if notice == NO_TITULAR_EMAIL:
            logger.info("month summary: no titular email to send it to")
        return None
    if await emailed(conn, month, notice.to):
        return None
    return notice


def email_job(notices: Notices) -> Job:
    """The email job, sending through `notices`."""

    async def run(conn: asyncpg.Connection, day: date) -> bool:
        if day.day > EMAIL_WITHIN_DAYS:
            return True
        due: list[Notice] = []

        async def read_gym(gym_conn: asyncpg.Connection, on: date) -> None:
            notice = await summary_notice(gym_conn, on)
            if notice is not None:
                due.append(notice)

        complete = await each_gym(
            conn,
            day,
            read_gym,
            job=EMAIL_NAME,
            logger=logger,
            failure="reading a gym's month summary email failed",
        )
        for notice in due:
            # Never raises: a notice it could not send is a `failed` row, tried again
            # on the next run.
            await notices.send(notice)
        return complete

    return Job(EMAIL_NAME, run)
