"""The `uploads` job: delete the proofs and receipts nobody claimed (#522).

A member's transfer proof (`app.api.proofs`) and an expense's receipt
(`app.api.expenses`) are PUT to the store first and claimed when the entry is saved.
An upload whose form was abandoned stays in the bucket with nothing pointing at it,
and a proof can show someone's bank details: kept with no purpose, so it goes.

Each run lists, per gym, the files under `proofs/<gym_id>/` and `receipts/<gym_id>/`
last written more than `GRACE` ago, far longer than anyone takes to send a form, and
deletes each one nothing refers to:

- a ledger entry's `proof_object_key`, of any status, voided or not;
- an expense's `receipt_object_key`, voided or not;
- an `expense_changed` audit row's before or after: a receipt replaced or taken off is
  kept as the correction's history (#314).

A person deleted ("Eliminar persona", 0044) takes their ledger entries with them, so
their proofs are deleted on the next run too.

Before it looks a file up it takes the key's advisory lock, the one a claim holds from
before it checks the file is there to the end of its transaction (`LOCK_PROOF`): a
claim either commits first, and the file is kept, or finds it gone and is refused. A
key whose lock is held is left for the next run rather than waited on.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do. The
deletions are not the database's to roll back, so a gym that fails partway has deleted
only files nothing refers to, and the next run deletes the rest. It logs how many
files it deleted and kept per gym, never a key: a proof's holds its person's id.

    uv run python -m app.jobs.uploads --grace-hours 0.01   # once, now, with that grace

runs it on its own, outside `job_run`, for a check on staging.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import asyncpg

from app.db_bootstrap import to_dsn
from app.domain.dates import gym_today
from app.integrations import build_blob_store
from app.integrations.blobstore import BlobStore
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.logging import configure_logging
from app.sentry import init_sentry
from app.settings import get_settings

logger = logging.getLogger(__name__)

NAME = "uploads"

# An upload this recent may still be claimed by a form left open: two days.
GRACE = timedelta(hours=48)

# The key roots an upload lands under, each followed by the gym's id.
ROOTS = ("proofs", "receipts")

# `app.api.proofs.LOCK_PROOF`'s lock, on this connection: released by `UNLOCK` once the
# key is dealt with, not at the end of the run's transaction, so a run that reaps
# thousands of files never holds thousands of locks.
LOCK = "SELECT pg_try_advisory_lock(hashtextextended($1, 0))"
UNLOCK = "SELECT pg_advisory_unlock(hashtextextended($1, 0))"

# Whether anything in the gym refers to the key. Its own statement, run after the lock
# is taken, so under READ COMMITTED it sees a claim that committed while it waited.
REFERENCED = """
SELECT EXISTS (SELECT FROM ledger_entry WHERE proof_object_key = $1)
    OR EXISTS (SELECT FROM expense WHERE receipt_object_key = $1)
    OR EXISTS (
        SELECT FROM audit_event
        WHERE action = 'expense_changed'
          AND $1 IN (detail -> 'before' ->> 'receipt_object_key',
                     detail -> 'after' ->> 'receipt_object_key')
    )
"""


@dataclass
class Reaped:
    deleted: int = 0
    # Referred to, or locked by a claim in progress.
    kept: int = 0
    # The store refused to delete it; tried again on the next run.
    failed: int = 0


class DeletionsFailed(Exception):
    """The store refused some deletions. Its own errors are left out: a local store's
    name the file, whose path holds the key."""


def now() -> datetime:
    return datetime.now(UTC)


async def reap_gym(
    conn: asyncpg.Connection, store: BlobStore, gym_id: str, before: datetime
) -> Reaped:
    """Delete the gym's uploads last written before `before` that nothing refers to."""
    reaped = Reaped()
    for root in ROOTS:
        for key in await store.keys_stored_before(f"{root}/{gym_id}/", before):
            if not await conn.fetchval(LOCK, key):
                reaped.kept += 1
                continue
            # If the lookup raises, the lock is held until the run's connection closes:
            # a claim of this key waits that long, and is then judged as ever.
            if await conn.fetchval(REFERENCED, key):
                reaped.kept += 1
            else:
                try:
                    await store.delete(key)
                except Exception:
                    reaped.failed += 1
                else:
                    reaped.deleted += 1
            await conn.fetchval(UNLOCK, key)
    return reaped


def job(store: BlobStore, *, grace: timedelta = GRACE, clock: Callable[[], datetime] = now) -> Job:
    """The nightly job, deleting from `store` what was written more than `grace` before
    `clock()`: the time it runs, not the day it runs for, since a file's age is real."""

    async def reap_one(conn: asyncpg.Connection, day: date) -> None:
        gym_id = await conn.fetchval("SELECT current_setting('app.gym_id')")
        started = time.monotonic()
        reaped = await reap_gym(conn, store, gym_id, clock() - grace)
        logger.info(
            "unclaimed uploads reaped",
            extra={
                "job": NAME,
                "run_date": day.isoformat(),
                "gym_id": gym_id,
                "deleted": reaped.deleted,
                "kept": reaped.kept,
                "failed": reaped.failed,
                "seconds": round(time.monotonic() - started, 3),
            },
        )
        if reaped.failed:
            # Fails the gym, and so the day, which the next run retries.
            raise DeletionsFailed(f"{reaped.failed} unclaimed uploads could not be deleted")

    async def reap(conn: asyncpg.Connection, day: date) -> bool:
        return await each_gym(
            conn,
            day,
            reap_one,
            job=NAME,
            logger=logger,
            failure="deleting a gym's unclaimed uploads failed",
        )

    return Job(NAME, reap)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete the uploads nobody claimed, now.")
    parser.add_argument(
        "--grace-hours",
        type=float,
        default=GRACE.total_seconds() / 3600,
        help="keep anything written less than this many hours ago (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.grace_hours < 0:
        parser.error("--grace-hours must not be negative")

    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(settings)
    reaper = job(build_blob_store(settings), grace=timedelta(hours=args.grace_hours))

    async def once() -> bool:
        conn = await asyncpg.connect(to_dsn(settings.migration_database_url))
        try:
            async with conn.transaction():
                return await reaper.run(conn, gym_today(settings.jobs_timezone)) is not False
        finally:
            await conn.close()

    return 0 if asyncio.run(once()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
