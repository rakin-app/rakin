"""Former students: why they left, and "Agregar exalumno" (#294).

Dar de baja takes a reason and a day as far back as history goes (60 years). The
reason is the owner's and admins': a coach's read of the person leaves it out, since
"lesión" is health data. `POST /api/people/former` adds someone who already left, with
no membership and no welcome. Each writes one `history_set` row. Rakin never writes to
a former student, whatever the path, and one can be deleted as anyone can
(docs/design/historical-data.md, sections 1, 4 and 7).
"""

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.auth import build_notices
from app.db import create_engine, create_sessionmaker
from app.db_bootstrap import to_dsn
from app.domain.dates import add_months
from app.jobs import daily
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_member_roll import count, enrolled, forget, leave, listed, memberships, plan
from tests.test_memberships import add_staff
from tests.test_people import new_phone, new_rut
from tests.test_proofs import RecordingMailer

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(db: Database, mailer: RecordingMailer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("gym"))


def former(client: TestClient, gym: uuid.UUID, *, by: uuid.UUID | None = None, **body: Any) -> Any:
    return client.post(
        "/api/people/former",
        json={"name": "Ex Alumna", "left_on": "2022-06-30", **body},
        headers=as_gym(gym, by),
    )


def added(client: TestClient, gym: uuid.UUID, **body: Any) -> dict[str, Any]:
    key: dict[str, Any] = {} if body.keys() & {"rut", "email"} else {"rut": new_rut()}
    response = former(client, gym, **key, **body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def history_rows(db: Database, gym: uuid.UUID, person: str) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT detail FROM audit_event WHERE person_id = $1 AND action = 'history_set'"
            " ORDER BY at, id",
            uuid.UUID(person),
        ),
    )
    return [json.loads(r["detail"]) for r in rows]


