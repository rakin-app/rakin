"""Guardians and dependents (migration 0010): the links, the rules they hold, who a
notice goes to, and what a guardian sees of each kid.

One payer, N dependents, and kids have no phone. Links belong to one gym: the other
gym that shares a parent never learns about the family.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from alembic import command
from app.contacts import Contact, contact_for
from app.db import create_engine, create_sessionmaker
from app.db_bootstrap import to_dsn
from app.main import create_app
from app.schemas.guardians import LinkDependent, NewDependent
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
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
from tests.test_people import new_phone

# --- input rules, no database -----------------------------------------------------

Body = TypeAdapter(LinkDependent | NewDependent)


def test_a_body_is_a_link_or_a_new_dependent() -> None:
    person = uuid.uuid4()
    assert Body.validate_python({"person_id": str(person)}) == LinkDependent(person_id=person)
    assert Body.validate_python({"name": " Mateo ", "rut": "7.654.321-6"}) == NewDependent(
        name="Mateo", rut="7654321-6"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Mateo", "phone": "123"},
        {"name": "  "},
        {"person_id": str(uuid.uuid4()), "name": "Mateo"},
        {},
    ],
    ids=str,
)
def test_a_body_refuses(body: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Body.validate_python(body)


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def norte(db: Database) -> uuid.UUID:
    return seed_gym(db, "dojo-norte")


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def add_person(
    client: TestClient,
    gym: uuid.UUID,
    name: str,
    phone: str | None = None,
    rut: str | None = None,
) -> str:
    body = {
        "phone": phone or new_phone(),
        "name": name,
        "email": f"{name.lower().replace(' ', '.')}@example.cl",
        "rut": rut or random_rut(),
    }
    response = client.post("/api/people", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    person: str = response.json()["id"]
    return person


def add_dependent(client: TestClient, gym: uuid.UUID, guardian: str, **body: Any) -> Any:
    return client.post(f"/api/people/{guardian}/dependents", json=body, headers=as_gym(gym))


def new_kid(client: TestClient, gym: uuid.UUID, guardian: str, name: str) -> str:
    response = add_dependent(client, gym, guardian, name=name)
    assert response.status_code == 201, response.text
    kid: str = next(d["id"] for d in response.json()["dependents"] if d["name"] == name)
    return kid


def family(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    response = client.get(f"/api/people/{person}/family", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def as_owner(db: Database, gym: uuid.UUID, sql: str, *args: object) -> Any:
    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            return await conn.fetchval(sql, *args)

    return run(db.owner_url, query)


# --- linking ----------------------------------------------------------------------


@pg
def test_a_new_dependent_has_no_phone_and_joins_the_gym(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    camila = add_person(client, sur, "Camila")
    response = add_dependent(client, sur, camila, name="Mateo", dob="2018-04-02")
    assert response.status_code == 201
    [mateo] = response.json()["dependents"]
    assert response.json() == {"guardian": None, "dependents": [mateo]}
    assert mateo["name"] == "Mateo"

    record = client.get(f"/api/people/{mateo['id']}", headers=as_gym(sur)).json()
    assert (record["phone"], record["email"], record["dob"]) == (None, None, "2018-04-02")
    assert family(client, sur, mateo["id"]) == {
        "guardian": {"id": camila, "name": "Camila"},
        "dependents": [],
    }
    # A person of their own, in this gym only.
    gyms = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT gym_id FROM gym_person WHERE person_id = $1", uuid.UUID(mateo["id"])
        ),
    )
    assert [r["gym_id"] for r in gyms] == [sur]


@pg
def test_one_guardian_pays_for_several(client: TestClient, sur: uuid.UUID) -> None:
    pedro = add_person(client, sur, "Pedro")
    sofia = new_kid(client, sur, pedro, "Sofía")
    ana = add_person(client, sur, "Ana")  # already in the gym, with a phone
    response = add_dependent(client, sur, pedro, person_id=ana)
    assert response.status_code == 201
    assert response.json()["dependents"] == [
        {"id": ana, "name": "Ana"},
        {"id": sofia, "name": "Sofía"},
    ]


@pg
def test_the_member_list_shows_the_family(client: TestClient, sur: uuid.UUID) -> None:
    rosa = add_person(client, sur, "Rosa Lista")
    kid = new_kid(client, sur, rosa, "Tomás Lista")
    new_kid(client, sur, rosa, "Inés Lista")
    response = client.get("/api/people", params={"q": "lista"}, headers=as_gym(sur))
    rows = {r["name"]: r for r in response.json()["items"]}
    assert (rows["Rosa Lista"]["guardian"], rows["Rosa Lista"]["dependents"]) == (None, 2)
    assert rows["Tomás Lista"]["guardian"] == {"id": rosa, "name": "Rosa Lista"}
    assert rows["Tomás Lista"]["dependents"] == 0
    assert rows["Tomás Lista"]["id"] == kid
    assert rows["Tomás Lista"]["phone"] is None


@pg
def test_a_dependent_has_one_guardian(client: TestClient, sur: uuid.UUID) -> None:
    mother, father = add_person(client, sur, "Madre"), add_person(client, sur, "Padre")
    kid = new_kid(client, sur, mother, "Hijo")
    response = add_dependent(client, sur, father, person_id=kid)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "has_guardian"}}
    assert family(client, sur, kid)["guardian"] == {"id": mother, "name": "Madre"}


@pg
def test_links_are_one_level_deep(client: TestClient, sur: uuid.UUID) -> None:
    grandma, mother = add_person(client, sur, "Abuela"), add_person(client, sur, "Mamá")
    kid = new_kid(client, sur, mother, "Nieto")
    # The dependent would be a guardian, and the guardian a dependent.
    for guardian, dependent in ((grandma, mother), (kid, grandma)):
        response = add_dependent(client, sur, guardian, person_id=dependent)
        assert response.status_code == 409, (guardian, dependent)
        assert response.json() == {"detail": {"code": "one_level"}}
    # Nothing was written by either refusal.
    assert family(client, sur, grandma) == {"guardian": None, "dependents": []}


@pg
def test_concurrent_links_cannot_make_a_chain(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    """A→B and B→C in two open transactions: the second waits for the first, then sees
    its row and is refused. Without the trigger's lock both would commit."""
    a, b, c = (add_person(client, sur, n) for n in ("Cadena A", "Cadena B", "Cadena C"))
    link = (
        "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
        " VALUES ($1, $2, $3)"
    )

    async def go() -> None:
        first = await asyncpg.connect(to_dsn(db.api_url))
        second = await asyncpg.connect(to_dsn(db.api_url))
        try:
            for conn in (first, second):
                await conn.execute("BEGIN")
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await first.execute(link, sur, uuid.UUID(a), uuid.UUID(b))
            waiting = asyncio.create_task(second.execute(link, sur, uuid.UUID(b), uuid.UUID(c)))
            await asyncio.sleep(0.5)
            assert not waiting.done(), "the second link did not wait for the first"
            await first.execute("COMMIT")
            with pytest.raises(asyncpg.CheckViolationError, match="the guardian is a dependent"):
                await waiting
        finally:
            await first.close()
            await second.close()

    asyncio.run(go())
    assert family(client, sur, b) == {
        "guardian": {"id": a, "name": "Cadena A"},
        "dependents": [],
    }


