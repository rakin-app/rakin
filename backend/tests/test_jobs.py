"""The nightly job runner: once per (job, day) via `job_run`, missed days in order.

Each test names its own jobs (`names`), since `job_run` is global and the database is
shared across the module. A job records the day it ran in `job_effect`, inside the
runner's transaction, so a rollback shows up as a missing row.
"""

import asyncio
import logging
import os
import signal
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.db_bootstrap import to_dsn
from app.jobs import Job, Outcome, Report, daily, run_due
from app.sentry import init_sentry
from tests.conftest import UNREACHABLE_DB, make_settings, require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

DAY = date(2026, 11, 8)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        run(
            database.owner_url,
            lambda c: c.execute("CREATE TABLE job_effect (job text NOT NULL, day date NOT NULL)"),
        )
        yield database


@pytest.fixture
def names() -> Iterator[str]:
    """A prefix unique to the test, for its job names."""
    yield uuid.uuid4().hex[:8]


def recording(name: str, fail_on: set[date] | None = None) -> Job:
    async def go(conn: asyncpg.Connection, day: date) -> None:
        await conn.execute("INSERT INTO job_effect (job, day) VALUES ($1, $2)", name, day)
        if day in (fail_on or set()):
            raise RuntimeError(f"{name} broke on {day}")

    return Job(name, go)


def run_jobs(db: Database, jobs: list[Job], today: date) -> Report:
    async def go(conn: asyncpg.Connection) -> Report:
        return await run_due(conn, jobs, today)

    report: Report = run(db.owner_url, go)
    return report


def effects(db: Database, prefix: str) -> list[tuple[str, date]]:
    rows = run(
        db.owner_url,
        lambda c: c.fetch(
            "SELECT job, day FROM job_effect WHERE job LIKE $1 || '%' ORDER BY job, day", prefix
        ),
    )
    return [(row["job"], row["day"]) for row in rows]


def runs(db: Database, prefix: str) -> dict[tuple[str, date], tuple[str, bool]]:
    """Each `job_run` row: its status, and whether it has a `finished_at`."""
    rows = run(
        db.owner_url,
        lambda c: c.fetch(
            "SELECT job_name, run_date, status, finished_at FROM job_run"
            " WHERE job_name LIKE $1 || '%'",
            prefix,
        ),
    )
    return {
        (row["job_name"], row["run_date"]): (row["status"], row["finished_at"] is not None)
        for row in rows
    }


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


@pytest.mark.postgres
def test_a_job_runs_once_per_day(db: Database, names: str) -> None:
    job = recording(f"{names}-a")

    first = run_jobs(db, [job], DAY)
    again = run_jobs(db, [job], DAY)

    assert first == Report(Outcome.SUCCEEDED, [(job.name, DAY)])
    assert again == Report(Outcome.SUCCEEDED, [])
    assert effects(db, names) == [(job.name, DAY)]
    assert runs(db, names) == {(job.name, DAY): ("succeeded", True)}


@pytest.mark.postgres
def test_a_new_job_starts_today_not_in_the_past(db: Database, names: str) -> None:
    old, new = recording(f"{names}-old"), recording(f"{names}-new")
    run_jobs(db, [old], DAY)

    report = run_jobs(db, [old, new], DAY + timedelta(days=2))

    # Days in order, and on each day the jobs in theirs.
    assert report.ran == [
        (old.name, DAY + timedelta(days=1)),
        (old.name, DAY + timedelta(days=2)),
        (new.name, DAY + timedelta(days=2)),
    ]


@pytest.mark.postgres
def test_missed_days_are_caught_up_in_order(db: Database, names: str) -> None:
    first, second = recording(f"{names}-1"), recording(f"{names}-2")
    run_jobs(db, [first, second], DAY)

    report = run_jobs(db, [first, second], DAY + timedelta(days=3))

    caught_up = days(DAY + timedelta(days=1), 3)
    assert report == Report(
        Outcome.SUCCEEDED, [(job.name, day) for day in caught_up for job in (first, second)]
    )
    assert effects(db, names) == [
        (job.name, day) for job in (first, second) for day in days(DAY, 4)
    ]


