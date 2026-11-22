"""Material de estudio (#537, migration 0088): notes and links on a class, for an audience.

A coach shares material on a class or a recurring class; it reaches who attended, the
class's program, or the members of some plans, and nobody else: the database decides,
so a member outside the audience reads none of it at the API or in SQL.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.study_material import MaterialChange, MaterialIn
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import changed, class_type, created, join, plan, program
from tests.test_guardians import add_person, new_kid
from tests.test_plans import MONTHLY, add_staff
from tests.test_schedule import backfilled_slot, change_slot, sessions_of, today

LINK = "https://www.youtube.com/watch?v=abc123"

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        "http://example.com/video",
        "javascript:alert(1)",
        "ftp://example.com/notes.pdf",
        "https://",
        "https://exa mple.com",
        "example.com",
    ],
)
def test_only_https_links_are_accepted(link: str) -> None:
    with pytest.raises(ValidationError):
        MaterialIn.model_validate({"title": "Guardia", "links": [link], "audience": "program"})


def test_a_link_with_a_host_and_path_is_accepted() -> None:
    body = MaterialIn.model_validate(
        {"title": " Guardia ", "links": [LINK, "https://drive.google.com/x"], "audience": "program"}
    )
    assert (body.title, body.links) == ("Guardia", [LINK, "https://drive.google.com/x"])


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x", "audience": "plans"},
        {"title": "x", "audience": "program", "plan_ids": [str(uuid.uuid4())]},
        {"title": "", "audience": "program"},
        {"title": "x", "audience": "everyone"},
        {"title": "x", "audience": "program", "links": [LINK] * 11},
    ],
    ids=["plans-without-plans", "plans-elsewhere", "no-title", "unknown-audience", "too-many"],
)
def test_a_material_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MaterialIn.model_validate(body)


def test_an_edit_cannot_clear_the_title() -> None:
    with pytest.raises(ValidationError):
        MaterialChange.model_validate({"title": None})
    assert MaterialChange.model_validate({"body": None}).model_fields_set == {"body"}


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


class Gym:
    """A gym with two programs, a plan of each, a member on each, and a coach."""

    def __init__(self, client: TestClient, db: Database) -> None:
        self.id = seed_gym(db, unique_slug("gym"))
        self.adults = program(client, self.id, "Adultos")
        self.kids = program(client, self.id, "Niños")
        self.fundamentals = class_type(client, self.id, self.adults)
        self.adults_plan = plan(client, self.id, {**MONTHLY, "program_id": self.adults})
        self.kids_plan = plan(
            client, self.id, {**MONTHLY, "name": "Mensual niños", "program_id": self.kids}
        )
        self.ana = add_person(client, self.id, "Ana Prueba")
        self.ana_membership = join(client, self.id, self.ana, self.adults_plan)
        self.beto = add_person(client, self.id, "Beto Prueba")
        join(client, self.id, self.beto, self.kids_plan)
        self.coach = add_staff(db, self.id, "coach")


@pytest.fixture
def gym(client: TestClient, db: Database) -> Gym:
    return Gym(client, db)


def one_off(client: TestClient, g: Gym, coach: uuid.UUID | None = None) -> str:
    body: dict[str, Any] = {"class_type_id": g.fundamentals}
    if coach is not None:
        body["coach_id"] = str(coach)
    return str(created(client.post("/api/sessions", json=body, headers=as_gym(g.id)))["id"])


def share(
    client: TestClient, g: Gym, session: str, by: uuid.UUID | None = None, **body: Any
) -> Any:
    body = {"title": "Pasaje de guardia", "links": [LINK], "audience": "program", **body}
    return client.post(f"/api/sessions/{session}/material", json=body, headers=as_gym(g.id, by))


def shared(client: TestClient, g: Gym, session: str, **body: Any) -> Any:
    return created(share(client, g, session, **body))


def mine(client: TestClient, g: Gym, person: str | uuid.UUID) -> list[str]:
    response = client.get("/api/me/material", headers=as_gym(g.id, uuid.UUID(str(person))))
    assert response.status_code == 200, response.text
    return [m["title"] for m in response.json()]


def in_sql(db: Database, g: Gym, person: str | uuid.UUID, gym_id: uuid.UUID | None = None) -> Any:
    """What the API's database user reads of the tables as `person`, RLS alone."""
    rows = run(
        db.api_url,
        in_gym(gym_id or g.id, "SELECT title FROM study_material", person=uuid.UUID(str(person))),
    )
    return [r["title"] for r in rows]


