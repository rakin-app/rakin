"""Gastos: what the gym spends, apart from billing, with receipts and corrections (#314).

An expense is recorded under one of the gym's categories, edited with an
`expense_changed` row and voided with an `expense_voided` one, never deleted. Holders of
`expenses_read` read them and `expenses_write` write them, at the API and at the
database, and an Administrador holds neither. Nothing in billing reads them: every
reader of money, the billing job and a member's balance are the same with and without.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import add_months
from app.jobs import billing
from app.main import create_app
from app.permissions import Permission
from app.schemas.expenses import MAX_CATEGORIES
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
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
from tests.test_history_payments import readers
from tests.test_member_roll import enrolled, memberships, plan
from tests.test_plans import add_staff

pg = pytest.mark.postgres

PDF = b"%PDF-1.7\n" + b"0" * 100

DEFAULTS = [
    "Arriendo",
    "Luz",
    "Agua",
    "Gas",
    "Internet y teléfono",
    "Federación",
    "Seguros",
    "Sueldos y honorarios",
    "Equipamiento",
    "Eventos y competencias",
    "Mantención y aseo",
    "Otros",
]


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("gym"))


def holding(db: Database, gym: uuid.UUID, *permissions: Permission) -> uuid.UUID:
    """Someone on the team holding, from today, a role of the gym's with `permissions`."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'Tesorera')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Tesorera')",
                gym,
                person,
            )
            await make_staff(conn, gym, person, "coach")
            await conn.execute("DELETE FROM staff_title WHERE person_id = $1", person)
            title = await conn.fetchval(
                "INSERT INTO gym_title (gym_id, name, permissions) VALUES ($1, $2, $3)"
                " RETURNING id",
                gym,
                f"Cargo {person}",
                sorted(permissions),
            )
            await conn.execute(
                "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
                " VALUES ($1, $2, $3, 'Cargo', $4)",
                gym,
                person,
                title,
                seeded_today(),
            )

    run(db.admin_url, query)
    return person


def categories(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> Any:
    response = client.get("/api/expenses/categories", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def category(client: TestClient, gym: uuid.UUID, name: str) -> str:
    [found] = [c["id"] for c in categories(client, gym) if c["name"] == name]
    return str(found)


def expense(client: TestClient, gym: uuid.UUID, **fields: Any) -> dict[str, Any]:
    """The form's fields: a rent paid today unless told otherwise."""
    return {
        "spent_on": seeded_today().isoformat(),
        "amount_clp": 650_000,
        "category_id": category(client, gym, "Arriendo"),
        "payee": "Inmobiliaria Los Robles",
        "method": "transfer",
        **fields,
    }


def record(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None, **fields: Any) -> Any:
    return client.post(
        "/api/expenses", json=expense(client, gym, **fields), headers=as_gym(gym, by)
    )


def recorded(client: TestClient, gym: uuid.UUID, **fields: Any) -> dict[str, Any]:
    response = record(client, gym, **fields)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def month(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None, **query: Any) -> Any:
    return client.get("/api/expenses", params=query, headers=as_gym(gym, by))


def change(client: TestClient, gym: uuid.UUID, expense_id: str, **fields: Any) -> Any:
    return client.patch(f"/api/expenses/{expense_id}", json=fields, headers=as_gym(gym))


def void(client: TestClient, gym: uuid.UUID, expense_id: str, reason: str = "duplicado") -> Any:
    return client.post(
        f"/api/expenses/{expense_id}/void", json={"reason": reason}, headers=as_gym(gym)
    )


def log(db: Database, gym: uuid.UUID) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT action, actor_id, person_id, reason, detail FROM audit_event"
            " WHERE starts_with(action, 'expense_') ORDER BY at, id",
        ),
    )
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


def upload(client: TestClient, gym: uuid.UUID, body: bytes = PDF) -> str:
    """Ask for a receipt's upload URL and PUT `body` there, as the browser does."""
    ticket = client.post(
        "/api/expenses/receipt-upload",
        json={"content_type": "application/pdf", "size_bytes": len(body)},
        headers=as_gym(gym),
    )
    assert ticket.status_code == 201, ticket.text
    put = client.put(ticket.json()["url"], content=body, headers=ticket.json()["headers"])
    assert put.status_code == 200, put.text
    key: str = ticket.json()["key"]
    return key


