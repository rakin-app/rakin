"""Attendance (migration 0023): a session's roster, tapping names on and off, trial
guests at the mat, credits spent and given back, and a person's counts.

The roster is everyone a class's program admits, one row per person; a coach marks it
in under five seconds (#44) and may not read the ledger, so the overdue flag is a
boolean from `overdue_memberships()`.
"""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.attendance import AttendanceChange
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
from tests.test_grades import BJJ
from tests.test_guardians import add_person, bill
from tests.test_people import new_phone
from tests.test_plans import CREDITS, TRIAL, add_staff

SANTIAGO = ZoneInfo("America/Santiago")
SOMEONE = str(uuid.uuid4())

# --- input rules, no database -----------------------------------------------------


def test_a_change_marks_and_unmarks_nothing_by_default() -> None:
    body = AttendanceChange.model_validate({})
    assert (body.mark, body.unmark) == ([], [])


@pytest.mark.parametrize(
    "body",
    [
        {"mark": [SOMEONE], "unmark": [SOMEONE]},
        {"mark": ["felipe"]},
        {"mark": [str(uuid.uuid4()) for _ in range(501)]},
        {"present": [SOMEONE]},
    ],
    ids=["both", "not-an-id", "too-many", "unknown-field"],
)
def test_a_change_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AttendanceChange.model_validate(body)


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
    """A gym of its own per test. Its seeded owner has a membership on a plan open to
    every class, so is on every roster."""
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def created(response: Any) -> Any:
    assert response.status_code == 201, response.text
    return response.json()


def program(client: TestClient, gym: uuid.UUID, name: str) -> str:
    made = created(client.post("/api/programs", json={"name": name}, headers=as_gym(gym)))
    return str(made["id"])


def class_type(
    client: TestClient, gym: uuid.UUID, program_id: str, name: str = "Fundamentos", cost: int = 1
) -> str:
    body = {"name": name, "program_id": program_id, "credit_cost": cost}
    return str(created(client.post("/api/class-types", json=body, headers=as_gym(gym)))["id"])


def plan(client: TestClient, gym: uuid.UUID, body: dict[str, Any]) -> str:
    return str(created(client.post("/api/plans", json=body, headers=as_gym(gym)))["id"])


def join(client: TestClient, gym: uuid.UUID, person: str, plan_id: str) -> str:
    body = {"person_id": person, "plan_id": plan_id}
    return str(created(client.post("/api/memberships", json=body, headers=as_gym(gym)))["id"])


def at(day: date, hour: int = 19) -> str:
    """`day` at `hour` in Santiago, as an ISO instant."""
    return datetime.combine(day, time(hour), tzinfo=SANTIAGO).isoformat()


def session_of(
    client: TestClient, gym: uuid.UUID, class_type_id: str, day: date | None = None
) -> str:
    body: dict[str, Any] = {"class_type_id": class_type_id}
    if day is not None:
        body["starts_at"] = at(day)
    return str(created(client.post("/api/sessions", json=body, headers=as_gym(gym)))["id"])