@pytest.mark.postgres
def test_a_gap_is_filled_even_behind_a_later_success(db: Database, names: str) -> None:
    job = recording(f"{names}-a")
    run_jobs(db, [job], DAY)
    run_jobs(db, [job], DAY + timedelta(days=3))
    # As if the 10th had been cleared by hand, or never committed.
    run(
        db.owner_url,
        lambda c: c.execute(
            "DELETE FROM job_run WHERE job_name = $1 AND run_date = $2",
            job.name,
            DAY + timedelta(days=2),
        ),
    )

    report = run_jobs(db, [job], DAY + timedelta(days=3))

    assert report.ran == [(job.name, DAY + timedelta(days=2))]


@pytest.mark.postgres
def test_a_failure_rolls_back_and_stops_the_run(
    db: Database, names: str, caplog: pytest.LogCaptureFixture
) -> None:
    broken_day = DAY + timedelta(days=2)
    first = recording(f"{names}-1", fail_on={broken_day})
    second = recording(f"{names}-2")
    run_jobs(db, [first, second], DAY)

    with caplog.at_level(logging.INFO, logger="app.jobs.runner"):
        report = run_jobs(db, [first, second], DAY + timedelta(days=4))

    assert report == Report(
        Outcome.FAILED,
        [
            (first.name, DAY + timedelta(days=1)),
            (second.name, DAY + timedelta(days=1)),
            (first.name, broken_day),
        ],
    )
    # The broken day's work is gone; the second job never ran that day, nor anyone later.
    assert effects(db, names) == [
        (first.name, DAY),
        (first.name, DAY + timedelta(days=1)),
        (second.name, DAY),
        (second.name, DAY + timedelta(days=1)),
    ]
    assert runs(db, names)[(first.name, broken_day)] == ("failed", True)
    assert (second.name, broken_day) not in runs(db, names)

    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "job failed"
    assert failure.__dict__["job"] == first.name
    assert failure.__dict__["run_date"] == broken_day.isoformat()
    assert failure.exc_info is not None
    assert str(failure.exc_info[1]) == f"{first.name} broke on {broken_day}"


