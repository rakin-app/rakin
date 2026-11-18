"""Términos de encargo (#367): a hosted gym signs them before its data goes in.

`app.gyms create` records the version signed and the date on the signed copy, or is told
the instance is not hosted; `app.gyms sign-terms` records a signature for a gym that
exists. The version is the terms' own "Versión" line.
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

from app.db_bootstrap import to_dsn
from app.domain.dates import gym_today
from app.gyms import PROCESSOR_TERMS_VERSION, SIGNED_IN, Signing, sign_terms
from app.gyms import parse as parse_command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database
from tests.test_gym_hosts import ARGS, create, new_gym, parse_gym

TERMS = Path(__file__).parents[2] / "docs" / "legal" / "terminos-de-encargo.md"
SIGNED = ["--processor-terms", PROCESSOR_TERMS_VERSION, "--signed-on", PROCESSOR_TERMS_VERSION]
WITHOUT_TERMS = ARGS[: ARGS.index("--processor-terms")]


def test_the_version_is_the_terms_own() -> None:
    found = re.search(r"\*\*Versión: (\d{4}-\d{2}-\d{2})\.\*\*", TERMS.read_text())
    assert found is not None
    assert found.group(1) == PROCESSOR_TERMS_VERSION


def test_create_records_the_terms_signed() -> None:
    gym = parse_gym([*WITHOUT_TERMS, *SIGNED])
    assert (gym.processor_terms, gym.signed_on) == (
        PROCESSOR_TERMS_VERSION,
        date.fromisoformat(PROCESSOR_TERMS_VERSION),
    )


def test_an_instance_the_company_does_not_host_signs_none() -> None:
    gym = parse_gym([*WITHOUT_TERMS, "--no-processor-terms"])
    assert (gym.processor_terms, gym.signed_on) == (None, None)


@pytest.mark.parametrize(
    "extra",
    [
        [],
        [*SIGNED, "--no-processor-terms"],
        ["--processor-terms", PROCESSOR_TERMS_VERSION],
        ["--signed-on", PROCESSOR_TERMS_VERSION],
        ["--no-processor-terms", "--signed-on", PROCESSOR_TERMS_VERSION],
    ],
)
def test_create_needs_the_terms_or_to_be_told_there_are_none(
    extra: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        parse_command([*WITHOUT_TERMS, *extra])
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
def test_a_gym_created_with_the_terms_has_them_recorded(db: Database) -> None:
    gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}").model_copy(
        update={"processor_terms": PROCESSOR_TERMS_VERSION, "signed_on": SIGNED_ON}
    )
    created = create(db, gym)
    assert signatures(db, created.gym_id) == [(PROCESSOR_TERMS_VERSION, SIGNED_ON)]


@pytest.mark.postgres
def test_a_gym_created_without_them_has_none(db: Database) -> None:
    created = create(db, new_gym(f"meta-{uuid.uuid4().hex[:6]}"))
    assert signatures(db, created.gym_id) == []


@pytest.mark.postgres
def test_a_gym_that_exists_signs_them_once(db: Database) -> None:
    gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}")
    created = create(db, gym)
    signing = Signing(slug=gym.slug, processor_terms=PROCESSOR_TERMS_VERSION, signed_on=SIGNED_ON)

    first = sign(db, signing)
    again = sign(db, signing.model_copy(update={"signed_on": gym_today(SIGNED_IN)}))

    assert (first.gym_id, first.name, first.recorded) == (created.gym_id, gym.name, True)
    assert (again.gym_id, again.recorded) == (created.gym_id, False)
    assert signatures(db, created.gym_id) == [(PROCESSOR_TERMS_VERSION, SIGNED_ON)]


@pytest.mark.postgres
def test_no_gym_with_the_slug_signs_nothing(db: Database) -> None:
    signing = Signing(
        slug=f"nadie-{uuid.uuid4().hex[:6]}",
        processor_terms=PROCESSOR_TERMS_VERSION,
        signed_on=SIGNED_ON,
    )
    assert sign(db, signing) is None


@pytest.mark.postgres
def test_a_gym_sees_only_its_own_signatures(db: Database) -> None:
    ours = create(
        db,
        new_gym(f"meta-{uuid.uuid4().hex[:6]}").model_copy(
            update={"processor_terms": PROCESSOR_TERMS_VERSION, "signed_on": SIGNED_ON}
        ),
    )
    other = create(db, new_gym(f"otro-{uuid.uuid4().hex[:6]}"))

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
