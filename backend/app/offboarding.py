"""A gym's offboarding (#377): its data handed back, then its rows and files deleted.

The Términos de encargo (clause 14, "Al terminar") and Ley 19.628's art. 15 bis make
both a duty of the processor once the service ends: the data is returned to the gym,
then deleted. `app.platform.removal` holds the schedule; `python -m app.gyms export`
and `delete` (`app.gyms`) call this.

`export_gym` writes a directory, readable only by whoever ran it:

- `manifest.json`: the gym, when, and how many rows and files each part holds;
- `data/<table>.json`: every row of each table with the gym's id, as JSON objects
  named by column, plus `gym.json` (the gym's own row) and `person.json` (the shared
  record of each of its people). A sensitive custom field's value, stored sealed
  (`app.domain.custom_fields.FieldCipher`), is opened into `value`: a copy the gym
  cannot read is no copy. Not its sign-in sessions or idempotency keys
  (`NOT_EXPORTED`): those are the app's machinery, not the gym's data;
- `files/<key>`: each file it stored, at its key (`FILE_ROOTS`: payment proofs,
  expense receipts and its logo).

`delete_gym` refuses a gym whose removal has not started, or whose export window is
still open with no early deletion recorded. Otherwise it deletes the gym's files, then
calls migration 0094's `delete_gym`, which deletes every row with its id, the gym,
and each of its people no other gym knows, in one transaction, and logs it in
`platform_event`. The files go first: a failure in between leaves rows that name
files no longer there, and running it again finishes the job, where the other order
would leave files no row names.
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg

from app.domain.custom_fields import FieldCipher
from app.integrations.blobstore import BlobStore
from app.platform import removal

# The key roots a gym's files live under, each followed by its id (`app.api.proofs`,
# `app.api.expenses`, `app.logos`).
FILE_ROOTS = ("proofs", "receipts", "logos")

# Tables with a gym's id that hold no data of its own, kept out of the export.
NOT_EXPORTED = frozenset({"auth_session", "idempotency_key"})
# The platform's own log of what it did with the gym: never the gym's data.
PLATFORM_LOG = "platform_event"


def file_prefixes(gym_id: uuid.UUID) -> list[str]:
    return [f"{root}/{gym_id}/" for root in FILE_ROOTS]


@dataclass(frozen=True)
class Found:
    id: uuid.UUID
    slug: str
    name: str
    suspended_at: datetime | None
    removal_started_at: datetime | None
    early_deletion_on: date | None


async def find_gym(conn: asyncpg.Connection, slug: str) -> Found | None:
    """The gym with `slug`, read as the owner, with `app.gym_id` naming it for the rest
    of the transaction the caller holds."""
    found = await conn.fetchrow("SELECT id FROM auth_gym_by_slug($1)", slug)
    if found is None:
        return None
    await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(found["id"]))
    row = await conn.fetchrow(
        "SELECT id, slug, name, suspended_at, removal_started_at, early_deletion_on"
        " FROM gym WHERE id = $1",
        found["id"],
    )
    assert row is not None
    return Found(**dict(row))


async def gym_tables(conn: asyncpg.Connection) -> list[str]:
    """Every table in the schema with a `gym_id`, but the platform's log."""
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_catalog.pg_attribute a"
        " JOIN pg_catalog.pg_class c ON c.oid = a.attrelid"
        " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attname = 'gym_id'"
        " AND NOT a.attisdropped AND c.relname <> $1 ORDER BY c.relname",
        PLATFORM_LOG,
    )
    return [row["relname"] for row in rows]


@dataclass(frozen=True)
class Exported:
    gym_id: uuid.UUID
    slug: str
    path: Path
    rows: dict[str, int]
    files: int


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _rows(conn: asyncpg.Connection, sql: str, *args: object) -> list[Any]:
    found = await conn.fetchval(
        f"SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]') FROM ({sql}) t", *args
    )
    return list(json.loads(found))


