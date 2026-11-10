"""The promotion log (#48): awarding a rank against the gym's scheme, the current rank on
the ficha and the student page, and the `promoted` plan event a promotion writes.
Classes since the last promotion are attendance's (`tests/test_attendance.py`).

Every staff role's access is covered with the other endpoint groups in
`tests/test_roles.py`; a coach awarding is checked here, since coaches are who promote.
"""

import copy
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.grading import PRESETS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_guardians import add_person, bill
from tests.test_plans import add_staff

pg = pytest.mark.postgres

BJJ = next(p.scheme.model_dump() for p in PRESETS if p.key == "bjj")
JUDO = next(p.scheme.model_dump() for p in PRESETS if p.key == "judo-karate")


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


def gym_with(client: TestClient, db: Database, scheme: dict[str, Any] | None = BJJ) -> uuid.UUID:
    gym = seed_gym(db, f"academia-{uuid.uuid4().hex[:8]}")
    if scheme is not None:
        response = client.put("/api/gym/grading-scheme", json=scheme, headers=as_gym(gym))
        assert response.status_code == 200, response.text
    return gym


def member(client: TestClient, db: Database, gym: uuid.UUID, name: str = "Felipe Díaz") -> str:
    person = add_person(client, gym, name)
    bill(db, gym, person, [])
    return person


def award(
    client: TestClient,
    gym: uuid.UUID,
    person: str,
    by: uuid.UUID | None = None,
    **body: Any,
) -> Any:
    return client.post(f"/api/people/{person}/grades", json=body, headers=as_gym(gym, by))


