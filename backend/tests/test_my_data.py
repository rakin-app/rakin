"""Mis datos (#371): `GET /api/me/data` holds every row the gym keeps on the person and
their dependents, and nothing of anyone else's or another gym's.

Each person here gets a row in every table `EXPORTED` names, and in those that hang off
a membership, each carrying a marker of its own; the export must hold each of the
person's rows by id, and no other person's marker. A structural test fails when a table
with a `person_id` (or a `guardian_person_id`, any column so named) is neither exported
nor left out with a reason.
"""

import dataclasses
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.my_data import EXPORTED, NOT_EXPORTED
from app.api.requirements import bound_to
from app.domain.custom_fields import FieldCipher
from app.main import create_app
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
from tests.test_guardians import add_person, new_kid
from tests.test_proofs import RecordingMailer

pytestmark = pytest.mark.postgres

PERSON_TABLES = """
    SELECT DISTINCT c.table_name FROM information_schema.columns c
    JOIN information_schema.tables t USING (table_schema, table_name)
    WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
      AND c.column_name LIKE '%person_id'
"""

# Two custom fields: one in the clear, and a sensitive one, stored sealed.
FIELDS = [
    {"key": "contacto", "label": "Contacto de emergencia", "type": "text"},
    {"key": "salud", "label": "Condición médica", "type": "text", "sensitive": True},
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
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=RecordingMailer())
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cipher(client: TestClient) -> FieldCipher:
    return FieldCipher(client.app.state.settings.field_encryption_key)  # type: ignore[attr-defined]


def gym_with_fields(db: Database) -> uuid.UUID:
    gym = seed_gym(db, unique_slug("mis-datos"))

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "UPDATE gym SET settings = settings || jsonb_build_object("
                " 'custom_fields', CAST($2 AS jsonb),"
                " 'privacy', jsonb_build_object('legal_name', 'Academia Sur SpA',"
                "   'rut', '76.123.456-0', 'email', 'privacidad@example.cl',"
                "   'updated_on', '2026-11-01'))"
                " WHERE id = $1",
                gym,
                json.dumps(FIELDS),
            )

    run(db.owner_url, query)
    return gym