def read(client: TestClient, gym: uuid.UUID, person: str, by: uuid.UUID | None = None) -> Any:
    response = client.get(f"/api/people/{person}", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


# --- Dar de baja, with a reason ---------------------------------------------------


@pg
def test_dar_de_baja_keeps_the_reason_and_a_coach_never_reads_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    response = leave(client, gym, ana["id"], left_reason="  Lesión  ")
    assert response.status_code == 200, response.text
    assert response.json()["left_reason"] == "Lesión"
    assert read(client, gym, ana["id"])["left_reason"] == "Lesión"
    admin = add_staff(db, gym, "admin")
    assert read(client, gym, ana["id"], admin)["left_reason"] == "Lesión"

    coach = add_staff(db, gym, "coach")
    seen = read(client, gym, ana["id"], coach)
    assert seen["left_on"] is not None
    assert seen["left_reason"] is None
    # Nor through an edit's answer.
    edited = client.patch(
        f"/api/people/{ana['id']}", json={"name": "Ana S."}, headers=as_gym(gym, coach)
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["left_reason"] is None

    assert history_rows(db, gym, ana["id"]) == [
        {"left_reason": {"before": None, "after": "Lesión"}}
    ]


@pg
def test_a_reason_left_blank_is_none_and_records_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    response = leave(client, gym, ana["id"], left_reason="   ")
    assert response.status_code == 200, response.text
    assert response.json()["left_reason"] is None
    assert history_rows(db, gym, ana["id"]) == []

    bea = enrolled(client, gym)
    assert leave(client, gym, bea["id"], left_reason="x" * 201).status_code == 422
    assert read(client, gym, bea["id"])["left_on"] is None


@pg
def test_dar_de_baja_reaches_back_sixty_years_and_no_further(
    client: TestClient, gym: uuid.UUID
) -> None:
    today = seeded_today()
    ana = enrolled(client, gym)
    too_far = add_months(today, -12 * 60) - timedelta(days=1)
    response = leave(client, gym, ana["id"], left_on=too_far.isoformat())
    assert response.status_code == 422
    assert "60 years" in response.text
    # Further back than a plan's five years.
    response = leave(client, gym, ana["id"], left_on="2017-03-01")
    assert response.status_code == 200, response.text
    assert response.json()["left_on"] == "2017-03-01"


@pg
def test_reactivar_clears_the_reason_and_records_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    leave(client, gym, ana["id"], left_reason="Precio")
    back = client.post(f"/api/people/{ana['id']}/return", json={}, headers=as_gym(gym))
    assert back.status_code == 200, back.text
    assert (back.json()["left_on"], back.json()["left_reason"]) == (None, None)
    assert history_rows(db, gym, ana["id"]) == [
        {"left_reason": {"before": None, "after": "Precio"}},
        {"left_reason": {"before": "Precio", "after": None}},
    ]


# --- Agregar exalumno -------------------------------------------------------------


@pg
def test_an_exalumno_is_added_with_no_membership_and_no_message(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()
    email = f"ex-{uuid.uuid4().hex[:8]}@example.cl"
    body = added(
        client,
        gym,
        name="Ex Alumna",
        email=email,
        member_since="2017-03-05",
        left_on="2022-06-30",
        left_reason="Se cambió",
    )
    assert (body["member_since"], body["left_on"], body["left_reason"]) == (
        "2017-03-05",
        "2022-06-30",
        "Se cambió",
    )
    # Nobody will write to them: no phone is not "Falta teléfono".
    assert (body["phone"], body["missing_phone"]) == (None, False)
    assert memberships(client, gym, body["id"]) == []
    assert "Ex Alumna" in listed(client, gym, left="only")
    assert "Ex Alumna" not in listed(client, gym)
    assert mailer.sent == []
    messages = "SELECT count(*) FROM message_log WHERE person_id = $1"
    assert count(db, gym, messages, uuid.UUID(body["id"])) == 0
    assert history_rows(db, gym, body["id"]) == [
        {
            "member_since": {"before": None, "after": "2017-03-05"},
            "left_on": {"before": None, "after": "2022-06-30"},
            "left_reason": {"before": None, "after": "Se cambió"},
        }
    ]


@pg
def test_an_exalumno_needs_who_they_are_and_days_in_order(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    assert former(client, gym).status_code == 422
    rut = new_rut()
    refusals: list[dict[str, Any]] = [
        {"rut": rut, "left_on": (today + timedelta(days=1)).isoformat()},
        {"rut": rut, "member_since": "2022-07-01", "left_on": "2022-06-30"},
        {"rut": rut, "member_since": (add_months(today, -12 * 60) - timedelta(days=1)).isoformat()},
        {"rut": rut, "left_reason": "x" * 201},
    ]
    for body in refusals:
        assert former(client, gym, **body).status_code == 422, body
    # The phone, when given, is a phone.
    assert former(client, gym, rut=rut, phone="123").status_code == 422

    here = enrolled(client, gym)
    taken = former(client, gym, rut=here["rut"])
    assert taken.status_code == 409
    assert taken.json()["detail"] == {"code": "rut_in_gym", "person_id": here["id"]}

    coach = add_staff(db, gym, "coach")
    assert former(client, gym, by=coach, rut=new_rut()).status_code == 403
    admin = add_staff(db, gym, "admin")
    assert former(client, gym, by=admin, rut=new_rut(), phone=new_phone()).status_code == 201


@pg
def test_an_exalumno_reactivated_starts_a_plan(client: TestClient, gym: uuid.UUID) -> None:
    body = added(client, gym, left_reason="Horario")
    back = client.post(
        f"/api/people/{body['id']}/return",
        json={"membership": {"plan_id": plan(client, gym)}},
        headers=as_gym(gym),
    )
    assert back.status_code == 200, back.text
    assert [m["status"] for m in memberships(client, gym, body["id"])] == ["active"]


@pg
def test_deleting_an_exalumno_takes_their_history_rows_and_counts_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    body = added(client, gym, member_since="2017-03-05", left_on="2022-06-30", left_reason="Otro")
    person = uuid.UUID(body["id"])
    asked = client.get(f"/api/people/{body['id']}/deletion", headers=as_gym(gym))
    assert asked.json() == {"refused": None, "amount_clp": None}

    assert forget(client, gym, body["id"]).status_code == 204
    assert client.get(f"/api/people/{body['id']}", headers=as_gym(gym)).status_code == 404
    assert count(db, gym, "SELECT count(*) FROM gym_person WHERE person_id = $1", person) == 0
    assert count(db, gym, "SELECT count(*) FROM audit_event WHERE person_id = $1", person) == 0
    [deleted] = run(
        db.owner_url,
        in_gym(gym, "SELECT detail FROM audit_event WHERE action = 'person_deleted'"),
    )
    detail = json.loads(deleted["detail"])
    assert (detail["history_set"], detail["corrections"]) == (1, 0)
    # The row that stays names nobody.
    assert body["name"] not in deleted["detail"]
    assert body["rut"] not in deleted["detail"]


# --- never messaged ---------------------------------------------------------------


def nights(db: Database, days: list[date], outbox: RecordingMailer) -> None:
    """Every nightly job (`app.jobs.daily`) for each of `days`, as the runner runs them,
    each in its own transaction."""

    async def go() -> None:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            notices = build_notices(db.settings, outbox, lambda: sessionmaker)
            conn = await asyncpg.connect(to_dsn(db.owner_url))
            try:
                for day in days:
                    for job in daily.jobs(notices):
                        async with conn.transaction():
                            await job.run(conn, day)
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    asyncio.run(go())


@pg
def test_nothing_is_ever_sent_to_someone_who_left(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    """Whatever the path, welcome, billing, overdue, cobros: a former student added as
    one, and a member who left owing, are written to by none of them. A member still
    here, on the same plan, is, so each path did run."""
    today = seeded_today()
    tag = uuid.uuid4().hex[:8]
    monthly = plan(client, gym)
    started_on = (today - timedelta(days=20)).isoformat()

    def on_plan(name: str) -> dict[str, Any]:
        return enrolled(
            client,
            gym,
            name=name,
            email=f"{name.lower()}-{tag}@example.cl",
            membership={"plan_id": monthly, "started_on": started_on},
        )

    stays = on_plan("Sigue")
    went = on_plan("Fue")
    leave(client, gym, went["id"], left_reason="Precio")
    ex = added(client, gym, email=f"ex-{tag}@example.cl", left_reason="Se cambió")
    gone = {went["email"], ex["email"]}
    gone_ids = {went["id"], ex["id"]}
    mailer.sent.clear()

    # Welcome: the ficha's is refused for someone who left.
    for person in gone_ids:
        welcome = client.post(f"/api/people/{person}/welcome", headers=as_gym(gym))
        assert welcome.status_code == 409

    # The overdue email, sent by hand from Pagos, has no period of theirs to go about.
    reminders = client.get("/api/reminders", headers=as_gym(gym)).json()
    assert stays["id"] in {r["person_id"] for r in reminders}
    assert gone_ids.isdisjoint({r["person_id"] for r in reminders})

    # A cobro: picking them is refused, and "everyone active" leaves them out.
    def cobro(person_ids: list[str]) -> Any:
        return client.post(
            "/api/extra-charges",
            json={
                "title": "Rifa de fin de año",
                "category": "rifa",
                "due_date": (today + timedelta(days=10)).isoformat(),
                "message": "Cada uno vende diez números.",
                "target": {"kind": "people", "person_ids": person_ids},
                "amount_mode": "fixed",
                "amount_clp": 10_000,
            },
            headers=as_gym(gym),
        )

    for person in gone_ids:
        assert cobro([stays["id"], person]).status_code == 422
    assert cobro([stays["id"]]).status_code == 201
    everyone = client.post(
        "/api/extra-charges/preview",
        json={"target": {"kind": "active"}, "amount_mode": "fixed", "amount_clp": 5_000},
        headers=as_gym(gym),
    )
    assert everyone.status_code == 200, everyone.text
    assert gone_ids.isdisjoint({line["person"]["id"] for line in everyone.json()["lines"]})
    assert any(e.to == stays["email"] for e in mailer.sent)

    # Billing, statements, lapse and overdue, over the next two months.
    outbox = RecordingMailer()
    nights(db, [today + timedelta(days=d) for d in (0, 1, 7, 12, 20, 30, 40, 50, 60)], outbox)
    assert any(e.to == stays["email"] for e in outbox.sent)

    assert gone.isdisjoint({e.to for e in [*mailer.sent, *outbox.sent]})
    messages = "SELECT count(*) FROM message_log WHERE person_id = ANY($1::uuid[])"
    assert count(db, gym, messages, [uuid.UUID(p) for p in gone_ids]) == 0
