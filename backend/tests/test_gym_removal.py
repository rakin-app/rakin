"""Baja de un gimnasio (#377): the panel schedules a suspended gym's removal, and the
host's shell exports it and then deletes it (`app.offboarding`, migration 0094).

The panel's side runs the app as in production against a real database
(`test_platform_auth`'s panel). The deletion's runs against the demo gym, which fills
nearly every table, beside a second gym that shares one of its people.
"""

import asyncio
import importlib.util
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app import gyms
from app.db_bootstrap import to_dsn
from app.domain.custom_fields import FieldCipher
from app.domain.dates import gym_today
from app.integrations.blobstore import LocalBlobStore
from app.offboarding import (
    NOT_EXPORTED,
    Deleted,
    Exported,
    Refused,
    delete_gym,
    export_gym,
    file_prefixes,
)
from app.platform import removal
from app.seed import load, store_proofs
from app.seed.build import GYM_ID
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_platform_auth import Panel
from tests.test_platform_auth import db as db
from tests.test_platform_auth import panel as panel
from tests.test_platform_create import gym_events, new_slug, signed_in
from tests.test_platform_edit import create, stale
from tests.test_platform_suspend import gym_rows, resume, suspend

pytestmark = pytest.mark.postgres

TZ = "America/Santiago"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _terms_signed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_gym_hosts import SIGNED_TODAY

    monkeypatch.setattr(gyms, "gym_today", lambda tz: SIGNED_TODAY)


def start(client: TestClient, gym_id: uuid.UUID, slug: str) -> Any:
    return client.post(f"/api/platform/gyms/{gym_id}/removal", json={"slug": slug})


def cancel(client: TestClient, gym_id: uuid.UUID) -> Any:
    return client.delete(f"/api/platform/gyms/{gym_id}/removal")


def early(client: TestClient, gym_id: uuid.UUID, asked_on: date) -> Any:
    return client.post(
        f"/api/platform/gyms/{gym_id}/removal/early", json={"asked_on": asked_on.isoformat()}
    )


def detail(client: TestClient, gym_id: uuid.UUID) -> Any:
    return client.get(f"/api/platform/gyms/{gym_id}").json()


def today(panel: Panel) -> date:
    return gym_today(panel.app.state.settings.jobs_timezone)


# --- the panel ------------------------------------------------------------------------