def fill(db: Database, cipher: FieldCipher, gym: uuid.UUID, person: str, mark: str) -> None:
    """A row for `person` in every table the export reads, each text carrying `mark`."""
    who = uuid.UUID(person)
    owner = seeded_owner(gym)

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))

            async def one(sql: str, *args: object) -> Any:
                return await conn.fetchval(sql, gym, *args)

            await one(
                "INSERT INTO person_field_value (gym_id, person_id, field_key, value)"
                " VALUES ($1, $2, 'contacto', to_jsonb($3::text))",
                who,
                f"contacto {mark}",
            )
            await one(
                "INSERT INTO person_field_value (gym_id, person_id, field_key, secret)"
                " VALUES ($1, $2, 'salud', $3)",
                who,
                cipher.seal(gym, who, "salud", f"asma {mark}"),
            )
            membership = await one(
                "INSERT INTO membership (gym_id, person_id, plan_id, status, discount_pct,"
                " discount_reason) SELECT $1, $2, id, 'active', 10, $3 FROM plan"
                " WHERE name = 'Mensual' RETURNING id",
                who,
                f"beca {mark}",
            )
            period = await one(
                "INSERT INTO billing_period (gym_id, membership_id, period_start, period_end,"
                " amount_due_clp, due_date)"
                " VALUES ($1, $2, '2026-10-01', '2026-10-31', 45000, '2026-10-01') RETURNING id",
                membership,
            )
            await one(
                "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
                " kind, status, method, note)"
                " VALUES ($1, $2, $3, 45000, 'payment', 'pending', 'transfer', $4)",
                membership,
                period,
                f"pagó en dos partes {mark}",
            )
            await one(
                "INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)"
                " VALUES ($1, $2, 'frozen', '2026-09-01')",
                membership,
            )
            await one(
                "INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason)"
                " VALUES ($1, $2, '2026-09-01', '2026-09-15', $3)",
                membership,
                f"viaje {mark}",
            )
            await one(
                "INSERT INTO freeze_request (gym_id, membership_id, requested_by, from_date,"
                " to_date, reason, note)"
                " VALUES ($1, $2, $3, '2026-12-01', '2026-12-20', 'otro', $4)",
                membership,
                who,
                f"cirugía {mark}",
            )
            charge = await one(
                "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode,"
                " amount_clp, target_kind, created_by)"
                " VALUES ($1, $2, 'seminario', '2026-11-10', 'fixed', 20000, 'people', $3)"
                " RETURNING id",
                f"Seminario {mark}",
                owner,
            )
            line = await one(
                "INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp,"
                " due_date) VALUES ($1, $2, $3, 20000, '2026-11-10') RETURNING id",
                charge,
                who,
            )
            await one(
                "INSERT INTO ledger_entry (gym_id, extra_line_id, amount_clp, kind, status)"
                " VALUES ($1, $2, 20000, 'payment', 'validated')",
                line,
            )
            await one(
                "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
                " plan_name, note, created_by)"
                " VALUES ($1, $2, '2019-05-03', 30000, 'manual', $3, $4, $5)",
                who,
                f"Plan antiguo {mark}",
                f"pagó en efectivo {mark}",
                owner,
            )
            program = await one(
                "INSERT INTO program (gym_id, name) VALUES ($1, $2) RETURNING id", f"Prog {mark}"
            )
            class_type = await one(
                "INSERT INTO class_type (gym_id, program_id, name) VALUES ($1, $2, $3)"
                " RETURNING id",
                program,
                f"Clase {mark}",
            )
            session = await one(
                "INSERT INTO session (gym_id, class_type_id, starts_at, coach_id, notes)"
                " VALUES ($1, $2, now() - interval '1 day', $3, 'nota del coach') RETURNING id",
                class_type,
                owner,
            )
            await one(
                "INSERT INTO attendance (gym_id, session_id, membership_id) VALUES ($1, $2, $3)",
                session,
                membership,
            )
            await one(
                "INSERT INTO grade_event (gym_id, person_id, rank_key, awarded_on, note)"
                " VALUES ($1, $2, $3, '2026-06-01', $4)",
                who,
                f"rank-{mark}",
                f"buena guardia {mark}",
            )
            requirement = await one(
                "INSERT INTO requirement (gym_id, name) VALUES ($1, $2) RETURNING id",
                f"Deslinde {mark}",
            )
            await one(
                "INSERT INTO person_requirement (gym_id, person_id, requirement_id, done_on,"
                " note, recorded_by) VALUES ($1, $2, $3, $4, $5, $6)",
                who,
                requirement,
                seeded_today(),
                f"firmado en papel {mark}",
                owner,
            )
            # A sensitive one's note is stored sealed, bound to its record.
            medical = await one(
                "INSERT INTO requirement (gym_id, name, sensitive, visible_to)"
                " VALUES ($1, $2, true, 'owner') RETURNING id",
                f"Certificado {mark}",
            )
            record = uuid.uuid4()
            await one(
                "INSERT INTO person_requirement (id, gym_id, person_id, requirement_id, done_on,"
                " note_secret, recorded_by) VALUES ($2, $1, $3, $4, $5, $6, $7)",
                record,
                who,
                medical,
                seeded_today(),
                cipher.seal(gym, who, bound_to(record), f"apto con asma {mark}"),
                owner,
            )
            await one(
                "INSERT INTO consent_event (gym_id, person_id, action, by_person_id, source)"
                " VALUES ($1, $2, 'notice_accepted', $2, 'join')",
                who,
            )
            await one(
                "INSERT INTO message_log (gym_id, person_id, channel, template, to_address,"
                " status, payload) VALUES ($1, $2, 'email', 'welcome', $3, 'sent', '{}')",
                who,
                f"{mark}@example.cl",
            )
            await one(
                "INSERT INTO message_log (gym_id, person_id, channel, template, to_address,"
                " status, error, payload)"
                " VALUES ($1, $2, 'email', 'statement', $3, 'failed', $4, '{}')",
                who,
                f"{mark}@example.cl",
                "MailDeliveryError: smtp smtp.internal:587: refused",
            )
            group = await one(
                "INSERT INTO charge_group (gym_id, name) VALUES ($1, $2) RETURNING id",
                f"Grupo {mark}",
            )
            await one(
                "INSERT INTO charge_group_member (gym_id, group_id, person_id) VALUES ($1, $2, $3)",
                group,
                who,
            )
            await one("INSERT INTO mail_unsubscribe (gym_id, person_id) VALUES ($1, $2)", who)

    run(db.owner_url, query)


def my_data(client: TestClient, gym: uuid.UUID, person: str, **params: Any) -> Any:
    response = client.get("/api/me/data", params=params, headers=as_gym(gym, uuid.UUID(person)))
    assert response.status_code == 200, response.text
    return response


