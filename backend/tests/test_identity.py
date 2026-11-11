"""Identity by RUT, or by an email in one gym, never by phone (migration 0036, #165).

The cross-gym tests ask what a curious admin would: having typed a RUT that another
gym already has, can they tell? The answer, the record they then read, and the
database grants must all say no. And an email, which a gym types freely, must never
join one gym's person to another's.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.rut import check_digit, format_rut
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres


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


_ruts = iter(range(30_000_000, 50_000_000, 7_919))
_emails = iter(range(1_000_000))


def new_rut() -> str:
    body = next(_ruts)
    return f"{body}-{check_digit(body)}"


def new_email() -> str:
    return f"someone{next(_emails)}@example.com"


def create(client: TestClient, gym: uuid.UUID, **fields: Any) -> Any:
    return client.post("/api/people", json=fields, headers=as_gym(gym))


def entered(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in ("id", "left_on", "created_at", "updated_at")}


def people_with_rut(db: Database, rut: str) -> list[asyncpg.Record]:
    return list(run(db.admin_url, lambda c: c.fetch("SELECT * FROM person WHERE rut = $1", rut)))


def gyms_of(db: Database, person_id: str) -> set[uuid.UUID]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT gym_id FROM gym_person WHERE person_id = $1", uuid.UUID(person_id)
        ),
    )
    return {r["gym_id"] for r in rows}


# --- the oracle-free answer ---------------------------------------------------------


def test_a_rut_known_elsewhere_answers_like_a_new_one(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    known = new_rut()
    norte_body = create(
        client, norte, rut=known, name="Camila R.", email="cr@norte.cl", phone="+56911110000"
    ).json()

    before = datetime.now(UTC)
    typed = {"name": "Camila Rojas", "phone": None, "dob": None}
    fresh = create(client, sur, **typed, email="camila@sur.cl", rut=new_rut())
    attached = create(client, sur, **typed, email="camila.r@sur.cl", rut=format_rut(known))

    # Same status, same shape, and only what sur typed: nothing of norte's record.
    assert attached.status_code == fresh.status_code == 201
    assert set(attached.json()) == set(fresh.json())
    shown = {**typed, "no_whatsapp": False, "missing_phone": True, "missing_rut": False}
    assert entered(attached.json()) == {**shown, "email": "camila.r@sur.cl", "rut": known}
    assert {k: v for k, v in entered(fresh.json()).items() if k != "rut"} == {
        **shown,
        "email": "camila@sur.cl",
    }
    for field in ("created_at", "updated_at"):
        assert datetime.fromisoformat(attached.json()[field]) >= before

    # One person, in both gyms, each with its own record.
    [person] = people_with_rut(db, known)
    assert str(person["id"]) == attached.json()["id"] == norte_body["id"]
    assert client.get(f"/api/people/{person['id']}", headers=as_gym(norte)).json() == norte_body
    sur_view = client.get(f"/api/people/{person['id']}", headers=as_gym(sur)).json()
    assert sur_view == attached.json()


def test_the_function_answers_alike_for_a_new_and_a_known_rut(
    db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    join = "SELECT joined FROM join_gym($1, NULL, 'x', NULL, NULL)"
    known = new_rut()
    run(db.api_url, in_gym(norte, join, known))
    answers = [run(db.api_url, in_gym(sur, join, rut))[0]["joined"] for rut in (known, new_rut())]
    assert answers == [True, True]
    # The person this gym found is the one it already has: that alone it can tell.
    assert run(db.api_url, in_gym(sur, join, known))[0]["joined"] is False


def test_the_api_reads_nothing_of_a_person_but_their_id(db: Database, sur: uuid.UUID) -> None:
    async def columns(conn: asyncpg.Connection) -> list[str]:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.column_privileges"
            " WHERE table_name = 'person' AND grantee = 'rakin_app'"
            " AND privilege_type = 'SELECT'"
        )
        return [r["column_name"] for r in rows]

    assert run(db.admin_url, columns) == ["id"]
    for sql in (
        "SELECT rut FROM person",
        "SELECT email FROM person",
        "SELECT created_at FROM person",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(sur, sql))


def test_the_api_cannot_insert_a_person_to_probe_a_rut(db: Database, sur: uuid.UUID) -> None:
    known = new_rut()
    run(db.api_url, in_gym(sur, "SELECT * FROM join_gym($1, NULL, 'x', NULL, NULL)", known))
    insert = "INSERT INTO person (id, name, rut) VALUES (gen_random_uuid(), 'x', $1)"
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(sur, insert, known))


def test_the_lookup_ends_with_the_function(db: Database, sur: uuid.UUID) -> None:
    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await conn.fetch("SELECT * FROM join_gym($1, NULL, 'x', NULL, NULL)", new_rut())
            return await conn.fetchval("SELECT current_setting('app.person_lookup', true)")

    assert run(db.api_url, query) == "off"


def test_joining_needs_a_gym(db: Database) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match=r"app\.gym_id"):
        run(
            db.api_url, in_gym(None, "SELECT * FROM join_gym($1, NULL, 'x', NULL, NULL)", new_rut())
        )


# --- email: one gym's key, never a link between gyms ----------------------------------


def test_an_email_never_links_two_gyms_people(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    email = new_email()
    in_norte = create(client, norte, email=email, name="Ana").json()
    in_sur = create(client, sur, email=email.upper(), name="Ana")
    assert in_sur.status_code == 201
    assert in_sur.json()["id"] != in_norte["id"]
    assert gyms_of(db, in_norte["id"]) == {norte}
    assert gyms_of(db, in_sur.json()["id"]) == {sur}


def test_an_email_already_in_this_gym_names_that_person(client: TestClient, sur: uuid.UUID) -> None:
    email = new_email()
    first = create(client, sur, email=email, name="Ana").json()
    again = create(client, sur, email=f" {email.upper()} ", name="Ana Pérez")
    assert again.status_code == 409
    assert again.json() == {"detail": {"code": "email_in_gym", "person_id": first["id"]}}


def test_one_gym_holds_an_email_once_whatever_the_rut(client: TestClient, sur: uuid.UUID) -> None:
    # Sign-in goes by the gym and the email (#146): two records with one would be ambiguous.
    email = new_email()
    first = create(client, sur, email=email, name="Mamá", rut=new_rut()).json()
    second = create(client, sur, email=email, name="Hija", rut=new_rut())
    assert second.status_code == 409
    assert second.json() == {"detail": {"code": "email_in_gym", "person_id": first["id"]}}


def test_someone_needs_a_rut_or_an_email(client: TestClient, sur: uuid.UUID) -> None:
    response = create(client, sur, name="Nadie", phone="+56912345678")
    assert response.status_code == 422


# --- the phone: a contact, per gym ----------------------------------------------------


def test_a_phone_finds_nobody(client: TestClient, sur: uuid.UUID) -> None:
    phone = "+56955550000"
    first = create(client, sur, rut=new_rut(), name="Uno", phone=phone).json()
    second = create(client, sur, rut=new_rut(), name="Dos", phone=phone)
    assert second.status_code == 201
    assert second.json()["id"] != first["id"]
    assert second.json()["phone"] == phone


def test_the_phone_is_each_gyms_own_and_editable(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    rut = new_rut()
    norte_body = create(client, norte, rut=rut, name="Pedro", phone="+56911112222").json()
    sur_body = create(client, sur, rut=rut, name="Pedro").json()
    assert sur_body["phone"] is None

    edit = client.patch(
        f"/api/people/{sur_body['id']}", json={"phone": "9 3333 4444"}, headers=as_gym(sur)
    )
    assert edit.status_code == 200
    assert edit.json()["phone"] == "+56933334444"
    # A member's phone goes only with "No tiene WhatsApp" ticked in its place.
    refused = client.patch(
        f"/api/people/{sur_body['id']}", json={"phone": None}, headers=as_gym(sur)
    )
    assert refused.status_code == 422
    cleared = client.patch(
        f"/api/people/{sur_body['id']}",
        json={"phone": None, "no_whatsapp": True},
        headers=as_gym(sur),
    )
    assert (cleared.json()["phone"], cleared.json()["no_whatsapp"]) == (None, True)
    assert client.get(f"/api/people/{norte_body['id']}", headers=as_gym(norte)).json() == norte_body


def test_a_bad_phone_is_refused(client: TestClient, sur: uuid.UUID) -> None:
    assert create(client, sur, rut=new_rut(), name="X", phone="22 345 6789").status_code == 422


# --- the phone a member needs (#165) ---------------------------------------------


def test_a_member_with_no_phone_is_flagged_and_listed_until_one_is_given(
    client: TestClient, sur: uuid.UUID
) -> None:
    body = create(client, sur, rut=new_rut(), name="Sin Fono").json()
    assert (body["phone"], body["no_whatsapp"], body["missing_phone"]) == (None, False, True)
    listed = client.get("/api/people?missing_phone=true", headers=as_gym(sur)).json()["items"]
    assert body["id"] in {row["id"] for row in listed}
    assert all(row["missing_phone"] for row in listed)

    # Editing something else leaves them as they were; ticking the box clears the flag.
    renamed = client.patch(
        f"/api/people/{body['id']}", json={"name": "Sin Fono Aún"}, headers=as_gym(sur)
    )
    assert renamed.status_code == 200
    ticked = client.patch(
        f"/api/people/{body['id']}", json={"no_whatsapp": True}, headers=as_gym(sur)
    ).json()
    assert ticked["missing_phone"] is False
    listed = client.get("/api/people?missing_phone=true", headers=as_gym(sur)).json()["items"]
    assert body["id"] not in {row["id"] for row in listed}

    # Unticking it needs a phone.
    unticked = client.patch(
        f"/api/people/{body['id']}", json={"no_whatsapp": False}, headers=as_gym(sur)
    )
    assert unticked.status_code == 422
    with_phone = client.patch(
        f"/api/people/{body['id']}",
        json={"no_whatsapp": False, "phone": "9 4444 5555"},
        headers=as_gym(sur),
    )
    assert (with_phone.status_code, with_phone.json()["missing_phone"]) == (200, False)


def test_staff_need_no_phone(client: TestClient, sur: uuid.UUID) -> None:
    address = f"{uuid.uuid4().hex[:8]}@example.cl"
    invited = client.post(
        "/api/staff",
        json={"name": "Coach", "email": address, "role": "coach"},
        headers=as_gym(sur),
    )
    assert invited.status_code == 201, invited.text
    person = client.get(f"/api/people/{invited.json()['person_id']}", headers=as_gym(sur)).json()
    assert (person["phone"], person["missing_phone"]) == (None, False)


# --- the migration, on data as 0035 left it --------------------------------------


def test_the_upgrade_keeps_every_phone_and_keys_people_by_rut() -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0035")
        sur, norte = uuid.uuid4(), uuid.uuid4()
        both, typo, agreed, kid, bad = (uuid.uuid4() for _ in range(5))

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO gym (id, name, slug) VALUES ($1, 's', 's'), ($2, 'n', 'n')", sur, norte
            )
            # `both` is in two gyms; `typo` was added later under the same RUT; `agreed`
            # has none on `person`, and the one its gyms agree on; `bad` one not in the
            # stored form; `kid` no phone at all.
            await conn.executemany(
                "INSERT INTO person (id, name, phone, rut, created_at) VALUES ($1, $2, $3, $4, $5)",
                [
                    (both, "Ana", "+56911110001", "7654321-6", datetime(2025, 1, 1, tzinfo=UTC)),
                    (
                        typo,
                        "Ana bis",
                        "+56911110002",
                        "7654321-6",
                        datetime(2025, 6, 1, tzinfo=UTC),
                    ),
                    (agreed, "Beto", "+56911110003", None, datetime(2025, 1, 1, tzinfo=UTC)),
                    (bad, "Carla", "+56911110004", "7.654.321-6", datetime(2025, 1, 1, tzinfo=UTC)),
                    (kid, "Kid", None, None, datetime(2025, 1, 1, tzinfo=UTC)),
                ],
            )
            await conn.executemany(
                "INSERT INTO gym_person (gym_id, person_id, name, rut) VALUES ($1, $2, $3, $4)",
                [
                    (sur, both, "Ana", "7654321-6"),
                    (norte, both, "Ana N.", "7654321-6"),
                    (sur, typo, "Ana bis", "7654321-6"),
                    (sur, agreed, "Beto", "11111111-1"),
                    (norte, agreed, "Beto", "11111111-1"),
                    (sur, bad, "Carla", None),
                    (sur, kid, "Kid", None),
                ],
            )
            await conn.execute(
                "INSERT INTO join_request (gym_id, first_name, last_name, rut, phone, email, dob,"
                " consented_at) VALUES ($1, 'Pía', 'Soto', '12345678-5', '+56911110009',"
                " 'pia@example.cl', '1990-01-01', now())",
                sur,
            )

        run(db.admin_url, seed)
        before = run(db.admin_url, lambda c: c.fetchval("SELECT count(*) FROM gym_person"))
        migrate(db)

        people = {
            r["id"]: r["rut"]
            for r in run(db.admin_url, lambda c: c.fetch("SELECT id, rut FROM person"))
        }
        assert people == {both: "7654321-6", typo: None, agreed: "11111111-1", bad: None, kid: None}
        records = run(
            db.admin_url,
            lambda c: c.fetch("SELECT gym_id, person_id, phone, rut, no_whatsapp FROM gym_person"),
        )
        assert len(records) == before
        phones = {(r["gym_id"], r["person_id"]): r["phone"] for r in records}
        assert phones[(sur, both)] == phones[(norte, both)] == "+56911110001"
        assert phones[(sur, typo)] == "+56911110002"
        assert phones[(sur, kid)] is None
        # Both in sur under one RUT: the later one's record there loses it, so one gym
        # never holds a RUT twice.
        assert {(r["gym_id"], r["person_id"]): r["rut"] for r in records}[(sur, typo)] is None
        assert not any(r["no_whatsapp"] for r in records)
        assert run(db.admin_url, lambda c: c.fetchval("SELECT count(*) FROM join_request")) == 1

        # Lossless: down again, every phone is back on its person.
        command.downgrade(db.alembic(), "0035")
        restored = run(db.admin_url, lambda c: c.fetch("SELECT id, phone FROM person"))
        assert {r["id"]: r["phone"] for r in restored} == {
            both: "+56911110001",
            typo: "+56911110002",
            agreed: "+56911110003",
            bad: "+56911110004",
            kid: None,
        }


def test_a_record_under_a_shared_rut_moves_to_the_person_who_keeps_it() -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0035")
        sur, norte, kept, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO gym (id, name, slug) VALUES ($1, 's', 's'), ($2, 'n', 'n')", sur, norte
            )
            # One human, added under two phones: `kept` in sur, `other` in norte, later.
            await conn.executemany(
                "INSERT INTO person (id, name, phone, rut, created_at) VALUES ($1, $2, $3, $4, $5)",
                [
                    (kept, "Ana", "+56911110001", "7654321-6", datetime(2025, 1, 1, tzinfo=UTC)),
                    (other, "Ana", "+56911110002", "7654321-6", datetime(2025, 6, 1, tzinfo=UTC)),
                ],
            )
            await conn.executemany(
                "INSERT INTO gym_person (gym_id, person_id, name, rut) VALUES ($1, $2, 'Ana', $3)",
                [(sur, kept, "7654321-6"), (norte, other, "7654321-6")],
            )
            plan = await conn.fetchval(
                "INSERT INTO plan (gym_id, name, kind, price_clp, anchor)"
                " VALUES ($1, 'M', 'monthly', 1, 'signup') RETURNING id",
                norte,
            )
            await conn.execute(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " VALUES ($1, $2, $3, 'active')",
                norte,
                other,
                plan,
            )
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')", norte, other
            )

        run(db.admin_url, seed)
        migrate(db)

        def owners(sql: str) -> set[uuid.UUID]:
            return {r[0] for r in run(db.admin_url, lambda c: c.fetch(sql, norte))}

        # Norte's record, its membership and its staff row are now `kept`'s.
        assert owners("SELECT person_id FROM gym_person WHERE gym_id = $1") == {kept}
        assert owners("SELECT person_id FROM membership WHERE gym_id = $1") == {kept}
        assert owners("SELECT person_id FROM staff WHERE gym_id = $1") == {kept}
        ruts = run(db.admin_url, lambda c: c.fetch("SELECT id, rut FROM person"))
        assert {r["id"]: r["rut"] for r in ruts} == {kept: "7654321-6", other: None}
        # And `join_gym` in norte finds them, as the one person they are.
        join = "SELECT person_id, joined FROM join_gym('7654321-6', NULL, 'x', NULL, NULL)"
        assert [tuple(r) for r in run(db.api_url, in_gym(norte, join))] == [(kept, False)]


def test_of_two_records_under_a_shared_rut_in_one_gym_the_first_moves() -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0035")
        sur, norte = uuid.uuid4(), uuid.uuid4()
        kept, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO gym (id, name, slug) VALUES ($1, 's', 's'), ($2, 'n', 'n')", sur, norte
            )
            # Three people one RUT: `kept` in sur, and norte added the same human twice.
            await conn.executemany(
                "INSERT INTO person (id, name, phone, rut, created_at) VALUES ($1, $2, $3, $4, $5)",
                [
                    (kept, "Ana", "+56911110001", "7654321-6", datetime(2025, 1, 1, tzinfo=UTC)),
                    (first, "Ana", "+56911110002", "7654321-6", datetime(2025, 2, 1, tzinfo=UTC)),
                    (second, "Ana", "+56911110003", "7654321-6", datetime(2025, 3, 1, tzinfo=UTC)),
                ],
            )
            await conn.executemany(
                "INSERT INTO gym_person (gym_id, person_id, name, rut, created_at)"
                " VALUES ($1, $2, $3, '7654321-6', $4)",
                [
                    (sur, kept, "Ana", datetime(2025, 1, 1, tzinfo=UTC)),
                    (norte, first, "Ana", datetime(2025, 2, 1, tzinfo=UTC)),
                    (norte, second, "Ana bis", datetime(2025, 3, 1, tzinfo=UTC)),
                ],
            )

        run(db.admin_url, seed)
        migrate(db)

        records = run(
            db.admin_url,
            lambda c: c.fetch(
                "SELECT person_id, name, rut FROM gym_person WHERE gym_id = $1", norte
            ),
        )
        # The earlier record moves to `kept`; the later stays its own and loses the RUT.
        assert {r["person_id"]: (r["name"], r["rut"]) for r in records} == {
            kept: ("Ana", "7654321-6"),
            second: ("Ana bis", None),
        }
        ruts = run(db.admin_url, lambda c: c.fetch("SELECT id, rut FROM person"))
        assert {r["id"]: r["rut"] for r in ruts} == {kept: "7654321-6", first: None, second: None}
        missing = (
            "SELECT person_id FROM gym_person WHERE gym_id = $1 AND rut IS NULL AND email IS NULL"
        )
        assert [r[0] for r in run(db.admin_url, lambda c: c.fetch(missing, norte))] == [second]


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE gym_person SET phone = '+56922220000' WHERE gym_id = $1",
        "UPDATE gym_person SET no_whatsapp = true WHERE gym_id = $1",
        "UPDATE join_request SET rut = NULL WHERE gym_id = $1",
    ],
    ids=["two-phones", "no-whatsapp", "request-without-rut"],
)
def test_the_downgrade_refuses_what_it_would_lose(change: str) -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0035")
        sur, norte, ana = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO gym (id, name, slug) VALUES ($1, 's', 's'), ($2, 'n', 'n')", sur, norte
            )
            await conn.execute(
                "INSERT INTO person (id, name, phone) VALUES ($1, 'Ana', '+56911110001')", ana
            )
            await conn.executemany(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Ana')",
                [(sur, ana), (norte, ana)],
            )
            await conn.execute(
                "INSERT INTO join_request (gym_id, first_name, last_name, rut, phone, email, dob,"
                " consented_at) VALUES ($1, 'Pía', 'Soto', '12345678-5', '+56911110009',"
                " 'pia@example.cl', '1990-01-01', now())",
                sur,
            )

        run(db.admin_url, seed)
        migrate(db)
        run(db.admin_url, lambda c: c.execute(change, sur))

        with pytest.raises(Exception, match="downgrade from 0036 refused"):
            command.downgrade(db.alembic(), "0035")
        # Nothing changed: still at 0036.
        version = run(db.admin_url, lambda c: c.fetchval("SELECT version_num FROM alembic_version"))
        assert version == "0036"
