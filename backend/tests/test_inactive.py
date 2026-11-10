"""The inactive list and its WhatsApp nudge (#50).

`v_inactive` says when each live member last came (`tests/test_attendance.py`); this
is what the endpoint adds: the 14 and 30 day buckets, the payment status, the `wa.me`
link to them or their guardian, and the nudge recorded in `message_log`.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.main import create_app
from app.notices.whatsapp import inactive_nudge
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
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
from tests.test_attendance import changed, class_type, join, plan, program, session_of
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import CREDITS, TRIAL, add_staff

# --- the message, no database -----------------------------------------------------


def test_the_nudge_greets_by_first_name_and_says_how_long() -> None:
    text = inactive_nudge(
        to_name="Ignacio Vera",
        about_name=None,
        gym_name="Academia Sur",
        days_absent=16,
        attended=True,
    )
    assert text == (
        "Hola Ignacio, te echamos de menos en Academia Sur: hace 16 días que no vienes"
        " a entrenar. ¿Todo bien? ¡Te esperamos!"
    )


def test_a_nudge_about_a_dependent_is_to_the_guardian_about_them() -> None:
    text = inactive_nudge(
        to_name="Ana Rojas",
        about_name="Tomás Rojas",
        gym_name="Academia Sur",
        days_absent=0,
        attended=False,
    )
    assert text == (
        "Hola Ana, echamos de menos a Tomás en Academia Sur: todavía no viene a su"
        " primera clase. ¿Todo bien? ¡Los esperamos!"
    )


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def listed(client: TestClient, gym: uuid.UUID) -> Any:
    response = client.get("/api/inactive", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def by_name(rows: Any) -> dict[str, Any]:
    return {r["name"]: r for r in rows}


def nudge(client: TestClient, gym: uuid.UUID, person: str, **kw: Any) -> Any:
    return client.post(f"/api/inactive/{person}/nudge", headers=as_gym(gym, **kw))


def came(client: TestClient, gym: uuid.UUID, membership: str, days_ago: int) -> None:
    """`membership` at a class `days_ago` days ago, free to attend."""
    free = class_type(client, gym, program(client, gym, f"P {uuid.uuid4().hex[:6]}"), cost=0)
    day = seeded_today() - timedelta(days=days_ago)
    changed(client, gym, session_of(client, gym, free, day), mark=[membership])


def member_since(db: Database, membership: str, days_ago: int) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET started_at = now() - make_interval(days => $1) WHERE id = $2",
            days_ago,
            uuid.UUID(membership),
        ),
    )


def a_member(client: TestClient, gym: uuid.UUID, name: str, days_ago: int) -> str:
    person = add_person(client, gym, name)
    came(client, gym, join(client, gym, person, plan(client, gym, CREDITS)), days_ago)
    return person


def logged(db: Database, gym: uuid.UUID) -> list[Any]:
    return list(
        run(
            db.api_url,
            in_gym(
                gym,
                "SELECT person_id, channel, template, to_address, status, payload"
                " FROM message_log WHERE channel = 'whatsapp' ORDER BY sent_at",
            ),
        )
    )


def phone_of(db: Database, person: str) -> str:
    rows = run(
        db.admin_url, lambda c: c.fetch("SELECT phone FROM person WHERE id = $1", uuid.UUID(person))
    )
    return str(rows[0]["phone"])


@pg
def test_members_away_14_days_or_more_in_two_buckets_nearest_first(
    client: TestClient, gym: uuid.UUID
) -> None:
    a_member(client, gym, "Antonia Rojas", 5)
    a_member(client, gym, "Javiera Silva", 13)
    a_member(client, gym, "Diego Morales", 31)
    a_member(client, gym, "Ignacio Vera", 16)
    a_member(client, gym, "Felipe Díaz", 30)
    a_member(client, gym, "Tomás Pérez", 14)

    rows = listed(client, gym)

    assert [(r["name"], r["days_absent"], r["bucket"]) for r in rows] == [
        ("Tomás Pérez", 14, 14),
        ("Ignacio Vera", 16, 14),
        ("Felipe Díaz", 30, 30),
        ("Diego Morales", 31, 30),
    ]
    assert rows[1]["last_attended_on"] == (seeded_today() - timedelta(days=16)).isoformat()


@pg
def test_someone_who_never_came_counts_from_when_they_joined(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    pack = plan(client, gym, CREDITS)
    member_since(db, join(client, gym, add_person(client, gym, "Paula Contreras"), pack), 20)
    join(client, gym, add_person(client, gym, "Andrés Molina"), pack)  # joined today

    rows = listed(client, gym)

    # The seeded owner joined today too, and is not listed either.
    assert [(r["name"], r["last_attended_on"], r["days_absent"]) for r in rows] == [
        ("Paula Contreras", None, 20)
    ]


@pg
def test_each_says_whether_they_are_up_to_date_on_their_payments(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_member(client, gym, "Al Día", 20)
    owing = add_person(client, gym, "Debe Plata")
    came(client, gym, bill(db, gym, owing, [(-10, 30000, 5000, 0), (-40, 45000, 0, 0)]), 20)
    trying = add_person(client, gym, "En Prueba")
    came(client, gym, join(client, gym, trying, plan(client, gym, TRIAL)), 20)

    rows = by_name(listed(client, gym))

    status = {name: (r["payment_status"], r["overdue_clp"]) for name, r in rows.items()}
    assert status == {
        "Al Día": ("up_to_date", 0),
        "Debe Plata": ("overdue", 70000),
        "En Prueba": ("trial", 0),
    }


@pg
def test_the_link_opens_whatsapp_on_them_with_the_nudge(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = a_member(client, gym, "Ignacio Vera", 16)

    row = listed(client, gym)[0]

    url = urlsplit(row["whatsapp_url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "wa.me", f"/{phone_of(db, ignacio)[1:]}")
    gym_name = run(db.admin_url, lambda c: c.fetchval("SELECT name FROM gym WHERE id = $1", gym))
    assert parse_qs(url.query)["text"] == [
        inactive_nudge(
            to_name="Ignacio Vera",
            about_name=None,
            gym_name=gym_name,
            days_absent=16,
            attended=True,
        )
    ]
    assert row["contact_name"] == "Ignacio Vera"


@pg
def test_a_dependent_is_nudged_through_their_guardian(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = add_person(client, gym, "Ana Rojas")
    tomas = new_kid(client, gym, ana, "Tomás Rojas")
    came(client, gym, join(client, gym, tomas, plan(client, gym, CREDITS)), 15)

    row = listed(client, gym)[0]

    assert (row["name"], row["contact_name"]) == ("Tomás Rojas", "Ana Rojas")
    url = urlsplit(row["whatsapp_url"])
    assert url.path == f"/{phone_of(db, ana)[1:]}"
    assert "echamos de menos a Tomás" in parse_qs(url.query)["text"][0]

    assert nudge(client, gym, tomas).status_code == 201
    [log] = logged(db, gym)
    assert (str(log["person_id"]), log["to_address"]) == (ana, phone_of(db, ana))
    assert '"about": "' + tomas in log["payload"]


@pg
def test_opening_the_nudge_records_it_in_message_log(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = a_member(client, gym, "Ignacio Vera", 16)
    assert listed(client, gym)[0]["nudged_at"] is None

    response = nudge(client, gym, ignacio)

    assert response.status_code == 201, response.text
    [log] = logged(db, gym)
    assert (str(log["person_id"]), log["channel"], log["template"], log["status"]) == (
        ignacio,
        "whatsapp",
        "inactive_nudge",
        "sent",
    )
    assert log["to_address"] == phone_of(db, ignacio)
    assert log["payload"] == f'{{"about": "{ignacio}", "attended": true, "days_absent": 16}}'
    assert listed(client, gym)[0]["nudged_at"] == response.json()["sent_at"]


@pg
def test_with_whatsapp_off_there_is_no_link_and_no_nudge(
    client: TestClient, gym: uuid.UUID
) -> None:
    ignacio = a_member(client, gym, "Ignacio Vera", 16)
    off = {"channels": {"whatsapp": False}}
    assert client.patch("/api/gym/settings", json=off, headers=as_gym(gym)).status_code == 200

    assert listed(client, gym)[0]["whatsapp_url"] is None
    assert nudge(client, gym, ignacio).status_code == 409


@pg
def test_someone_with_no_phone_to_write_to_has_no_link(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = a_member(client, gym, "Ignacio Vera", 16)
    run(
        db.admin_url,
        lambda c: c.execute("UPDATE person SET phone = NULL WHERE id = $1", uuid.UUID(ignacio)),
    )

    assert listed(client, gym)[0]["whatsapp_url"] is None
    assert nudge(client, gym, ignacio).status_code == 409


@pg
def test_only_someone_on_the_list_is_nudged(client: TestClient, gym: uuid.UUID) -> None:
    recent = a_member(client, gym, "Antonia Rojas", 3)

    assert nudge(client, gym, recent).status_code == 404
    assert nudge(client, gym, str(uuid.uuid4())).status_code == 404


@pg
def test_another_gyms_members_are_not_listed_or_nudged(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:6]}")
    bea = a_member(client, norte, "Bea Soto", 20)

    assert listed(client, gym) == []
    assert nudge(client, gym, bea).status_code == 404


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_read_it(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    person = seeded_owner(gym) if role == "owner" else add_staff(db, gym, role)

    assert client.get("/api/inactive", headers=as_gym(gym, person_id=person)).status_code == 200


@pg
def test_a_coach_neither_reads_it_nor_nudges(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = a_member(client, gym, "Ignacio Vera", 16)
    coach = add_staff(db, gym, "coach")

    assert client.get("/api/inactive", headers=as_gym(gym, person_id=coach)).status_code == 403
    assert nudge(client, gym, ignacio, person_id=coach).status_code == 403


@pg
def test_upgrade_and_downgrade_0024() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0023")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0023")
        refused = run(
            scratch.admin_url,
            lambda c: c.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'message_log_channel_check'"
            ),
        )
        assert "whatsapp" not in refused
        migrate(scratch)
