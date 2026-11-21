"""Resumen del mes by email (#507): the `month_summary_email` job sends each gym's
titular the month `month_summary` kept, from the stored figures, laid out as the page.

The email alone, without a database, first; then the job, on `tests.test_month_summary`'s
gyms and months: `MONTH` kept on `NEXT`'s 1st.
"""

import asyncio
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
from app.domain.value_summary import REQUIRED_FIGURES, Figure
from app.domain.vocabulary import DEFAULT_WORDS, Vocabulary, Words
from app.jobs import month_summary, month_summary_email
from app.main import create_app
from app.notices import MONTHLY_SUMMARY, Notice, Outcome, payload, render
from app.schemas.summary import has_news
from app.schemas.summary import month_summary as summary_of
from tests.auth import FakeAuth
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_month_summary import FIRST, a_busy_month, keep
from tests.test_statements_job import Outbox
from tests.test_summary import MONTH, admin, opened_on

# --- the email, no database ---------------------------------------------------------

OCTOBER = date(2026, 10, 1)
GYM = uuid.UUID("00000000-0000-4000-8000-000000000001")
TITULAR = uuid.UUID("00000000-0000-4000-8000-000000000002")
APP = "https://sur.rakin.test"
CLUB = Words(Vocabulary(place="club", members="socios", coach="entrenador"))


def figures(**values: int) -> dict[Figure, int]:
    """A month with every figure at 0 but `values`, by `Figure` value."""
    found = dict.fromkeys(REQUIRED_FIGURES, 0)
    found.update({Figure(k): v for k, v in values.items()})
    return found


# The design doc's example month (`docs/design/value-summary.md`, section 4).
BUSY = figures(
    income_clp=6_900_000,
    income_payments=52,
    reminder_emails=52,
    reminder_whatsapps=12,
    emails_only_payments=23,
    emails_only_clp=900_000,
    after_whatsapp_payments=8,
    after_whatsapp_clp=340_000,
    nudged=12,
    nudged_back=5,
    emails_sent=140,
    by_members=38,
    proofs_reviewed=40,
    proof_review_median_minutes=95,
    overdue_clp=120_000,
)


def notice(found: dict[Figure, int], *, whatsapp: bool = True, since: date | None = None) -> Notice:
    summary = summary_of(
        found, month=OCTOBER, months=[OCTOBER], since=since, whatsapp=whatsapp, kept=None
    )
    return Notice(
        MONTHLY_SUMMARY,
        "carla@example.cl",
        TITULAR,
        GYM,
        {
            "name": "Carla",
            "gym": "Academia Ejemplo",
            "month": OCTOBER,
            "summary": summary.model_dump(exclude={"month", "months", "kept"}),
        },
    )


def rendered(n: Notice, words: Words = DEFAULT_WORDS) -> Any:
    return render(n, unsubscribe_url=f"{APP}/u/token", app_url=APP, words=words)


def test_the_headline_figures_as_the_page_has_them() -> None:
    email = rendered(notice(BUSY))

    assert email.subject == "Resumen de octubre en Academia Ejemplo"
    assert email.text.startswith("Hola, Carla:\n\n")
    text = email.text
    assert "Pagos atrasados que llegaron después de un recordatorio: $1.240.000" in text
    assert "31 pagos atrasados · el 18\u00a0% de $6.900.000 cobrado en octubre" in text
    assert "Volvieron a clases después de un WhatsApp del equipo: 5 de 12" in text
    assert "Alumnos que no venían hace 14 días o más; volvieron dentro de dos semanas" in text
    assert "Recordatorios de pago enviados: 64" in text
    assert "52 por correo de Rakin · 12 por WhatsApp del equipo" in text
    assert "- Sin mensaje del equipo: 23 pagos · $900.000" in text
    assert "- Después de un WhatsApp del equipo: 8 pagos · $340.000" in text
    assert "- Pagos que informaron los mismos alumnos, con su comprobante: 38 de 52" in text
    assert "- Comprobantes revisados: 40 · la mitad en 2 horas o menos" in text
    assert "- Deuda vencida al cierre del mes: $120.000" in text
    assert "Cómo contamos esto" in text
    assert f"{APP}/admin/pagos/resumen?month=2026-10-01" in text
    # The same in the html, each figure as text beside its bar.
    html = email.html
    assert html is not None
    assert "$1.240.000" in html and "5 de 12" in html
    assert f'href="{APP}/admin/pagos/resumen?month=2026-10-01"' in html