def _opened(gym_id: uuid.UUID, cipher: FieldCipher, row: dict[str, Any]) -> dict[str, Any]:
    """A `person_field_value` row with its sealed value opened into `value`."""
    if row["secret"] is None:
        return row
    # `to_jsonb` writes bytea as text: `\x` and its hex.
    sealed = bytes.fromhex(row["secret"].removeprefix("\\x"))
    value = cipher.open(gym_id, uuid.UUID(row["person_id"]), row["field_key"], sealed)
    return {**row, "value": value, "secret": None}


async def export_gym(
    conn: asyncpg.Connection, store: BlobStore, cipher: FieldCipher, slug: str, into: Path
) -> Exported | None:
    """Write everything the gym with `slug` holds under a new directory in `into`;
    None if no gym has the slug. Read in one snapshot, so the rows agree."""
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        gym = await find_gym(conn, slug)
        if gym is None:
            return None
        now = datetime.now(UTC)
        path = into / f"{gym.slug}-{now.strftime('%Y%m%dT%H%M%SZ')}"
        # Its members' data: no one else on the host reads it.
        path.mkdir(mode=0o700, parents=True)
        data = path / "data"
        counts: dict[str, int] = {}
        [gym_row] = await _rows(conn, "SELECT * FROM gym WHERE id = $1", gym.id)
        _write_json(data / "gym.json", gym_row)
        # The people `person_read` (0003) shows in this gym: its own.
        people = await _rows(conn, "SELECT * FROM person ORDER BY id")
        _write_json(data / "person.json", people)
        counts["person"] = len(people)
        for table in await gym_tables(conn):
            if table in NOT_EXPORTED:
                continue
            rows = await _rows(conn, f'SELECT * FROM "{table}" WHERE gym_id = $1', gym.id)
            if table == "person_field_value":
                rows = [_opened(gym.id, cipher, row) for row in rows]
            _write_json(data / f"{table}.json", rows)
            counts[table] = len(rows)
    files = 0
    for prefix in file_prefixes(gym.id):
        for key in await store.keys_under(prefix):
            body = await store.get(key)
            if body is None:  # deleted in between
                continue
            target = path / "files" / key
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(body)
            files += 1
    _write_json(
        path / "manifest.json",
        {
            "gym": {"id": str(gym.id), "slug": gym.slug, "name": gym.name},
            "exported_at": now.isoformat(),
            "format": "data/<table>.json: the table's rows as JSON objects; files/<key>",
            "rows": counts,
            "files": files,
        },
    )
    os.chmod(path, 0o700)
    return Exported(gym.id, gym.slug, path, counts, files)


@dataclass(frozen=True)
class Refused:
    reason: str


@dataclass(frozen=True)
class Deleted:
    gym_id: uuid.UUID
    slug: str
    rows: int
    tables: dict[str, int]
    files: int
    people_deleted: int
    people_kept: int
    backups_gone_by: date


def deletion_refusal(found: Found, timezone: str, today: date) -> str | None:
    """Why `found` cannot be deleted `today`, or None when it can."""
    if found.removal_started_at is None:
        return "its removal has not started: start it from the panel, on a suspended gym"
    started = removal.started_on(found.removal_started_at, timezone)
    return removal.deletion_problem(started, found.early_deletion_on, today)


async def delete_gym(
    conn: asyncpg.Connection,
    store: BlobStore,
    slug: str,
    *,
    timezone: str,
    today: date,
    by: str,
) -> Deleted | Refused | None:
    """Delete the gym with `slug`, its files and its people no other gym knows; None if
    no gym has the slug. `by` is who ran it, for the log."""
    async with conn.transaction():
        found = await find_gym(conn, slug)
        if found is None:
            return None
        refusal = deletion_refusal(found, timezone, today)
    if refusal is not None:
        return Refused(refusal)
    files = 0
    for prefix in file_prefixes(found.id):
        for key in await store.keys_under(prefix):
            await store.delete(key)
            files += 1
    async with conn.transaction():
        detail = json.loads(
            await conn.fetchval("SELECT delete_gym($1, $2, $3)", found.id, by, files)
        )
    return Deleted(
        gym_id=found.id,
        slug=found.slug,
        rows=detail["rows"],
        tables=detail["tables"],
        files=files,
        people_deleted=detail["people_deleted"],
        people_kept=detail["people_kept"],
        backups_gone_by=removal.backups_gone_by(today),
    )
