"""Equipo (#311): the gym's own roles, appointments with their terms, and the history.

docs/design/expenses-and-officers.md, sections 1 to 4 and 8: Cargos creates, edits,
archives and adds presets of roles; Personas appoints, ends and corrects; Historial
lists every appointment as it was; the `staff` row follows the appointments; and the
titular can never be locked out.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.db_bootstrap import to_dsn
from app.jobs import team
from app.main import create_app
from app.permissions import (
    ACADEMIA,
    ADMINISTRADOR,
    CLUB_FEDERADO,
    COACH,
    PRESETS,
    SECRETARIO,
    Permission,
    preset_title_id,
)
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)

pytestmark = pytest.mark.postgres


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
    return seed_gym(db, f"equipo-{uuid.uuid4().hex[:6]}")


def admin(db: Database, sql: str, *args: object) -> list[Any]:
    return list(run(db.admin_url, lambda c: c.fetch(sql, *args)))


def person_in(db: Database, gym: uuid.UUID, role: str | None = None, **term: Any) -> uuid.UUID:
    """Someone with a record in `gym`; staff in `role` ("admin", "coach") for `term`."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, $2)", person, "x")
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, $3)",
                gym,
                person,
                f"Persona {person.hex[:6]}",
            )
            if role is not None:
                await make_staff(conn, gym, person, role, **term)

    run(db.admin_url, query)
    return person


def academia(gym: uuid.UUID, key: str) -> str:
    return str(preset_title_id(gym, ACADEMIA, key))


def add_club(client: TestClient, gym: uuid.UUID) -> dict[str, str]:
    """The Club federado's roles added to `gym`, by name: their ids."""
    response = client.post(
        "/api/titles/presets", json={"preset": CLUB_FEDERADO}, headers=as_gym(gym)
    )
    assert response.status_code == 201, response.text
    return {t["name"]: t["id"] for t in titles(client, gym)}