def test_a_removal_starts_only_for_a_suspended_gym_its_slug_typed_again(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    with signing_in as client:
        slug = new_slug()
        gym_id = create(client, slug)
        before = gym_rows(panel, gym_id)

        refused = start(client, gym_id, slug)
        assert (refused.status_code, refused.json()) == (
            409,
            {"detail": {"code": "not_suspended"}},
        )
        assert suspend(client, gym_id).status_code == 200
        refused = start(client, gym_id, slug + "x")
        assert (refused.status_code, refused.json()) == (
            409,
            {"detail": {"code": "slug_mismatch"}},
        )
        assert detail(client, gym_id)["removal"]["started_on"] is None

        assert start(client, gym_id, slug).json() == {"changed": True}
        assert start(client, gym_id, slug).json() == {"changed": False}

        dates = detail(client, gym_id)["removal"]
        started = today(panel)
        planned = removal.schedule(started)
        assert dates["started_on"] == started.isoformat()
        assert dates["early_deletion_on"] is None
        assert dates["export_until"] == planned.export_until.isoformat()
        assert dates["deletion_from"] == (planned.export_until + timedelta(days=1)).isoformat()
        assert dates["deleted_by"] == planned.deleted_by.isoformat()
        assert dates["backups_gone_by"] == planned.backups_gone_by.isoformat()
    # Nothing is deleted from the panel, and the gym stays suspended.
    assert gym_rows(panel, gym_id) == before
    removals = [e for e in gym_events(panel, gym_id) if e[0].startswith("gym_removal")]
    assert removals == [("gym_removal_started", operator_id, {"slug": slug})]


def test_a_gym_being_removed_is_not_resumed_until_its_removal_is_cancelled(
    panel: Panel,
) -> None:
    operator_id, signing_in = signed_in(panel)
    with signing_in as client:
        slug = new_slug()
        gym_id = create(client, slug)
        assert suspend(client, gym_id).status_code == 200
        assert start(client, gym_id, slug).status_code == 200
        assert early(client, gym_id, today(panel)).status_code == 200

        refused = resume(client, gym_id)
        assert (refused.status_code, refused.json()) == (
            409,
            {"detail": {"code": "removal_started"}},
        )

        assert cancel(client, gym_id).json() == {"changed": True}
        assert cancel(client, gym_id).json() == {"changed": False}
        shown = detail(client, gym_id)
        assert shown["suspended_at"] is not None
        assert (shown["removal"]["started_on"], shown["removal"]["early_deletion_on"]) == (
            None,
            None,
        )
        assert resume(client, gym_id).json() == {"changed": True}
    actions = [e[:2] for e in gym_events(panel, gym_id) if e[0].startswith("gym_r")]
    assert actions == [
        ("gym_removal_started", operator_id),
        ("gym_removal_cancelled", operator_id),
        ("gym_resumed", operator_id),
    ]


def test_an_early_deletion_opens_the_deletion_on_the_day_the_gym_asked(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    with signing_in as client:
        slug = new_slug()
        gym_id = create(client, slug)
        assert suspend(client, gym_id).status_code == 200
        refused = early(client, gym_id, today(panel))
        assert (refused.status_code, refused.json()) == (
            409,
            {"detail": {"code": "not_removing"}},
        )
        assert start(client, gym_id, slug).status_code == 200

        to_come = early(client, gym_id, today(panel) + timedelta(days=1))
        assert to_come.status_code == 422
        assert to_come.json()["detail"][0]["type"] == "early_deletion_future"

        # The letter that ended the service may have asked it, before the removal.
        asked = today(panel) - timedelta(days=3)
        assert early(client, gym_id, asked).json() == {"changed": True}
        assert early(client, gym_id, asked).json() == {"changed": False}
        dates = detail(client, gym_id)["removal"]
        assert dates["early_deletion_on"] == asked.isoformat()
        # Never before the removal itself.
        assert dates["deletion_from"] == today(panel).isoformat()
    [event] = [e for e in gym_events(panel, gym_id) if e[0] == "gym_early_deletion"]
    assert event == ("gym_early_deletion", operator_id, {"slug": slug, "asked_on": str(asked)})


def test_a_removal_asks_for_a_recent_proof(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        slug = new_slug()
        gym_id = create(client, slug)
        assert suspend(client, gym_id).status_code == 200
        stale(panel, client)
        for response in (
            start(client, gym_id, slug),
            cancel(client, gym_id),
            early(client, gym_id, today(panel)),
        ):
            assert (response.status_code, response.json()) == (
                401,
                {"detail": {"code": "reauth"}},
            )
        assert detail(client, gym_id)["removal"]["started_on"] is None


# --- the schedule ---------------------------------------------------------------------


def test_deletion_opens_after_the_window_or_on_the_day_the_gym_asked() -> None:
    started = date(2026, 1, 10)
    window = removal.schedule(started).export_until
    assert removal.deletion_opens(started, None) == window + timedelta(days=1)
    assert removal.deletion_opens(started, date(2026, 1, 20)) == date(2026, 1, 20)
    assert removal.deletion_opens(started, date(2026, 1, 1)) == started
    assert removal.deletion_problem(started, None, window) is not None
    assert removal.deletion_problem(started, None, window + timedelta(days=1)) is None
    assert removal.backups_gone_by(date(2026, 3, 1)) == date(2026, 3, 1) + timedelta(
        days=removal.BACKUP_DAYS
    )


# --- the host's shell: export, then delete --------------------------------------------


@pytest.fixture
def fresh() -> Iterator[Database]:
    """A database of its own: each test here deletes the demo gym."""
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def _owner(fresh: Database, query: Any) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(fresh.owner_url))
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


def admin(fresh: Database, sql: str, *args: object) -> Any:
    return run(fresh.admin_url, lambda c: c.fetch(sql, *args))


# Every table with a gym's id, but the platform's own log of what it did with gyms.
GYM_TABLES = (
    "SELECT table_name FROM information_schema.columns c"
    " JOIN information_schema.tables t USING (table_schema, table_name)"
    " WHERE c.table_schema = 'public' AND c.column_name = 'gym_id'"
    " AND t.table_type = 'BASE TABLE' AND table_name <> 'platform_event'"
)


def rows_of(fresh: Database, gym_id: uuid.UUID) -> dict[str, int]:
    """How many rows each table holds with the gym's id, and its own row."""

    async def query(conn: asyncpg.Connection) -> dict[str, int]:
        tables = await conn.fetch(GYM_TABLES)
        counts = {}
        for row in tables:
            name = row["table_name"]
            counts[name] = await conn.fetchval(
                f'SELECT count(*) FROM "{name}" WHERE gym_id = $1', gym_id
            )
        counts["gym"] = await conn.fetchval("SELECT count(*) FROM gym WHERE id = $1", gym_id)
        return counts

    return dict(run(fresh.admin_url, query))


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(root=tmp_path / "blobs", secret_key="k" * 32, ttl_seconds=60)


@pytest.fixture
def two(fresh: Database, store: LocalBlobStore) -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """The demo gym, with its files, and another gym that knows one of its people:
    the demo's id, the other's, and the person they share."""

    async def seed(conn: asyncpg.Connection) -> Any:
        return await load(conn)

    loaded = _owner(fresh, seed)
    asyncio.run(store_proofs(loaded.seed, store))
    asyncio.run(store.put(f"receipts/{GYM_ID}/{uuid.uuid4()}", "image/png", PNG))
    asyncio.run(store.put(f"logos/{GYM_ID}/v1/mark.png", "image/png", PNG))
    other = seed_gym(fresh, unique_slug("otro"))
    asyncio.run(store.put(f"logos/{other}/v1/mark.png", "image/png", PNG))
    [shared] = admin(
        fresh,
        "SELECT person_id, name FROM gym_person WHERE gym_id = $1 ORDER BY person_id LIMIT 1",
        GYM_ID,
    )
    admin(
        fresh,
        "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, $3)",
        other,
        shared["person_id"],
        shared["name"],
    )
    # A sensitive custom field's value, sealed as the API stores it.
    admin(
        fresh,
        "INSERT INTO person_field_value (gym_id, person_id, field_key, secret)"
        " VALUES ($1, $2, 'salud', $3)",
        GYM_ID,
        shared["person_id"],
        CIPHER.seal(GYM_ID, shared["person_id"], "salud", "asma"),
    )
    yield GYM_ID, other, shared["person_id"]


def removing(fresh: Database, gym_id: uuid.UUID, days_ago: int) -> date:
    """The gym suspended, and its removal started `days_ago` days ago; that day."""
    admin(
        fresh,
        "UPDATE gym SET suspended_at = now() - interval '1 day' * ($2 + 1),"
        " removal_started_at = now() - interval '1 day' * $2 WHERE id = $1",
        gym_id,
        days_ago,
    )
    [row] = admin(fresh, "SELECT removal_started_at FROM gym WHERE id = $1", gym_id)
    return removal.started_on(row["removal_started_at"], TZ)


def delete(fresh: Database, store: LocalBlobStore, slug: str, on: date) -> Any:
    async def go(conn: asyncpg.Connection) -> Any:
        return await delete_gym(conn, store, slug, timezone=TZ, today=on, by="ops")

    return _owner(fresh, go)


CIPHER = FieldCipher("a field key for the tests, not a real one")


def export(fresh: Database, store: LocalBlobStore, slug: str, into: Path) -> Any:
    return _owner(fresh, lambda conn: export_gym(conn, store, CIPHER, slug, into))


def slug_of(fresh: Database, gym_id: uuid.UUID) -> str:
    [row] = admin(fresh, "SELECT slug FROM gym WHERE id = $1", gym_id)
    return str(row["slug"])


def test_the_export_holds_every_row_and_file_of_the_gym(
    fresh: Database,
    store: LocalBlobStore,
    two: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    tmp_path: Path,
) -> None:
    gym_a, _, shared = two
    counts = rows_of(fresh, gym_a)
    done = export(fresh, store, slug_of(fresh, gym_a), tmp_path / "out")
    assert isinstance(done, Exported)
    assert done.path.stat().st_mode & 0o077 == 0
    manifest = json.loads((done.path / "manifest.json").read_text())
    assert manifest["gym"]["id"] == str(gym_a)
    for table, count in counts.items():
        if table in NOT_EXPORTED or table == "gym":
            continue
        rows = json.loads((done.path / "data" / f"{table}.json").read_text())
        assert len(rows) == count == manifest["rows"][table], table
        assert all(r["gym_id"] == str(gym_a) for r in rows)
    sealed = json.loads((done.path / "data" / "person_field_value.json").read_text())
    [opened] = [r for r in sealed if r["field_key"] == "salud"]
    assert (opened["value"], opened["secret"]) == ("asma", None)
    gym_row = json.loads((done.path / "data" / "gym.json").read_text())
    assert gym_row["id"] == str(gym_a)
    people = {p["id"] for p in json.loads((done.path / "data" / "person.json").read_text())}
    assert str(shared) in people
    assert len(people) == counts["gym_person"]
    keys = [k for prefix in file_prefixes(gym_a) for k in asyncio.run(store.keys_under(prefix))]
    assert keys and manifest["files"] == len(keys) == done.files
    for key in keys:
        assert (done.path / "files" / key).read_bytes() == asyncio.run(store.get(key))
    assert not (done.path / "files" / "logos" / str(two[1])).exists()


def test_deletion_waits_for_a_removal_and_for_the_end_of_its_window(
    fresh: Database, store: LocalBlobStore, two: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    gym_a = two[0]
    slug = slug_of(fresh, gym_a)
    before = rows_of(fresh, gym_a)
    refused = delete(fresh, store, slug, date(2099, 1, 1))
    assert isinstance(refused, Refused) and "has not started" in refused.reason

    started = removing(fresh, gym_a, days_ago=0)
    window = removal.schedule(started).export_until
    refused = delete(fresh, store, slug, window)
    assert isinstance(refused, Refused) and str(window) in refused.reason
    assert rows_of(fresh, gym_a) == before
    assert asyncio.run(store.keys_under(f"logos/{gym_a}/"))

    # The gym asked in writing for its deletion today.
    admin(fresh, "UPDATE gym SET early_deletion_on = $2 WHERE id = $1", gym_a, started)
    assert isinstance(delete(fresh, store, slug, started), Deleted)
    assert delete(fresh, store, slug, started) is None


def test_deletion_leaves_no_row_with_the_gyms_id_and_the_other_gym_as_it_was(
    fresh: Database, store: LocalBlobStore, two: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    gym_a, gym_b, shared = two
    slug = slug_of(fresh, gym_a)
    before_b = rows_of(fresh, gym_b)
    [b_record] = admin(
        fresh, "SELECT * FROM gym_person WHERE gym_id = $1 AND person_id = $2", gym_b, shared
    )
    people_a = {
        r["person_id"]
        for r in admin(fresh, "SELECT person_id FROM gym_person WHERE gym_id = $1", gym_a)
    }
    started = removing(fresh, gym_a, days_ago=removal.EXPORT_DAYS + 1)

    on = started + timedelta(days=removal.EXPORT_DAYS + 1)
    done = delete(fresh, store, slug, on)

    assert isinstance(done, Deleted)
    assert done.backups_gone_by == on + timedelta(days=removal.BACKUP_DAYS)
    left = {table: n for table, n in rows_of(fresh, gym_a).items() if n}
    assert left == {}
    assert rows_of(fresh, gym_b) == before_b
    # The person both gyms know keeps the other gym's record of them; the rest are gone.
    assert admin(fresh, "SELECT id FROM person WHERE id = $1", shared)
    assert admin(
        fresh, "SELECT * FROM gym_person WHERE gym_id = $1 AND person_id = $2", gym_b, shared
    ) == [b_record]
    gone = people_a - {shared}
    assert admin(fresh, "SELECT id FROM person WHERE id = ANY($1::uuid[])", list(gone)) == []
    assert (done.people_deleted, done.people_kept) == (len(gone), 1)
    # Its files are gone, and only its.
    for prefix in file_prefixes(gym_a):
        assert asyncio.run(store.keys_under(prefix)) == []
    assert asyncio.run(store.keys_under(f"logos/{gym_b}/")) != []
    # The platform's log says so, by the gym's id and slug only.
    [event] = admin(
        fresh, "SELECT operator_id, detail FROM platform_event WHERE action = 'gym_deleted'"
    )
    logged = json.loads(event["detail"])
    assert event["operator_id"] is None
    assert (logged["slug"], logged["by"], logged["host_user"]) == (slug, "cli", "ops")
    assert (logged["rows"], logged["files"]) == (done.rows, done.files)
    assert logged["people_deleted"] == len(gone)
    names = {
        r["name"] for r in admin(fresh, "SELECT name FROM gym_person WHERE gym_id = $1", gym_b)
    }
    assert not any(name in event["detail"] for name in names)


def test_only_the_owner_deletes_a_gym_and_only_one_being_removed(
    fresh: Database, two: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    gym_a = two[0]

    async def as_api(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval("SELECT delete_gym($1, 'x', 0)", gym_a)

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(fresh.api_url, as_api)

    async def ledger(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_a))
            await conn.execute("SELECT set_config('app.forget_gym', $1, true)", str(gym_a))
            return await conn.execute("DELETE FROM ledger_entry WHERE gym_id = $1", gym_a)

    # The API's role has no DELETE on an append-only table, whatever it sets.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(fresh.api_url, ledger)
    # And the owner is held to it while no removal has started.
    with pytest.raises(asyncpg.RestrictViolationError):
        run(fresh.owner_url, ledger)
    with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="no removal started"):
        run(fresh.owner_url, lambda c: c.fetchval("SELECT delete_gym($1, 'x', 0)", gym_a))


def test_delete_gym_covers_every_table_with_a_gym_id(fresh: Database) -> None:
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0094_gym_removal.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tables = {r["table_name"] for r in admin(fresh, GYM_TABLES)}
    assert set(module.TABLES) == tables
    assert len(module.TABLES) == len(set(module.TABLES))


def test_a_downgrade_refuses_while_a_removal_is_started(fresh: Database) -> None:
    gym_id = seed_gym(fresh, unique_slug("bajando"))
    admin(
        fresh,
        "INSERT INTO platform_event (action, gym_id, detail)"
        """ VALUES ('gym_removal_started', $1, '{"by": "cli"}')""",
        gym_id,
    )
    removing(fresh, gym_id, days_ago=0)
    with pytest.raises(Exception, match="has a removal started"):
        command.downgrade(fresh.alembic(), "0093")
    admin(fresh, "UPDATE gym SET removal_started_at = NULL WHERE id = $1", gym_id)
    command.downgrade(fresh.alembic(), "0093")
    command.upgrade(fresh.alembic(), "head")


def test_the_command_asks_for_the_slug_twice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        gyms.parse(["delete", "meta", "--confirm", "mata"])
    assert exited.value.code == 2
    assert "not the slug" in capsys.readouterr().err
    assert gyms.parse(["delete", "meta", "--confirm", "meta", "--by", "ana"]) == gyms.Deletion(
        "meta", "meta", "ana"
    )
    assert gyms.parse(["export", "meta", "--to", "out"]) == gyms.Export("meta", Path("out"))