def test_the_bars_are_tables_with_background_colours() -> None:
    html = rendered(notice(BUSY)).html

    # The share of income (1.240.000 of 6.900.000) and the share back (5 of 12), in
    # the default theme's accent.
    assert 'width="18%" height="8" bgcolor="#23643f"' in html
    assert 'width="42%" height="8" bgcolor="#23643f"' in html
    # The split's longest row is full, the other as a share of it.
    assert 'width="100%" height="8" bgcolor="#23643f"' in html
    assert 'width="38%" height="8" bgcolor="#23643f"' in html
    assert "<img" not in html.split("<body")[1].split("Academia Ejemplo, a través de")[0]


def test_never_thanks_to_and_no_percentage_under_5() -> None:
    few = figures(
        income_clp=100_000,
        income_payments=3,
        reminder_emails=2,
        emails_only_payments=1,
        emails_only_clp=30_000,
        nudged=3,
        nudged_back=1,
    )
    email = rendered(notice(few))

    for body in (email.text, email.html):
        assert "gracias a" not in body.replace("«gracias a»", "")
        assert "%" not in body.replace('%"', "").replace("%;", "")
    assert "1 pago atrasado · de $100.000 cobrado en octubre" in email.text
    assert "Volvieron a clases después de un WhatsApp del equipo: 1 de 3" in email.text


def test_a_figure_shows_only_when_it_exists() -> None:
    email = rendered(notice(figures(income_clp=50_000, income_payments=1, emails_sent=2)))

    text = email.text
    assert "Pagos atrasados que llegaron" not in text
    assert "Volvieron" not in text
    assert "recordatorio de pago" not in text.lower()
    assert "Cómo llegaron los pagos atrasados" not in text
    assert "- Avisos de cobro y recibos enviados por correo: 2" in text
    assert "Comprobantes revisados" not in text
    assert "Deuda vencida" not in text


def test_never_a_zero() -> None:
    """#516: a figure, a part of a line, a split row or an "Otros números" line shows
    only above zero, and no sentence says nothing happened."""
    found = figures(
        income_clp=200_000,
        income_payments=4,
        reminder_emails=14,
        emails_only_payments=2,
        emails_only_clp=60_000,
        nudged=2,
        nudged_back=0,
        overdue_clp=0,
    )
    email = rendered(notice(found))

    for body in (email.text, email.html):
        # Nudges sent, nobody back yet: no "0 de 2".
        assert "Volvieron" not in body and "0 de 2" not in body
        # Reminders by email only: no WhatsApp part.
        assert "14 por correo de Rakin" in body
        assert "por WhatsApp del equipo" not in body
        # One kind in the split: one row.
        assert "Sin mensaje del equipo" in body
        assert "Después de un WhatsApp del equipo" not in body
        # A zero closing debt is no line; nor is any other zero.
        assert "Deuda vencida" not in body
        assert "Otros números del mes" not in body
        assert "ningún" not in body
    assert "$0" not in email.text


def test_reminders_by_whatsapp_only_show_no_email_part() -> None:
    text = rendered(notice(figures(reminder_whatsapps=3))).text

    assert "Recordatorios de pago enviados: 3\n3 por WhatsApp del equipo\n" in text
    assert "por correo de Rakin" not in text


def test_no_whatsapp_line_with_the_channel_off() -> None:
    assert "Volvieron" not in rendered(notice(BUSY, whatsapp=False)).text


def test_a_partial_first_month_says_since_when() -> None:
    assert (
        "OCTUBRE 2026 · desde el 12 de octubre de 2026"
        in rendered(notice(BUSY, since=date(2026, 10, 12))).text
    )


def test_in_the_gyms_words() -> None:
    email = rendered(notice(BUSY), CLUB)

    assert "Socios que no venían hace 14 días o más" in email.text
    assert "los mismos socios, con su comprobante" in email.text
    assert "alumnos" not in email.text and "alumnos" not in email.html


def test_it_is_not_essential_and_keeps_no_name() -> None:
    n = notice(BUSY)
    email = rendered(n)

    assert not MONTHLY_SUMMARY.essential
    assert dict(email.headers)["List-Unsubscribe"] == f"<{APP}/u/token>"
    kept = json.loads(payload(n))
    assert "name" not in kept
    assert "Carla" not in payload(n)
    assert kept["month"] == "2026-10-01"
    assert kept["summary"]["after_reminders"]["total"] == {"payments": 31, "amount_clp": 1240000}