def on_session(client: TestClient, g: Gym, session: str, by: uuid.UUID | None = None) -> Any:
    response = client.get(f"/api/sessions/{session}/material", headers=as_gym(g.id, by))
    assert response.status_code == 200, response.text
    return [m["title"] for m in response.json()]


# --- audiences --------------------------------------------------------------------


@pg
def test_the_program_sees_it_and_another_program_does_not(
    client: TestClient, db: Database, gym: Gym
) -> None:
    session = one_off(client, gym, gym.coach)
    made = shared(client, gym, session, body="Repasen\nlos tres pasos.")

    assert made["audience"] == "program"
    assert made["body"] == "Repasen\nlos tres pasos."
    listed = client.get("/api/me/material", headers=as_gym(gym.id, uuid.UUID(gym.ana))).json()
    assert [
        (m["title"], m["class_type_name"], m["program_name"], m["links"], m["recurring"])
        for m in listed
    ] == [("Pasaje de guardia", "Fundamentos", "Adultos", [LINK], False)]
    assert listed[0]["day"] == today().isoformat()
    assert mine(client, gym, gym.beto) == []
    # The database decides, not only the API.
    assert in_sql(db, gym, gym.ana) == ["Pasaje de guardia"]
    assert in_sql(db, gym, gym.beto) == []


@pg
def test_who_attended_sees_it_and_who_did_not_does_not(
    client: TestClient, db: Database, gym: Gym
) -> None:
    carla = add_person(client, gym.id, "Carla Prueba")
    join(client, gym.id, carla, gym.adults_plan)
    session = one_off(client, gym)
    changed(client, gym.id, session, mark=[gym.ana_membership])
    shared(client, gym, session, audience="attendees")

    assert mine(client, gym, gym.ana) == ["Pasaje de guardia"]
    assert mine(client, gym, carla) == []
    assert in_sql(db, gym, carla) == []


@pg
def test_members_of_the_plans_see_it_and_no_one_else(
    client: TestClient, db: Database, gym: Gym
) -> None:
    session = one_off(client, gym)
    made = shared(client, gym, session, audience="plans", plan_ids=[gym.kids_plan])

    assert [p["name"] for p in made["plans"]] == ["Mensual niños"]
    assert mine(client, gym, gym.beto) == ["Pasaje de guardia"]
    assert mine(client, gym, gym.ana) == []
    assert in_sql(db, gym, gym.ana) == []


@pg
def test_a_guardian_sees_what_reaches_their_dependent(client: TestClient, gym: Gym) -> None:
    guardian = add_person(client, gym.id, "Dora Prueba")
    kid = new_kid(client, gym.id, guardian, "Eli Prueba")
    join(client, gym.id, kid, gym.kids_plan)
    session = one_off(client, gym)
    shared(client, gym, session, audience="plans", plan_ids=[gym.kids_plan])

    assert mine(client, gym, guardian) == ["Pasaje de guardia"]


@pg
def test_another_gym_s_member_sees_nothing(client: TestClient, db: Database, gym: Gym) -> None:
    shared(client, gym, one_off(client, gym))
    other = Gym(client, db)

    assert mine(client, other, other.ana) == []
    assert in_sql(db, gym, other.ana, gym_id=other.id) == []
    # Even naming the first gym, a person of the other reaches nothing in it.
    assert in_sql(db, gym, other.ana) == []


@pg
def test_staff_see_every_material_on_the_class(client: TestClient, db: Database, gym: Gym) -> None:
    session = one_off(client, gym)
    shared(client, gym, session, audience="plans", plan_ids=[gym.kids_plan])

    assert on_session(client, gym, session, by=gym.coach) == ["Pasaje de guardia"]
    assert in_sql(db, gym, gym.coach) == ["Pasaje de guardia"]
    # A member is not staff.
    response = client.get(
        f"/api/sessions/{session}/material", headers=as_gym(gym.id, uuid.UUID(gym.ana))
    )
    assert response.status_code == 403


