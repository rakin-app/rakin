"""The class timer's data (migration 0028): block kinds, open mats, a session's blocks
and a person's time from the sessions they attended.

A gym starts with six block kinds; one in use is archived, not deleted. A session's plan
is replaced whole and keeps, by block id, what was recorded, so the timer's offline
queue may resend. Everyone present at a session gets all its blocks' time.
"""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.dates import gym_today
from app.main import create_app
from app.schemas.blocks import MAX_BLOCKS, BlockActual, PlanReplace
from app.schemas.classes import ClassTypeCreate
from app.seed.build import default_block_kind_id
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import (
    SANTIAGO,
    changed,
    class_type,
    created,
    join,
    plan,
    program,
    roster,
)
from tests.test_guardians import add_person
from tests.test_plans import MONTHLY, add_staff

KIND = str(uuid.uuid4())

# --- input rules, no database -----------------------------------------------------


def test_a_class_type_is_a_class_unless_told() -> None:
    body = ClassTypeCreate.model_validate({"name": "x", "program_id": KIND})
    assert (body.kind, body.counts_as_class) == ("class", None)


@pytest.mark.parametrize(
    "body",
    [
        {"blocks": [{"id": KIND, "block_kind_id": KIND, "planned_seconds": 60}] * 2},
        {"blocks": [{"block_kind_id": KIND, "planned_seconds": 60}] * (MAX_BLOCKS + 1)},
        {"blocks": [{"block_kind_id": KIND, "planned_seconds": 0}]},
        {"blocks": [{"block_kind_id": KIND, "rounds_planned": 0}]},
        {"blocks": [{"block_kind_id": KIND, "planned_seconds": 60, "actual_seconds": 60}]},
    ],
    ids=["id-twice", "too-many", "no-seconds", "no-rounds", "actuals-in-plan"],
)
def test_a_plan_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanReplace.model_validate(body)


def test_an_actual_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        BlockActual.model_validate({"actual_seconds": -1})


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
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


def kinds(client: TestClient, gym: uuid.UUID) -> dict[str, Any]:
    return {k["name"]: k for k in ok(client.get("/api/block-kinds", headers=as_gym(gym)))}


def open_mat(client: TestClient, gym: uuid.UUID, program_id: str) -> str:
    body = {"name": "Open mat", "program_id": program_id, "kind": "open_mat"}
    return str(created(client.post("/api/class-types", json=body, headers=as_gym(gym)))["id"])


def start(
    client: TestClient,
    gym: uuid.UUID,
    class_type_id: str,
    starts_at: datetime | None = None,
    by: uuid.UUID | None = None,
) -> str:
    body: dict[str, Any] = {"class_type_id": class_type_id}
    if starts_at is not None:
        body["starts_at"] = starts_at.isoformat()
    response = client.post("/api/sessions", json=body, headers=as_gym(gym, by))
    return str(created(response)["id"])


def put_plan(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    blocks: list[dict[str, Any]],
    by: uuid.UUID | None = None,
) -> Any:
    return client.put(
        f"/api/sessions/{session}/blocks", json={"blocks": blocks}, headers=as_gym(gym, by)
    )


def record(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    block: str,
    body: dict[str, Any],
    by: uuid.UUID | None = None,
) -> Any:
    return client.put(
        f"/api/sessions/{session}/blocks/{block}/actual", json=body, headers=as_gym(gym, by)
    )


def error_type(response: Any) -> str:
    assert response.status_code == 422, response.text
    return str(response.json()["detail"][0]["type"])


def classes(client: TestClient, gym: uuid.UUID) -> tuple[str, str]:
    """A program open to the seeded owner, and a class type of it."""
    adults = program(client, gym, "Adultos")
    return adults, class_type(client, gym, adults)


def technique_and_sparring(k: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"block_kind_id": k["Técnica"]["id"], "planned_seconds": 1200},
        {
            "block_kind_id": k["Sparring"]["id"],
            "rounds_planned": 5,
            "round_seconds": 300,
            "rest_seconds": 60,
        },
    ]