def test_a_month_with_nothing_in_it_is_no_news() -> None:
    def news(found: dict[Figure, int]) -> bool:
        summary = summary_of(
            found, month=OCTOBER, months=[OCTOBER], since=None, whatsapp=True, kept=None
        )
        return has_news(summary)

    assert not news(figures())
    assert not news({**figures(), Figure.OVERDUE_CLP: 30_000})
    assert news(figures(reminder_emails=1))
    # Only figures the email would show above zero are news (#516).
    assert not news(figures(income_payments=1, income_clp=1))
    assert not news(figures(nudged=3))
    assert news(figures(nudged=3, nudged_back=1))
    assert not news(figures(proofs_reviewed=0))
    assert news(figures(proofs_reviewed=2, proof_review_median_minutes=30))
    assert news(figures(by_members=1, income_payments=1))
    assert news(figures(emails_only_payments=1, emails_only_clp=10_000))
    assert news(BUSY)


# --- the job --------------------------------------------------------------------------

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
    """A gym on Rakin since well before `MONTH`, whose titular has an address."""
    made = seed_gym(db, unique_slug("academia"))
    opened_on(db, made, MONTH - timedelta(days=90))
    admin(
        db,
        "UPDATE gym_person SET email = $2 WHERE gym_id = $1 AND person_id = $3",
        made,
        address(made),
        seeded_owner(made),
    )
    return made


def address(gym: uuid.UUID) -> str:
    return f"titular-{gym.hex[:8]}@example.cl"


def email(db: Database, on: date, outbox: Outbox) -> bool:
    """Run the email job for the day `on`, as the runner does, in a transaction."""

    async def go() -> bool:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            notices = build_notices(db.settings, outbox, lambda: sessionmaker)
            conn = await asyncpg.connect(to_dsn(db.owner_url))
            try:
                async with conn.transaction():
                    return await month_summary.email_job(notices).run(conn, on) is not False
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    return asyncio.run(go())


def logged(db: Database, gym: uuid.UUID) -> list[Any]:
    return list(
        run(
            db.admin_url,
            lambda c: c.fetch(
                "SELECT person_id, status, payload FROM message_log"
                " WHERE gym_id = $1 AND template = 'monthly_summary' ORDER BY sent_at",
                gym,
            ),
        )
    )