# --- categories ----------------------------------------------------------------------


@pg
def test_a_new_gym_starts_with_the_default_categories(client: TestClient, gym: uuid.UUID) -> None:
    listed = categories(client, gym)
    assert [c["name"] for c in listed] == DEFAULTS
    assert [c["name"] for c in listed if c["is_other"]] == ["Otros"]
    assert {(c["archived"], c["expenses"]) for c in listed} == {(False, 0)}


@pg
def test_categories_are_renamed_added_reordered_and_archived(
    client: TestClient, gym: uuid.UUID
) -> None:
    headers = as_gym(gym)
    luz = category(client, gym, "Luz")
    renamed = client.patch(
        f"/api/expenses/categories/{luz}", json={"name": " Electricidad "}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    assert "Electricidad" in [c["name"] for c in renamed.json()]

    added = client.post("/api/expenses/categories", json={"name": "Publicidad"}, headers=headers)
    assert added.status_code == 201, added.text
    assert added.json()[len(DEFAULTS)]["name"] == "Publicidad"
    taken = client.post("/api/expenses/categories", json={"name": "arriendo"}, headers=headers)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "name_taken"

    ids = [c["id"] for c in added.json()]
    reordered = client.post(
        "/api/expenses/categories/order", json={"ids": ids[::-1]}, headers=headers
    )
    assert reordered.status_code == 200, reordered.text
    assert [c["id"] for c in reordered.json()] == ids[::-1]
    partial = client.post("/api/expenses/categories/order", json={"ids": ids[1:]}, headers=headers)
    assert partial.status_code == 422

    # A category with an expense is archived, kept on that expense and off the form.
    gas = category(client, gym, "Gas")
    rent = recorded(client, gym, category_id=gas, amount_clp=20_000)
    archived = client.post(f"/api/expenses/categories/{gas}/archive", headers=headers)
    assert archived.status_code == 200, archived.text
    last = archived.json()[-1]
    assert (last["name"], last["archived"], last["expenses"]) == ("Gas", True, 1)
    assert month(client, gym).json()["items"][0]["category_name"] == "Gas"
    refused = record(client, gym, category_id=gas)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "category_archived"
    # An expense already under it keeps it through an edit of anything else.
    assert change(client, gym, rent["id"], amount_clp=21_000).status_code == 200

    # A new one may take an archived one's name; then the old cannot come back.
    assert (
        client.post("/api/expenses/categories", json={"name": "Gas"}, headers=headers).status_code
        == 201
    )
    restored = client.post(f"/api/expenses/categories/{gas}/restore", headers=headers)
    assert restored.status_code == 409

    otros = category(client, gym, "Otros")
    kept = client.post(f"/api/expenses/categories/{otros}/archive", headers=headers)
    assert kept.status_code == 409 and kept.json()["detail"]["code"] == "other_kept"
    nobody = client.post(f"/api/expenses/categories/{uuid.uuid4()}/archive", headers=headers)
    assert nobody.status_code == 404


@pg
def test_otros_is_kept_at_the_database_too(db: Database, gym: uuid.UUID) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.owner_url,
            in_gym(gym, "UPDATE expense_category SET archived_at = now() WHERE is_other"),
        )


# --- recording -----------------------------------------------------------------------


