"""Anonimizar (#372): someone the gym kept money from leaves its books as an anonymous
record, and nothing else of theirs stays.

Their memberships, periods and ledger amounts stay, so every total the gym reads is
what it was; they move onto a record named "Exalumno anonimizado" that no row leads
from them to. Everything else goes: the record's RUT, email, phone and birth date, the
gym's messages to them, their sign-in links, sessions, idempotency keys and fields,
their proof files, and the global person when no other gym knows them. Another gym's
record of the same RUT is untouched, and they may join here again as anyone.

Eliminar (`forget_gym_person`) deletes the same leftovers now.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.rut import format_rut
from app.integrations.blobstore import BlobStore
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_member_roll import enrolled, forget, leave, memberships, plan
from tests.test_memberships import add_staff
from tests.test_people import new_phone, new_rut
from tests.test_proofs import RecordingMailer, upload
from tests.test_voids import ok, refund

pg = pytest.mark.postgres

REASON = "pidió que borremos sus datos"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(
    db: Database, mailer: RecordingMailer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    blobs: Path = tmp_path_factory.mktemp("blobs")
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=blobs,
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("sur"))


def store(client: TestClient) -> BlobStore:
    found: BlobStore = client.app.state.integrations.blob_store  # type: ignore[attr-defined]
    return found


def stored(client: TestClient, key: str) -> bool:
    return asyncio.run(store(client).stat(key)) is not None


def anonymise(client: TestClient, gym: uuid.UUID, person: str, by: uuid.UUID | None = None) -> Any:
    return client.post(
        f"/api/people/{person}/anonymise", json={"reason": REASON}, headers=as_gym(gym, by)
    )


def asked(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    return ok(client.get(f"/api/people/{person}/anonymisation", headers=as_gym(gym)))


@dataclasses.dataclass
class Member:
    id: str
    name: str
    rut: str
    email: str
    phone: str
    membership: str
    proof: str


def paid_member(client: TestClient, db: Database, gym: uuid.UUID, rut: str | None = None) -> Member:
    """Someone on a monthly plan since 40 days ago who paid both periods, one by a
    transfer proof they claimed and the gym validated, one in cash with a note; with a
    welcome sent, a field, a sign-in link and an idempotency key; then dado de baja."""
    rut = rut or new_rut()
    # Their own surname, so no other test's member in this database shares it.
    name = f"Valentina Riquelme{uuid.uuid4().hex[:6]}"
    email = f"vale-{uuid.uuid4().hex[:8]}@example.cl"
    phone = new_phone()
    started_on = (seeded_today() - timedelta(days=40)).isoformat()
    body = enrolled(
        client,
        gym,
        name=name,
        rut=rut,
        email=email,
        phone=phone,
        dob="1990-04-12",
        membership={"plan_id": plan(client, gym), "started_on": started_on},
        send_welcome=True,
    )
    person = body["id"]
    [membership] = memberships(client, gym, person)
    periods = ok(client.get(f"/api/ledger/memberships/{membership['id']}", headers=as_gym(gym)))[
        "open_periods"
    ]
    first, *rest = periods

    key = upload(client, gym, person)
    claimed = client.post(
        "/api/me/payments",
        json={"billing_period_id": first["id"], "amount_clp": 45_000, "proof_key": key},
        headers={**as_gym(gym, uuid.UUID(person)), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert claimed.status_code == 201, claimed.text
    ok(client.post(f"/api/ledger/proofs/{claimed.json()['id']}/validate", headers=as_gym(gym)))
    for period in rest:
        body = {
            "membership_id": membership["id"],
            "billing_period_id": period["id"],
            "amount_clp": 45_000,
            "method": "cash",
            "note": f"lo trajo {name}",
        }
        ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)

    field = ok(
        client.post(
            "/api/custom-fields", json={"label": "Talla", "type": "text"}, headers=as_gym(gym)
        ),
        201,
    )
    ok(
        client.patch(
            f"/api/people/{person}/fields",
            json={"values": {field["key"]: "M"}},
            headers=as_gym(gym),
        )
    )
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO auth_link (token_hash, person_id, email, expires_at)"
            " VALUES ($1, $2, $3, now() + interval '1 hour')",
            uuid.uuid4().bytes * 2,
            uuid.UUID(person),
            email,
        ),
    )
    ok(leave(client, gym, person, left_reason="se mudó a Valdivia"))
    return Member(person, name, rut, email, phone, membership["id"], key)


def figures(client: TestClient, gym: uuid.UUID) -> Any:
    """What the gym's books say: Finanzas' year, and the ledger's export in pesos."""
    year = ok(client.get("/api/finances/year", headers=as_gym(gym)))
    export = client.get("/api/ledger/export", headers=as_gym(gym))
    assert export.status_code == 200, export.text
    return year, len(export.text.splitlines())