def grades(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    response = client.get(f"/api/people/{person}/grades", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def plan_events(db: Database, gym: uuid.UUID) -> list[tuple[str, date]]:
    rows = run(
        db.api_url,
        in_gym(gym, "SELECT kind, occurred_on FROM plan_event ORDER BY occurred_on, created_at"),
    )
    return [(r["kind"], r["occurred_on"]) for r in rows]


@pg
def test_a_member_with_no_promotion_has_no_rank(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    assert grades(client, gym, person) == {"current": None, "events": []}


@pg
def test_a_promotion_is_the_current_rank_with_the_schemes_labels(
    client: TestClient, db: Database
) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    on = seeded_today() - timedelta(days=30)

    response = award(
        client, gym, person, rank_key="blue", sub_rank="2", awarded_on=str(on), note=" Buen año "
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["current"] == {
        "rank_key": "blue",
        "rank_label": "Azul",
        "sub_rank": "2",
        "sub_rank_label": "2 grados",
        "awarded_on": str(on),
        "belt": {"colors": ["#1f4fa3"], "stripes": 2, "max_stripes": 4},
    }
    [event] = body["events"]
    assert event["note"] == "Buen año"
    assert event["awarded_by_name"] == f"owner of {_slug(client, gym)}"
    assert body == grades(client, gym, person)


def _slug(client: TestClient, gym: uuid.UUID) -> str:
    return str(client.get("/api/gym/settings", headers=as_gym(gym)).json()["name"])


@pg
def test_the_latest_award_is_current_and_the_log_is_newest_first(
    client: TestClient, db: Database
) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    award(client, gym, person, rank_key="blue", sub_rank="0", awarded_on=str(seeded_today()))
    # Entered afterwards, but given earlier: history, not the current rank.
    award(client, gym, person, rank_key="white", sub_rank="4", awarded_on="2024-03-01")

    body = grades(client, gym, person)
    assert (body["current"]["rank_key"], body["current"]["sub_rank"]) == ("blue", "0")
    assert [(e["rank_key"], e["awarded_on"]) for e in body["events"]] == [
        ("blue", str(seeded_today())),
        ("white", "2024-03-01"),
    ]

    # Two on one day: the one recorded last is current.
    award(client, gym, person, rank_key="blue", sub_rank="1")
    assert grades(client, gym, person)["current"]["sub_rank"] == "1"


@pg
def test_a_promotion_to_the_current_rank_writes_a_promoted_plan_event(
    client: TestClient, db: Database
) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    yesterday = seeded_today() - timedelta(days=1)

    award(client, gym, person, rank_key="blue", sub_rank="0", awarded_on=str(yesterday))
    assert plan_events(db, gym) == [("promoted", yesterday)]

    # A past promotion entered later is history: nothing to tell the member.
    award(client, gym, person, rank_key="white", sub_rank="4", awarded_on="2024-03-01")
    assert plan_events(db, gym) == [("promoted", yesterday)]

    # A second award the same day is still one promotion to tell them about.
    award(client, gym, person, rank_key="blue", sub_rank="1", awarded_on=str(yesterday))
    assert plan_events(db, gym) == [("promoted", yesterday)]

    award(client, gym, person, rank_key="blue", sub_rank="2")
    assert plan_events(db, gym) == [("promoted", yesterday), ("promoted", seeded_today())]


@pg
def test_the_rank_spans_memberships(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    award(client, gym, person, rank_key="purple", sub_rank="1")

    # They cancel and come back on a new membership: still purple.
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET status = 'cancelled', cancel_reason = 'x',"
            " cancelled_at = now() WHERE person_id = $1",
            uuid.UUID(person),
        ),
    )
    bill(db, gym, person, [])
    assert grades(client, gym, person)["current"]["rank_key"] == "purple"
    assert award(client, gym, person, rank_key="purple", sub_rank="2").status_code == 201


@pg
def test_a_kids_ladder_rank_and_a_rank_without_sub_ranks(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    kid = member(client, db, gym, "Mateo Ortiz")
    response = award(client, gym, kid, rank_key="grey-white", sub_rank="1")
    assert response.status_code == 201, response.text
    current = response.json()["current"]
    assert current["rank_label"] == "Gris y blanca"
    # Two-tone: grey with a white stripe through it.
    assert current["belt"] == {"colors": ["#8b8f94", "#f4f4f1"], "stripes": 1, "max_stripes": 4}

    dojo = gym_with(client, db, JUDO)
    judoka = member(client, db, dojo)
    response = award(client, dojo, judoka, rank_key="kyu-9")
    assert response.status_code == 201, response.text
    current = response.json()["current"]
    assert (current["rank_label"], current["sub_rank"], current["sub_rank_label"]) == (
        "9.º kyu",
        None,
        None,
    )
    # The preset gives kyu and dan no colours: shown as the label, as before.
    assert current["belt"] is None


@pg
def test_a_belt_follows_the_schemes_colours_and_sub_ranks(client: TestClient, db: Database) -> None:
    scheme = copy.deepcopy(JUDO)
    scheme["ranks"][0]["colors"] = ["#FFFFFF"]
    scheme["ranks"][1].update(colors=["#f2c12e"], sub_ranks=[{"key": "a", "label": "A"}])
    dojo = gym_with(client, db, scheme)
    judoka = member(client, db, dojo)

    award(client, dojo, judoka, rank_key="kyu-10")
    # Stored lower-case; a rank without sub-ranks has no stripes to earn.
    assert grades(client, dojo, judoka)["current"]["belt"] == {
        "colors": ["#ffffff"],
        "stripes": 0,
        "max_stripes": 0,
    }
    award(client, dojo, judoka, rank_key="kyu-9", sub_rank="a")
    belt = grades(client, dojo, judoka)["current"]["belt"]
    assert (belt["stripes"], belt["max_stripes"]) == (0, 0)


@pg
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"rank_key": "red", "sub_rank": "0"}, "unknown_rank"),
        ({"rank_key": "blue", "sub_rank": "5"}, "unknown_sub_rank"),
        ({"rank_key": "blue"}, "sub_rank_required"),
        ({"rank_key": "blue", "sub_rank": "0", "awarded_on": "2999-01-01"}, "awarded_in_future"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_an_award_the_scheme_does_not_allow_is_refused(
    client: TestClient, db: Database, body: dict[str, Any], code: str
) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    response = award(client, gym, person, **body)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": code}}
    assert grades(client, gym, person)["events"] == []
    assert plan_events(db, gym) == []


@pg
def test_a_sub_rank_on_a_rank_without_them_is_refused(client: TestClient, db: Database) -> None:
    dojo = gym_with(client, db, JUDO)
    judoka = member(client, db, dojo)
    response = award(client, dojo, judoka, rank_key="kyu-9", sub_rank="1")
    assert response.json() == {"detail": {"code": "unknown_sub_rank"}}


@pg
def test_a_gym_with_no_scheme_awards_nothing(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db, None)
    person = member(client, db, gym)
    response = award(client, gym, person, rank_key="white")
    assert response.json() == {"detail": {"code": "unknown_rank"}}


@pg
def test_a_bad_note_or_field_is_a_422(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    for body in (
        {"rank_key": "blue", "sub_rank": "0", "note": "x" * 501},
        {"rank_key": "blue", "sub_rank": "0", "awarded_by": str(uuid.uuid4())},
        {"rank_key": "Azul", "sub_rank": "0"},
    ):
        response = client.post(f"/api/people/{person}/grades", json=body, headers=as_gym(gym))
        assert response.status_code == 422, body


@pg
def test_someone_with_no_membership_cannot_be_promoted(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = add_person(client, gym, "Sin Plan")
    response = award(client, gym, person, rank_key="white", sub_rank="0")
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "no_membership"}}


@pg
def test_another_gyms_person_is_not_found(client: TestClient, db: Database) -> None:
    sur, norte = gym_with(client, db), gym_with(client, db)
    person = member(client, db, sur)
    award(client, sur, person, rank_key="blue", sub_rank="0")

    assert client.get(f"/api/people/{person}/grades", headers=as_gym(norte)).status_code == 404
    assert award(client, norte, person, rank_key="blue", sub_rank="0").status_code == 404
    rows = run(db.api_url, in_gym(norte, "SELECT id FROM grade_event"))
    assert rows == []


@pg
def test_a_coach_promotes(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    coach = add_staff(db, gym, "coach")
    response = award(client, gym, person, by=coach, rank_key="blue", sub_rank="0")
    assert response.status_code == 201, response.text
    rows = run(db.api_url, in_gym(gym, "SELECT awarded_by FROM grade_event"))
    assert [r["awarded_by"] for r in rows] == [coach]


@pg
def test_a_key_the_scheme_no_longer_has_reads_as_its_key(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    award(client, gym, person, rank_key="blue", sub_rank="3")
    edited = copy.deepcopy(BJJ)
    edited["ranks"] = [r for r in edited["ranks"] if r["key"] != "blue"]
    client.put("/api/gym/grading-scheme", json=edited, headers=as_gym(gym))

    current = grades(client, gym, person)["current"]
    assert (current["rank_label"], current["sub_rank_label"]) == ("blue", "3")


@pg
def test_a_stored_scheme_that_no_longer_fits_still_reads_and_refuses_awards(
    client: TestClient, db: Database
) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    award(client, gym, person, rank_key="blue", sub_rank="3")
    old = {"ranks": [{"key": "white", "label": "Blanca", "sub_ranks": 4}]}
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE gym SET settings = settings || $2::jsonb WHERE id = $1",
            gym,
            json.dumps({"grading": old}),
        ),
    )

    assert grades(client, gym, person)["current"]["rank_label"] == "blue"
    response = award(client, gym, person, rank_key="white", sub_rank="0")
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "grading_scheme_invalid"}}


@pg
def test_the_student_page_shows_the_rank(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)

    def mine() -> Any:
        response = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person)))
        assert response.status_code == 200, response.text
        return response.json()

    assert mine()["rank"] is None
    award(client, gym, person, rank_key="purple", sub_rank="1", awarded_on="2025-06-14")
    assert mine()["rank"] == {
        "rank_key": "purple",
        "rank_label": "Morada",
        "sub_rank": "1",
        "sub_rank_label": "1 grado",
        "awarded_on": "2025-06-14",
        "belt": {"colors": ["#6b2d8f"], "stripes": 1, "max_stripes": 4},
    }


@pg
def test_promotions_are_history(db: Database, client: TestClient) -> None:
    gym = gym_with(client, db)
    person = member(client, db, gym)
    award(client, gym, person, rank_key="blue", sub_rank="0")
    for sql in ("UPDATE grade_event SET rank_key = 'black'", "DELETE FROM grade_event"):
        with pytest.raises(Exception, match="permission denied"):
            run(db.api_url, in_gym(gym, sql))