def mark_owner(client: TestClient, gym: uuid.UUID, session: str) -> None:
    membership = roster(client, gym, session)["members"][0]["membership_id"]
    changed(client, gym, session, mark=[membership])


# --- block kinds -------------------------------------------------------------------


@pg
def test_a_gym_starts_with_the_six_kinds_in_order(client: TestClient, gym: uuid.UUID) -> None:
    listed = ok(client.get("/api/block-kinds", headers=as_gym(gym)))
    assert [(k["name"], k["is_sparring"], k["position"]) for k in listed] == [
        ("Calentamiento", False, 0),
        ("Técnica", False, 1),
        ("Drilling", False, 2),
        ("Juegos", False, 3),
        ("Sparring", True, 4),
        ("Otro", False, 5),
    ]
    # The ids the demo seed derives for its blocks.
    assert listed[4]["id"] == str(default_block_kind_id(gym, "sparring"))


@pg
def test_the_migration_gives_the_gyms_already_there_their_kinds() -> None:
    with throwaway_database(require_test_database_url()) as fresh:
        migrate(fresh, "0025")
        before = seed_gym(fresh, "before")
        migrate(fresh)
        rows = run(
            fresh.api_url,
            in_gym(before, "SELECT name FROM block_kind ORDER BY position"),
        )
        assert [r["name"] for r in rows][::5] == ["Calentamiento", "Otro"]
        assert len(rows) == 6


@pg
def test_block_kinds_are_created_renamed_ordered_and_deleted(
    client: TestClient, gym: uuid.UUID
) -> None:
    headers = as_gym(gym)
    made = created(client.post("/api/block-kinds", json={"name": " Lucha "}, headers=headers))
    assert (made["name"], made["is_sparring"], made["position"]) == ("Lucha", False, 6)
    taken = client.post("/api/block-kinds", json={"name": "JUEGOS"}, headers=headers)
    assert taken.status_code == 409
    renamed = client.patch(
        f"/api/block-kinds/{made['id']}", json={"name": "Lucha de pie"}, headers=headers
    )
    assert ok(renamed)["name"] == "Lucha de pie"
    assert (
        client.patch(
            f"/api/block-kinds/{made['id']}", json={"name": "Otro"}, headers=headers
        ).status_code
        == 409
    )

    ids = [k["id"] for k in ok(client.get("/api/block-kinds", headers=headers))]
    reordered = ok(client.put("/api/block-kinds/order", json={"ids": ids[::-1]}, headers=headers))
    assert [k["id"] for k in reordered] == ids[::-1]
    assert [k["position"] for k in reordered] == list(range(len(ids)))
    for partial in (ids[1:], [*ids, ids[0]], [*ids[1:], str(uuid.uuid4())]):
        response = client.put("/api/block-kinds/order", json={"ids": partial}, headers=headers)
        assert response.status_code == 422

    deleted = client.delete(f"/api/block-kinds/{made['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/block-kinds", headers=headers).json()[0]["name"] == "Otro"
    assert client.delete(f"/api/block-kinds/{made['id']}", headers=headers).status_code == 404


@pg
def test_a_kind_in_use_is_archived_not_deleted(client: TestClient, gym: uuid.UUID) -> None:
    _, fundamentals = classes(client, gym)
    k = kinds(client, gym)
    session = start(client, gym, fundamentals)
    ok(put_plan(client, gym, session, technique_and_sparring(k)))
    technique = k["Técnica"]["id"]

    refused = client.delete(f"/api/block-kinds/{technique}", headers=as_gym(gym))
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "block_kind_in_use", "blocks": 1}}
    flipped = client.patch(
        f"/api/block-kinds/{technique}", json={"is_sparring": True}, headers=as_gym(gym)
    )
    assert flipped.status_code == 409

    archived = ok(
        client.patch(f"/api/block-kinds/{technique}", json={"archived": True}, headers=as_gym(gym))
    )
    assert archived["archived"]
    listed = ok(client.get("/api/block-kinds?archived=false", headers=as_gym(gym)))
    assert "Técnica" not in [k["name"] for k in listed]
    assert ok(client.get("/api/block-kinds", headers=as_gym(gym)))[-1]["name"] == "Técnica"
    # Its blocks keep it, and a plan that keeps them is still taken; a new one is not.
    blocks = ok(client.get(f"/api/sessions/{session}/blocks", headers=as_gym(gym)))["blocks"]
    assert blocks[0]["block_kind_name"] == "Técnica"
    kept = [{k: b[k] for k in ("id", "block_kind_id", "planned_seconds")} for b in blocks[:1]]
    ok(put_plan(client, gym, session, kept))
    fresh = [{"block_kind_id": technique, "planned_seconds": 60}]
    assert error_type(put_plan(client, gym, session, fresh)) == "archived_block_kind"


