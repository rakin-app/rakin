"""The nightly jobs and the runner that runs each of them once per day.

    uv run python -m app.jobs.daily                      # once, as a cron entry would
    uv run python -m app.jobs.daily --every 3600         # Compose's `jobs` service
    uv run python -m app.jobs.daily --today 2026-11-08   # as if it were that date

A `Job` is a name and an async function of a connection and a date. `run_due` runs
every job for every day it is owed, in date order: a day counts as done once
`job_run` holds a `succeeded` row for `(job_name, run_date)`, and a job owes every day
from its first `job_run` row to today that has none. So a run that finds nothing owed
does nothing, and a run after a week of downtime catches the week up, oldest day
first. A job that has never run starts today, not at some day in the past.

Each `(job, day)` runs in one transaction that also marks its `job_run` row
`succeeded`, so the work and the record of it commit together or not at all. A
failure rolls the work back, marks the row `failed`, logs the exception (which Sentry
receives when `SENTRY_DSN` is set) and stops the run there: later days, and later jobs
on the same day, may depend on it. The next run retries that day first. A job that
works in pieces (per gym, say) may instead roll back only a piece that broke, to a
savepoint, and return `False`: the rest of its work commits, and the day is failed,
logged and retried the same way, so the job must be safe to run again on it.

One runner works at a time, under a Postgres advisory lock; a second one exits
without doing anything. A `running` row found under the lock is therefore left by a
runner that died mid-job, and is run again.

Days are calendar dates in `JOBS_TIMEZONE`. The runner connects as the table owner,
as the seed does: RLS still holds it to one gym at a time, so a job that works per gym
sets `app.gym_id` (`set_config(..., true)`) for each, and treats the date as that
gym's local date.
"""

from app.jobs.runner import Job, Outcome, Report, run_due

__all__ = ["Job", "Outcome", "Report", "run_due"]