def roster(client: TestClient, gym: uuid.UUID, session: str, by: uuid.UUID | None = None) -> Any:
    response = client.get(f"/api/sessions/{session}/roster", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def change(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    by: uuid.UUID | None = None,
    **body: list[str],
) -> Any:
    return client.patch(f"/api/sessions/{session}/attendance", json=body, headers=as_gym(gym, by))


def changed(client: TestClient, gym: uuid.UUID, session: str, **body: list[str]) -> Any:
    response = change(client, gym, session, None, **body)
    assert response.status_code == 200, response.text
    return response.json()


def row(listed: Any, name: str) -> Any:
    return next(m for m in listed["members"] if m["name"] == name)


def names(listed: Any) -> list[str]:
    return [m["name"] for m in listed["members"]]


def credits_left(db: Database, gym: uuid.UUID, membership: str) -> Any:
    rows = run(
        db.api_url,
        in_gym(
            gym, "SELECT credits_remaining FROM membership WHERE id = $1", uuid.UUID(membership)
        ),
    )
    return rows[0]["credits_remaining"]


@pg
def test_the_roster_is_who_the_program_admits_by_name(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults, kids = program(client, gym, "Adultos"), program(client, gym, "Kids")
    adult_plan = plan(client, gym, {**CREDITS, "program_id": adults})
    kids_plan = plan(client, gym, {**CREDITS, "name": "Pack kids", "program_id": kids})
    join(client, gym, add_person(client, gym, "Paula Contreras"), adult_plan)
    join(client, gym, add_person(client, gym, "Antonia Rojas"), adult_plan)
    join(client, gym, add_person(client, gym, "Mateo Ortiz"), kids_plan)
    add_person(client, gym, "Sin Plan")
    session = session_of(client, gym, class_type(client, gym, adults))

    listed = roster(client, gym, session)
    owner = f"owner of {_slug(client, gym)}"
    # The seeded owner's plan is open to any class; the kids' pack is not for adults.
    assert names(listed) == ["Antonia Rojas", owner, "Paula Contreras"]
    assert listed["present"] == 0
    paula = row(listed, "Paula Contreras")
    assert paula["plan_name"] == "Pack 12 clases"
    assert (paula["plan_kind"], paula["status"], paula["credits_remaining"]) == (
        "credits",
        "active",
        12,
    )
    assert (paula["present"], paula["days_absent"], paula["rank"]) == (False, None, None)


def _slug(client: TestClient, gym: uuid.UUID) -> str:
    response = client.get("/api/gym/settings", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return str(response.json()["slug"])


@pg
def test_tapping_marks_counts_and_unmarks(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    adults = program(client, gym, "Adultos")
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    session = session_of(client, gym, class_type(client, gym, adults))

    marked = changed(client, gym, session, mark=[paula])
    assert (marked["present"], row(marked, "Paula Contreras")["present"]) == (1, True)
    # Sent again, as a phone resending its queue would: still once.
    assert changed(client, gym, session, mark=[paula])["present"] == 1
    count = run(
        db.api_url,
        in_gym(
            gym, "SELECT count(*) AS n FROM attendance WHERE session_id = $1", uuid.UUID(session)
        ),
    )
    assert count[0]["n"] == 1

    unmarked = changed(client, gym, session, unmark=[paula])
    assert (unmarked["present"], row(unmarked, "Paula Contreras")["present"]) == (0, False)
    assert changed(client, gym, session, unmark=[paula])["present"] == 0


@pg
def test_marking_records_who_and_when(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    coach = add_staff(db, gym, "coach")
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    assert change(client, gym, session, coach, mark=[paula]).status_code == 200
    rows = run(
        db.api_url,
        in_gym(gym, "SELECT marked_by, marked_at, credits_consumed FROM attendance"),
    )
    assert [(r["marked_by"], r["credits_consumed"]) for r in rows] == [(coach, 1)]
    assert rows[0]["marked_at"] is not None


@pg
def test_a_pack_pays_the_class_cost_and_unmarking_gives_it_back(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    competition = session_of(client, gym, class_type(client, gym, adults, "Competición", cost=2))
    open_mat = session_of(client, gym, class_type(client, gym, adults, "Open mat", cost=0))

    changed(client, gym, competition, mark=[paula])
    assert credits_left(db, gym, paula) == 10
    assert row(roster(client, gym, competition), "Paula Contreras")["credits_remaining"] == 10
    changed(client, gym, open_mat, mark=[paula])
    assert credits_left(db, gym, paula) == 10

    changed(client, gym, competition, unmark=[paula])
    assert credits_left(db, gym, paula) == 12


@pg
def test_a_spent_pack_still_trains_and_is_lapsed_by_the_nightly_job_not_here(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    pack = plan(client, gym, {**CREDITS, "credits": 1})
    paula = join(client, gym, add_person(client, gym, "Paula Contreras"), pack)
    first = session_of(client, gym, class_type(client, gym, adults, cost=2))
    second = session_of(client, gym, class_type(client, gym, adults, "Sparring"))

    changed(client, gym, first, mark=[paula])
    changed(client, gym, second, mark=[paula])
    assert credits_left(db, gym, paula) == 0
    consumed = run(
        db.api_url, in_gym(gym, "SELECT credits_consumed FROM attendance ORDER BY marked_at")
    )
    assert [r["credits_consumed"] for r in consumed] == [1, 0]
    assert row(roster(client, gym, second), "Paula Contreras")["status"] == "active"


@pg
def test_monthly_members_spend_nothing(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    owner_membership = run(db.api_url, in_gym(gym, "SELECT id, credits_remaining FROM membership"))[
        0
    ]
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    changed(client, gym, session, mark=[str(owner_membership["id"])])
    consumed = run(db.api_url, in_gym(gym, "SELECT credits_consumed FROM attendance"))
    assert [r["credits_consumed"] for r in consumed] == [0]


@pg
def test_overdue_members_are_flagged_and_still_marked_even_for_a_coach(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    felipe = add_person(client, gym, "Felipe Díaz")
    felipe_membership = bill(db, gym, felipe, [(-3, 45_000, 0, 0)])
    antonia = add_person(client, gym, "Antonia Rojas")
    bill(db, gym, antonia, [(-3, 45_000, 45_000, 0)])
    tomas = add_person(client, gym, "Tomás Pérez")
    bill(db, gym, tomas, [(0, 30_000, 0, 0)])  # due today: not yet overdue
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    for by in (None, coach):
        listed = roster(client, gym, session, by)
        flags = {m["name"]: m["overdue"] for m in listed["members"]}
        assert (flags["Felipe Díaz"], flags["Antonia Rojas"], flags["Tomás Pérez"]) == (
            True,
            False,
            False,
        )
    marked = change(client, gym, session, coach, mark=[felipe_membership])
    assert marked.status_code == 200, marked.text
    assert row(marked.json(), "Felipe Díaz")["present"] is True


@pg
def test_the_overdue_lookup_is_the_current_gyms_only(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    bill(db, other, add_person(client, other, "Felipe Díaz"), [(-3, 45_000, 0, 0)])
    ours = run(db.api_url, in_gym(gym, "SELECT * FROM overdue_memberships()"))
    theirs = run(db.api_url, in_gym(other, "SELECT * FROM overdue_memberships()"))
    nobody = run(db.api_url, in_gym(None, "SELECT * FROM overdue_memberships()"))
    # Felipe owes, in the other gym; the seeded owners' charges were never validated.
    assert (ours, len(theirs), nobody) == ([], 1, [])


@pg
def test_lapsed_members_are_listed_and_cancelled_ones_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    pack = plan(client, gym, CREDITS)
    lapsed = join(client, gym, add_person(client, gym, "Ignacio Vera"), pack)
    cancelled = join(client, gym, add_person(client, gym, "Diego Morales"), pack)
    run(
        db.owner_url,
        in_gym(gym, "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(lapsed)),
    )
    response = client.post(
        f"/api/memberships/{cancelled}/cancel", json={"reason": "se mudó"}, headers=as_gym(gym)
    )
    assert response.status_code == 200, response.text
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    listed = roster(client, gym, session)
    assert "Diego Morales" not in names(listed)
    assert row(listed, "Ignacio Vera")["status"] == "lapsed"
    # A lapsed pack trains for nothing.
    changed(client, gym, session, mark=[lapsed])
    assert credits_left(db, gym, lapsed) == 12

    refused = change(client, gym, session, mark=[cancelled])
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["type"] == "cancelled_membership"


@pg
def test_a_frozen_member_is_listed_marked_for_nothing_and_stays_frozen(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    body = {"to_date": (seeded_today() + timedelta(days=14)).isoformat(), "reason": "lesión"}
    response = client.post(f"/api/memberships/{paula}/freeze", json=body, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    assert row(roster(client, gym, session), "Paula Contreras")["status"] == "frozen"
    marked = changed(client, gym, session, mark=[paula])
    assert row(marked, "Paula Contreras")["present"] is True
    assert row(marked, "Paula Contreras")["status"] == "frozen"
    assert credits_left(db, gym, paula) == 12


@pg
def test_a_plan_for_another_program_is_not_marked_or_started_here(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults, kids = program(client, gym, "Adultos"), program(client, gym, "Kids")
    kids_pack = plan(client, gym, {**CREDITS, "name": "Pack kids", "program_id": kids})
    mateo = join(client, gym, add_person(client, gym, "Mateo Ortiz"), kids_pack)
    kids_trial = plan(client, gym, {**TRIAL, "name": "Prueba kids", "program_id": kids})
    session = session_of(client, gym, class_type(client, gym, adults))

    refused = change(client, gym, session, mark=[mateo])
    assert (refused.status_code, refused.json()["detail"][0]["type"]) == (422, "not_in_program")
    assert credits_left(db, gym, mateo) == 12
    response = guest(client, gym, session, add_person(client, gym, "Camila Ortiz"), kids_trial)
    assert (response.status_code, response.json()["detail"][0]["type"]) == (422, "not_in_program")
    assert roster(client, gym, session)["present"] == 0


@pg
def test_unknown_marks_and_sessions(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    refused = change(client, gym, session, mark=[SOMEONE])
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["type"] == "unknown_membership"
    assert change(client, gym, session, unmark=[SOMEONE]).status_code == 200

    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    theirs = run(db.api_url, in_gym(other, "SELECT id FROM membership"))[0]["id"]
    assert change(client, gym, session, mark=[str(theirs)]).status_code == 422
    assert client.get(f"/api/sessions/{session}/roster", headers=as_gym(other)).status_code == 404
    assert change(client, other, session, mark=[str(theirs)]).status_code == 404


@pg
def test_a_failed_mark_writes_nothing(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    assert change(client, gym, session, mark=[paula, SOMEONE]).status_code == 422
    assert roster(client, gym, session)["present"] == 0
    assert credits_left(db, gym, paula) == 12


@pg
def test_a_session_and_membership_are_marked_once_at_the_database(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    membership = run(db.api_url, in_gym(gym, "SELECT id FROM membership"))[0]["id"]
    insert = "INSERT INTO attendance (gym_id, session_id, membership_id) VALUES ($1, $2, $3)"
    run(db.api_url, in_gym(gym, insert, gym, uuid.UUID(session), membership))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(db.api_url, in_gym(gym, insert, gym, uuid.UUID(session), membership))


@pg
def test_another_gyms_attendance_is_invisible(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    membership = run(db.api_url, in_gym(gym, "SELECT id FROM membership"))[0]["id"]
    changed(client, gym, session, mark=[str(membership)])
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    assert len(run(db.api_url, in_gym(gym, "SELECT FROM attendance"))) == 1
    assert run(db.api_url, in_gym(other, "SELECT FROM attendance")) == []
    assert run(db.api_url, in_gym(None, "SELECT FROM attendance")) == []


@pg
def test_attendance_is_never_changed_in_place(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    membership = run(db.api_url, in_gym(gym, "SELECT id FROM membership"))[0]["id"]
    changed(client, gym, session, mark=[str(membership)])
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, "UPDATE attendance SET credits_consumed = 5"))


@pg
def test_a_coach_marks_and_a_member_may_not(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    paula = add_person(client, gym, "Paula Contreras")
    membership = join(client, gym, paula, plan(client, gym, CREDITS))
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    assert roster(client, gym, session, coach)["present"] == 0
    assert change(client, gym, session, coach, mark=[membership]).status_code == 200
    member = uuid.UUID(paula)
    assert (
        client.get(f"/api/sessions/{session}/roster", headers=as_gym(gym, member)).status_code
        == 403
    )
    assert change(client, gym, session, member, unmark=[membership]).status_code == 403


@pg
def test_days_absent_count_from_the_last_class_before_this_one(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    ignacio = join(client, gym, add_person(client, gym, "Ignacio Vera"), plan(client, gym, CREDITS))
    today = seeded_today()
    long_ago = session_of(client, gym, fundamentals, today - timedelta(days=16))
    changed(client, gym, long_ago, mark=[ignacio])
    now = session_of(client, gym, fundamentals, today)

    assert row(roster(client, gym, now), "Ignacio Vera")["days_absent"] == 16
    changed(client, gym, now, mark=[ignacio])
    assert row(roster(client, gym, now), "Ignacio Vera")["days_absent"] == 16
    assert row(roster(client, gym, long_ago), "Ignacio Vera")["days_absent"] is None


@pg
def test_the_roster_shows_the_rank(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    response = client.put("/api/gym/grading-scheme", json=BJJ, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    felipe = add_person(client, gym, "Felipe Díaz")
    join(client, gym, felipe, plan(client, gym, CREDITS))
    award = {"rank_key": "blue", "sub_rank": "2"}
    response = client.post(f"/api/people/{felipe}/grades", json=award, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    rank = row(roster(client, gym, session), "Felipe Díaz")["rank"]
    assert (rank["rank_label"], rank["sub_rank_label"]) == ("Azul", "2 grados")


@pg
def test_one_row_per_person_and_the_marked_membership_wins(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    felipe = add_person(client, gym, "Felipe Díaz")
    pack = join(client, gym, felipe, plan(client, gym, CREDITS))
    monthly = bill(db, gym, felipe, [])
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    assert names(roster(client, gym, session)).count("Felipe Díaz") == 1
    for membership in (pack, monthly):
        marked = changed(client, gym, session, mark=[membership])
        assert row(marked, "Felipe Díaz")["membership_id"] == membership
        changed(client, gym, session, unmark=[membership])


# --- trial guests -------------------------------------------------------------------


def guest(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    person: str,
    plan_id: str,
    by: uuid.UUID | None = None,
) -> Any:
    return client.post(
        f"/api/sessions/{session}/trials",
        json={"person_id": person, "plan_id": plan_id},
        headers=as_gym(gym, by),
    )


@pg
def test_a_coach_adds_a_trial_guest_present_at_the_class(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    trial = plan(client, gym, TRIAL)
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    body = {"phone": new_phone(), "rut": random_rut(), "name": "Camila Ortiz"}
    person = created(client.post("/api/people", json=body, headers=as_gym(gym, coach)))["id"]

    listed = created(guest(client, gym, session, person, trial, coach))
    camila = row(listed, "Camila Ortiz")
    assert (camila["present"], camila["status"], camila["plan_kind"]) == (True, "trial", "trial")
    # One of the two free classes, taken.
    assert camila["credits_remaining"] == 1
    started = run(
        db.api_url,
        in_gym(
            gym,
            "SELECT current_period_end FROM membership WHERE id = $1",
            uuid.UUID(camila["membership_id"]),
        ),
    )
    assert started[0]["current_period_end"] == seeded_today() + timedelta(days=13)


@pg
def test_a_guest_who_is_already_a_member_is_a_409_naming_the_membership(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    trial = plan(client, gym, TRIAL)
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    owner = seeded_owner(gym)
    membership = run(db.api_url, in_gym(gym, "SELECT id FROM membership"))[0]["id"]

    response = guest(client, gym, session, str(owner), trial)
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "already_member", "membership_id": str(membership)}
    assert roster(client, gym, session)["present"] == 0


@pg
def test_a_guest_needs_an_active_trial_plan_and_a_person_here(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    person = add_person(client, gym, "Camila Ortiz")
    pack = plan(client, gym, CREDITS)
    trial = plan(client, gym, TRIAL)

    response = guest(client, gym, session, person, pack)
    assert (response.status_code, response.json()["detail"][0]["type"]) == (422, "not_a_trial_plan")
    response = guest(client, gym, session, SOMEONE, trial)
    assert (response.status_code, response.json()["detail"][0]["type"]) == (422, "unknown_person")
    response = client.patch(f"/api/plans/{trial}", json={"active": False}, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    response = guest(client, gym, session, person, trial)
    assert (response.status_code, response.json()["detail"][0]["type"]) == (422, "inactive_plan")


# --- a person's counts ------------------------------------------------------------


def counts(client: TestClient, gym: uuid.UUID, person: str, by: uuid.UUID | None = None) -> Any:
    response = client.get(f"/api/people/{person}/attendance", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


@pg
def test_a_persons_classes_in_30_days_in_all_and_since_their_rank(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    response = client.put("/api/gym/grading-scheme", json=BJJ, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"), cost=0)
    felipe = add_person(client, gym, "Felipe Díaz")
    pack = join(client, gym, felipe, plan(client, gym, CREDITS))
    monthly = bill(db, gym, felipe, [])
    today = seeded_today()
    assert counts(client, gym, felipe) == {"last_30_days": 0, "total": 0, "since_promotion": None}

    for days_ago, membership in ((40, pack), (30, pack), (29, monthly), (10, pack), (0, monthly)):
        changed(
            client,
            gym,
            session_of(client, gym, fundamentals, today - timedelta(days=days_ago)),
            mark=[membership],
        )
    assert counts(client, gym, felipe)["since_promotion"] is None

    award = {
        "rank_key": "blue",
        "sub_rank": "0",
        "awarded_on": (today - timedelta(days=10)).isoformat(),
    }
    response = client.post(f"/api/people/{felipe}/grades", json=award, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    # The class on the day of the promotion is the old rank's.
    coach = add_staff(db, gym, "coach")
    assert counts(client, gym, felipe, coach) == {
        "last_30_days": 3,
        "total": 5,
        "since_promotion": 1,
    }
    assert client.get(f"/api/people/{SOMEONE}/attendance", headers=as_gym(gym)).status_code == 404


@pg
def test_the_student_page_counts_this_month_and_all(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"), cost=0)
    paula = add_person(client, gym, "Paula Contreras")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    today = seeded_today()
    for day in (today - timedelta(days=40), today):
        changed(client, gym, session_of(client, gym, fundamentals, day), mark=[pack])

    response = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(paula)))
    assert response.status_code == 200, response.text
    assert response.json()["attendance"] == {"this_month": 1, "total": 2}


# --- v_inactive -------------------------------------------------------------------


@pg
def test_v_inactive_is_each_live_members_last_class(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"), cost=0)
    pack = plan(client, gym, CREDITS)
    ignacio = add_person(client, gym, "Ignacio Vera")
    changed(
        client,
        gym,
        session_of(client, gym, fundamentals, seeded_today() - timedelta(days=16)),
        mark=[join(client, gym, ignacio, pack)],
    )
    never = add_person(client, gym, "Diego Morales")
    join(client, gym, never, pack)
    add_person(client, gym, "Sin Plan")

    rows = run(db.api_url, in_gym(gym, "SELECT person_id, days_absent FROM v_inactive"))
    absent = {str(r["person_id"]): r["days_absent"] for r in rows}
    assert absent == {str(seeded_owner(gym)): None, ignacio: 16, never: None}