@pg
def test_a_plan_of_another_gym_is_refused(client: TestClient, db: Database, gym: Gym) -> None:
    other = Gym(client, db)
    response = share(
        client, gym, one_off(client, gym), audience="plans", plan_ids=[other.kids_plan]
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["type"] == "unknown_plan"


@pg
def test_an_http_link_is_refused_by_the_api(client: TestClient, gym: Gym) -> None:
    response = share(client, gym, one_off(client, gym), links=["http://example.com"])
    assert response.status_code == 422


# --- who may share ----------------------------------------------------------------


@pg
def test_the_class_s_coach_shares_and_another_coach_does_not(
    client: TestClient, db: Database, gym: Gym
) -> None:
    mine_ = one_off(client, gym, gym.coach)
    theirs = one_off(client, gym)

    assert share(client, gym, mine_, by=gym.coach).status_code == 201
    assert share(client, gym, theirs, by=gym.coach).status_code == 403
    assert share(client, gym, theirs, by=uuid.UUID(gym.ana)).status_code == 403
    # Whoever manages the classes shares on any.
    assert share(client, gym, theirs).status_code == 201


# --- edit and remove --------------------------------------------------------------


def audit(db: Database, g: Gym) -> list[Any]:
    return list(
        run(
            db.owner_url,
            in_gym(
                g.id,
                "SELECT action, actor_id, detail FROM audit_event"
                " WHERE action LIKE 'study_material_%' ORDER BY at, id",
            ),
        )
    )


@pg
def test_an_edit_and_a_removal_keep_an_audit_row_and_removal_hides_it(
    client: TestClient, db: Database, gym: Gym
) -> None:
    session = one_off(client, gym, gym.coach)
    made = shared(client, gym, session, by=gym.coach)
    headers = as_gym(gym.id, gym.coach)

    response = client.patch(
        f"/api/material/{made['id']}",
        json={
            "title": "Pasaje de guardia, parte 2",
            "audience": "plans",
            "plan_ids": [gym.kids_plan],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated_at"] is not None
    assert mine(client, gym, gym.ana) == []
    assert mine(client, gym, gym.beto) == ["Pasaje de guardia, parte 2"]
    # The same edit again changes nothing and logs nothing.
    again = client.patch(f"/api/material/{made['id']}", json={"audience": "plans"}, headers=headers)
    assert again.status_code == 200, again.text

    assert client.delete(f"/api/material/{made['id']}", headers=headers).status_code == 204
    assert mine(client, gym, gym.beto) == []
    assert in_sql(db, gym, gym.beto) == []
    assert on_session(client, gym, session) == []
    assert client.delete(f"/api/material/{made['id']}", headers=headers).status_code == 404

    rows = audit(db, gym)
    assert [(r["action"], r["actor_id"]) for r in rows] == [
        ("study_material_changed", gym.coach),
        ("study_material_removed", gym.coach),
    ]
    detail = json.loads(rows[0]["detail"])
    assert detail["before"] == {
        "title": "Pasaje de guardia",
        "audience": "program",
        "plan_ids": [],
    }
    assert detail["after"]["plan_ids"] == [gym.kids_plan]


@pg
def test_another_coach_cannot_edit_or_remove(client: TestClient, db: Database, gym: Gym) -> None:
    made = shared(client, gym, one_off(client, gym))
    other = add_staff(db, gym.id, "coach")
    headers = as_gym(gym.id, other)
    assert (
        client.patch(
            f"/api/material/{made['id']}", json={"title": "x"}, headers=headers
        ).status_code
        == 403
    )
    assert client.delete(f"/api/material/{made['id']}", headers=headers).status_code == 403


# --- a recurring class ------------------------------------------------------------


def slot_sessions(db: Database, g: Gym) -> dict[Any, str]:
    return {r["slot_date"]: str(r["id"]) for r in sessions_of(db, g.id) if r["slot_id"]}


@pg
def test_a_recurring_material_shows_from_its_date_on_not_before(
    client: TestClient, db: Database, gym: Gym
) -> None:
    slot = backfilled_slot(client, db, gym.id, gym.fundamentals)
    days = slot_sessions(db, gym)
    start = today() + timedelta(days=3)
    response = client.post(
        f"/api/schedule/{slot['id']}/material",
        json={"title": "Ciclo de fuerza", "audience": "program", "starts_on": start.isoformat()},
        headers=as_gym(gym.id),
    )
    made = created(response)
    assert (made["session_id"], made["starts_on"]) == (None, start.isoformat())

    assert on_session(client, gym, days[start]) == ["Ciclo de fuerza"]
    assert on_session(client, gym, days[start + timedelta(days=1)]) == ["Ciclo de fuerza"]
    assert on_session(client, gym, days[start - timedelta(days=1)]) == []
    assert on_session(client, gym, days[today() - timedelta(days=2)]) == []
    listed = client.get(f"/api/schedule/{slot['id']}/material", headers=as_gym(gym.id)).json()
    assert [m["title"] for m in listed] == ["Ciclo de fuerza"]
    # Its program sees it once its day has come, not before.
    assert mine(client, gym, gym.ana) == []
    moved = client.patch(
        f"/api/material/{made['id']}",
        json={"starts_on": today().isoformat()},
        headers=as_gym(gym.id),
    )
    assert moved.status_code == 200, moved.text
    assert mine(client, gym, gym.ana) == ["Ciclo de fuerza"]
    assert mine(client, gym, gym.beto) == []


@pg
def test_a_recurring_material_reaches_who_attended_a_class_from_its_date_on(
    client: TestClient, db: Database, gym: Gym
) -> None:
    slot = backfilled_slot(client, db, gym.id, gym.fundamentals)
    days = slot_sessions(db, gym)
    carla = add_person(client, gym.id, "Carla Prueba")
    carla_membership = join(client, gym.id, carla, gym.adults_plan)
    # Ana attended before its date, Carla on it.
    changed(client, gym.id, days[today() - timedelta(days=5)], mark=[gym.ana_membership])
    changed(client, gym.id, days[today() - timedelta(days=3)], mark=[carla_membership])
    made = shared(
        client,
        gym,
        days[today() - timedelta(days=3)],
        title="Ciclo de fuerza",
        audience="attendees",
        recurring=True,
    )

    assert made["starts_on"] == (today() - timedelta(days=3)).isoformat()
    assert mine(client, gym, carla) == ["Ciclo de fuerza"]
    assert mine(client, gym, gym.ana) == []
    assert in_sql(db, gym, gym.ana) == []
    # Tomorrow's class: today's is not made once it has begun (`first_made`).
    assert on_session(client, gym, days[today() + timedelta(days=1)]) == ["Ciclo de fuerza"]
    assert slot["id"]


@pg
def test_a_one_off_class_has_no_recurring_class(client: TestClient, gym: Gym) -> None:
    response = share(client, gym, one_off(client, gym), recurring=True)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "not_recurring"


@pg
def test_a_recurring_material_follows_its_class_when_the_schedule_changes(
    client: TestClient, db: Database, gym: Gym
) -> None:
    slot = backfilled_slot(client, db, gym.id, gym.fundamentals)
    days = slot_sessions(db, gym)
    shared(
        client,
        gym,
        days[today() - timedelta(days=6)],
        title="Ciclo de fuerza",
        recurring=True,
    )
    split = today() + timedelta(days=2)
    response = change_slot(
        client, gym.id, slot["id"], {"from_date": split.isoformat(), "start_time": "20:00"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] != slot["id"]

    assert on_session(client, gym, days[today() - timedelta(days=4)]) == ["Ciclo de fuerza"]
    assert on_session(client, gym, days[split + timedelta(days=1)]) == ["Ciclo de fuerza"]
    new = client.get(f"/api/schedule/{response.json()['id']}/material", headers=as_gym(gym.id))
    assert [m["title"] for m in new.json()] == ["Ciclo de fuerza"]