@pg
def test_one_email_per_month_to_the_titular_only(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    outbox = Outbox()

    assert email(db, FIRST, outbox)
    assert email(db, FIRST + timedelta(days=1), outbox)

    [sent] = outbox.to(address(gym))
    assert sent.subject.startswith("Resumen de ")
    assert "2 pagos atrasados" in sent.text
    assert f"/admin/pagos/resumen?month={MONTH.isoformat()}" in sent.text
    # Nobody else in the gym got one: the members in `a_busy_month` have no address
    # here, and the outbox holds only the titular's.
    assert [e.to for e in outbox.sent if "Resumen de" in e.subject] == [address(gym)]
    [row] = logged(db, gym)
    assert (row["person_id"], row["status"]) == (seeded_owner(gym), "sent")


@pg
def test_the_payload_holds_the_figures_and_no_person(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)

    assert email(db, FIRST, Outbox())

    [row] = logged(db, gym)
    kept = json.loads(row["payload"])
    assert set(kept) == {"gym", "month", "summary"}
    assert kept["month"] == MONTH.isoformat()
    assert kept["summary"]["after_reminders"]["total"]["payments"] == 2
    assert kept["summary"]["nudges"] == {"nudged": 1, "back": 1, "percent": None}
    people = run(
        db.admin_url,
        lambda c: c.fetch("SELECT person_id::text, name FROM gym_person WHERE gym_id = $1", gym),
    )
    for person in people:
        assert person["person_id"] not in row["payload"]
        assert person["name"] not in row["payload"]


@pg
def test_none_for_an_empty_month(db: Database, gym: uuid.UUID) -> None:
    assert keep(db, FIRST)
    outbox = Outbox()

    assert email(db, FIRST, outbox)

    assert outbox.sent == [] and logged(db, gym) == []


@pg
def test_none_for_a_month_not_kept_or_weeks_late(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    outbox = Outbox()

    assert email(db, FIRST, outbox)
    assert outbox.to(address(gym)) == []
    # Kept on the 9th, say, back from a suspension: the page has it, the email is late.
    assert keep(db, FIRST + timedelta(days=8))
    assert email(db, FIRST + timedelta(days=8), outbox)
    assert outbox.to(address(gym)) == []


@pg
def test_none_after_unsubscribing(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    admin(
        db,
        "INSERT INTO mail_unsubscribe (gym_id, person_id) VALUES ($1, $2)",
        gym,
        seeded_owner(gym),
    )
    outbox = Outbox()

    assert email(db, FIRST, outbox)
    assert email(db, FIRST + timedelta(days=1), outbox)

    assert outbox.to(address(gym)) == []
    # Recorded once, then left alone.
    assert [r["status"] for r in logged(db, gym)] == ["suppressed"]


@pg
def test_none_with_it_turned_off_in_ajustes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    admin(
        db,
        "UPDATE gym SET settings = settings || '{\"summary_email\": false}' WHERE id = $1",
        gym,
    )
    outbox = Outbox()

    assert email(db, FIRST, outbox)

    assert outbox.to(address(gym)) == [] and logged(db, gym) == []


@pg
def test_a_failed_send_is_tried_again_the_next_day(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    outbox = Outbox()
    outbox.fail = True

    assert email(db, FIRST, outbox)
    outbox.fail = False
    assert email(db, FIRST + timedelta(days=1), outbox)

    assert len(outbox.to(address(gym))) == 1
    assert [r["status"] for r in logged(db, gym)] == ["failed", "sent"]


@pg
def test_in_a_club_s_words(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    admin(
        db,
        "UPDATE gym SET settings = settings || jsonb_build_object('vocabulary',"
        ' \'{"place": "club", "members": "socios", "coach": "entrenador"}\'::jsonb)'
        " WHERE id = $1",
        gym,
    )
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    outbox = Outbox()

    assert email(db, FIRST, outbox)

    [sent] = outbox.to(address(gym))
    assert "Socios que no venían" in sent.text
    assert "alumnos" not in sent.text


# --- sending one month now, to check an inbox -------------------------------------------


def send_now(db: Database, gym: uuid.UUID, outbox: Outbox, **request: Any) -> Any:
    """Run `app.jobs.month_summary_email` for `gym`'s `MONTH`, as the command does."""

    slug = admin(db, "SELECT slug FROM gym WHERE id = $1", gym)

    async def go() -> Any:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            notices = build_notices(db.settings, outbox, lambda: sessionmaker)
            conn = await asyncpg.connect(to_dsn(db.owner_url))
            try:
                return await month_summary_email.send(
                    conn, notices, month_summary_email.Request(slug=slug, month=MONTH, **request)
                )
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    return asyncio.run(go())


CHECKER = "operator@example.cl"


@pg
def test_a_copy_sent_now_is_the_jobs_email_and_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    outbox = Outbox()

    assert send_now(db, gym, outbox, to=CHECKER) is Outcome.SENT
    assert email(db, FIRST, outbox)

    [copy] = outbox.to(CHECKER)
    [real] = outbox.to(address(gym))
    assert (copy.subject, copy.text, copy.html) == (real.subject, real.text, real.html)
    rows = logged(db, gym)
    assert [r["status"] for r in rows] == ["sent", "sent"]
    assert rows[0]["payload"] == rows[1]["payload"]


@pg
def test_sent_now_to_the_titular_it_counts_and_is_not_sent_twice(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    outbox = Outbox()

    assert send_now(db, gym, outbox) is Outcome.SENT
    assert email(db, FIRST, outbox)
    assert send_now(db, gym, outbox) == month_summary_email.ALREADY_SENT

    assert len(outbox.to(address(gym))) == 1


@pg
def test_sending_now_is_refused_without_a_kept_month_with_news(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    outbox = Outbox()

    assert send_now(db, gym, outbox, to=CHECKER) == month_summary.NOT_KEPT
    assert keep(db, FIRST)
    assert send_now(db, gym, outbox, to=CHECKER) == month_summary.NO_NEWS
    assert outbox.sent == [] and logged(db, gym) == []


@pg
def test_sending_now_to_a_titular_who_turned_it_off_is_refused_but_a_copy_goes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    admin(
        db,
        "UPDATE gym SET settings = settings || '{\"summary_email\": false}' WHERE id = $1",
        gym,
    )
    outbox = Outbox()

    assert send_now(db, gym, outbox) == month_summary_email.TURNED_OFF
    assert send_now(db, gym, outbox, to=CHECKER) is Outcome.SENT
    assert outbox.to(address(gym)) == [] and len(outbox.to(CHECKER)) == 1


def test_the_command_takes_a_months_first_day() -> None:
    request = month_summary_email.parse(["--slug", "sur", "--month", "2026-10-01"])
    assert request == month_summary_email.Request("sur", date(2026, 10, 1), None)
    with pytest.raises(SystemExit):
        month_summary_email.parse(["--slug", "sur", "--month", "2026-10-15"])