@pg
def test_a_month_lists_its_expenses_newest_first_with_their_total(
    client: TestClient, gym: uuid.UUID
) -> None:
    today = seeded_today()
    this_month = today.replace(day=1)
    first = recorded(client, gym, spent_on=this_month.isoformat(), amount_clp=650_000)
    luz = category(client, gym, "Luz")
    second = recorded(
        client, gym, spent_on=today.isoformat(), amount_clp=84_000, category_id=luz, payee="Enel"
    )
    last_month = add_months(this_month, -1)
    recorded(client, gym, spent_on=last_month.isoformat(), amount_clp=600_000)

    shown = month(client, gym).json()
    assert shown["month"] == shown["current_month"] == this_month.isoformat()
    assert [e["id"] for e in shown["items"]] == [second["id"], first["id"]]
    assert (shown["total_clp"], shown["count"]) == (734_000, 2)
    assert second["category_name"] == "Luz" and second["created_by_name"].startswith("owner of")
    assert second["has_receipt"] is False and second["voided_at"] is None

    earlier = month(client, gym, month=last_month.isoformat()).json()
    assert (earlier["total_clp"], earlier["count"]) == (600_000, 1)
    of_luz = month(client, gym, category=luz).json()
    assert [e["id"] for e in of_luz["items"]] == [second["id"]]
    assert of_luz["total_clp"] == 84_000

    assert month(client, gym, month=add_months(this_month, 1).isoformat()).status_code == 422
    assert month(client, gym, month=this_month.replace(day=2).isoformat()).status_code == 422


@pg
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"amount_clp": 0}, None),
        ({"amount_clp": -5}, None),
        ({"spent_on": "2999-01-01"}, "future"),
        ({"category_id": str(uuid.uuid4())}, "no_category"),
        ({"method": "cheque"}, None),
        ({"payee": "   "}, None),
    ],
    ids=["zero", "negative", "future", "unknown-category", "unknown-method", "blank-payee"],
)
def test_a_bad_expense_is_refused(
    client: TestClient, gym: uuid.UUID, fields: dict[str, Any], code: str | None
) -> None:
    response = record(client, gym, **fields)
    assert response.status_code == 422, response.text
    if code is not None:
        assert response.json()["detail"]["code"] == code
    assert month(client, gym).json()["items"] == []


@pg
def test_an_expense_from_another_gym_is_not_found(client: TestClient, db: Database) -> None:
    sur, norte = seed_gym(db, unique_slug("sur")), seed_gym(db, unique_slug("norte"))
    rent = recorded(client, sur)
    assert change(client, norte, rent["id"], amount_clp=1).status_code == 404
    assert void(client, norte, rent["id"]).status_code == 404
    other = record(client, norte, category_id=category(client, sur, "Luz"))
    assert other.status_code == 422 and other.json()["detail"]["code"] == "no_category"


# --- corrections ---------------------------------------------------------------------


@pg
def test_an_edit_writes_expense_changed_with_before_and_after(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rent = recorded(client, gym, note="noviembre")
    luz = category(client, gym, "Luz")
    edited = change(client, gym, rent["id"], amount_clp=640_000, category_id=luz, note=None)
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["amount_clp"], body["category_name"], body["note"]) == (640_000, "Luz", None)
    assert body["updated_at"] is not None

    [row] = log(db, gym)
    assert row["action"] == "expense_changed"
    assert (row["actor_id"], row["person_id"]) == (seeded_owner(gym), None)
    assert row["detail"] == {
        "expense_id": rent["id"],
        "before": {
            "amount_clp": 650_000,
            "category_id": rent["category_id"],
            "category_name": "Arriendo",
            "note": "noviembre",
        },
        "after": {
            "amount_clp": 640_000,
            "category_id": luz,
            "category_name": "Luz",
            "note": None,
        },
    }

    # An edit that changes nothing writes nothing.
    same = change(client, gym, rent["id"], amount_clp=640_000, payee=rent["payee"])
    assert same.status_code == 200
    assert len(log(db, gym)) == 1
    # An expense always has a day, an amount and a category.
    assert change(client, gym, rent["id"], amount_clp=None).status_code == 422