@pg
def test_nobody_is_their_own_guardian(client: TestClient, sur: uuid.UUID) -> None:
    person = add_person(client, sur, "Solo")
    assert add_dependent(client, sur, person, person_id=person).status_code == 422


@pg
def test_a_new_dependent_refused_with_its_link_is_not_added(
    client: TestClient, sur: uuid.UUID
) -> None:
    mother = add_person(client, sur, "Mamá Dos")
    kid = new_kid(client, sur, mother, "Niña Dos")
    before = client.get("/api/people", params={"q": "Nieta Huérfana"}, headers=as_gym(sur))
    # `kid` is a dependent, so it cannot be a guardian: the new person goes too.
    response = add_dependent(client, sur, kid, name="Nieta Huérfana")
    assert response.status_code == 409
    after = client.get("/api/people", params={"q": "Nieta Huérfana"}, headers=as_gym(sur))
    assert after.json()["total"] == before.json()["total"] == 0


@pg
def test_people_outside_the_gym_are_not_found(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    here = add_person(client, sur, "Aquí")
    there = add_person(client, norte, "Allá")
    assert add_dependent(client, sur, here, person_id=there).status_code == 404
    assert add_dependent(client, sur, there, name="Kid").status_code == 404
    assert client.get(f"/api/people/{there}/family", headers=as_gym(sur)).status_code == 404


@pg
def test_unlinking_keeps_both_in_the_gym(client: TestClient, sur: uuid.UUID) -> None:
    mother = add_person(client, sur, "Mamá Tres")
    kid = new_kid(client, sur, mother, "Hijo Tres")
    url = f"/api/people/{mother}/dependents/{kid}"
    assert client.delete(url, headers=as_gym(sur)).status_code == 204
    assert client.delete(url, headers=as_gym(sur)).status_code == 404
    assert family(client, sur, mother) == {"guardian": None, "dependents": []}
    assert client.get(f"/api/people/{kid}", headers=as_gym(sur)).status_code == 200


@pg
def test_a_family_stays_in_its_gym(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    # A parent in both gyms, whose kid trains only in Sur.
    rut = random_rut()
    parent = add_person(client, sur, "Compartida", rut=rut)
    assert add_person(client, norte, "Compartida", rut=rut) == parent
    new_kid(client, sur, parent, "Solo en Sur")

    assert family(client, norte, parent) == {"guardian": None, "dependents": []}
    links = "SELECT gym_id FROM guardian_link"
    assert run(db.api_url, in_gym(norte, links)) == []
    assert run(db.api_url, in_gym(None, links)) == []
    assert {r["gym_id"] for r in run(db.api_url, in_gym(sur, links))} == {sur}


@pg
def test_the_api_cannot_link_in_another_gym(db: Database, sur: uuid.UUID, norte: uuid.UUID) -> None:
    insert = (
        "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
        " VALUES ($1, $2, $3)"
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(db.api_url, in_gym(sur, insert, norte, seeded_owner(norte), uuid.uuid4()))


# --- who a notice goes to ---------------------------------------------------------


def contact(db: Database, gym: uuid.UUID, person: str) -> Contact | None:
    async def go() -> Contact | None:
        engine = create_engine(make_settings(database_url=db.api_url))
        try:
            async with create_sessionmaker(engine)() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.gym_id', :gym, true)"), {"gym": str(gym)}
                )
                return await contact_for(session, uuid.UUID(person))
        finally:
            await engine.dispose()

    return asyncio.run(go())


@pg
def test_notices_about_a_dependent_go_to_the_guardian(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    phone = new_phone()
    lucia = add_person(client, sur, "Lucía", phone=phone)
    kid = new_kid(client, sur, lucia, "Benja")

    assert contact(db, sur, kid) == Contact(
        person_id=uuid.UUID(lucia),
        name="Lucía",
        email="lucía@example.cl",
        phone=phone,
        on_behalf_of=uuid.UUID(kid),
    )
    assert contact(db, sur, lucia) == Contact(
        person_id=uuid.UUID(lucia),
        name="Lucía",
        email="lucía@example.cl",
        phone=phone,
        on_behalf_of=None,
    )
    assert contact(db, norte, kid) is None


# --- what the guardian sees -------------------------------------------------------


def bill(
    db: Database, gym: uuid.UUID, person: str, periods: list[tuple[int, int, int, int]]
) -> str:
    """A membership for `person`, and per period (days until due, amount due, validated
    payments, pending payments), its charge and payments."""

    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            membership = await conn.fetchval(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " SELECT gym_id, $1, id, 'active' FROM plan WHERE name = 'Mensual'"
                " RETURNING id",
                uuid.UUID(person),
            )
            for due_in, due, paid, pending in periods:
                start = seeded_today() + timedelta(days=due_in)
                period = await conn.fetchval(
                    "INSERT INTO billing_period (gym_id, membership_id, period_start,"
                    " period_end, amount_due_clp, due_date) VALUES ($1, $2, $3, $4, $5, $3)"
                    " RETURNING id",
                    gym,
                    membership,
                    start,
                    start + timedelta(days=29),
                    due,
                )
                entry = (
                    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id,"
                    " amount_clp, kind, status) VALUES ($1, $2, $3, $4, $5, $6)"
                )
                await conn.execute(entry, gym, membership, period, due, "charge", "validated")
                for amount, status in ((paid, "validated"), (pending, "pending")):
                    if amount:
                        await conn.execute(
                            entry, gym, membership, period, amount, "payment", status
                        )
            return membership  # type: ignore[no-any-return]

    return str(run(db.owner_url, query))


@pg
def test_a_guardian_sees_each_dependents_balance(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    eva = new_kid(client, sur, marta, "Eva")
    # Juan: last month part-paid, this month paid, next month not due yet.
    bill(db, sur, juan, [(-35, 30000, 10000, 0), (-5, 30000, 30000, 0), (25, 30000, 0, 0)])
    # Eva: due today, a proof sent and waiting.
    membership = bill(db, sur, eva, [(0, 25000, 0, 25000)])

    response = client.get("/api/me/dependents", headers=as_gym(sur, uuid.UUID(marta)))
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": eva,
            "name": "Eva",
            "membership": {
                "id": membership,
                "status": "active",
                "plan_id": response.json()[0]["membership"]["plan_id"],
                "plan_name": "Mensual",
            },
            "balance": {"owed_clp": 25000, "pending_clp": 25000},
        },
        {
            "id": juan,
            "name": "Juan",
            "membership": response.json()[1]["membership"],
            "balance": {"owed_clp": 20000, "pending_clp": 0},
        },
    ]


@pg
def test_a_dependent_without_a_membership_owes_nothing(client: TestClient, sur: uuid.UUID) -> None:
    parent = add_person(client, sur, "Sin Plan")
    kid = new_kid(client, sur, parent, "Recién Llegado")
    response = client.get("/api/me/dependents", headers=as_gym(sur, uuid.UUID(parent)))
    assert response.json() == [
        {
            "id": kid,
            "name": "Recién Llegado",
            "membership": None,
            "balance": {"owed_clp": 0, "pending_clp": 0},
        }
    ]


@pg
def test_someone_with_no_dependents_sees_none(client: TestClient, sur: uuid.UUID) -> None:
    alone = add_person(client, sur, "Nadie A Cargo")
    assert client.get("/api/me/dependents", headers=as_gym(sur, uuid.UUID(alone))).json() == []
    assert client.get("/api/me/dependents").status_code == 401


LEDGER = "SELECT DISTINCT membership_id FROM ledger_entry"


@pg
def test_a_person_reads_only_their_own_and_their_dependents_ledger(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    parent = add_person(client, sur, "Papá Libro")
    kid = new_kid(client, sur, parent, "Hija Libro")
    other = add_person(client, sur, "Otro Libro")
    own = bill(db, sur, parent, [(-5, 1000, 0, 0)])
    kids = bill(db, sur, kid, [(-5, 1000, 0, 0)])
    others = bill(db, sur, other, [(-5, 1000, 0, 0)])

    def seen(person: str) -> set[str]:
        rows = run(db.api_url, in_gym(sur, LEDGER, person=uuid.UUID(person)))
        return {str(r["membership_id"]) for r in rows}

    assert seen(parent) == {own, kids}
    assert seen(other) == {others}
    assert seen(kid) == {kids}

    # Read only: a guardian records no entry for their kid.
    payment = (
        "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, method)"
        " VALUES ($1, $2, 1000, 'payment', 'cash')"
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(
            db.api_url,
            in_gym(sur, payment, sur, uuid.UUID(kids), person=uuid.UUID(parent)),
        )


# --- sign-in ----------------------------------------------------------------------


@pg
def test_a_guardian_who_does_not_train_can_sign_in(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # Added by phone: a `gym_person` record but no membership or staff row.
    parent = add_person(client, sur, "Apoderada")
    email = "apoderada@example.cl"
    lookup = "SELECT person_id FROM auth_people_by_email($1)"
    gyms = "SELECT auth_gyms_of($1, $2)"
    assert run(db.api_url, in_gym(None, lookup, email)) == []

    kid = new_kid(client, sur, parent, "Kid Apoderada")
    assert [r[0] for r in run(db.api_url, in_gym(None, lookup, email))] == [uuid.UUID(parent)]
    assert [r[0] for r in run(db.api_url, in_gym(None, gyms, uuid.UUID(parent), email))] == [sur]

    # A session in the gym lasts while the link does.
    token = uuid.uuid4().bytes * 2
    as_owner(
        db,
        sur,
        "INSERT INTO auth_session (token_hash, person_id, email, gym_id, expires_at)"
        " VALUES ($1, $2, $3, $4, now() + interval '1 day')",
        token,
        uuid.UUID(parent),
        email,
        sur,
    )
    live = "SELECT person_id FROM auth_live_session($1, now())"
    assert len(run(db.api_url, in_gym(None, live, token))) == 1
    client.delete(f"/api/people/{parent}/dependents/{kid}", headers=as_gym(sur))
    assert run(db.api_url, in_gym(None, live, token)) == []
    assert run(db.api_url, in_gym(None, lookup, email)) == []


# --- the migration ----------------------------------------------------------------


@pg
def test_downgrade_to_0009_and_back() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0009")
        tables = "SELECT to_regclass('guardian_link') IS NULL"
        assert run(scratch.admin_url, lambda c: c.fetchval(tables)) is True
        migrate(scratch)
        assert run(scratch.admin_url, lambda c: c.fetchval(tables)) is False