# Each table the export reads by id, and where in a person's data its rows are.
BY_ID = {
    "membership": "memberships",
    "billing_period": "periods",
    "extra_line": "extra_charges",
    "ledger_entry": "entries",
    "history_payment": "history_payments",
    "grade_event": "grades",
    "person_requirement": "requirements",
    "consent_event": "consents",
    "message_log": "messages",
}

# How each table reaches the person: its own `person_id`, or its membership's or line's.
OWNER_OF = {
    "billing_period": "(SELECT person_id FROM membership m WHERE m.id = t.membership_id)",
    "ledger_entry": "coalesce((SELECT person_id FROM membership m WHERE m.id = t.membership_id),"
    " (SELECT person_id FROM extra_line l WHERE l.id = t.extra_line_id))",
}


def held(db: Database, gym: uuid.UUID, person: str) -> dict[str, set[str]]:
    """The ids of the person's rows in each `BY_ID` table, as the database holds them."""

    async def query(conn: asyncpg.Connection) -> dict[str, set[str]]:
        out = {}
        for table in BY_ID:
            whose = OWNER_OF.get(table, "t.person_id")
            rows = await conn.fetch(
                f"SELECT t.id FROM {table} t WHERE t.gym_id = $1 AND {whose} = $2",
                gym,
                uuid.UUID(person),
            )
            out[table] = {str(r["id"]) for r in rows}
        return out

    result: dict[str, set[str]] = run(db.admin_url, query)
    return result


def unaccounted(tables: set[str]) -> set[str]:
    """The tables with a person's rows that the export neither reads nor leaves out."""
    return tables - set(EXPORTED) - set(NOT_EXPORTED)


def test_every_table_with_a_person_id_is_exported_or_left_out_with_a_reason(
    db: Database,
) -> None:
    tables = {r["table_name"] for r in run(db.admin_url, lambda c: c.fetch(PERSON_TABLES))}

    assert set(EXPORTED) & set(NOT_EXPORTED) == set()
    assert unaccounted(tables) == set(), "add it to EXPORTED, or to NOT_EXPORTED with why"
    assert set(EXPORTED) | set(NOT_EXPORTED) <= tables, "a table here no longer exists"


@pytest.mark.parametrize("column", ["person_id", "coach_person_id"])
def test_the_structural_test_fails_on_a_new_table_with_a_person(db: Database, column: str) -> None:
    async def query(conn: asyncpg.Connection) -> set[str]:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(f"CREATE TABLE locker (gym_id uuid, {column} uuid)")
            return {r["table_name"] for r in await conn.fetch(PERSON_TABLES)}
        finally:
            await tx.rollback()

    assert unaccounted(run(db.admin_url, query)) == {"locker"}


