"""The terms on the command line (#367, #499): `app.gyms create` makes a gym pending its
terms, which its titular accepts in the app, or exempt on an instance the company does
not host; `app.gyms sign-terms` records an acceptance signed outside the app. Each
text's version is its own "Versión" line.
"""

import asyncio
import re
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from app import gyms
from app.db_bootstrap import to_dsn
from app.gyms import PROCESSOR_TERMS_VERSION, SERVICE_TERMS_VERSION, Signing, sign_terms
from app.gyms import parse as parse_command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, run, throwaway_database
from tests.test_gym_hosts import ARGS, SIGNED_TODAY, create, new_gym, parse_gym

LEGAL = Path(__file__).parents[2] / "docs" / "legal"
SIGNED = ["--processor-terms", PROCESSOR_TERMS_VERSION, "--signed-on", PROCESSOR_TERMS_VERSION]


@pytest.fixture(autouse=True)
def _terms_signed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gyms, "gym_today", lambda tz: SIGNED_TODAY)


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("terminos-de-encargo.md", PROCESSOR_TERMS_VERSION),
        ("terminos-de-servicio.md", SERVICE_TERMS_VERSION),
    ],
)
def test_each_version_is_the_texts_own(name: str, version: str) -> None:
    found = re.search(r"\*\*Versión: (\d{4}-\d{2}-\d{2})\.\*\*", (LEGAL / name).read_text())
    assert found is not None
    assert found.group(1) == version


def test_create_makes_a_gym_pending_its_terms() -> None:
    assert parse_gym(ARGS).terms_exempt is False


def test_an_instance_the_company_does_not_host_is_exempt() -> None:
    assert parse_gym([*ARGS, "--no-processor-terms"]).terms_exempt is True


def test_create_takes_no_signature(capsys: pytest.CaptureFixture[str]) -> None:
    """Accepted in the app (#499), or recorded with `sign-terms`: never at creation."""
    with pytest.raises(SystemExit) as exit_:
        parse_command([*ARGS, *SIGNED])
    assert exit_.value.code == 2
    assert "--processor-terms" in capsys.readouterr().err


def test_sign_terms_reads_its_arguments() -> None:
    signing = parse_command(["sign-terms", "--slug", "meta", *SIGNED])
    assert signing == Signing(
        slug="meta",
        processor_terms=PROCESSOR_TERMS_VERSION,
        signed_on=date.fromisoformat(PROCESSOR_TERMS_VERSION),
    )