# Every table, each row as text, bytea columns read as text too.
ROWS_HOLDING = """
    SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1
"""


def tables_holding(db: Database, needle: str, *, gym: uuid.UUID | None = None) -> list[str]:
    """The tables a row of which holds `needle`, as the superuser sees them; with `gym`,
    only that gym's rows of the tables that have one, and every row of those that do
    not."""

    async def scan(conn: asyncpg.Connection) -> list[str]:
        found = []
        for (table,) in await conn.fetch(ROWS_HOLDING):
            columns = await conn.fetch(
                "SELECT attname, format_type(atttypid, atttypmod) AS type FROM pg_attribute"
                " WHERE attrelid = $1::regclass AND attnum > 0 AND NOT attisdropped",
                table,
            )
            texts = [
                f"coalesce(convert_from({c['attname']}, 'UTF8'), '')"
                if c["type"] == "bytea"
                else f"coalesce({c['attname']}::text, '')"
                for c in columns
                if c["attname"] not in ("token_hash", "code_hash", "note_secret", "secret")
            ]
            where = f"concat_ws(' ', {', '.join(texts)}) ILIKE '%' || $1 || '%'"
            if gym is not None and any(c["attname"] == "gym_id" for c in columns):
                where += " AND gym_id = $2"
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {table} WHERE {where}", needle, gym
                )
            else:
                count = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE {where}", needle)
            if count:
                found.append(table)
        return found

    result: list[str] = run(db.admin_url, scan)
    return result


def needles(member: Member) -> list[str]:
    """What would say who they were: their surname, RUT, email, phone and id."""
    return [
        member.name.split()[1],
        member.rut,
        format_rut(member.rut),
        member.email,
        member.phone,
        member.id,
    ]


@pg
def test_anonymising_keeps_the_books_and_nothing_of_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    member = paid_member(client, db, gym)
    assert stored(client, member.proof)
    # Eliminar is refused for the money the gym kept; Anonimizar is offered instead.
    deletion = ok(client.get(f"/api/people/{member.id}/deletion", headers=as_gym(gym)))
    assert deletion["refused"] == "payment"
    assert asked(client, gym, member.id) == {"refused": None, "amount_clp": None}
    before = figures(client, gym)
    for needle in needles(member):
        if needle != format_rut(member.rut):
            assert tables_holding(db, needle, gym=gym), needle

    response = anonymise(client, gym, member.id)
    assert response.status_code == 204, response.text

    assert figures(client, gym) == before
    assert client.get(f"/api/people/{member.id}", headers=as_gym(gym)).status_code == 404
    for needle in needles(member):
        assert tables_holding(db, needle) == [], needle
    assert not stored(client, member.proof)
    # No other gym knew them: the global person is gone with them.
    gone = run(
        db.admin_url,
        lambda c: c.fetchval("SELECT count(*) FROM person WHERE id = $1", uuid.UUID(member.id)),
    )
    assert gone == 0

    # The anonymous record is among the former students, with the books on it.
    former = ok(client.get("/api/people?left=only", headers=as_gym(gym)))["items"]
    [record] = [p for p in former if p["name"] == "Exalumno anonimizado"]
    anonymous = ok(client.get(f"/api/people/{record['id']}", headers=as_gym(gym)))
    assert anonymous["anonymised"] is True
    assert (anonymous["rut"], anonymous["email"], anonymous["phone"], anonymous["dob"]) == (
        None,
        None,
        None,
        None,
    )
    [kept] = memberships(client, gym, record["id"])
    assert kept["id"] == member.membership
    entries = ok(client.get(f"/api/ledger/memberships/{kept['id']}", headers=as_gym(gym)))[
        "entries"
    ]
    assert sum(e["amount_clp"] for e in entries if e["kind"] == "payment") == 90_000

    # Nothing of it is edited again, and it is not anonymised twice.
    edited = client.patch(
        f"/api/people/{record['id']}", json={"name": member.name}, headers=as_gym(gym)
    )
    assert (edited.status_code, edited.json()["detail"]) == (409, "anonymised")
    back = client.post(f"/api/people/{record['id']}/return", json={}, headers=as_gym(gym))
    assert (back.status_code, back.json()["detail"]) == (409, "anonymised")
    again = anonymise(client, gym, record["id"])
    assert again.json()["detail"] == {"code": "anonymised", "amount_clp": None}

    # The gym's log says who did it, when and why, and nothing about them.
    [logged] = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT actor_id, person_id, reason, detail FROM audit_event"
            " WHERE action = 'person_anonymised'",
        ),
    )
    assert (logged["actor_id"], logged["person_id"], logged["reason"]) == (
        seeded_owner(gym),
        None,
        REASON,
    )