@pytest.mark.postgres
def test_a_job_returning_false_keeps_its_work_and_fails_the_day(
    db: Database, names: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def incomplete(conn: asyncpg.Connection, day: date) -> bool:
        await conn.execute("INSERT INTO job_effect (job, day) VALUES ($1, $2)", partial.name, day)
        return False

    partial = Job(f"{names}-1", incomplete)
    later = recording(f"{names}-2")

    with caplog.at_level(logging.INFO, logger="app.jobs.runner"):
        report = run_jobs(db, [partial, later], DAY)

    assert report == Report(Outcome.FAILED, [(partial.name, DAY)])
    assert effects(db, names) == [(partial.name, DAY)]
    assert runs(db, names) == {(partial.name, DAY): ("failed", True)}
    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "job incomplete"
    assert failure.__dict__["job"] == partial.name

    # Retried first on the next run, like any failed day.
    assert run_jobs(db, [recording(partial.name)], DAY).ran == [(partial.name, DAY)]


@pytest.mark.postgres
def test_a_failed_day_is_retried_first(db: Database, names: str) -> None:
    broken_day = DAY + timedelta(days=1)
    flaky = recording(f"{names}-a", fail_on={broken_day})
    run_jobs(db, [flaky], DAY)
    run_jobs(db, [flaky], DAY + timedelta(days=2))

    fixed = recording(flaky.name)
    report = run_jobs(db, [fixed], DAY + timedelta(days=2))

    assert report == Report(Outcome.SUCCEEDED, [(fixed.name, d) for d in days(broken_day, 2)])
    assert runs(db, names) == {(fixed.name, d): ("succeeded", True) for d in days(DAY, 3)}


@pytest.mark.postgres
def test_a_run_left_running_by_a_dead_runner_is_run_again(db: Database, names: str) -> None:
    job = recording(f"{names}-a")
    run_jobs(db, [job], DAY)
    run(
        db.owner_url,
        lambda c: c.execute(
            "INSERT INTO job_run (job_name, run_date, status) VALUES ($1, $2, 'running')",
            job.name,
            DAY + timedelta(days=1),
        ),
    )

    report = run_jobs(db, [job], DAY + timedelta(days=1))

    assert report.ran == [(job.name, DAY + timedelta(days=1))]
    assert runs(db, names)[(job.name, DAY + timedelta(days=1))] == ("succeeded", True)


@pytest.mark.postgres
def test_a_second_runner_does_nothing_while_one_works(db: Database, names: str) -> None:
    job = recording(f"{names}-a")

    async def go() -> Report:
        holder = await asyncpg.connect(to_dsn(db.owner_url))
        other = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            assert await holder.fetchval("SELECT pg_try_advisory_lock(hashtext('rakin.jobs'))")
            return await run_due(other, [job], DAY)
        finally:
            await holder.close()
            await other.close()

    assert asyncio.run(go()) == Report(Outcome.LOCKED, [])
    assert runs(db, names) == {}
    # Closing the holder released the lock.
    assert run_jobs(db, [job], DAY).ran == [(job.name, DAY)]


@pytest.mark.postgres
def test_job_names_must_be_unique(db: Database, names: str) -> None:
    job = recording(f"{names}-a")

    with pytest.raises(ValueError, match="unique"):
        run_jobs(db, [job, job], DAY)


class Captured(Transport):
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture
def sentry() -> Iterator[Captured]:
    transport = Captured()
    settings = make_settings(sentry_dsn="https://public@sentry.invalid/1")
    assert init_sentry(settings, transport=transport)
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.init()  # no DSN: a client that sends nothing


@pytest.mark.postgres
def test_a_failure_reaches_sentry(db: Database, names: str, sentry: Captured) -> None:
    job = recording(f"{names}-a", fail_on={DAY})

    assert run_jobs(db, [job], DAY).outcome is Outcome.FAILED
    sentry_sdk.flush()

    events = [e for env in sentry.envelopes if (e := env.get_event()) is not None]
    [event] = events
    assert event["logentry"]["message"] == "job failed"
    assert event["extra"]["job"] == job.name
    assert event["extra"]["run_date"] == DAY.isoformat()
    [exception] = event["exception"]["values"]
    assert exception["type"] == "RuntimeError"


def test_sentry_is_off_without_a_dsn() -> None:
    assert not init_sentry(make_settings())


def test_today_is_the_date_in_the_jobs_timezone() -> None:
    ahead, behind = (
        daily.today(make_settings(jobs_timezone=tz)) for tz in ("Pacific/Kiritimati", "Etc/GMT+12")
    )

    # UTC+14 and UTC-12: always a day or two apart, never the same date.
    assert ahead - behind in (timedelta(days=1), timedelta(days=2))


@pytest.mark.postgres
def test_main_exits_non_zero_when_a_job_fails(
    db: Database, names: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daily, "get_settings", lambda: db.settings)
    monkeypatch.setattr(daily, "configure_logging", lambda level: None)
    ok, broken = recording(f"{names}-ok"), recording(f"{names}-broken", fail_on={DAY})

    monkeypatch.setattr(daily, "JOBS", (ok,))
    assert daily.main(["--today", DAY.isoformat()]) == 0
    monkeypatch.setattr(daily, "JOBS", (broken,))
    assert daily.main(["--today", DAY.isoformat()]) == 1

    assert effects(db, names) == [(ok.name, DAY)]


def test_main_refuses_today_with_every() -> None:
    with pytest.raises(SystemExit) as exit_:
        daily.main(["--today", DAY.isoformat(), "--every", "60"])
    assert exit_.value.code == 2


def stop_soon(seconds: float) -> None:
    asyncio.get_running_loop().call_later(seconds, os.kill, os.getpid(), signal.SIGTERM)


@pytest.mark.postgres
def test_serve_runs_on_every_tick_until_stopped(db: Database, names: str) -> None:
    job = recording(f"{names}-a")

    async def go() -> None:
        stop_soon(0.5)
        await daily.serve(db.settings, 0.05, [job])

    asyncio.run(go())

    # Many ticks, one run: the rest found nothing owed.
    assert effects(db, names) == [(job.name, daily.today(db.settings))]


def test_serve_keeps_going_when_a_run_fails(caplog: pytest.LogCaptureFixture) -> None:
    settings = make_settings(migration_database_url=UNREACHABLE_DB)

    async def go() -> None:
        stop_soon(0.5)
        await daily.serve(settings, 0.05, [])

    with caplog.at_level(logging.INFO, logger="app.jobs.daily"):
        asyncio.run(go())

    messages = [r.getMessage() for r in caplog.records]
    assert messages[0] == "job runner started"
    assert messages.count("job runner failed") >= 2
    assert messages[-1] == "job runner stopped"