@pg
def test_a_void_keeps_the_expense_struck_through_and_out_of_the_total(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rent = recorded(client, gym)
    luz = recorded(client, gym, amount_clp=84_000, category_id=category(client, gym, "Luz"))
    assert void(client, gym, rent["id"], "  ").status_code == 422
    voided = void(client, gym, rent["id"], "pagado dos veces")
    assert voided.status_code == 200, voided.text
    assert voided.json()["void_reason"] == "pagado dos veces"
    assert voided.json()["voided_by_name"].startswith("owner of")

    shown = month(client, gym).json()
    assert {e["id"] for e in shown["items"]} == {rent["id"], luz["id"]}
    assert (shown["total_clp"], shown["count"]) == (84_000, 1)

    [row] = log(db, gym)
    assert (row["action"], row["reason"], row["person_id"]) == (
        "expense_voided",
        "pagado dos veces",
        None,
    )
    assert row["detail"] == {
        "expense_id": rent["id"],
        "spent_on": rent["spent_on"],
        "amount_clp": 650_000,
        "category_name": "Arriendo",
    }

    # Voided is final: no second void, no edit, at the API and the database.
    assert void(client, gym, rent["id"]).status_code == 409
    assert change(client, gym, rent["id"], amount_clp=1).json()["detail"]["code"] == "voided"
    with pytest.raises(asyncpg.RestrictViolationError):
        run(
            db.owner_url,
            in_gym(gym, "UPDATE expense SET amount_clp = 1 WHERE id = $1", uuid.UUID(rent["id"])),
        )


@pg
def test_nothing_deletes_an_expense(db: Database, client: TestClient, gym: uuid.UUID) -> None:
    rent = recorded(client, gym)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                gym,
                "DELETE FROM expense WHERE id = $1",
                uuid.UUID(rent["id"]),
                person=seeded_owner(gym),
            ),
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, "DELETE FROM expense_category", person=seeded_owner(gym)))


# --- receipts ------------------------------------------------------------------------