@pg
def test_another_gyms_record_of_the_same_rut_is_untouched_and_they_may_join_again(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, unique_slug("norte"))
    rut = new_rut()
    theirs = enrolled(client, norte, name="Vale R.", rut=rut, email="vale@norte.cl")
    member = paid_member(client, db, gym, rut=rut)
    assert member.id == theirs["id"]

    assert anonymise(client, gym, member.id).status_code == 204

    assert client.get(f"/api/people/{theirs['id']}", headers=as_gym(norte)).json() == theirs
    rows = run(db.admin_url, lambda c: c.fetch("SELECT id FROM person WHERE rut = $1", rut))
    assert [str(r["id"]) for r in rows] == [theirs["id"]]
    # Nothing in this gym names them any more: only the identity the other gym shares.
    for needle in needles(member):
        assert tables_holding(db, needle, gym=gym) in ([], ["person"]), needle

    # Back here, they are someone new to this gym, not the anonymous record.
    again = enrolled(client, gym, name=member.name, rut=rut)
    assert again["id"] == theirs["id"]
    assert again["anonymised"] is False
    assert memberships(client, gym, again["id"]) == []


@pg
def test_anonymising_is_refused_while_they_train_owe_wait_or_answer_for_someone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    running = enrolled(client, gym, membership={"plan_id": plan(client, gym)})
    assert asked(client, gym, running["id"])["refused"] == "running"
    response = anonymise(client, gym, running["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "running", "amount_clp": None}

    # Dado de baja with the first charge unpaid: what they owe stays owed.
    ok(leave(client, gym, running["id"]))
    assert asked(client, gym, running["id"]) == {"refused": "owes", "amount_clp": 45_000}

    coach = add_staff(db, gym, "coach")
    assert asked(client, gym, str(coach))["refused"] == "staff"

    marta = enrolled(client, gym, name="Marta")
    enrolled(client, gym, phone=None, name="Tomás", guardian={"person_id": marta["id"]})
    assert asked(client, gym, marta["id"])["refused"] == "guardian"

    assert (
        client.get(f"/api/people/{uuid.uuid4()}/anonymisation", headers=as_gym(gym)).status_code
        == 404
    )
    assert anonymise(client, gym, str(uuid.uuid4())).status_code == 404
    # Nothing was written by a refusal.
    assert client.get(f"/api/people/{running['id']}", headers=as_gym(gym)).status_code == 200


@pg
def test_a_proof_waiting_is_refused(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    body = enrolled(
        client, gym, email="espera@example.cl", membership={"plan_id": plan(client, gym)}
    )
    [membership] = memberships(client, gym, body["id"])
    [period, *_] = ok(
        client.get(f"/api/ledger/memberships/{membership['id']}", headers=as_gym(gym))
    )["open_periods"]
    key = upload(client, gym, body["id"])
    claimed = client.post(
        "/api/me/payments",
        json={"billing_period_id": period["id"], "amount_clp": 45_000, "proof_key": key},
        headers=as_gym(gym, uuid.UUID(body["id"])),
    )
    assert claimed.status_code == 201, claimed.text
    ok(leave(client, gym, body["id"]))
    assert asked(client, gym, body["id"])["refused"] == "pending"


@pg
def test_only_the_titular_anonymises(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    member = paid_member(client, db, gym)
    admin = add_staff(db, gym, "admin")
    assert anonymise(client, gym, member.id, admin).status_code == 403
    path = f"/api/people/{member.id}/anonymisation"
    assert client.get(path, headers=as_gym(gym, admin)).status_code == 403


@pg
def test_the_app_role_cannot_open_the_guards(db: Database, gym: uuid.UUID) -> None:
    async def forge(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "INSERT INTO person_anonymisation VALUES ($1, $2, $3, now())",
                gym,
                uuid.uuid4(),
                uuid.uuid4(),
            )

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, forge)

    async def call(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT retire_person($1, false, NULL)", uuid.uuid4())

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, call)


@pg
def test_deleting_takes_the_leftovers_too(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    """Eliminar's gaps (#366): messages, sign-in links, idempotency keys, proof files and
    the global person."""
    member = paid_member(client, db, gym)
    # Back on the roll is not needed to refund: give the money back, then void what is owed.
    entries = ok(client.get(f"/api/ledger/memberships/{member.membership}", headers=as_gym(gym)))[
        "entries"
    ]
    for entry in entries:
        if entry["kind"] == "payment":
            refund(client, gym, entry["id"])
    ok(
        client.post(
            f"/api/memberships/{member.membership}/void",
            json={"reason": "prueba"},
            headers=as_gym(gym),
        )
    )
    deletion = ok(client.get(f"/api/people/{member.id}/deletion", headers=as_gym(gym)))
    assert deletion["refused"] is None, deletion

    assert forget(client, gym, member.id).status_code == 204

    for needle in needles(member):
        assert tables_holding(db, needle) == [], needle
    assert not stored(client, member.proof)
