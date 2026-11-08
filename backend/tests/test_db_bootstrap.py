import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import make_url

from app.db_bootstrap import bootstrap
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, run, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        yield database


def test_the_owner_owns_the_database_and_is_not_a_superuser(db: Database) -> None:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole"
            " FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba"
            " WHERE d.datname = current_database()"
        ),
    )
    assert tuple(row) == ("rakin_owner", False, False, False)


def test_both_users_can_log_in(db: Database) -> None:
    assert run(db.owner_url, lambda c: c.fetchval("SELECT current_user")) == "rakin_owner"
    assert run(db.api_url, lambda c: c.fetchval("SELECT current_user")) == "rakin_api"


def test_running_twice_is_harmless(db: Database) -> None:
    asyncio.run(bootstrap(db.admin_url, db.settings))
    assert run(db.api_url, lambda c: c.fetchval("SELECT current_user")) == "rakin_api"


def test_without_a_url_it_connects_with_the_pg_environment_variables(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = make_url(db.admin_url)
    for name, value in {
        "PGHOST": admin.host,
        "PGPORT": admin.port,
        "PGUSER": admin.username,
        "PGPASSWORD": admin.password,
        "PGDATABASE": admin.database,
    }.items():
        monkeypatch.setenv(name, str(value))

    asyncio.run(bootstrap(None, db.settings))

    assert run(db.api_url, lambda c: c.fetchval("SELECT current_user")) == "rakin_api"


def test_refuses_to_turn_a_superuser_into_the_api_user(db: Database) -> None:
    # The admin itself, as in a DATABASE_URL left pointing at the Docker image's user.
    settings = make_settings(
        database_url=db.admin_url, migration_database_url=db.settings.migration_database_url
    )
    with pytest.raises(SystemExit, match="is a superuser"):
        asyncio.run(bootstrap(db.admin_url, settings))
    assert run(
        db.admin_url,
        lambda c: c.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"),
    )


def test_refuses_one_user_for_both_roles(db: Database) -> None:
    settings = make_settings(database_url=db.owner_url, migration_database_url=db.owner_url)
    with pytest.raises(SystemExit, match="different users"):
        asyncio.run(bootstrap(db.admin_url, settings))


def test_refuses_a_non_superuser_connection(db: Database) -> None:
    with pytest.raises(SystemExit, match="superuser connection"):
        asyncio.run(bootstrap(db.owner_url, db.settings))
