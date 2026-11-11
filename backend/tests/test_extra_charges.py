"""Cobros extra (#195): one-off charges, fixed or split across a group, with email notice.

Each person gets a line, paid through the same ledger as a billing period: a proof,
validation, a payment the admin records, a refund. The money counts in the book, the
student page lists the lines, and no membership is touched. Coaches see none of it.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db_bootstrap import to_dsn
from app.main import create_app
from app.schemas.extra_charges import Target
from app.schemas.proofs import ProofClaim
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
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer, upload

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "active", "group_id": str(uuid.uuid4())},
        {"kind": "group"},
        {"kind": "program", "person_ids": [str(uuid.uuid4())]},
        {"kind": "people", "person_ids": []},
    ],
    ids=str,
)
def test_a_target_names_only_what_it_needs(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Target.model_validate(body)


def test_a_claim_pays_one_thing() -> None:
    period, line = str(uuid.uuid4()), str(uuid.uuid4())
    for body in ({}, {"billing_period_id": period, "extra_line_id": line}):
        with pytest.raises(ValidationError):
            ProofClaim.model_validate({"amount_clp": 1, "proof_key": "k", **body})
    assert ProofClaim.model_validate({"amount_clp": 1, "proof_key": "k", "extra_line_id": line})


# --- against real Postgres --------------------------------------------------------

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(
    db: Database, mailer: RecordingMailer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def draft(person_ids: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "title": "Rifa de fin de año",
        "category": "rifa",
        "due_date": str(seeded_today() + timedelta(days=10)),
        "message": "Cada uno vende diez números.",
        "target": {"kind": "people", "person_ids": person_ids},
        "amount_mode": "fixed",
        "amount_clp": 10000,
        **extra,
    }


def create(client: TestClient, gym: uuid.UUID, body: dict[str, Any]) -> Any:
    return ok(client.post("/api/extra-charges", json=body, headers=as_gym(gym)), 201)


def line_of(charge: dict[str, Any], person: str) -> dict[str, Any]:
    return next(line for line in charge["people"] if line["person"]["id"] == person)


def get(client: TestClient, gym: uuid.UUID, charge_id: str) -> Any:
    return ok(client.get(f"/api/extra-charges/{charge_id}", headers=as_gym(gym)))


# --- groups -----------------------------------------------------------------------


def test_a_group_is_saved_reused_and_edited(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana, bea, carla = (add_person(client, sur, n) for n in ("Ana", "Bea", "Carla"))
    made = ok(
        client.post(
            "/api/groups",
            json={"name": "Clasificados final", "person_ids": [bea, ana]},
            headers=as_gym(sur),
        ),
        201,
    )
    assert [m["name"] for m in made["members"]] == ["Ana", "Bea"]

    again = client.post(
        "/api/groups", json={"name": "clasificados FINAL", "person_ids": []}, headers=as_gym(sur)
    )
    assert again.status_code == 409

    edited = ok(
        client.put(
            f"/api/groups/{made['id']}",
            json={"name": "Final", "person_ids": [ana, carla]},
            headers=as_gym(sur),
        )
    )
    assert (edited["name"], [m["name"] for m in edited["members"]]) == ("Final", ["Ana", "Carla"])

    # A coach reads the names, for rosters, and nothing else.
    coach = add_staff(db, sur, "coach")
    listed = ok(client.get("/api/groups", headers=as_gym(sur, coach)))
    assert [(g["name"], g["size"]) for g in listed] == [("Final", 2)]
    assert client.get(f"/api/groups/{made['id']}", headers=as_gym(sur, coach)).status_code == 403
    assert (
        client.post(
            "/api/groups", json={"name": "x", "person_ids": []}, headers=as_gym(sur, coach)
        ).status_code
        == 403
    )

    # Reused: a cobro for the group charges who is in it.
    charge = create(client, sur, draft([], target={"kind": "group", "group_id": made["id"]}))
    assert sorted(line["person"]["name"] for line in charge["people"]) == ["Ana", "Carla"]
    assert charge["target_label"] == "Final"

    assert client.delete(f"/api/groups/{made['id']}", headers=as_gym(sur)).status_code == 204
    assert len(get(client, sur, charge["id"])["people"]) == 2


def test_a_group_takes_only_people_in_the_gym(client: TestClient, sur: uuid.UUID) -> None:
    response = client.post(
        "/api/groups", json={"name": "X", "person_ids": [str(uuid.uuid4())]}, headers=as_gym(sur)
    )
    assert response.status_code == 422


# --- amounts ----------------------------------------------------------------------


def test_a_split_previews_its_share_remainder_and_overrides(
    client: TestClient, sur: uuid.UUID
) -> None:
    names = ["Ana", "Bea", "Carla", "Dani", "Eva", "Fran", "Gabi"]
    people = [add_person(client, sur, n) for n in names]
    body = {
        "target": {"kind": "people", "person_ids": people},
        "amount_mode": "split",
        "amount_clp": 100_003,
        "overrides": [{"person_id": people[6], "amount_clp": 0}],
    }

    preview = ok(client.post("/api/extra-charges/preview", json=body, headers=as_gym(sur)))

    assert (preview["share_clp"], preview["remainder_clp"]) == (14_286, 1)
    amounts = {line["person"]["name"]: line["amount_clp"] for line in preview["lines"]}
    assert amounts == {
        "Ana": 14_287,
        "Bea": 14_286,
        "Carla": 14_286,
        "Dani": 14_286,
        "Eva": 14_286,
        "Fran": 14_286,
        "Gabi": 0,
    }
    assert preview["total_clp"] == 100_003 - 14_286
    assert [line["overridden"] for line in preview["lines"]].count(True) == 1


def test_a_split_too_small_or_an_empty_target_is_refused(
    client: TestClient, sur: uuid.UUID
) -> None:
    ana, bea = add_person(client, sur, "Ana"), add_person(client, sur, "Bea")
    small = {"target": {"kind": "people", "person_ids": [ana, bea]}, "amount_mode": "split"}
    response = client.post(
        "/api/extra-charges/preview", json={**small, "amount_clp": 1}, headers=as_gym(sur)
    )
    assert response.status_code == 422
    empty = ok(
        client.post("/api/groups", json={"name": "Vacío", "person_ids": []}, headers=as_gym(sur)),
        201,
    )
    nobody = {
        "target": {"kind": "group", "group_id": empty["id"]},
        "amount_mode": "fixed",
        "amount_clp": 1,
    }
    response = client.post("/api/extra-charges/preview", json=nobody, headers=as_gym(sur))
    assert response.status_code == 422


def test_the_target_is_everyone_active_or_a_program(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana, bea = add_person(client, sur, "Ana"), add_person(client, sur, "Bea")
    add_person(client, sur, "Carla")  # no membership
    bill(db, sur, ana, [])
    bill(db, sur, bea, [])
    body = {"target": {"kind": "active"}, "amount_mode": "fixed", "amount_clp": 5000}
    preview = ok(client.post("/api/extra-charges/preview", json=body, headers=as_gym(sur)))
    # The seeded owner holds an active membership too.
    assert {"Ana", "Bea"} <= {line["person"]["name"] for line in preview["lines"]}
    assert "Carla" not in {line["person"]["name"] for line in preview["lines"]}

    program = run(
        db.owner_url,
        in_gym(
            sur,
            "WITH p AS (INSERT INTO program (gym_id, name) VALUES ($1, 'Kids') RETURNING id)"
            " UPDATE plan SET program_id = (SELECT id FROM p) WHERE gym_id = $1"
            " RETURNING program_id",
            sur,
        ),
    )[0]["program_id"]
    body["target"] = {"kind": "program", "program_id": str(program)}
    charge = create(client, sur, {**draft([]), **body})
    assert charge["target_label"] == "Kids"


# --- notice -----------------------------------------------------------------------


def test_each_person_is_emailed_their_own_amount_and_a_guardian_for_a_kid(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, sur, "Ana")
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    mailer.sent.clear()

    charge = create(
        client,
        sur,
        draft(
            [ana, juan],
            amount_mode="split",
            amount_clp=30_001,
            category="gasto_compartido",
            title="Bencina final",
        ),
    )

    assert {line["person"]["name"]: line["amount_due_clp"] for line in charge["people"]} == {
        "Ana": 15_001,
        "Juan": 15_000,
    }
    to = {email.to: email for email in mailer.sent}
    assert set(to) == {"ana@example.cl", "marta@example.cl"}
    assert "$15.001" in to["ana@example.cl"].text
    assert "Cada uno vende diez números." in to["ana@example.cl"].text
    assert "A Juan le corresponde pagar $15.000" in to["marta@example.cl"].text
    assert "/api/auth/callback?token=" in to["marta@example.cl"].text
    assert to["ana@example.cl"].subject.startswith("Bencina final en")

    # Without notify, nobody hears of it.
    mailer.sent.clear()
    create(client, sur, draft([ana], notify=False))
    assert mailer.sent == []


def test_someone_with_no_email_is_listed_with_a_whatsapp_link(
    client: TestClient, sur: uuid.UUID
) -> None:
    person = ok(
        client.post(
            "/api/people",
            json={
                "name": "Pedro",
                "rut": None,
                "email": "pedro@example.cl",
                "phone": "+56987654321",
            },
            headers=as_gym(sur),
        ),
        201,
    )["id"]
    ok(
        client.patch(
            f"/api/people/{person}", json={"email": None, "rut": "11111111-1"}, headers=as_gym(sur)
        )
    )
    body = {**draft([person]), "notify": True}
    preview = ok(client.post("/api/extra-charges/preview", json=body, headers=as_gym(sur)))
    [line] = preview["lines"]
    assert line["has_email"] is False
    assert line["whatsapp_url"].startswith("https://wa.me/56987654321?text=")


def test_remind_emails_only_who_still_owes_with_no_proof_waiting(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana, bea, carla = (add_person(client, sur, n) for n in ("Ana", "Bea", "Carla"))
    charge = create(client, sur, draft([ana, bea, carla], notify=False))
    pay = line_of(charge, bea)["id"]
    ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{pay}/payments",
            json={"amount_clp": 10000, "method": "cash"},
            headers=as_gym(sur),
        ),
        201,
    )
    claim_line(client, sur, carla, line_of(charge, carla)["id"])
    mailer.sent.clear()

    reminded = ok(client.post(f"/api/extra-charges/{charge['id']}/remind", headers=as_gym(sur)))

    assert reminded == {"sent": 1, "without_email": 0}
    [email] = mailer.sent
    assert email.to == "ana@example.cl"
    assert email.subject.startswith("Recordatorio:")


# --- money ------------------------------------------------------------------------


def claim_line(
    client: TestClient, gym: uuid.UUID, person: str, line: str, amount: int = 10000
) -> Any:
    key = upload(client, gym, person)
    return ok(
        client.post(
            "/api/me/payments",
            json={"extra_line_id": line, "amount_clp": amount, "proof_key": key},
            headers=as_gym(gym, uuid.UUID(person)),
        ),
        201,
    )


def test_a_line_is_paid_by_proof_validated_partly_and_refunded(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], amount_clp=25_000, category="seminario"))
    line = line_of(charge, ana)["id"]

    [mine] = ok(client.get("/api/me/extra-lines", headers=as_gym(sur, uuid.UUID(ana))))
    assert (mine["title"], mine["outstanding_clp"], mine["status"]) == (
        "Rifa de fin de año",
        25_000,
        "open",
    )
    page = ok(client.get("/api/me/page", headers=as_gym(sur, uuid.UUID(ana))))
    assert [x["id"] for x in page["extra_charges"]] == [line]
    assert page["next_payment"] is None

    mailer.sent.clear()
    entry = claim_line(client, sur, ana, line, 10_000)
    assert (entry["extra_line_id"], entry["membership_id"]) == (line, None)
    assert mailer.sent[0].subject == "Recibimos tu comprobante"
    assert "por Rifa de fin de año" in mailer.sent[0].text
    assert line_of(get(client, sur, charge["id"]), ana)["status"] == "in_review"

    # Validar comprobante shows it beside the plans' proofs.
    queue = ok(client.get("/api/ledger/proofs", headers=as_gym(sur)))
    [review] = [r for r in queue if r["id"] == entry["id"]]
    assert review["period"] is None
    assert review["extra_line"]["title"] == "Rifa de fin de año"
    assert review["extra_line"]["outstanding_clp"] == 25_000
    assert ok(client.get("/api/ledger/pending", headers=as_gym(sur)))["count"] == 1

    mailer.sent.clear()
    validated = ok(client.post(f"/api/ledger/proofs/{entry['id']}/validate", headers=as_gym(sur)))
    assert validated["period"] == {
        "id": line,
        "amount_due_clp": 25_000,
        "paid_clp": 10_000,
        "outstanding_clp": 15_000,
        "closed": False,
    }
    assert "De este cobro quedan $15.000 por pagar." in mailer.sent[0].text

    # Partial: still owed, and the rest is recorded by the admin.
    after = line_of(get(client, sur, charge["id"]), ana)
    assert (after["status"], after["paid_clp"]) == ("open", 10_000)
    paid = ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/payments",
            json={"amount_clp": 15_000, "method": "cash"},
            headers=as_gym(sur),
        ),
        201,
    )
    assert paid["period"]["closed"] is True
    summary = ok(client.get("/api/extra-charges", headers=as_gym(sur)))
    [mine_summary] = [c for c in summary if c["id"] == charge["id"]]
    assert (mine_summary["paid_lines"], mine_summary["lines"]) == (1, 1)
    assert (mine_summary["collected_clp"], mine_summary["due_clp"]) == (25_000, 25_000)
    assert ok(client.get("/api/me/extra-lines", headers=as_gym(sur, uuid.UUID(ana)))) == []

    # The book lists both payments, labelled by the cobro, and Cobrado counts them.
    book = ok(client.get("/api/ledger/book", headers=as_gym(sur)))
    extra = [item for item in book["items"] if item["extra"]]
    assert len(extra) == 2
    assert {(i["extra"]["category"], i["person"]["name"], i["period"]) for i in extra} == {
        ("seminario", "Ana", None)
    }
    assert book["kpis"]["collected_extra_clp"] == 25_000
    assert book["kpis"]["collected_clp"] >= 25_000
    me_payments = ok(client.get("/api/me/page", headers=as_gym(sur, uuid.UUID(ana))))["payments"]
    assert {p["charge_title"] for p in me_payments} == {"Rifa de fin de año"}

    # A refund gives part back, and the line is owed again.
    refund = ok(
        client.post(
            "/api/ledger/refunds",
            json={"payment_id": paid["payment"]["id"], "amount_clp": 5_000, "method": "transfer"},
            headers=as_gym(sur),
        ),
        201,
    )
    assert refund["period"]["outstanding_clp"] == 5_000
    reopened = line_of(get(client, sur, charge["id"]), ana)
    assert (reopened["status"], reopened["outstanding_clp"]) == ("open", 5_000)
    assert [p["refundable_clp"] for p in reopened["refundable_payments"]] == [10_000, 10_000]
    too_much = client.post(
        "/api/ledger/refunds",
        json={"payment_id": paid["payment"]["id"], "amount_clp": 10_001, "method": "transfer"},
        headers=as_gym(sur),
    )
    assert too_much.status_code == 409


def test_a_rejected_proof_leaves_the_line_owed(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    entry = claim_line(client, sur, ana, line_of(charge, ana)["id"])
    mailer.sent.clear()

    ok(
        client.post(
            f"/api/ledger/proofs/{entry['id']}/reject",
            json={"note": "No se ve el monto"},
            headers=as_gym(sur),
        )
    )

    assert line_of(get(client, sur, charge["id"]), ana)["status"] == "open"
    [email] = mailer.sent
    assert "por Rifa de fin de año" in email.text
    assert "No se ve el monto" in email.text


def test_a_line_adjusts_and_a_paid_line_takes_no_more(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    base = f"/api/extra-charges/{charge['id']}/lines/{line_of(charge, ana)['id']}"
    adjusted = ok(
        client.post(
            f"{base}/adjustments",
            json={"amount_clp": 4_000, "note": "Vendió menos"},
            headers=as_gym(sur),
        ),
        201,
    )
    assert adjusted["period"]["outstanding_clp"] == 6_000
    ok(
        client.post(
            f"{base}/payments", json={"amount_clp": 6_000, "method": "cash"}, headers=as_gym(sur)
        ),
        201,
    )
    again = client.post(
        f"{base}/payments", json={"amount_clp": 1, "method": "cash"}, headers=as_gym(sur)
    )
    assert again.status_code == 409


def test_membership_status_is_never_affected(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 30000, 0)])
    # Long past due and unpaid.
    create(client, sur, draft([ana], due_date=str(seeded_today() - timedelta(days=60))))

    overdue = ok(client.get("/api/ledger/overdue", headers=as_gym(sur)))
    assert ana not in {p["person_id"] for p in overdue["periods"]}
    ledger = ok(client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(sur)))
    assert ledger["owed_clp"] == 0
    rows = run(
        db.admin_url, lambda c: c.fetch("SELECT * FROM v_balance WHERE membership_id IS NULL")
    )
    assert rows == []
    status = run(
        db.admin_url,
        lambda c: c.fetchval("SELECT status FROM membership WHERE id = $1", uuid.UUID(membership)),
    )
    assert status == "active"


# --- changing lines ---------------------------------------------------------------


def test_an_override_and_a_resplit_when_someone_leaves_before_anyone_paid(
    client: TestClient, sur: uuid.UUID
) -> None:
    ana, bea, carla = (add_person(client, sur, n) for n in ("Ana", "Bea", "Carla"))
    charge = create(
        client, sur, draft([ana, bea, carla], amount_mode="split", amount_clp=90_000, notify=False)
    )
    cid = charge["id"]
    carlas = line_of(charge, carla)["id"]
    changed = ok(
        client.patch(
            f"/api/extra-charges/{cid}/lines/{line_of(charge, ana)['id']}",
            json={"amount_clp": 0},
            headers=as_gym(sur),
        )
    )
    assert (changed["amount_due_clp"], changed["overridden"], changed["status"]) == (
        0,
        True,
        "waived",
    )

    preview = ok(client.get(f"/api/extra-charges/{cid}/lines/{carlas}/cancel", headers=as_gym(sur)))
    assert preview["resplit_allowed"] is True
    assert preview["amounts"] == {line_of(charge, ana)["id"]: 0, line_of(charge, bea)["id"]: 45_000}

    after = ok(
        client.post(
            f"/api/extra-charges/{cid}/lines/{carlas}/cancel",
            json={"resplit": True},
            headers=as_gym(sur),
        )
    )
    assert {
        line["person"]["name"]: (line["amount_due_clp"], line["status"]) for line in after["people"]
    } == {
        "Ana": (0, "waived"),
        "Bea": (45_000, "open"),
        "Carla": (30_000, "cancelled"),
    }
    # Exenta, Ana is not counted among who pays: "0 de 1 pagaron".
    assert (after["lines"], after["paid_lines"], after["waived_lines"]) == (1, 0, 1)
    assert after["due_clp"] == 45_000
    # Cancelled: it takes no money.
    paid = client.post(
        f"/api/extra-charges/{cid}/lines/{carlas}/payments",
        json={"amount_clp": 1, "method": "cash"},
        headers=as_gym(sur),
    )
    assert paid.status_code == 409


def test_no_resplit_once_someone_paid_and_no_cancel_with_money_on_the_line(
    client: TestClient, sur: uuid.UUID
) -> None:
    ana, bea, carla = (add_person(client, sur, n) for n in ("Ana", "Bea", "Carla"))
    charge = create(
        client, sur, draft([ana, bea, carla], amount_mode="split", amount_clp=90_000, notify=False)
    )
    cid = charge["id"]
    ok(
        client.post(
            f"/api/extra-charges/{cid}/lines/{line_of(charge, ana)['id']}/payments",
            json={"amount_clp": 30_000, "method": "cash"},
            headers=as_gym(sur),
        ),
        201,
    )
    carlas = line_of(charge, carla)["id"]
    preview = ok(client.get(f"/api/extra-charges/{cid}/lines/{carlas}/cancel", headers=as_gym(sur)))
    assert preview == {"resplit_allowed": False, "amounts": {}}
    refused = client.post(
        f"/api/extra-charges/{cid}/lines/{carlas}/cancel",
        json={"resplit": True},
        headers=as_gym(sur),
    )
    assert refused.status_code == 409
    ok(client.post(f"/api/extra-charges/{cid}/lines/{carlas}/cancel", json={}, headers=as_gym(sur)))
    with_money = client.post(
        f"/api/extra-charges/{cid}/lines/{line_of(charge, ana)['id']}/cancel",
        json={},
        headers=as_gym(sur),
    )
    assert with_money.status_code == 409
    below_paid = client.patch(
        f"/api/extra-charges/{cid}/lines/{line_of(charge, ana)['id']}",
        json={"amount_clp": 29_999},
        headers=as_gym(sur),
    )
    assert below_paid.status_code == 409


def test_the_ficha_lists_a_persons_cobros_still_owed(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    [line] = ok(client.get(f"/api/people/{ana}/extra-lines", headers=as_gym(sur)))
    assert (line["extra_charge_id"], line["outstanding_clp"]) == (charge["id"], 10_000)


# --- roles and RLS ----------------------------------------------------------------


def test_a_coach_reads_no_cobros_or_amounts(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    line = line_of(charge, ana)["id"]
    coach = add_staff(db, sur, "coach")
    as_coach = as_gym(sur, coach)

    body = draft([ana])
    amounts = {k: body[k] for k in ("target", "amount_mode", "amount_clp")}
    for method, path, json in [
        ("get", "/api/extra-charges", None),
        ("get", f"/api/extra-charges/{charge['id']}", None),
        ("post", "/api/extra-charges/preview", amounts),
        ("post", "/api/extra-charges", body),
        ("post", f"/api/extra-charges/{charge['id']}/remind", None),
        ("get", f"/api/people/{ana}/extra-lines", None),
        ("patch", f"/api/extra-charges/{charge['id']}/lines/{line}", {"amount_clp": 1}),
    ]:
        response = client.request(method, path, json=json, headers=as_coach)
        assert response.status_code == 403, path

    # And at the database: no cobro, line or line entry reaches them.
    for table in ("extra_charge", "extra_line", "ledger_entry WHERE extra_line_id IS NOT NULL"):
        rows = run(db.api_url, in_gym(sur, f"SELECT * FROM {table}", person=coach))
        assert rows == [], table


def test_a_member_reads_their_own_lines_and_their_dependents_only(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    create(client, sur, draft([ana, juan], notify=False))

    martas = ok(client.get("/api/me/extra-lines", headers=as_gym(sur, uuid.UUID(marta))))
    assert [x["person_name"] for x in martas] == ["Juan"]
    rows = run(db.api_url, in_gym(sur, "SELECT person_id FROM extra_line", person=uuid.UUID(marta)))
    assert [r["person_id"] for r in rows] == [uuid.UUID(juan)]
    charges = run(
        db.api_url, in_gym(sur, "SELECT title FROM extra_charge", person=uuid.UUID(marta))
    )
    assert [r["title"] for r in charges] == ["Rifa de fin de año"]

    # Nobody claims someone else's line, at the API or the database.
    anas = next(
        x for x in ok(client.get("/api/me/extra-lines", headers=as_gym(sur, uuid.UUID(ana))))
    )
    key = upload(client, sur, marta)
    response = client.post(
        "/api/me/payments",
        json={"extra_line_id": anas["id"], "amount_clp": 1, "proof_key": key},
        headers=as_gym(sur, uuid.UUID(marta)),
    )
    assert response.status_code == 404


def test_a_person_with_a_line_is_kept_by_forget(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    create(client, sur, draft([ana], notify=False))
    refusal = ok(client.get(f"/api/people/{ana}/deletion", headers=as_gym(sur)))
    assert refusal == {"refused": "ledger"}


def test_forget_takes_someone_out_of_every_group(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    group = ok(
        client.post("/api/groups", json={"name": "G", "person_ids": [ana]}, headers=as_gym(sur)),
        201,
    )
    assert client.delete(f"/api/people/{ana}", headers=as_gym(sur)).status_code == 204
    assert ok(client.get(f"/api/groups/{group['id']}", headers=as_gym(sur)))["members"] == []


def test_someone_let_off_at_nothing_is_not_emailed(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana, bea = add_person(client, sur, "Ana"), add_person(client, sur, "Bea")
    mailer.sent.clear()

    create(client, sur, draft([ana, bea], overrides=[{"person_id": bea, "amount_clp": 0}]))

    assert [email.to for email in mailer.sent] == ["ana@example.cl"]


# --- review fixes -----------------------------------------------------------------


def test_an_adjusted_line_with_no_money_cancels_and_resplits(
    client: TestClient, sur: uuid.UUID
) -> None:
    ana, bea, carla = (add_person(client, sur, n) for n in ("Ana", "Bea", "Carla"))
    charge = create(
        client, sur, draft([ana, bea, carla], amount_mode="split", amount_clp=90_000, notify=False)
    )
    cid, carlas = charge["id"], line_of(charge, carla)["id"]
    ok(
        client.post(
            f"/api/extra-charges/{cid}/lines/{carlas}/adjustments",
            json={"amount_clp": 5_000, "note": "Trajo la bencina"},
            headers=as_gym(sur),
        ),
        201,
    )

    preview = ok(client.get(f"/api/extra-charges/{cid}/lines/{carlas}/cancel", headers=as_gym(sur)))
    assert preview["resplit_allowed"] is True
    after = ok(
        client.post(
            f"/api/extra-charges/{cid}/lines/{carlas}/cancel",
            json={"resplit": True},
            headers=as_gym(sur),
        )
    )
    assert line_of(after, carla)["status"] == "cancelled"
    assert line_of(after, bea)["amount_due_clp"] == 45_000


def test_a_refunded_payment_still_blocks_a_resplit(client: TestClient, sur: uuid.UUID) -> None:
    ana, bea = add_person(client, sur, "Ana"), add_person(client, sur, "Bea")
    charge = create(
        client, sur, draft([ana, bea], amount_mode="split", amount_clp=20_000, notify=False)
    )
    cid, anas = charge["id"], line_of(charge, ana)["id"]
    paid = ok(
        client.post(
            f"/api/extra-charges/{cid}/lines/{anas}/payments",
            json={"amount_clp": 10_000, "method": "cash"},
            headers=as_gym(sur),
        ),
        201,
    )
    ok(
        client.post(
            "/api/ledger/refunds",
            json={"payment_id": paid["payment"]["id"], "amount_clp": 10_000, "method": "cash"},
            headers=as_gym(sur),
        ),
        201,
    )
    # Refunded in full, the line holds no money and may be cancelled, but money moved
    # through the cobro, so its total is not divided again.
    preview = ok(client.get(f"/api/extra-charges/{cid}/lines/{anas}/cancel", headers=as_gym(sur)))
    assert preview["resplit_allowed"] is False
    ok(client.post(f"/api/extra-charges/{cid}/lines/{anas}/cancel", json={}, headers=as_gym(sur)))


def test_a_resplit_breaks_a_tie_in_names_as_create_did(client: TestClient, sur: uuid.UUID) -> None:
    first = add_person(client, sur, "Ana Soto")
    second = ok(
        client.post(
            "/api/people",
            json={"name": "Ana Soto", "email": "ana.soto.2@example.cl", "rut": random_rut()},
            headers=as_gym(sur),
        ),
        201,
    )["id"]
    bea = add_person(client, sur, "Bea")
    charge = create(
        client,
        sur,
        draft([first, second, bea], amount_mode="split", amount_clp=100_001, notify=False),
    )
    # 100.001 among three: two get the extra peso, the Anas, by person id.
    created = {line["person"]["id"]: line["amount_due_clp"] for line in charge["people"]}
    assert created[bea] == 33_333
    after = ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line_of(charge, bea)['id']}/cancel",
            json={"resplit": True},
            headers=as_gym(sur),
        )
    )
    # 100.001 between the two: the extra peso goes to the lower person id.
    lower = min(first, second)
    shares = {line["person"]["id"]: line["amount_due_clp"] for line in after["people"]}
    assert (shares[lower], shares[max(first, second)]) == (50_001, 50_000)


def test_a_hand_picked_leaver_is_not_charged(client: TestClient, sur: uuid.UUID) -> None:
    ana, bea = add_person(client, sur, "Ana"), add_person(client, sur, "Bea")
    ok(client.post(f"/api/people/{bea}/leave", json={}, headers=as_gym(sur)))
    response = client.post("/api/extra-charges", json=draft([ana, bea]), headers=as_gym(sur))
    assert response.status_code == 422


def test_notices_read_no_contact_per_line(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.extra_charges as module

    async def no_lookup(*_: Any) -> None:
        raise AssertionError("one contact query per line")

    monkeypatch.setattr(module, "contact_for", no_lookup)
    people = [add_person(client, sur, f"P{i}") for i in range(5)]
    mailer.sent.clear()
    charge = create(client, sur, draft(people))
    assert len(mailer.sent) == 5
    reminded = ok(client.post(f"/api/extra-charges/{charge['id']}/remind", headers=as_gym(sur)))
    assert reminded == {"sent": 5, "without_email": 0}
    line = charge["people"][0]["id"]
    one = ok(
        client.post(f"/api/extra-charges/{charge['id']}/lines/{line}/notify", headers=as_gym(sur))
    )
    assert one == {"sent": 1, "without_email": 0}


def test_only_an_owner_or_admin_writes_groups_at_the_database(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    group = ok(
        client.post("/api/groups", json={"name": "G", "person_ids": [ana]}, headers=as_gym(sur)),
        201,
    )
    coach = add_staff(db, sur, "coach")
    # Read, for rosters.
    rows = run(db.api_url, in_gym(sur, "SELECT name FROM charge_group", person=coach))
    assert [r["name"] for r in rows] == ["G"]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                sur,
                "INSERT INTO charge_group (gym_id, name) VALUES ($1, 'X')",
                sur,
                person=coach,
            ),
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                sur,
                "INSERT INTO charge_group_member (gym_id, group_id, person_id) VALUES ($1, $2, $3)",
                sur,
                uuid.UUID(group["id"]),
                coach,
                person=coach,
            ),
        )
    for sql in (
        "DELETE FROM charge_group_member RETURNING person_id",
        "UPDATE charge_group SET name = 'Y' RETURNING id",
        "DELETE FROM charge_group RETURNING id",
    ):
        assert run(db.api_url, in_gym(sur, sql, person=coach)) == [], sql
    assert ok(client.get(f"/api/groups/{group['id']}", headers=as_gym(sur)))["name"] == "G"


def test_the_ficha_answers_404_for_someone_not_in_the_gym(
    client: TestClient, sur: uuid.UUID
) -> None:
    response = client.get(f"/api/people/{uuid.uuid4()}/extra-lines", headers=as_gym(sur))
    assert response.status_code == 404


def test_a_claim_on_a_cancelled_line_is_refused_at_the_database(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    line = line_of(charge, ana)["id"]
    ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/cancel", json={}, headers=as_gym(sur)
        )
    )
    with pytest.raises(asyncpg.CheckViolationError, match="is cancelled"):
        run(db.api_url, in_gym(sur, claim_sql(sur, ana), uuid.UUID(line), person=uuid.UUID(ana)))


def claim_sql(gym: uuid.UUID, person: str) -> str:
    """A student's claim on the line `$1`, as `app.api.proofs` writes it."""
    key = f"proofs/{gym}/{person}/{uuid.uuid4()}"
    return (
        "INSERT INTO ledger_entry (gym_id, extra_line_id, amount_clp, kind, status, method,"
        " claimed_by, claimed_at, proof_object_key)"
        f" VALUES ('{gym}', $1, 1000, 'payment', 'pending', 'transfer', '{person}', now(), '{key}')"
    )


