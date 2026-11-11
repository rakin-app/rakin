"""Academia Sur, the demo gym used by dev, the 90-day simulation and the self-host demo.

    uv run python -m app.seed                      # as of today, gym-local
    uv run python -m app.seed --today 2026-11-08   # the date the UI design depicts

`app.seed.data` is who trains there, `app.seed.build` turns that into rows for a seed
date, and `load` writes them. Every row has a fixed id, so loading again inserts
nothing new: the ledger is append-only and the seed never deletes or rewrites. The
first load stores its date in `gym.settings["seed"]["as_of"]`, and later loads build
for that date again, so the rows stay consistent with each other. `store_proofs` puts a
placeholder image at every seeded transfer's proof key, so Validar comprobante opens one.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import asyncpg

from app.domain.dates import gym_today
from app.integrations.blobstore import BlobStore
from app.seed.build import GYM_ID, Seed, build
from app.seed.data import TIMEZONE

# The primary key a re-run collides on. Any other unique violation (a RUT already
# taken by someone outside the seed, a slug already used) is a real conflict and fails.
CONFLICT_KEYS = {
    "staff": "(gym_id, person_id)",
    "gym_person": "(gym_id, person_id)",
    "guardian_link": "(gym_id, dependent_person_id)",
    "attendance": "(session_id, membership_id)",
}
# `ON CONFLICT` holds the new row to the table's read policy, and a person joins the
# gym only once their `gym_person` row exists (0004), so these rows are tried one by one.
NO_ON_CONFLICT = {"person": "person_pkey"}
# What every seeded proof shows: a made-up receipt marked as demo data. Its keys end in
# `.jpg`, as `build` writes them.
PROOF_IMAGE = Path(__file__).with_name("proof.jpg")


@dataclass(frozen=True)
class Loaded:
    seed: Seed
    inserted: dict[str, int]
    # The date asked for, when an earlier load had already fixed another one.
    ignored_today: date | None = None


async def load(conn: asyncpg.Connection, today: date | None = None) -> Loaded:
    """Write the demo gym in one transaction; rows already there are left as they are."""
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    async with conn.transaction():
        # RLS is forced, so the owner writes only in the gym `app.gym_id` names.
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(GYM_ID))
        stored = await conn.fetchval(
            "SELECT settings -> 'seed' ->> 'as_of' FROM gym WHERE id = $1", GYM_ID
        )
        as_of = date.fromisoformat(stored) if stored else today or gym_today(TIMEZONE)
        seed = build(as_of)
        inserted: dict[str, int] = {}
        for table, rows in seed.tables():
            columns = list(rows[0])
            sql = (
                f"INSERT INTO {table} ({', '.join(columns)})"
                f" VALUES ({', '.join(f'${i}' for i in range(1, len(columns) + 1))})"
            )
            if table not in NO_ON_CONFLICT:
                sql += f" ON CONFLICT {CONFLICT_KEYS.get(table, '(id)')} DO NOTHING"
            count = 0
            for row in rows:
                count += await _insert(conn, table, sql, [row[c] for c in columns])
            inserted[table] = count
    ignored = today if stored and today and today != as_of else None
    return Loaded(seed, inserted, ignored)


async def _insert(conn: asyncpg.Connection, table: str, sql: str, values: list[object]) -> int:
    """1 if the row was written, 0 if it was already there."""
    if table not in NO_ON_CONFLICT:
        status: str = await conn.execute(sql, *values)
        return int(status.rsplit(" ", 1)[1])
    try:
        async with conn.transaction():
            await conn.execute(sql, *values)
    except asyncpg.UniqueViolationError as error:
        if error.constraint_name != NO_ON_CONFLICT[table]:
            raise
        return 0
    return 1


async def store_proofs(seed: Seed, store: BlobStore) -> int:
    """Put `PROOF_IMAGE` at each proof key of `seed` that has no file yet; how many it put.

    Like the rows, a file already there is left as it is."""
    image = PROOF_IMAGE.read_bytes()
    keys = sorted({e["proof_object_key"] for e in seed.ledger_entries if e["proof_object_key"]})
    count = 0
    for key in keys:
        if await store.stat(key) is None:
            await store.put(key, "image/jpeg", image)
            count += 1
    return count
