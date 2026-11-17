"""The gym's words outside the screens (#345): emails, the ledger export, the import
template.

A gym with no words of its own gets exactly today's: "la academia", "alumnos", the
"Alumno" column, the Alumnos tab. A gym of "club" and "socios" gets its own, and a sheet
filled in with today's Alumnos headers still imports there.
"""

import asyncio
import csv
import io
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.auth import build_notices
from app.db import create_engine, create_sessionmaker
from app.domain.vocabulary import DEFAULT_WORDS, Vocabulary, Words
from app.ledger_export import HEADERS, MonthExport, Totals, to_csv, to_xlsx
from app.main import create_app
from app.member_import.rows import Field, suggest_mapping
from app.member_import.sheet import read_book
from app.member_import.template import COLUMNS, template, template_name
from app.notices import FREEZE_REJECTED, JOIN_APPROVED, STAFF_INVITE, WELCOME, Notice, render
from app.notices.unsubscribe import UNSUBSCRIBE_PATH, UnsubscribeSigner
from app.permissions import ADMINISTRADOR, Permission
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_notices import Outbox

pg = pytest.mark.postgres

GYM = uuid.UUID("00000000-0000-4000-8000-000000000001")
PERSON = uuid.UUID("00000000-0000-4000-8000-000000000002")

CLUB = {"place": "club", "members": "socios", "coach": "entrenador"}
CLUB_WORDS = Words(Vocabulary.model_validate(CLUB))

BASE = {"name": "Ana", "gym": "Club Sur", "dependent_name": None}
CONTEXTS: dict[str, dict[str, Any]] = {
    "welcome": {**BASE, "plan_name": None, "bank_account": None},
    "join_approved": BASE,
    "freeze_rejected": {
        **BASE,
        "from_date": date(2026, 12, 1),
        "to_date": date(2026, 12, 31),
        "note": None,
    },
    "staff_invite": {
        **BASE,
        "inviter": "Pía",
        "roles": ["Administrador"],
        "can": [p.value for p in Permission if p in ADMINISTRADOR.permissions],
    },
}
TEMPLATES = {"welcome": WELCOME, "join_approved": JOIN_APPROVED}
TEMPLATES |= {"freeze_rejected": FREEZE_REJECTED, "staff_invite": STAFF_INVITE}

# Each changed sentence as it read before #345, and in a club of socios.
SENTENCES = {
    "welcome": ("Ya estás en su lista de alumnos.", "Ya estás en su lista de socios."),
    "join_approved": ("La academia te contará qué plan", "El club te contará qué plan"),
    "freeze_rejected": ("habla con la academia.", "habla con el club."),
    # What the roles let one do, since #311.
    "staff_invite": (
        "registrar pagos, llevar a los alumnos, tomar asistencia, configurar la academia",
        "registrar pagos, llevar a los socios, tomar asistencia, configurar el club",
    ),
}


def notice(name: str) -> Notice:
    return Notice(TEMPLATES[name], "ana@example.cl", PERSON, GYM, CONTEXTS[name])


# --- emails -------------------------------------------------------------------------


@pytest.mark.parametrize("name", SENTENCES)
def test_a_gym_with_no_words_gets_todays_emails(name: str) -> None:
    today, _ = SENTENCES[name]
    email = render(notice(name))

    assert email == render(notice(name), words=DEFAULT_WORDS)
    assert today in email.text
    assert email.html is not None and today in email.html


@pytest.mark.parametrize("name", SENTENCES)
def test_a_club_of_socios_gets_its_own_words_in_its_emails(name: str) -> None:
    today, club = SENTENCES[name]
    email = render(notice(name), words=CLUB_WORDS)

    assert club in email.text
    assert email.html is not None and club in email.html
    assert today not in email.text


# --- the ledger export ----------------------------------------------------------------


