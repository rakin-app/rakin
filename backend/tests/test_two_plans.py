"""Un curso además del plan (#354): a member on a monthly plan who also takes a course.

A climbing gym's member on a monthly plan open to every class signs up for an 8-session
course, a credits pack in its own program. At a course class the roster marks the
course and spends it; at any other class, and at the course's once it is spent, the
monthly plan. Each plan is billed, paid and lapsed on its own, and the student page
says which plan each payment paid.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, seed_gym, seeded_today, throwaway_database
from tests.test_attendance import changed, class_type, credits_left, program, roster, row
from tests.test_attendance import session_of as class_session
from tests.test_lapsed_reassign import ledger, ok, run_lapse, start, status
from tests.test_member_roll import enrolled, plan
from tests.test_plans import CREDITS
from tests.test_reactivate import pay

pytestmark = pytest.mark.postgres

NAME = "Rosa Vidal"


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
    return seed_gym(db, f"muro-{uuid.uuid4().hex[:8]}")


def on_both(client: TestClient, gym: uuid.UUID, credits: int = 8) -> tuple[str, str, str, str, str]:
    """Rosa on a monthly plan open to every class, then on a course of `credits` in the
    "Curso" program, both from today. Her person, the monthly membership, the course's,
    and the programs of an ordinary class and of the course."""
    adults, course_program = program(client, gym, "Adultos"), program(client, gym, "Curso")
    monthly_plan = plan(client, gym, "signup")
    person = enrolled(
        client,
        gym,
        name=NAME,
        membership={"plan_id": monthly_plan, "started_on": seeded_today().isoformat()},
    )["id"]
    course_plan = ok(
        client.post(
            "/api/plans",
            json={
                **CREDITS,
                "name": "Curso de iniciación",
                "credits": credits,
                "program_id": course_program,
            },
            headers=as_gym(gym),
        ),
        201,
    )["id"]
    [monthly] = [
        m["id"] for m in ok(client.get(f"/api/memberships?person_id={person}", headers=as_gym(gym)))
    ]
    course = ok(start(client, gym, person, course_plan, seeded_today()), 201)["id"]
    return person, monthly, course, adults, course_program


def test_a_course_class_marks_and_spends_the_course(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, monthly, course, adults, course_program = on_both(client, gym)
    lesson = class_session(client, gym, class_type(client, gym, course_program, "Curso"))
    ordinary = class_session(client, gym, class_type(client, gym, adults))

    # One row for her at each class: the course at its own, the monthly plan elsewhere.
    listed = roster(client, gym, lesson)
    assert [m["name"] for m in listed["members"]].count(NAME) == 1
    assert row(listed, NAME)["membership_id"] == course
    assert row(roster(client, gym, ordinary), NAME)["membership_id"] == monthly

    changed(client, gym, lesson, mark=[course])
    changed(client, gym, ordinary, mark=[monthly])
    assert credits_left(db, gym, course) == 7
    assert credits_left(db, gym, monthly) is None


def test_a_spent_course_leaves_its_classes_to_the_monthly_plan(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, monthly, course, _, course_program = on_both(client, gym, credits=1)
    course_type = class_type(client, gym, course_program, "Curso")
    first = class_session(client, gym, course_type)
    changed(client, gym, first, mark=[course])
    assert credits_left(db, gym, course) == 0

    # Both admit the class, neither has credits left: the one started first.
    second = class_session(client, gym, course_type)
    assert row(roster(client, gym, second), NAME)["membership_id"] == monthly
    changed(client, gym, second, mark=[monthly])
    assert credits_left(db, gym, course) == 0


def test_each_plan_bills_and_lapses_on_its_own(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, monthly, course, _, _ = on_both(client, gym)

    # Each is billed on its own ledger as it starts.
    [month] = ledger(client, gym, monthly)["open_periods"]
    [pack] = ledger(client, gym, course)["open_periods"]
    assert month["id"] != pack["id"]

    # The course is paid; the month is not, and lapses once its grace is past.
    pay(client, gym, course, pack["id"], pack["outstanding_clp"])
    assert ledger(client, gym, course)["open_periods"] == []
    assert ledger(client, gym, monthly)["owed_clp"] == month["outstanding_clp"]
    run_lapse(db, seeded_today() + timedelta(days=6))
    assert (status(client, gym, monthly), status(client, gym, course)) == ("lapsed", "active")


def test_a_spent_course_lapses_and_the_monthly_plan_runs_on(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, monthly, course, _, course_program = on_both(client, gym, credits=1)
    [month] = ledger(client, gym, monthly)["open_periods"]
    pay(client, gym, monthly, month["id"], month["outstanding_clp"])
    lesson = class_session(client, gym, class_type(client, gym, course_program, "Curso"))
    changed(client, gym, lesson, mark=[course])

    run_lapse(db, seeded_today() + timedelta(days=1))
    assert (status(client, gym, monthly), status(client, gym, course)) == ("active", "lapsed")


def page(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    return ok(client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person))))


def test_the_student_page_names_the_plan_each_payment_paid(
    client: TestClient, gym: uuid.UUID
) -> None:
    person, monthly, course, _, _ = on_both(client, gym)
    for membership in (monthly, course):
        [period] = ledger(client, gym, membership)["open_periods"]
        pay(client, gym, membership, period["id"], period["outstanding_clp"])

    paid = page(client, gym, person)["payments"]
    assert sorted(p["plan_name"] for p in paid) == ["Curso de iniciación", "Mensual"]
    assert sorted(p["plan_name"] for p in page(client, gym, person)["plans"]) == [
        "Curso de iniciación",
        "Mensual",
    ]