@pg
def test_a_coach_reads_block_kinds_and_changes_none(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    assert len(ok(client.get("/api/block-kinds", headers=as_gym(gym, coach)))) == 6
    sparring = kinds(client, gym)["Sparring"]["id"]
    for response in (
        client.post("/api/block-kinds", json={"name": "x"}, headers=as_gym(gym, coach)),
        client.patch(
            f"/api/block-kinds/{sparring}", json={"archived": True}, headers=as_gym(gym, coach)
        ),
        client.delete(f"/api/block-kinds/{sparring}", headers=as_gym(gym, coach)),
    ):
        assert response.status_code == 403


@pg
def test_block_kinds_stay_in_their_gym(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    theirs = kinds(client, other)["Técnica"]["id"]
    assert (
        client.patch(
            f"/api/block-kinds/{theirs}", json={"name": "x"}, headers=as_gym(gym)
        ).status_code
        == 404
    )
    _, fundamentals = classes(client, gym)
    session = start(client, gym, fundamentals)
    planned = put_plan(client, gym, session, [{"block_kind_id": theirs, "planned_seconds": 60}])
    assert error_type(planned) == "unknown_block_kind"
    # RLS alone, past the API: the other gym's kinds are not there.
    rows = run(
        db.api_url,
        in_gym(gym, "SELECT count(*) AS n FROM block_kind WHERE id = $1", uuid.UUID(theirs)),
    )
    assert rows[0]["n"] == 0


# --- class types: classes and open mats --------------------------------------------


@pg
def test_an_open_mat_does_not_count_as_a_class_unless_told(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults, fundamentals = classes(client, gym)
    headers = as_gym(gym)
    mat = ok(client.get(f"/api/class-types/{open_mat(client, gym, adults)}", headers=headers))
    assert (mat["kind"], mat["counts_as_class"]) == ("open_mat", False)
    regular = ok(client.get(f"/api/class-types/{fundamentals}", headers=headers))
    assert (regular["kind"], regular["counts_as_class"]) == ("class", True)

    counted = created(
        client.post(
            "/api/class-types",
            json={
                "name": "Open mat Kids",
                "program_id": adults,
                "kind": "open_mat",
                "counts_as_class": True,
            },
            headers=headers,
        )
    )
    assert counted["counts_as_class"]
    # A new kind takes its default; an explicit value wins.
    became = ok(
        client.patch(f"/api/class-types/{mat['id']}", json={"kind": "class"}, headers=headers)
    )
    assert became["counts_as_class"]
    back = ok(
        client.patch(
            f"/api/class-types/{mat['id']}",
            json={"kind": "open_mat", "counts_as_class": True},
            headers=headers,
        )
    )
    assert (back["kind"], back["counts_as_class"]) == ("open_mat", True)
    off = ok(
        client.patch(
            f"/api/class-types/{mat['id']}", json={"counts_as_class": False}, headers=headers
        )
    )
    assert (off["kind"], off["counts_as_class"]) == ("open_mat", False)
    bad = client.patch(f"/api/class-types/{mat['id']}", json={"kind": "seminar"}, headers=headers)
    assert bad.status_code == 422


@pg
def test_an_open_mat_is_left_out_of_the_class_counts(client: TestClient, gym: uuid.UUID) -> None:
    adults, fundamentals = classes(client, gym)
    mat = open_mat(client, gym, adults)
    for class_type_id in (fundamentals, mat):
        mark_owner(client, gym, start(client, gym, class_type_id))
    owner = roster(client, gym, start(client, gym, fundamentals))["members"][0]["person_id"]
    counts = ok(client.get(f"/api/people/{owner}/attendance", headers=as_gym(gym)))
    assert (counts["total"], counts["last_30_days"]) == (1, 1)


# --- a session's plan ---------------------------------------------------------------


@pg
def test_a_plan_is_replaced_whole_and_keeps_what_ran(client: TestClient, gym: uuid.UUID) -> None:
    _, fundamentals = classes(client, gym)
    k = kinds(client, gym)
    session = start(client, gym, fundamentals)
    assert ok(client.get(f"/api/sessions/{session}/blocks", headers=as_gym(gym))) == {
        "session_id": session,
        "class_kind": "class",
        "blocks": [],
    }
    warmup_id = str(uuid.uuid4())
    blocks = [
        {"id": warmup_id, "block_kind_id": k["Calentamiento"]["id"], "planned_seconds": 600},
        *technique_and_sparring(k),
    ]
    plan_ = ok(put_plan(client, gym, session, blocks))["blocks"]
    assert [b["position"] for b in plan_] == [0, 1, 2]
    assert plan_[0]["id"] == warmup_id
    assert plan_[2]["planned_seconds"] == 1500  # 5 rounds of 300, rest not counted
    assert all(b["actual_seconds"] is None for b in plan_)

    # Stopped two minutes early; sent twice, as an offline queue may.
    for _ in range(2):
        warm = ok(record(client, gym, session, warmup_id, {"actual_seconds": 480}))
    assert warm["actual_seconds"] == 480
    sparring = plan_[2]["id"]
    spar = ok(
        record(client, gym, session, sparring, {"actual_seconds": 900, "rounds_completed": 3})
    )
    assert (spar["actual_seconds"], spar["rounds_completed"]) == (900, 3)

    # The coach drops técnica and adds a round while running: what ran is kept.
    replanned = [
        {"id": warmup_id, "block_kind_id": k["Calentamiento"]["id"], "planned_seconds": 600},
        {
            "id": sparring,
            "block_kind_id": k["Sparring"]["id"],
            "rounds_planned": 6,
            "round_seconds": 300,
            "rest_seconds": 60,
            "planned_seconds": 1800,
        },
    ]
    for _ in range(2):
        again = ok(put_plan(client, gym, session, replanned))["blocks"]
    assert [(b["id"], b["position"], b["actual_seconds"]) for b in again] == [
        (warmup_id, 0, 480),
        (sparring, 1, 900),
    ]
    assert (again[1]["rounds_planned"], again[1]["rounds_completed"]) == (6, 3)
    # Fewer rounds than completed: completed is cut to the plan.
    fewer = [{**replanned[1], "rounds_planned": 2, "planned_seconds": 600}]
    assert ok(put_plan(client, gym, session, fewer))["blocks"][0]["rounds_completed"] == 2

    gone = record(client, gym, session, warmup_id, {"actual_seconds": 1})
    assert gone.status_code == 404
    assert ok(put_plan(client, gym, session, []))["blocks"] == []


@pg
@pytest.mark.parametrize(
    ("kind", "block", "expected"),
    [
        ("Sparring", {"rounds_planned": 3, "round_seconds": 300}, "missing"),
        ("Sparring", {"planned_seconds": 60}, "missing"),
        (
            "Sparring",
            {"rounds_planned": 3, "round_seconds": 300, "rest_seconds": 60, "planned_seconds": 1},
            "planned_seconds_mismatch",
        ),
        (
            "Sparring",
            {"rounds_planned": 100, "round_seconds": 3600, "rest_seconds": 0},
            "less_than_equal",
        ),
        ("Técnica", {}, "missing"),
        ("Técnica", {"planned_seconds": 60, "rounds_planned": 2}, "not_sparring"),
    ],
    ids=["no-rest", "seconds-not-rounds", "mismatch", "too-long", "no-seconds", "rounds"],
)
def test_a_block_is_held_to_its_kind(
    client: TestClient, gym: uuid.UUID, kind: str, block: dict[str, Any], expected: str
) -> None:
    _, fundamentals = classes(client, gym)
    session = start(client, gym, fundamentals)
    body = [{"block_kind_id": kinds(client, gym)[kind]["id"], **block}]
    assert error_type(put_plan(client, gym, session, body)) == expected


@pg
def test_an_actual_is_held_to_its_block(client: TestClient, gym: uuid.UUID) -> None:
    _, fundamentals = classes(client, gym)
    session = start(client, gym, fundamentals)
    technique, sparring = ok(
        put_plan(client, gym, session, technique_and_sparring(kinds(client, gym)))
    )["blocks"]
    assert error_type(record(client, gym, session, sparring["id"], {"actual_seconds": 60})) == (
        "missing"
    )
    over = record(
        client, gym, session, sparring["id"], {"actual_seconds": 60, "rounds_completed": 6}
    )
    assert error_type(over) == "less_than_equal"
    rounds = record(
        client, gym, session, technique["id"], {"actual_seconds": 60, "rounds_completed": 1}
    )
    assert error_type(rounds) == "not_sparring"
    # Another session's block is not this one's.
    other = start(client, gym, fundamentals)
    assert record(client, gym, other, technique["id"], {"actual_seconds": 1}).status_code == 404
    taken = put_plan(
        client,
        gym,
        other,
        [
            {
                "id": technique["id"],
                "block_kind_id": technique["block_kind_id"],
                "planned_seconds": 60,
            }
        ],
    )
    assert taken.status_code == 409


@pg
def test_an_open_mat_is_one_sparring_block(client: TestClient, gym: uuid.UUID) -> None:
    adults, _ = classes(client, gym)
    session = start(client, gym, open_mat(client, gym, adults))
    k = kinds(client, gym)
    both = technique_and_sparring(k)
    assert error_type(put_plan(client, gym, session, both)) == "open_mat_plan"
    assert error_type(put_plan(client, gym, session, both[:1])) == "open_mat_plan"
    planned = ok(put_plan(client, gym, session, both[1:]))
    assert planned["class_kind"] == "open_mat"
    assert [b["block_kind_name"] for b in planned["blocks"]] == ["Sparring"]


@pg
def test_the_coach_of_the_session_or_an_admin_runs_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, fundamentals = classes(client, gym)
    coach, other_coach, admin = (add_staff(db, gym, r) for r in ("coach", "coach", "admin"))
    session = start(client, gym, fundamentals, by=coach)
    blocks = technique_and_sparring(kinds(client, gym))

    assert put_plan(client, gym, session, blocks, by=other_coach).status_code == 403
    planned = ok(put_plan(client, gym, session, blocks, by=coach))["blocks"]
    assert ok(put_plan(client, gym, session, blocks, by=admin))
    owner_plan = ok(put_plan(client, gym, session, blocks))["blocks"]
    block = owner_plan[0]["id"]
    refused = record(client, gym, session, block, {"actual_seconds": 60}, by=other_coach)
    assert refused.status_code == 403
    assert ok(record(client, gym, session, block, {"actual_seconds": 60}, by=coach))
    # Any coach reads the plan and the suggestion.
    assert ok(client.get(f"/api/sessions/{session}/blocks", headers=as_gym(gym, other_coach)))
    assert ok(
        client.get(f"/api/sessions/{session}/blocks/suggested", headers=as_gym(gym, other_coach))
    )
    assert len(planned) == 2


@pg
def test_a_session_and_its_blocks_stay_in_their_gym(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, fundamentals = classes(client, gym)
    session = start(client, gym, fundamentals)
    blocks = ok(put_plan(client, gym, session, technique_and_sparring(kinds(client, gym))))[
        "blocks"
    ]
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    headers = as_gym(other)
    assert client.get(f"/api/sessions/{session}/blocks", headers=headers).status_code == 404
    assert put_plan(client, other, session, []).status_code == 404
    assert record(client, other, session, blocks[0]["id"], {"actual_seconds": 1}).status_code == 404
    rows = run(db.api_url, in_gym(other, "SELECT count(*) AS n FROM session_block"))
    assert rows[0]["n"] == 0


@pg
def test_the_suggested_plan_is_the_last_one_of_the_class_type(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults, fundamentals = classes(client, gym)
    advanced = class_type(client, gym, adults, "Avanzado")
    k = kinds(client, gym)
    today = gym_today(SANTIAGO)
    first, second, unplanned, other_type, now = (
        start(client, gym, ct, datetime.combine(today - timedelta(days=d), time(19), SANTIAGO))
        for ct, d in (
            (fundamentals, 3),
            (fundamentals, 2),
            (fundamentals, 1),
            (advanced, 1),
            (fundamentals, 0),
        )
    )
    empty = ok(client.get(f"/api/sessions/{first}/blocks/suggested", headers=as_gym(gym)))
    assert empty == {"session_id": first, "from_session_id": None, "blocks": []}

    ok(put_plan(client, gym, first, technique_and_sparring(k)))
    games = [
        {"block_kind_id": k["Juegos"]["id"], "planned_seconds": 900},
        {"block_kind_id": k["Drilling"]["id"], "planned_seconds": 300},
    ]
    second_plan = ok(put_plan(client, gym, second, games))["blocks"]
    ok(record(client, gym, second, second_plan[0]["id"], {"actual_seconds": 100}))
    ok(
        put_plan(
            client, gym, other_type, [{"block_kind_id": k["Otro"]["id"], "planned_seconds": 60}]
        )
    )
    assert unplanned

    suggested = ok(client.get(f"/api/sessions/{now}/blocks/suggested", headers=as_gym(gym)))
    assert suggested["from_session_id"] == second
    assert suggested["blocks"] == [
        {
            "block_kind_id": k["Juegos"]["id"],
            "block_kind_name": "Juegos",
            "is_sparring": False,
            "planned_seconds": 900,
            "rounds_planned": None,
            "round_seconds": None,
            "rest_seconds": None,
        },
        {
            "block_kind_id": k["Drilling"]["id"],
            "block_kind_name": "Drilling",
            "is_sparring": False,
            "planned_seconds": 300,
            "rounds_planned": None,
            "round_seconds": None,
            "rest_seconds": None,
        },
    ]
    # An archived kind is left out of the suggestion.
    ok(
        client.patch(
            f"/api/block-kinds/{k['Drilling']['id']}", json={"archived": True}, headers=as_gym(gym)
        )
    )
    trimmed = ok(client.get(f"/api/sessions/{now}/blocks/suggested", headers=as_gym(gym)))
    assert [b["block_kind_name"] for b in trimmed["blocks"]] == ["Juegos"]


# --- a person's time ----------------------------------------------------------------


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=SANTIAGO)


def run_class(
    client: TestClient,
    gym: uuid.UUID,
    class_type_id: str,
    starts_at: datetime,
    blocks: list[dict[str, Any]],
    actuals: list[dict[str, Any] | None],
    present: list[str],
) -> str:
    """A session at `starts_at` with `blocks` run as `actuals`, and `present` marked."""
    session = start(client, gym, class_type_id, starts_at)
    planned = ok(put_plan(client, gym, session, blocks))["blocks"]
    for block, actual in zip(planned, actuals, strict=True):
        if actual is not None:
            ok(record(client, gym, session, block["id"], actual))
    if present:
        changed(client, gym, session, mark=present)
    return session


@pg
def test_a_persons_time_is_every_block_of_the_sessions_they_attended(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults, fundamentals = classes(client, gym)
    mat = open_mat(client, gym, adults)
    monthly = plan(client, gym, {**MONTHLY, "program_id": adults})
    ana = add_person(client, gym, "Ana Rojas")
    ana_membership = join(client, gym, ana, monthly)
    bruno = add_person(client, gym, "Bruno Díaz")
    bruno_membership = join(client, gym, bruno, monthly)
    k = kinds(client, gym)
    month_start = gym_today(SANTIAGO).replace(day=1)
    blocks = technique_and_sparring(k)

    # This month, from its first minutes on the gym's calendar: técnica stopped early
    # and three of five rounds. Ana arrived late; she gets it all the same.
    run_class(
        client,
        gym,
        fundamentals,
        local(month_start, 0, 30),
        blocks,
        [{"actual_seconds": 1000}, {"actual_seconds": 900, "rounds_completed": 3}],
        [ana_membership, bruno_membership],
    )
    # The last evening of last month: all time only.
    run_class(
        client,
        gym,
        fundamentals,
        local(month_start - timedelta(days=1), 23, 30),
        blocks,
        [{"actual_seconds": 1200}, {"actual_seconds": 1500, "rounds_completed": 5}],
        [ana_membership],
    )
    # An open mat this month: sparring, and open mat time of its own.
    run_class(
        client,
        gym,
        mat,
        local(month_start, 1),
        blocks[1:],
        [{"actual_seconds": 600, "rounds_completed": 2}],
        [ana_membership],
    )
    # A planned block never run counts nothing; Bruno was not at this one.
    run_class(client, gym, fundamentals, local(month_start, 2), blocks, [None, None], [])

    time_ = ok(client.get(f"/api/people/{ana}/time", headers=as_gym(gym)))
    assert (time_["timezone"], time_["month_start"]) == ("America/Santiago", str(month_start))

    def by_kind(totals: Any) -> dict[str, int]:
        return {t["name"]: t["seconds"] for t in totals["by_kind"]}

    month, all_time = time_["this_month"], time_["all_time"]
    assert by_kind(month) == {"Técnica": 1000, "Sparring": 1500}
    assert (month["sparring_seconds"], month["open_mat_seconds"]) == (1500, 600)
    assert (month["classes"], month["open_mats"]) == (1, 1)
    assert by_kind(all_time) == {"Técnica": 2200, "Sparring": 3000}
    assert (all_time["sparring_seconds"], all_time["open_mat_seconds"]) == (3000, 600)
    assert (all_time["classes"], all_time["open_mats"]) == (2, 1)

    bruno_time = ok(client.get(f"/api/people/{bruno}/time", headers=as_gym(gym)))
    assert by_kind(bruno_time["all_time"]) == {"Técnica": 1000, "Sparring": 900}
    assert bruno_time["all_time"]["classes"] == 1


@pg
def test_a_session_counts_once_and_coaches_read_time(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults, fundamentals = classes(client, gym)
    ana = add_person(client, gym, "Ana Rojas")
    # Two memberships of Ana's, both marked at the same class.
    memberships = [
        join(client, gym, ana, plan(client, gym, {**MONTHLY, "name": name, "program_id": adults}))
        for name in ("Mensual", "Mensual 2")
    ]
    k = kinds(client, gym)
    run_class(
        client,
        gym,
        fundamentals,
        local(gym_today(SANTIAGO), 0, 5),
        [{"block_kind_id": k["Juegos"]["id"], "planned_seconds": 600}],
        [{"actual_seconds": 600}],
        memberships,
    )
    coach = add_staff(db, gym, "coach")
    totals = ok(client.get(f"/api/people/{ana}/time", headers=as_gym(gym, coach)))["all_time"]
    assert (totals["classes"], totals["by_kind"][0]["seconds"]) == (1, 600)

    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    assert client.get(f"/api/people/{ana}/time", headers=as_gym(other)).status_code == 404
    nobody = client.get(f"/api/people/{uuid.uuid4()}/time", headers=as_gym(gym))
    assert nobody.status_code == 404