def titles(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> list[Any]:
    response = client.get("/api/titles", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()["titles"]  # type: ignore[no-any-return]


def appoint(
    client: TestClient,
    gym: uuid.UUID,
    person: uuid.UUID,
    title: str,
    by: uuid.UUID | None = None,
    **term: Any,
) -> Any:
    body = {"title_id": title, **{k: str(v) for k, v in term.items()}}
    return client.post(f"/api/staff/{person}/appointments", json=body, headers=as_gym(gym, by))


def appointments(db: Database, person: uuid.UUID) -> list[Any]:
    return admin(
        db,
        "SELECT id, title_name, starts_on, ends_on FROM staff_title WHERE person_id = $1"
        " ORDER BY starts_on, created_at",
        person,
    )


def permissions(client: TestClient, gym: uuid.UUID, person: uuid.UUID) -> list[str] | None:
    answer = client.get("/api/me/role", headers=as_gym(gym, person)).json()
    return answer["permissions"]  # type: ignore[no-any-return]


def on_team(db: Database, person: uuid.UUID) -> bool:
    return bool(admin(db, "SELECT 1 FROM staff WHERE person_id = $1", person))


def log(db: Database, gym: uuid.UUID, *actions: str) -> list[Any]:
    return admin(
        db,
        "SELECT action, person_id, actor_id, detail FROM audit_event"
        " WHERE gym_id = $1 AND action = ANY($2) ORDER BY at, id",
        gym,
        list(actions),
    )


# --- Personas: appointments ---------------------------------------------------------


def test_a_person_with_two_roles_has_the_union_of_their_permissions(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    roles = add_club(client, gym)
    person = person_in(db, gym)
    assert appoint(client, gym, person, roles["Secretario"]).status_code == 201
    assert appoint(client, gym, person, roles["Delegado"]).status_code == 201

    union = SECRETARIO.permissions | {Permission.ATTENDANCE}
    assert permissions(client, gym, person) == sorted(union)
    [member] = [
        m
        for m in client.get("/api/staff", headers=as_gym(gym)).json()
        if m["person_id"] == str(person)
    ]
    assert [a["title_name"] for a in member["appointments"]] == ["Secretario", "Delegado"]
    assert set(member["permissions"]) == union


def test_the_first_appointment_writes_the_staff_row_even_a_future_one(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person = person_in(db, gym)
    tomorrow = seeded_today() + timedelta(days=1)

    response = appoint(client, gym, person, academia(gym, "coach"), starts_on=tomorrow)

    assert response.status_code == 201, response.text
    assert on_team(db, person)
    # A future appointment grants nothing before it starts.
    assert permissions(client, gym, person) is None
    assert client.get("/api/plans", headers=as_gym(gym, person)).status_code == 403
    # The day it starts, it grants everything its role allows, with no job run between:
    # the term moves to today, as the calendar would move under it.
    admin(db, "UPDATE staff_title SET starts_on = $2 WHERE person_id = $1", person, seeded_today())
    assert permissions(client, gym, person) == sorted(COACH.permissions)
    assert client.get("/api/plans", headers=as_gym(gym, person)).status_code == 200


def test_an_overlapping_appointment_to_the_same_role_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym, "coach", starts_on=today - timedelta(days=30))
    coach = academia(gym, "coach")

    assert (
        appoint(client, gym, person, coach, starts_on=today + timedelta(days=60)).status_code == 409
    )
    # A term that ends where another starts does not overlap it (half-open).
    other = person_in(db, gym)
    assert appoint(client, gym, other, coach, ends_on=today + timedelta(days=10)).status_code == 201
    later = appoint(client, gym, other, coach, starts_on=today + timedelta(days=10))
    assert later.status_code == 201, later.text
    assert (
        appoint(client, gym, other, coach, starts_on=today + timedelta(days=5)).status_code == 409
    )


def test_a_term_that_ends_before_it_starts_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym)
    terms: list[dict[str, Any]] = [
        {"ends_on": today},
        {"starts_on": today, "ends_on": today - timedelta(days=1)},
    ]
    for term in terms:
        assert appoint(client, gym, person, academia(gym, "coach"), **term).status_code == 422
    assert not on_team(db, person)


def test_ending_the_last_appointment_by_hand_takes_them_off_the_team_at_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    since = today - timedelta(days=30)
    person = person_in(db, gym, "coach", starts_on=since)
    [(appointment, *_)] = appointments(db, person)

    ended = client.post(f"/api/staff/{person}/appointments/{appointment}/end", headers=as_gym(gym))

    assert ended.status_code == 204, ended.text
    assert [tuple(a)[1:] for a in appointments(db, person)] == [("Coach", since, today)]
    assert not on_team(db, person)
    again = client.post(f"/api/staff/{person}/appointments/{appointment}/end", headers=as_gym(gym))
    assert again.status_code == 404
    [(_, logged_person, actor, detail)] = log(db, gym, "appointment_ended")
    assert (logged_person, actor) == (person, seeded_owner(gym))
    assert '"ends_on": "' + str(today) in detail


def test_ending_one_of_two_keeps_them_on_the_team(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    roles = add_club(client, gym)
    person = person_in(db, gym, "coach", starts_on=seeded_today() - timedelta(days=5))
    assert appoint(client, gym, person, roles["Delegado"]).status_code == 201
    coach = next(a["id"] for a in appointments(db, person) if a["title_name"] == "Coach")

    assert (
        client.post(
            f"/api/staff/{person}/appointments/{coach}/end", headers=as_gym(gym)
        ).status_code
        == 204
    )

    assert on_team(db, person)
    assert permissions(client, gym, person) == [Permission.ATTENDANCE]


def test_a_same_day_change_of_role_leaves_a_trail(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym)
    assert appoint(client, gym, person, academia(gym, "coach")).status_code == 201
    assert appoint(client, gym, person, academia(gym, "administrador")).status_code == 201
    coach = next(a["id"] for a in appointments(db, person) if a["title_name"] == "Coach")

    assert (
        client.post(
            f"/api/staff/{person}/appointments/{coach}/end", headers=as_gym(gym)
        ).status_code
        == 204
    )

    # Kept, ending on the day it started: it granted nothing, and the history shows it.
    terms = {(a["title_name"], a["starts_on"], a["ends_on"]) for a in appointments(db, person)}
    assert terms == {("Coach", today, today), ("Administrador", today, None)}
    history = client.get("/api/staff/history", headers=as_gym(gym)).json()
    assert {(h["title_name"], h["ends_on"]) for h in history} >= {
        ("Coach", str(today)),
        ("Administrador", None),
    }
    assert permissions(client, gym, person) == sorted(ADMINISTRADOR.permissions)


def test_a_future_appointment_ended_never_runs(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person = person_in(db, gym)
    starts = seeded_today() + timedelta(days=10)
    assert appoint(client, gym, person, academia(gym, "coach"), starts_on=starts).status_code == 201
    [(appointment, *_)] = appointments(db, person)

    assert (
        client.post(
            f"/api/staff/{person}/appointments/{appointment}/end", headers=as_gym(gym)
        ).status_code
        == 204
    )

    assert [tuple(a)[1:] for a in appointments(db, person)] == [("Coach", starts, starts)]
    assert not on_team(db, person)


def test_a_correction_changes_the_dates_never_the_holder_or_role(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym, "coach", starts_on=today - timedelta(days=10))
    [(appointment, *_)] = appointments(db, person)
    url = f"/api/staff/{person}/appointments/{appointment}"
    earlier, until = today - timedelta(days=40), today + timedelta(days=300)

    response = client.patch(
        url, json={"starts_on": str(earlier), "ends_on": str(until)}, headers=as_gym(gym)
    )

    assert response.status_code == 204, response.text
    assert [tuple(a)[1:] for a in appointments(db, person)] == [("Coach", earlier, until)]
    [(_, logged, _, detail)] = log(db, gym, "appointment_corrected")
    assert logged == person
    changed = json.loads(detail)
    assert changed["before"] == {"starts_on": str(today - timedelta(days=10)), "ends_on": None}
    assert changed["after"] == {"starts_on": str(earlier), "ends_on": str(until)}
    # Never who holds it, nor which role, nor a contact shown for them.
    for body in (
        {"person_id": str(uuid.uuid4())},
        {"title_id": academia(gym, "administrador")},
        {"public_contact": "phone"},
    ):
        assert client.patch(url, json=body, headers=as_gym(gym)).status_code == 422
    assert (
        client.patch(
            url, json={"ends_on": str(earlier - timedelta(days=1))}, headers=as_gym(gym)
        ).status_code
        == 422
    )
    assert client.patch(url, json={"starts_on": None}, headers=as_gym(gym)).status_code == 422


def test_a_correction_into_the_past_takes_them_off_the_team(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym, "coach", starts_on=today - timedelta(days=60))
    [(appointment, *_)] = appointments(db, person)
    url = f"/api/staff/{person}/appointments/{appointment}"

    assert (
        client.patch(
            url, json={"ends_on": str(today - timedelta(days=30))}, headers=as_gym(gym)
        ).status_code
        == 204
    )

    assert not on_team(db, person)


def test_a_correction_that_would_overlap_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym)
    coach = academia(gym, "coach")
    assert (
        appoint(client, gym, person, coach, ends_on=today + timedelta(days=10)).status_code == 201
    )
    assert (
        appoint(client, gym, person, coach, starts_on=today + timedelta(days=10)).status_code == 201
    )
    first = appointments(db, person)[0]["id"]

    widened = client.patch(
        f"/api/staff/{person}/appointments/{first}",
        json={"ends_on": str(today + timedelta(days=20))},
        headers=as_gym(gym),
    )
    assert widened.status_code == 409


def test_an_administrador_ends_only_what_they_may(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    administrador = person_in(db, gym, "admin")
    other = person_in(db, gym, "admin")
    [(theirs, *_)] = appointments(db, other)
    coach = person_in(db, gym, "coach")
    [(coachs, *_)] = appointments(db, coach)
    headers = as_gym(gym, administrador)

    assert (
        client.post(f"/api/staff/{other}/appointments/{theirs}/end", headers=headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/staff/{other}/appointments/{theirs}", json={"ends_on": None}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/staff/{coach}/appointments/{coachs}/end", headers=headers).status_code
        == 204
    )
    listed = {m["person_id"]: m for m in client.get("/api/staff", headers=headers).json()}
    assert listed[str(other)]["manageable"] is False
    assert listed[str(seeded_owner(gym))]["manageable"] is False


def test_a_correction_that_opens_a_term_again_puts_them_back_on_the_team(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(
        db, gym, "coach", starts_on=today - timedelta(days=60), ends_on=today - timedelta(days=30)
    )
    # Off the team since, as the nightly job leaves them.
    assert run_team_job(db, today) is True
    assert not on_team(db, person)
    [(appointment, *_)] = appointments(db, person)

    response = client.patch(
        f"/api/staff/{person}/appointments/{appointment}",
        json={"ends_on": None},
        headers=as_gym(gym),
    )

    assert response.status_code == 204, response.text
    assert on_team(db, person)
    assert permissions(client, gym, person) == sorted(COACH.permissions)


# --- one after the other ------------------------------------------------------------


def while_held(
    db: Database,
    hold: Callable[[asyncpg.Connection], Awaitable[object]],
    request: Callable[[], Any],
) -> Any:
    """`request`, run while another transaction holds what `hold` takes: it must wait for
    that transaction, and answers once it commits."""

    async def go() -> Any:
        other = await asyncpg.connect(to_dsn(db.admin_url))
        try:
            await other.execute("BEGIN")
            await hold(other)
            with ThreadPoolExecutor(1) as pool:
                waiting = asyncio.wrap_future(pool.submit(request))
                await asyncio.sleep(0.5)
                assert not waiting.done(), "it did not wait for the other transaction"
                await other.execute("COMMIT")
                return await waiting
        finally:
            await other.close()

    return asyncio.run(go())


def new_title(client: TestClient, gym: uuid.UUID) -> str:
    created = client.post(
        "/api/titles", json={"name": f"Ayudante {uuid.uuid4().hex[:4]}"}, headers=as_gym(gym)
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_an_appointment_waits_for_an_archive_and_finds_the_role_gone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    title, person = new_title(client, gym), person_in(db, gym)

    async def archive(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "UPDATE gym_title SET archived_at = now() WHERE id = $1", uuid.UUID(title)
        )

    response = while_held(db, archive, lambda: appoint(client, gym, person, title))

    assert response.status_code == 404, response.text
    assert appointments(db, person) == []


def test_an_archive_waits_for_an_appointment_and_sees_its_holder(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    title, person = new_title(client, gym), person_in(db, gym)

    async def appointing(conn: asyncpg.Connection) -> None:
        # As `titles_to_give` reads the role, then the appointment it writes.
        await conn.execute("SELECT FROM gym_title WHERE id = $1 FOR SHARE", uuid.UUID(title))
        await conn.execute(
            "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
            " VALUES ($1, $2, $3, 'Ayudante', $4)",
            gym,
            person,
            uuid.UUID(title),
            seeded_today(),
        )

    response = while_held(
        db, appointing, lambda: client.post(f"/api/titles/{title}/archive", headers=as_gym(gym))
    )

    assert response.status_code == 409, response.text
    assert title in {t["id"] for t in titles(client, gym)}


def test_the_job_waits_for_an_appointment_being_made_and_keeps_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym, "coach", starts_on=today - timedelta(days=60), ends_on=today)

    async def appointing(conn: asyncpg.Connection) -> None:
        # As `app.api.staff` does: the person's lock, then their new term.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('rakin.appointment'), hashtext($1))",
            f"{gym}:{person}",
        )
        await conn.execute(
            "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
            " VALUES ($1, $2, $3, 'Coach', $4)",
            gym,
            person,
            uuid.UUID(academia(gym, "coach")),
            today,
        )

    assert while_held(db, appointing, lambda: run_team_job(db, today)) is True

    assert on_team(db, person)
    assert permissions(client, gym, person) == sorted(COACH.permissions)


# --- Invitar ---------------------------------------------------------------------------


def test_an_invite_appoints_to_each_role_for_the_term(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    roles = add_club(client, gym)
    starts, ends = seeded_today() + timedelta(days=3), seeded_today() + timedelta(days=368)
    body = {
        "name": "Marta",
        "email": f"marta.{uuid.uuid4().hex[:6]}@example.cl",
        "title_ids": [roles["Tesorero"], roles["Secretario"]],
        "starts_on": str(starts),
        "ends_on": str(ends),
    }

    response = client.post("/api/staff", json=body, headers=as_gym(gym))

    assert response.status_code == 201, response.text
    marta = uuid.UUID(response.json()["person_id"])
    assert [tuple(a)[1:] for a in appointments(db, marta)] == [
        ("Tesorero", starts, ends),
        ("Secretario", starts, ends),
    ]
    # Not yet: the term starts in three days.
    assert response.json()["permissions"] == []
    assert len(log(db, gym, "appointment_started")) == 2


def test_an_invite_to_an_archived_or_unknown_role_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    archived = academia(gym, "coach")
    assert client.post(f"/api/titles/{archived}/archive", headers=as_gym(gym)).status_code == 204
    for title in (archived, str(uuid.uuid4())):
        body = {
            "name": "Nadie",
            "email": f"n.{uuid.uuid4().hex[:6]}@example.cl",
            "title_ids": [title],
        }
        assert client.post("/api/staff", json=body, headers=as_gym(gym)).status_code == 404


# --- Cargos -----------------------------------------------------------------------------


def test_a_new_role_stores_what_its_permissions_imply(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    body = {"name": "Tesorera", "permissions": ["money_write", "expenses_write"], "public": True}

    response = client.post("/api/titles", json=body, headers=as_gym(gym))

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["permissions"] == [
        "money_read",
        "money_write",
        "expenses_read",
        "expenses_write",
    ]
    assert (created["public"], created["holders"], created["preset"]) == (True, 0, None)
    [(action, person, _, detail)] = log(db, gym, "title_created")
    assert (action, person) == ("title_created", None)
    assert '"name": "Tesorera"' in detail
    assert (
        client.post(
            "/api/titles", json={**body, "name": "TESORERA"}, headers=as_gym(gym)
        ).status_code
        == 409
    )


def test_an_edit_applies_to_its_holders_at_once_and_is_audited(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = person_in(db, gym, "coach")
    title = academia(gym, "coach")

    response = client.patch(
        f"/api/titles/{title}",
        json={"permissions": ["attendance", "money_read"]},
        headers=as_gym(gym),
    )

    assert response.status_code == 200, response.text
    assert response.json()["holders"] == 1
    assert permissions(client, gym, coach) == sorted(["money_read", "attendance"])
    [(_, _, _, detail)] = log(db, gym, "title_changed")
    changed = json.loads(detail)
    assert changed["before"] == {
        "name": "Coach",
        "permissions": ["members_add", "attendance"],
        "public": True,
    }
    assert changed["after"] == {
        "name": "Coach",
        "permissions": ["money_read", "attendance"],
        "public": True,
    }


def test_renaming_or_archiving_a_role_leaves_the_history_as_it_was(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    former = person_in(
        db, gym, "coach", starts_on=today - timedelta(days=90), ends_on=today - timedelta(days=30)
    )
    current = person_in(db, gym, "coach", starts_on=today - timedelta(days=10))
    title = academia(gym, "coach")

    renamed = client.patch(f"/api/titles/{title}", json={"name": "Entrenador"}, headers=as_gym(gym))
    assert renamed.status_code == 200, renamed.text
    # Personas reads the role's name today; the history the name when appointed.
    listed = {m["person_id"]: m for m in client.get("/api/staff", headers=as_gym(gym)).json()}
    assert [a["title_name"] for a in listed[str(current)]["appointments"]] == ["Entrenador"]
    [(appointment, *_)] = appointments(db, current)
    assert (
        client.post(
            f"/api/staff/{current}/appointments/{appointment}/end", headers=as_gym(gym)
        ).status_code
        == 204
    )
    assert client.post(f"/api/titles/{title}/archive", headers=as_gym(gym)).status_code == 204

    history = client.get("/api/staff/history", headers=as_gym(gym)).json()
    assert [(h["person_id"], h["title_name"]) for h in history] == [
        (str(current), "Coach"),
        (str(former), "Coach"),
    ]
    assert title not in {t["id"] for t in titles(client, gym)}


def test_a_role_somebody_holds_is_not_archived(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person_in(db, gym, "coach", starts_on=seeded_today() + timedelta(days=5))
    title = academia(gym, "coach")
    assert client.post(f"/api/titles/{title}/archive", headers=as_gym(gym)).status_code == 409
    assert title in {t["id"] for t in titles(client, gym)}


def test_cargos_follow_the_strictly_fewer_rule(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    administrador = person_in(db, gym, "admin")
    headers = as_gym(gym, administrador)
    # Their own role is not fewer than theirs; one with expenses holds what they lack.
    assert (
        client.patch(
            f"/api/titles/{academia(gym, 'administrador')}", json={"name": "Jefe"}, headers=headers
        ).status_code
        == 403
    )
    expenses = {"name": "Contadora", "permissions": ["expenses_read"]}
    assert client.post("/api/titles", json=expenses, headers=headers).status_code == 403
    # Nor widen one they manage into one they do not.
    widen = {
        "permissions": ["attendance", "gym_setup", "team_manage", "money_write", "members_manage"]
    }
    assert (
        client.patch(
            f"/api/titles/{academia(gym, 'coach')}", json=widen, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/titles", json={"name": "Ayudante", "permissions": ["attendance"]}, headers=headers
        ).status_code
        == 201
    )
    # The Club federado's Tesorero holds expenses: the preset is refused, adding nothing.
    before = {t["name"] for t in titles(client, gym)}
    assert (
        client.post(
            "/api/titles/presets", json={"preset": CLUB_FEDERADO}, headers=headers
        ).status_code
        == 403
    )
    assert {t["name"] for t in titles(client, gym, administrador)} == before
    marked = {t["name"]: t["manageable"] for t in titles(client, gym, administrador)}
    assert marked == {"Administrador": False, "Coach": True, "Ayudante": True}


def test_a_preset_is_added_once_by_name(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    first = client.post("/api/titles/presets", json={"preset": CLUB_FEDERADO}, headers=as_gym(gym))
    assert first.status_code == 201, first.text
    # Coach is Academia's too, and already here.
    assert [t["name"] for t in first.json()] == [
        "Presidente",
        "Tesorero",
        "Secretario",
        "Director",
        "Delegado",
    ]
    again = client.post("/api/titles/presets", json={"preset": CLUB_FEDERADO}, headers=as_gym(gym))
    assert again.json() == []
    names = [t["name"] for t in titles(client, gym)]
    assert names == [
        "Administrador",
        "Coach",
        "Presidente",
        "Tesorero",
        "Secretario",
        "Director",
        "Delegado",
    ]
    assert len(log(db, gym, "title_created")) == 5


# --- first-run setup ----------------------------------------------------------------------


def test_a_new_gym_chooses_once_how_its_team_is_organised(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    assert client.get("/api/titles", headers=as_gym(gym)).json()["setup_pending"] is True

    response = client.post("/api/titles/setup", json={"preset": CLUB_FEDERADO}, headers=as_gym(gym))

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["setup_pending"] is False
    assert [t["name"] for t in answer["titles"]] == [t.name for t in PRESETS[CLUB_FEDERADO]]
    assert (
        client.post("/api/titles/setup", json={"preset": None}, headers=as_gym(gym)).status_code
        == 409
    )


def test_a_new_gym_may_start_with_no_roles(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    response = client.post("/api/titles/setup", json={"preset": None}, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    assert response.json()["titles"] == []
    # And keeps the Academia roles when it picks them.
    other = seed_gym(db, f"equipo-{uuid.uuid4().hex[:6]}")
    kept = client.post("/api/titles/setup", json={"preset": ACADEMIA}, headers=as_gym(other))
    assert [t["name"] for t in kept.json()["titles"]] == ["Administrador", "Coach"]


def test_a_gym_with_its_team_appointed_has_nothing_to_choose(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person_in(db, gym, "coach")
    assert client.get("/api/titles", headers=as_gym(gym)).json()["setup_pending"] is False
    assert (
        client.post("/api/titles/setup", json={"preset": None}, headers=as_gym(gym)).status_code
        == 409
    )


# --- Historial ----------------------------------------------------------------------------


def test_the_history_is_newest_first_and_for_team_managers(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    old = person_in(
        db, gym, "coach", starts_on=today - timedelta(days=400), ends_on=today - timedelta(days=35)
    )
    new = person_in(db, gym, "admin", starts_on=today - timedelta(days=5))
    coach = person_in(db, gym, "coach")

    history = client.get("/api/staff/history", headers=as_gym(gym)).json()

    assert [h["person_id"] for h in history] == [str(coach), str(new), str(old)]
    assert history[-1]["ends_on"] == str(today - timedelta(days=35))
    assert client.get("/api/staff/history", headers=as_gym(gym, new)).status_code == 200
    assert client.get("/api/staff/history", headers=as_gym(gym, coach)).status_code == 403


def test_the_teams_log_is_read_by_team_managers_alone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    roles = add_club(client, gym)
    treasurer, president = person_in(db, gym), person_in(db, gym)
    assert appoint(client, gym, treasurer, roles["Tesorero"]).status_code == 201
    assert appoint(client, gym, president, roles["Presidente"]).status_code == 201

    def seen_by(person: uuid.UUID) -> set[str]:
        rows = run(
            db.api_url,
            in_gym(gym, "SELECT DISTINCT action FROM audit_event", person=person),
        )
        return {r["action"] for r in rows}

    # The Tesorero reads money, not the team; the Presidente manages the team.
    assert seen_by(treasurer) == set()
    assert seen_by(president) == {"title_created", "appointment_started"}


def test_a_staff_members_appointments_are_not_corrections_of_their_billing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owner = seeded_owner(gym)
    person = person_in(db, gym)
    assert appoint(client, gym, person, academia(gym, "coach")).status_code == 201
    response = client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym, owner))
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 0, "items": []}


# --- the nightly job ------------------------------------------------------------------


def run_team_job(db: Database, day: date) -> bool:
    async def job(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await team.tidy(conn, day)

    return bool(run(db.owner_url, job))


def test_a_term_ending_today_is_refused_at_once_and_the_job_then_takes_them_off(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person = person_in(db, gym, "coach", starts_on=today - timedelta(days=200), ends_on=today)

    # From the day's first second, before any job: the dates are read at each request.
    assert on_team(db, person)
    assert permissions(client, gym, person) is None
    assert client.get("/api/sessions", headers=as_gym(gym, person)).status_code == 403

    assert run_team_job(db, today) is True

    # The row goes, and with it what is left of their staff session: since 0042 a
    # session reaches whoever has a record in the gym, as a member, never as staff.
    assert not on_team(db, person)
    assert permissions(client, gym, person) is None
    assert client.get("/api/staff", headers=as_gym(gym, person)).status_code == 403
    # The titular holds the account, not an appointment, and stays.
    assert on_team(db, seeded_owner(gym))


def test_the_job_keeps_whoever_holds_a_role_today_or_later(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    current = person_in(db, gym, "coach", starts_on=today - timedelta(days=10))
    future = person_in(db, gym, "coach", starts_on=today + timedelta(days=10))
    ending = person_in(
        db, gym, "coach", starts_on=today - timedelta(days=10), ends_on=today + timedelta(days=1)
    )

    assert run_team_job(db, today) is True

    assert all(on_team(db, p) for p in (current, future, ending))


# --- the titular can never be locked out ------------------------------------------------


def test_no_edit_leaves_the_titular_without_a_permission(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owner = seeded_owner(gym)
    for title in (academia(gym, "administrador"), academia(gym, "coach")):
        assert (
            client.patch(
                f"/api/titles/{title}", json={"permissions": []}, headers=as_gym(gym)
            ).status_code
            == 200
        )
        assert client.post(f"/api/titles/{title}/archive", headers=as_gym(gym)).status_code == 204
    assert titles(client, gym) == []
    assert permissions(client, gym, owner) == sorted(Permission)
    assert client.get("/api/staff", headers=as_gym(gym)).status_code == 200


def test_no_edit_leaves_the_gym_without_its_titular(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owner = seeded_owner(gym)
    administrador = person_in(db, gym, "admin")
    for by in (None, administrador):
        headers = as_gym(gym, by)
        assert client.delete(f"/api/staff/{owner}", headers=headers).status_code == 403
        appointed = appoint(client, gym, owner, academia(gym, "coach"), by=by)
        assert appointed.status_code == 403
    # Leaving the team, or being forgotten, is refused while they hold the account.
    refusal = run(
        db.api_url, in_gym(gym, "SELECT forget_gym_person($1, 'error')", owner, person=owner)
    )
    assert refusal != [(None,)]
    assert admin(db, "SELECT 1 FROM gym_person WHERE person_id = $1", owner) == [(1,)]
    # And the flag refuses a clear, at commit, with nobody given it instead.
    with pytest.raises(asyncpg.CheckViolationError):
        admin(db, "UPDATE staff SET account_holder = false WHERE person_id = $1", owner)
    assert admin(db, "SELECT account_holder FROM staff WHERE person_id = $1", owner) == [(True,)]