@pytest.mark.parametrize("missing", ["--processor-terms", "--signed-on"])
def test_sign_terms_needs_the_version_and_the_date(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["sign-terms", "--slug", "meta", *SIGNED]
    del args[args.index(missing) : args.index(missing) + 2]
    with pytest.raises(SystemExit) as exit_:
        parse_command(args)
    assert exit_.value.code == 2
    assert missing in capsys.readouterr().err


# --- with Postgres ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def signatures(db: Database, gym_id: uuid.UUID) -> list[tuple[str, date]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[str, date]]:
        rows = await conn.fetch(
            "SELECT version, signed_on FROM processor_terms WHERE gym_id = $1", gym_id
        )
        return [(r["version"], r["signed_on"]) for r in rows]

    return list(run(db.admin_url, query))


def acceptances(db: Database, gym_id: uuid.UUID) -> list[tuple[str, str | None, str, date]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[str, str | None, str, date]]:
        rows = await conn.fetch(
            "SELECT channel, service_version, processor_version, signed_on"
            " FROM terms_acceptance WHERE gym_id = $1",
            gym_id,
        )
        return [tuple(r) for r in rows]

    return list(run(db.admin_url, query))


def exempt(db: Database, gym_id: uuid.UUID) -> bool:
    return bool(
        run(
            db.admin_url,
            lambda c: c.fetchval("SELECT exempt FROM gym_terms WHERE gym_id = $1", gym_id),
        )
    )


def state(db: Database, gym_id: uuid.UUID) -> str:
    async def query(conn: asyncpg.Connection) -> str:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
            return str(
                await conn.fetchval(
                    "SELECT app_terms_state($1, $2)", SERVICE_TERMS_VERSION, PROCESSOR_TERMS_VERSION
                )
            )

    return str(run(db.api_url, query))


def sign(db: Database, signing: Signing) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            return await sign_terms(conn, signing)
        finally:
            await conn.close()

    return asyncio.run(go())


SIGNED_ON = date.fromisoformat(PROCESSOR_TERMS_VERSION)


@pytest.mark.postgres
def test_a_gym_created_is_pending_its_terms(db: Database) -> None:
    created = create(db, new_gym(unique_slug("meta")), accepted=False)
    assert (signatures(db, created.gym_id), acceptances(db, created.gym_id)) == ([], [])
    assert not exempt(db, created.gym_id)
    assert state(db, created.gym_id) == "pending"


@pytest.mark.postgres
def test_a_gym_on_an_instance_not_hosted_is_exempt(db: Database) -> None:
    gym = new_gym(unique_slug("propio")).model_copy(update={"terms_exempt": True})
    created = create(db, gym, accepted=False)
    assert exempt(db, created.gym_id)
    assert state(db, created.gym_id) == "current"


@pytest.mark.postgres
def test_a_gym_that_exists_signs_them_once(db: Database) -> None:
    gym = new_gym(unique_slug("meta"))
    created = create(db, gym, accepted=False)
    signing = Signing(slug=gym.slug, processor_terms=PROCESSOR_TERMS_VERSION, signed_on=SIGNED_ON)

    first = sign(db, signing)
    again = sign(db, signing.model_copy(update={"signed_on": SIGNED_TODAY}))

    assert (first.gym_id, first.name, first.recorded) == (created.gym_id, gym.name, True)
    assert (again.gym_id, again.recorded) == (created.gym_id, False)
    assert signatures(db, created.gym_id) == [(PROCESSOR_TERMS_VERSION, SIGNED_ON)]
    # Both texts, signed outside the app: the gym is current.
    assert acceptances(db, created.gym_id) == [
        ("outside", SERVICE_TERMS_VERSION, PROCESSOR_TERMS_VERSION, SIGNED_ON)
    ]
    assert state(db, created.gym_id) == "current"


@pytest.mark.postgres
def test_no_gym_with_the_slug_signs_nothing(db: Database) -> None:
    signing = Signing(
        slug=unique_slug("nadie"),
        processor_terms=PROCESSOR_TERMS_VERSION,
        signed_on=SIGNED_ON,
    )
    assert sign(db, signing) is None


@pytest.mark.postgres
def test_a_gym_sees_only_its_own_signatures(db: Database) -> None:
    gym = new_gym(unique_slug("meta"))
    ours = create(db, gym, accepted=False)
    sign(db, Signing(slug=gym.slug, processor_terms=PROCESSOR_TERMS_VERSION, signed_on=SIGNED_ON))
    other = create(db, new_gym(unique_slug("otro")), accepted=False)

    async def seen_from(conn: asyncpg.Connection, gym_id: uuid.UUID) -> int:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
            return int(await conn.fetchval("SELECT count(*) FROM processor_terms"))

    async def write_for_ours_from_other(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(other.gym_id))
            await conn.execute(
                "INSERT INTO processor_terms (gym_id, version, signed_on) VALUES ($1, $2, $3)",
                ours.gym_id,
                PROCESSOR_TERMS_VERSION,
                SIGNED_ON,
            )

    assert run(db.owner_url, lambda c: seen_from(c, ours.gym_id)) == 1
    assert run(db.owner_url, lambda c: seen_from(c, other.gym_id)) == 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.owner_url, write_for_ours_from_other)


@pytest.mark.postgres
def test_the_app_cannot_read_them(db: Database) -> None:
    async def query(conn: asyncpg.Connection) -> None:
        await conn.fetch("SELECT * FROM processor_terms")

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, query)


def run_main(
    argv: list[str], done: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    """`main`'s output, with `done` as what the database gave back."""

    async def fake_run(command: Any) -> Any:
        return done

    monkeypatch.setattr(gyms, "run", fake_run)
    gyms.main(argv)
    return capsys.readouterr().out


def test_create_says_the_owner_accepts_the_terms_there(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made = gyms.Created(uuid.uuid4(), "Meta", created=True)
    out = run_main(ARGS, made, monkeypatch, capsys)
    assert "accepts the terms there" in out
    out = run_main([*ARGS, "--no-processor-terms"], made, monkeypatch, capsys)
    assert "terms" not in out


def test_create_on_a_slug_taken_says_nothing_changed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    taken = gyms.Created(uuid.uuid4(), "Meta", created=False)
    out = run_main(ARGS, taken, monkeypatch, capsys)
    assert "nothing changed" in out
    assert "terms" not in out