def test_a_claim_waits_for_a_cancel_holding_the_cobro_and_is_refused(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    """The race: an admin cancels the line while the student's claim lands. The claim
    waits on the cobro's lock and, once the cancel commits, is refused, so a cancelled
    line never ends up with a proof waiting on it."""
    ana = add_person(client, sur, "Ana")
    charge = create(client, sur, draft([ana], notify=False))
    line = uuid.UUID(line_of(charge, ana)["id"])
    owner = seeded_owner(sur)

    async def race() -> None:
        admin = await asyncpg.connect(to_dsn(db.api_url))
        student = await asyncpg.connect(to_dsn(db.api_url))
        try:
            cancel = admin.transaction()
            await cancel.start()
            await admin.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await admin.execute("SELECT set_config('app.person_id', $1, true)", str(owner))
            await admin.execute(
                "SELECT FROM extra_charge WHERE id = $1 FOR UPDATE", uuid.UUID(charge["id"])
            )
            await admin.execute("UPDATE extra_line SET cancelled_at = now() WHERE id = $1", line)

            async def claim() -> None:
                async with student.transaction():
                    await student.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
                    await student.execute("SELECT set_config('app.person_id', $1, true)", ana)
                    await student.execute(claim_sql(sur, ana), line)

            claiming = asyncio.create_task(claim())
            await asyncio.sleep(0.5)
            assert not claiming.done(), "the claim did not wait for the cobro's lock"
            await cancel.commit()
            with pytest.raises(asyncpg.CheckViolationError, match="is cancelled"):
                await claiming
        finally:
            await admin.close()
            await student.close()

    asyncio.run(race())
    held = run(
        db.admin_url,
        lambda c: c.fetchval("SELECT count(*) FROM ledger_entry WHERE extra_line_id = $1", line),
    )
    assert held == 0