def test_the_export_holds_every_row_of_the_person_and_their_dependent_and_no_one_else(
    client: TestClient, db: Database, cipher: FieldCipher
) -> None:
    gym = gym_with_fields(db)
    other_gym = gym_with_fields(db)
    ana = add_person(client, gym, "Ana Mis Datos")
    kid = new_kid(client, gym, ana, "Tomás Mis Datos")
    beto = add_person(client, gym, "Beto Otro")
    carla = add_person(client, other_gym, "Carla Otro Gym")
    for g, p, mark in [
        (gym, ana, "ana-x1"),
        (gym, kid, "kid-x2"),
        (gym, beto, "beto-x3"),
        (other_gym, carla, "carla-x4"),
    ]:
        fill(db, cipher, g, p, mark)

    async def coach(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await make_staff(conn, gym, uuid.UUID(ana), "coach")

    run(db.owner_url, coach)

    response = my_data(client, gym, ana)
    data = response.json()

    # The person signed in, then their dependent; Beto and Carla are not there at all.
    assert [p["person_id"] for p in data["people"]] == [ana, kid]
    for marker, someone in [("beto-x3", beto), ("carla-x4", carla)]:
        assert marker not in response.text
        assert someone not in response.text

    mine, theirs = data["people"]
    assert mine["record"]["name"] == "Ana Mis Datos"
    assert mine["record"]["rut"] and mine["record"]["phone"] and mine["record"]["email"]
    assert mine["dependents"] == [{"person_id": kid, "name": "Tomás Mis Datos"}]
    assert theirs["guardians"] == [{"person_id": ana, "name": "Ana Mis Datos"}]
    assert data["gym"]["privacy"]["email"] == "privacidad@example.cl"

    for person, data_of, mark in [(ana, mine, "ana-x1"), (kid, theirs, "kid-x2")]:
        for table, ids in held(db, gym, person).items():
            assert ids, table
            assert {r["id"] for r in data_of[BY_ID[table]]} == ids, table
        # Sensitive values are the member's own: opened, not withheld.
        assert {f["key"]: f["value"] for f in data_of["fields"]} == {
            "contacto": f"contacto {mark}",
            "salud": f"asma {mark}",
        }
        assert [f["sensitive"] for f in data_of["fields"]] == [False, True]
        assert [f["label"] for f in data_of["fields"]] == [
            "Contacto de emergencia",
            "Condición médica",
        ]
        for part in ["plan_events", "freezes", "freeze_requests", "attendance"]:
            assert len(data_of[part]) == 1, part
        assert data_of["charge_groups"] == [f"Grupo {mark}"]
        assert data_of["unsubscribed_at"] is not None
        assert data_of["extra_charges"][0]["title"] == f"Seminario {mark}"

    # Ana is on the team; her dependent is not.
    assert mine["staff"]["role"] == "coach"
    assert [t["title_name"] for t in mine["staff"]["titles"]] == ["Coach"]
    assert theirs["staff"] is None

    # The notes the staff wrote about each person are theirs too, a sealed one opened.
    for data_of, mark in [(mine, "ana-x1"), (theirs, "kid-x2")]:
        assert f"pagó en dos partes {mark}" in [e["note"] for e in data_of["entries"]]
        assert [h["note"] for h in data_of["history_payments"]] == [f"pagó en efectivo {mark}"]
        assert [g["note"] for g in data_of["grades"]] == [f"buena guardia {mark}"]
        assert sorted(r["note"] for r in data_of["requirements"]) == [
            f"apto con asma {mark}",
            f"firmado en papel {mark}",
        ]
        # A failed message says so, without the provider's or the server's error.
        assert sorted(m["status"] for m in data_of["messages"]) == ["failed", "sent"]
        assert all("error" not in m for m in data_of["messages"])
    # Out: a coach's notes on a class as a whole, a send's error, and who on the staff
    # recorded a row.
    assert "nota del coach" not in response.text
    assert "smtp.internal" not in response.text
    owner = str(seeded_owner(gym))
    assert owner not in response.text


def test_the_download_is_the_same_document_as_a_file(
    client: TestClient, db: Database, cipher: FieldCipher
) -> None:
    gym = gym_with_fields(db)
    ana = add_person(client, gym, "Ana Descarga")
    fill(db, cipher, gym, ana, "ana-dl")

    shown = my_data(client, gym, ana).json()
    response = my_data(client, gym, ana, download=1)

    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="mis-datos-mis-datos-')
    assert disposition.endswith(f'-{seeded_today().isoformat()}.json"')
    assert response.headers["content-type"].startswith("application/json")
    downloaded = json.loads(response.content)
    assert {**downloaded, "exported_at": None} == {**shown, "exported_at": None}


def test_someone_with_no_dependents_sees_only_themselves(client: TestClient, db: Database) -> None:
    gym = gym_with_fields(db)
    ana = add_person(client, gym, "Ana Sola")

    data = my_data(client, gym, ana).json()

    [mine] = data["people"]
    assert mine["person_id"] == ana
    assert mine["memberships"] == mine["entries"] == mine["fields"] == []
    assert mine["guardians"] == mine["dependents"] == []
    assert mine["staff"] is None
    assert mine["unsubscribed_at"] is None


def test_a_member_reads_their_own_history_payments_and_no_one_elses(
    client: TestClient, db: Database, cipher: FieldCipher
) -> None:
    gym = gym_with_fields(db)
    ana = add_person(client, gym, "Ana Historia")
    kid = new_kid(client, gym, ana, "Kid Historia")
    beto = add_person(client, gym, "Beto Historia")
    for p, mark in [(ana, "a-h"), (kid, "k-h"), (beto, "b-h")]:
        fill(db, cipher, gym, p, mark)

    def plans(person: str) -> set[str]:
        rows = run(
            db.api_url,
            in_gym(gym, "SELECT plan_name FROM history_payment", person=uuid.UUID(person)),
        )
        return {r["plan_name"] for r in rows}

    assert plans(ana) == {"Plan antiguo a-h", "Plan antiguo k-h"}
    assert plans(beto) == {"Plan antiguo b-h"}