@pg
def test_a_receipt_is_claimed_once_and_downloaded_by_who_reads_expenses(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    key = upload(client, gym)
    assert key.startswith(f"receipts/{gym}/")
    rent = recorded(client, gym, receipt_key=key)
    assert rent["has_receipt"] is True
    taken = record(client, gym, receipt_key=key)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "receipt_taken"

    receipt = client.get(f"/api/expenses/{rent['id']}/receipt", headers=as_gym(gym))
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["content_type"] == "application/pdf"
    assert client.get(receipt.json()["url"]).content == PDF

    admin = add_staff(db, gym, "admin")
    refused = client.get(f"/api/expenses/{rent['id']}/receipt", headers=as_gym(gym, admin))
    assert refused.status_code == 403

    # An edit replaces it, or takes it off.
    other = upload(client, gym)
    replaced = change(client, gym, rent["id"], receipt_key=other)
    assert replaced.status_code == 200 and replaced.json()["has_receipt"] is True
    removed = change(client, gym, rent["id"], remove_receipt=True)
    assert removed.status_code == 200 and removed.json()["has_receipt"] is False
    gone = client.get(f"/api/expenses/{rent['id']}/receipt", headers=as_gym(gym))
    assert gone.status_code == 404
    [first, second] = log(db, gym)
    assert (first["detail"]["before"], first["detail"]["after"]) == (
        {"receipt_object_key": key},
        {"receipt_object_key": other},
    )
    assert second["detail"]["after"] == {"receipt_object_key": None}


@pg
def test_a_receipt_must_be_the_gyms_and_have_landed(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    never_put = f"receipts/{gym}/{uuid.uuid4()}"
    missing = record(client, gym, receipt_key=never_put)
    assert missing.json()["detail"]["code"] == "receipt_missing"
    elsewhere = seed_gym(db, unique_slug("otro"))
    theirs = upload(client, elsewhere)
    assert record(client, gym, receipt_key=theirs).json()["detail"]["code"] == "not_a_receipt"
    proof = f"proofs/{gym}/{seeded_owner(gym)}/{uuid.uuid4()}"
    assert record(client, gym, receipt_key=proof).json()["detail"]["code"] == "not_a_receipt"
    big = client.post(
        "/api/expenses/receipt-upload",
        json={"content_type": "application/pdf", "size_bytes": 10 * 1024 * 1024 + 1},
        headers=as_gym(gym),
    )
    assert big.status_code == 422
    svg = client.post(
        "/api/expenses/receipt-upload",
        json={"content_type": "image/svg+xml", "size_bytes": 100},
        headers=as_gym(gym),
    )
    assert svg.status_code == 422


# --- who reads them ------------------------------------------------------------------

READS = [
    ("GET", "/api/expenses"),
    ("GET", "/api/expenses/categories"),
    ("GET", "/api/expenses/{id}/receipt"),
]
WRITES = [
    ("POST", "/api/expenses/receipt-upload"),
    ("POST", "/api/expenses"),
    ("PATCH", "/api/expenses/{id}"),
    ("POST", "/api/expenses/{id}/void"),
    ("POST", "/api/expenses/categories"),
    ("POST", "/api/expenses/categories/order"),
]


def statuses(
    client: TestClient, gym: uuid.UUID, person: uuid.UUID, expense_id: str, ops: list[Any]
) -> set[int]:
    return {
        client.request(method, path.format(id=expense_id), headers=as_gym(gym, person)).status_code
        for method, path in ops
    }


@pg
def test_an_administrador_reads_no_expense_and_writes_none(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rent = recorded(client, gym)
    void(client, gym, recorded(client, gym)["id"])
    admin = add_staff(db, gym, "admin")
    coach = add_staff(db, gym, "coach")
    for person in (admin, coach):
        assert statuses(client, gym, person, rent["id"], READS + WRITES) == {403}

    # At the database, as the app role: no expense, category or expense log row.
    for table in ("expense", "expense_category"):
        rows = run(db.api_url, in_gym(gym, f"SELECT id FROM {table}", person=admin))
        assert rows == []
    logged = run(
        db.api_url,
        in_gym(
            gym,
            "SELECT action FROM audit_event WHERE starts_with(action, 'expense_')",
            person=admin,
        ),
    )
    assert logged == []
    assert len(log(db, gym)) == 1


@pg
def test_expenses_read_reads_and_expenses_write_records(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rent = recorded(client, gym)
    reader = holding(db, gym, Permission.EXPENSES_READ)
    assert statuses(client, gym, reader, rent["id"], READS[:2]) == {200}
    assert statuses(client, gym, reader, rent["id"], WRITES) == {403}

    writer = holding(db, gym, Permission.EXPENSES_READ, Permission.EXPENSES_WRITE)
    mine = record(client, gym, writer, amount_clp=32_990)
    assert mine.status_code == 201, mine.text
    assert mine.json()["created_by_name"] == "Tesorera"
    assert month(client, gym, reader).json()["count"] == 2
    # Money is another permission: neither reads Pagos.
    assert client.get("/api/ledger/book", headers=as_gym(gym, writer)).status_code == 403


# --- billing never reads them --------------------------------------------------------


@pg
def test_recording_and_voiding_expenses_leaves_billing_unchanged(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = today - timedelta(days=40)
    ana = enrolled(
        client,
        gym,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        membership={"plan_id": plan(client, gym), "started_on": started_on.isoformat()},
    )

    async def bill(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
        async with conn.transaction():
            await billing.generate_billing_periods(conn, today)
        await conn.execute("SELECT set_config('app.gym_id', $1, false)", str(gym))
        rows = await conn.fetch(
            "SELECT membership_id, period_start, period_end, due_date, amount_due_clp"
            " FROM billing_period ORDER BY 1, 2"
        )
        return [tuple(r) for r in rows]

    def balance() -> Any:
        [membership] = memberships(client, gym, ana["id"])
        return membership

    periods = run(db.owner_url, bill)
    before = (readers(client, db, gym), balance(), periods)

    for n in range(3):
        recorded(client, gym, amount_clp=100_000 + n, receipt_key=upload(client, gym))
    void(client, gym, recorded(client, gym, amount_clp=5)["id"])
    luz = category(client, gym, "Luz")
    change(client, gym, recorded(client, gym)["id"], category_id=luz, amount_clp=7)

    # The billing job runs again over the same days and writes the same.
    assert (readers(client, db, gym), balance(), run(db.owner_url, bill)) == before
    assert periods != []


# --- the migration -------------------------------------------------------------------


@pg
def test_upgrade_gives_existing_gyms_the_defaults_and_downgrade_takes_them_back() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        command.upgrade(scratch.alembic(), "0082")
        gym = seed_gym(scratch, "sur")
        command.upgrade(scratch.alembic(), "0083")
        names = run(
            scratch.owner_url,
            in_gym(gym, "SELECT name FROM expense_category ORDER BY sort"),
        )
        assert [r["name"] for r in names] == DEFAULTS
        owner = seeded_owner(gym)

        async def spend(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO expense (gym_id, spent_on, amount_clp, category_id, created_by)"
                " SELECT $1, current_date, 1000, id, $2 FROM expense_category"
                " WHERE gym_id = $1 AND is_other",
                gym,
                owner,
            )
            expense_id = await conn.fetchval("SELECT id FROM expense WHERE gym_id = $1", gym)
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
                " VALUES ($1, $2, 'expense_voided', $3)",
                gym,
                owner,
                json.dumps({"expense_id": str(expense_id)}),
            )

        run(scratch.admin_url, spend)
        command.downgrade(scratch.alembic(), "0082")
        left = run(
            scratch.admin_url,
            lambda c: c.fetchval("SELECT count(*) FROM audit_event WHERE action LIKE 'expense_%'"),
        )
        assert left == 0
        migrate(scratch)


@pg
def test_an_expense_row_of_the_log_names_nobody(db: Database, gym: uuid.UUID) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.owner_url,
            in_gym(
                gym,
                "INSERT INTO audit_event (gym_id, actor_id, person_id, action)"
                " VALUES ($1, $2, $2, 'expense_changed')",
                gym,
                seeded_owner(gym),
            ),
        )


# --- review of #521 ------------------------------------------------------------------


@pg
def test_a_category_past_the_cap_is_refused_so_the_list_still_reorders(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    headers = as_gym(gym)
    live = len(DEFAULTS)
    room = MAX_CATEGORIES - live
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO expense_category (gym_id, name, sort)"
            " SELECT $1, 'Extra ' || n, 100 + n FROM generate_series(1, $2) n",
            gym,
            room,
        ),
    )
    refused = client.post("/api/expenses/categories", json={"name": "Una más"}, headers=headers)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "too_many_categories"
    # Every live one still fits in one reorder.
    ids = [c["id"] for c in categories(client, gym) if not c["archived"]]
    assert len(ids) == MAX_CATEGORIES
    order = client.post("/api/expenses/categories/order", json={"ids": ids[::-1]}, headers=headers)
    assert order.status_code == 200, order.text

    # A restore is one more live category too.
    gas = category(client, gym, "Gas")
    assert (
        client.post(f"/api/expenses/categories/{gas}/archive", headers=headers).status_code == 200
    )
    assert (
        client.post("/api/expenses/categories", json={"name": "Otra"}, headers=headers).status_code
        == 201
    )
    full = client.post(f"/api/expenses/categories/{gas}/restore", headers=headers)
    assert full.status_code == 409 and full.json()["detail"]["code"] == "too_many_categories"


@pg
def test_restoring_a_live_category_leaves_it_where_it_is(
    client: TestClient, gym: uuid.UUID
) -> None:
    headers = as_gym(gym)
    luz = category(client, gym, "Luz")
    before = categories(client, gym)
    again = client.post(f"/api/expenses/categories/{luz}/restore", headers=headers)
    assert again.status_code == 200
    assert again.json() == before

    archived = client.post(f"/api/expenses/categories/{luz}/archive", headers=headers)
    assert archived.status_code == 200
    restored = client.post(f"/api/expenses/categories/{luz}/restore", headers=headers).json()
    twice = client.post(f"/api/expenses/categories/{luz}/restore", headers=headers).json()
    assert restored[len(DEFAULTS) - 1]["name"] == "Luz"
    assert twice == restored


@pg
def test_the_month_says_the_gyms_today(client: TestClient, gym: uuid.UUID) -> None:
    assert month(client, gym).json()["today"] == seeded_today().isoformat()


@pg
def test_a_replaced_receipt_stays_in_storage(client: TestClient, gym: uuid.UUID) -> None:
    first = upload(client, gym)
    rent = recorded(client, gym, receipt_key=first)
    assert change(client, gym, rent["id"], receipt_key=upload(client, gym)).status_code == 200
    stored = client.app.state.integrations.blob_store  # type: ignore[attr-defined]

    async def stat() -> Any:
        return await stored.stat(first)

    assert asyncio.run(stat()) is not None
