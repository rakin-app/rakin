"""`python -m app.jobs.daily`: run the nightly jobs that are due (see `app.jobs`).

Without `--every` it runs once and exits, non-zero if a job failed, for a cron entry.
With it, it stays up and runs again every that many seconds, which is how Compose's
`jobs` service runs it. A run that finds nothing owed does nothing, so running often
only shortens the wait between a day starting and its jobs running.
"""

import argparse
import asyncio
import contextlib
import logging
import signal
from collections.abc import Sequence
from datetime import UTC, date, datetime

import asyncpg

from app.db_bootstrap import to_dsn
from app.domain.dates import local_date
from app.jobs import billing, lapse
from app.jobs.runner import Job, Outcome, Report, run_due
from app.logging import configure_logging
from app.sentry import init_sentry
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# In the order they run on each day: a later job may rely on an earlier one's work.
JOBS: tuple[Job, ...] = (billing.JOB, lapse.JOB)


def today(settings: Settings) -> date:
    return local_date(datetime.now(UTC), settings.jobs_timezone)


async def run_once(settings: Settings, day: date, jobs: Sequence[Job]) -> Report:
    # The owner, as for the seed: RLS holds it to the gym each job sets.
    conn = await asyncpg.connect(to_dsn(settings.migration_database_url))
    try:
        return await run_due(conn, jobs, day)
    finally:
        await conn.close()


async def serve(settings: Settings, every: float, jobs: Sequence[Job]) -> None:
    """Run every `every` seconds until SIGTERM or SIGINT; a run in progress finishes."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    logger.info("job runner started", extra={"every_seconds": every})
    while not stop.is_set():
        try:
            await run_once(settings, today(settings), jobs)
        except Exception:
            # The database is down, say: the next run tries again.
            logger.exception("job runner failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), every)
    logger.info("job runner stopped")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the nightly jobs that are due.")
    when = parser.add_mutually_exclusive_group()
    when.add_argument(
        "--today",
        type=date.fromisoformat,
        help="run as if it were this date, YYYY-MM-DD (default: today in JOBS_TIMEZONE)",
    )
    when.add_argument(
        "--every",
        type=float,
        metavar="SECONDS",
        help="keep running, once every SECONDS, until stopped",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(settings)

    if args.every is not None:
        if args.every <= 0:
            parser.error("--every must be positive")
        asyncio.run(serve(settings, args.every, JOBS))
        return 0
    report = asyncio.run(run_once(settings, args.today or today(settings), JOBS))
    return 1 if report.outcome is Outcome.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