def month(words: Words = DEFAULT_WORDS) -> MonthExport:
    return MonthExport(
        month=date(2026, 11, 1),
        fields=("Cinturón",),
        entries=(),
        pending=(),
        totals=Totals(0, 0, 0, 0, 0, 0, 0),
        words=words,
    )


def csv_header(export: MonthExport) -> list[str]:
    return next(csv.reader(io.StringIO(to_csv(export).decode("utf-8-sig")), delimiter=";"))


def test_the_export_heads_the_member_alumno_with_no_words() -> None:
    today = (
        "Fecha",
        "Alumno",
        "RUT",
        "Plan o cobro",
        "Período",
        "Tipo",
        "Método",
        "Monto (CLP)",
        "Estado",
        "Ref. bancaria",
        "Nota",
    )
    assert today == HEADERS
    assert csv_header(month()) == [*today, "Cinturón"]


def test_a_club_of_socios_exports_a_socio_column() -> None:
    assert csv_header(month(CLUB_WORDS))[:3] == ["Fecha", "Socio", "RUT"]
    book = load_workbook(io.BytesIO(to_xlsx(month(CLUB_WORDS))))
    for sheet in ("Movimientos", "Por validar"):
        assert [c.value for c in book[sheet][1]][:3] == ["Fecha", "Socio", "RUT"]


# --- the import template ---------------------------------------------------------------


def cells(book: Any, tab: str) -> list[str]:
    return [str(c.value) for row in book[tab].iter_rows() for c in row if c.value is not None]


def test_a_gym_with_no_words_gets_todays_template() -> None:
    book = load_workbook(io.BytesIO(template(["Mensual"])))

    assert template_name(DEFAULT_WORDS) == "plantilla-alumnos.xlsx"
    assert book.sheetnames[:3] == ["Alumnos", "Pagos", "Instrucciones"]
    assert [c.value for c in book["Alumnos"][1]] == [h for h, _, _ in COLUMNS]
    assert "Alumno desde" in [h for h, _, _ in COLUMNS]
    instructions = cells(book, "Instrucciones")
    for line in (
        "Una fila por alumno, en la pestaña Alumnos. La fila gris de cada pestaña es un"
        " ejemplo: bórrala antes de subir la planilla.",
        "Súbela en Alumnos, botón Importar. Primero revisamos cada fila sin guardar nada.",
        "El plan que tiene hoy, de la lista. Vacío para un exalumno.",
        "Para un exalumno: el día que dejó de venir. Se importa sin plan.",
        "¿Tu planilla tiene un alumno por fila y un mes por columna? Pásala a filas así:",
        "2. En RUT o Nombre, el del alumno de esa fila.",
    ):
        assert line in instructions
    assert not any("{" in line for line in instructions)


def test_a_club_of_socios_gets_a_socios_template() -> None:
    book = load_workbook(io.BytesIO(template(["Mensual"], words=CLUB_WORDS)))

    assert template_name(CLUB_WORDS) == "plantilla-socios.xlsx"
    assert book.sheetnames[:3] == ["Socios", "Pagos", "Instrucciones"]
    headers = [c.value for c in book["Socios"][1]]
    assert "Socio desde" in headers and "Alumno desde" not in headers
    instructions = " ".join(cells(book, "Instrucciones"))
    assert "Una fila por socio, en la pestaña Socios." in instructions
    assert "Vacío para un exsocio." in instructions
    assert "alumno" not in instructions.lower()


def test_a_socios_template_reads_back_as_the_people_tab() -> None:
    # The Socios tab behind another, so only its name says it is the people's.
    book = load_workbook(io.BytesIO(template([], words=CLUB_WORDS)))
    book.move_sheet("Socios", offset=2)
    out = io.BytesIO()
    book.save(out)

    people = read_book(out.getvalue())["alumnos"]
    mapping = suggest_mapping(people.headers)
    assert mapping[Field.MEMBER_SINCE] == people.headers.index("Socio desde")
    assert mapping[Field.NAME] == people.headers.index("Nombre")


