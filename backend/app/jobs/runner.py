"""Run each job once per day, catching up missed days in order (see `app.jobs`)."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

import asyncpg

logger = logging.getLogger(__name__)

# Held for the whole run, on the runner's own connection; released when it closes.
LOCK = "SELECT pg_try_advisory_lock(hashtext('rakin.jobs'))"

# Every day from the job's first row to today without a succeeded one. A job with no
# rows owes only today.
OWED = """
SELECT day::date
FROM generate_series(
    COALESCE((SELECT min(run_date) FROM job_run WHERE job_name = $1), $2::date),
    $2::date,
    interval '1 day'
) AS day
WHERE NOT EXISTS (
    SELECT FROM job_run
    WHERE job_name = $1 AND run_date = day::date AND status = 'succeeded'
)
ORDER BY 1
"""

# A failed row, or a running one left by a dead runner, is taken over; a succeeded one
# is not, and returns no id.
CLAIM = """
INSERT INTO job_run (job_name, run_date, status) VALUES ($1, $2, 'running')
ON CONFLICT (job_name, run_date) DO UPDATE
    SET status = 'running', started_at = now(), finished_at = NULL
    WHERE job_run.status <> 'succeeded'
RETURNING id
"""

FINISH = "UPDATE job_run SET status = $2, finished_at = now() WHERE id = $1"


@dataclass(frozen=True)
class Job:
    name: str
    # Runs inside the transaction that marks the day succeeded; raise to fail it.
    run: Callable[[asyncpg.Connection, date], Awaitable[None]]


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Another runner held the lock, so this one did nothing.
    LOCKED = "locked"


@dataclass
class Report:
    outcome: Outcome = Outcome.SUCCEEDED
    # Each (job name, day) run, in the order they ran; a failure is the last one.
    ran: list[tuple[str, date]] = field(default_factory=list)


async def run_due(conn: asyncpg.Connection, jobs: Sequence[Job], today: date) -> Report:
    """Run every job for every day up to `today` it has not yet succeeded on."""
    names = [job.name for job in jobs]
    if len(set(names)) != len(names):
        raise ValueError(f"job names must be unique: {names}")

    if not await conn.fetchval(LOCK):
        logger.info("another job runner is working; nothing to do")
        return Report(Outcome.LOCKED)

    owed: dict[str, set[date]] = {
        job.name: {row[0] for row in await conn.fetch(OWED, job.name, today)} for job in jobs
    }
    report = Report()
    for day in sorted(set().union(*owed.values())):
        for job in jobs:
            if day not in owed[job.name]:
                continue
            report.ran.append((job.name, day))
            if not await _run_one(conn, job, day):
                report.outcome = Outcome.FAILED
                return report
    return report


async def _run_one(conn: asyncpg.Connection, job: Job, day: date) -> bool:
    log = {"job": job.name, "run_date": day.isoformat()}
    # Committed on its own, so the row says `running` while the job works.
    run_id: uuid.UUID | None = await conn.fetchval(CLAIM, job.name, day)
    if run_id is None:  # succeeded meanwhile: only a runner without the lock could
        return True

    started = time.monotonic()
    try:
        async with conn.transaction():
            await job.run(conn, day)
            await conn.execute(FINISH, run_id, "succeeded")
    except Exception:
        await conn.execute(FINISH, run_id, "failed")
        logger.exception("job failed", extra={**log, "seconds": _since(started)})
        return False
    logger.info("job succeeded", extra={**log, "seconds": _since(started)})
    return True


def _since(started: float) -> float:
    return round(time.monotonic() - started, 3)