@pytest.mark.parametrize("member", ["Alumno", "Socio", "Deportista", "Miembro"])
def test_every_gyms_member_since_header_maps(member: str) -> None:
    assert suggest_mapping(["Nombre", f"{member} desde"]) == {
        Field.NAME: 0,
        Field.MEMBER_SINCE: 1,
    }


# --- through the API, in a gym with words of its own --------------------------------------


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
def club(db: Database, client: TestClient) -> uuid.UUID:
    gym = seed_gym(db, f"club-{uuid.uuid4().hex[:8]}")
    response = client.patch("/api/gym/settings", json={"vocabulary": CLUB}, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return gym


@pg
def test_a_club_of_socios_sends_its_welcome_in_its_words(db: Database, club: uuid.UUID) -> None:
    outbox = Outbox()
    welcome = Notice(WELCOME, "ana@example.cl", seeded_owner(club), club, CONTEXTS["welcome"])

    async def go() -> None:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            await build_notices(db.settings, outbox, lambda: sessionmaker).send(welcome)
        finally:
            await engine.dispose()

    asyncio.run(go())

    [email] = outbox.sent
    assert "Ya estás en su lista de socios." in email.text


@pg
def test_a_club_of_socios_downloads_a_socio_export(client: TestClient, club: uuid.UUID) -> None:
    response = client.get(
        "/api/ledger/export", params={"month": "2020-03-01"}, headers=as_gym(club)
    )
    assert response.status_code == 200, response.text
    header = next(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert header[:3] == ["Fecha", "Socio", "RUT"]


@pg
def test_a_club_of_socios_downloads_a_socios_template(client: TestClient, club: uuid.UUID) -> None:
    response = client.get("/api/import/template.xlsx", headers=as_gym(club))
    assert response.status_code == 200, response.text
    assert "plantilla-socios.xlsx" in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames[0] == "Socios"
    assert "Socio desde" in [c.value for c in book["Socios"][1]]


@pg
def test_todays_alumnos_sheet_still_imports_in_a_club_of_socios(
    db: Database, client: TestClient, club: uuid.UUID
) -> None:
    book = Workbook()
    alumnos = book.active
    assert alumnos is not None
    alumnos.title = "Alumnos"
    alumnos.append(["Nombre", "Apellido", "RUT", "Alumno desde"])
    alumnos.append(["Martina", "Soto Pérez", "12.345.678-5", "05-03-2019"])
    out = io.BytesIO()
    book.save(out)

    sheet = client.post(
        "/api/import/sheet",
        content=out.getvalue(),
        headers={
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            **as_gym(club),
        },
    )
    assert sheet.status_code == 200, sheet.text
    found = sheet.json()
    assert found["mapping"] == {"name": 0, "last_name": 1, "rut": 2, "member_since": 3}

    body = {
        "rows": found["rows"],
        "mapping": found["mapping"],
        "plans": {},
        "dry_run": False,
        "file": found["file"],
    }
    response = client.post("/api/import/members", json=body, headers=as_gym(club))
    assert response.status_code == 200, response.text
    since = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT member_since FROM gym_person WHERE gym_id = $1 AND name = 'Martina Soto Pérez'",
            club,
        ),
    )
    assert str(since) == "2019-03-05"


@pg
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_stale_unsubscribe_link_names_the_club(
    db: Database, client: TestClient, club: uuid.UUID, method: str
) -> None:
    # Signed for the club, but for someone who is not one of its people.
    token = UnsubscribeSigner(db.settings.secret_key).sign(club, uuid.uuid4())

    response = client.request(method, f"{UNSUBSCRIBE_PATH}/{token}")

    assert response.status_code == 404
    assert "escríbele a tu club." in response.text
    garbage = client.request(method, f"{UNSUBSCRIBE_PATH}/garbage")
    assert "escríbele a tu academia." in garbage.text
