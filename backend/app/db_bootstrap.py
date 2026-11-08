"""Database roles, created once per database by a superuser, before any migration.

    uv run python -m app.db_bootstrap postgresql://postgres:secret@host:5432/rakin

The argument is a superuser connection to the database to bootstrap. The two roles it
provisions come from the settings, user and password included:

- `MIGRATION_DATABASE_URL` names the owner: a plain login role that owns the database
  (and so its `public` schema) and every table the migrations create. It is not a
  superuser and does not bypass RLS.
- `DATABASE_URL` names the API's login user, made a member of `rakin_app`: the role
  migrations grant table privileges to. `rakin_app` cannot log in, owns nothing and
  does not bypass RLS, so row-level security always applies to the API.

Re-running is safe: missing roles are created, existing ones get their password and
attributes reset to the above.
"""

import argparse
import asyncio

import asyncpg
from sqlalchemy.engine import make_url

from app.settings import Settings, get_settings

APP_ROLE = "rakin_app"

# Attributes every role here must have; Postgres takes them on CREATE and ALTER alike.
SAFE = "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"


def to_dsn(url: str) -> str:
    """A SQLAlchemy URL as a plain libpq DSN asyncpg accepts."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def credentials(url: str) -> tuple[str, str]:
    parsed = make_url(url)
    if not parsed.username or parsed.password is None:
        raise SystemExit(f"{parsed.render_as_string()}: needs a user and a password")
    return parsed.username, parsed.password


async def ensure_role(conn: asyncpg.Connection, name: str, attributes: str) -> None:
    ident = await conn.fetchval("SELECT quote_ident($1)", name)
    exists = await conn.fetchval("SELECT EXISTS (SELECT FROM pg_roles WHERE rolname = $1)", name)
    await conn.execute(f"{'ALTER' if exists else 'CREATE'} ROLE {ident} {attributes}")


async def ensure_login(conn: asyncpg.Connection, name: str, password: str) -> None:
    # Never demote an existing superuser (such as the one running this) into an app role.
    if await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = $1", name):
        raise SystemExit(f"{name} is a superuser; give the API and the owner their own users")
    await ensure_role(conn, name, f"LOGIN {SAFE}")
    # Passwords can't be bound parameters in DDL; quote_literal escapes them.
    ident = await conn.fetchval("SELECT quote_ident($1)", name)
    literal = await conn.fetchval("SELECT quote_literal($1)", password)
    await conn.execute(f"ALTER ROLE {ident} PASSWORD {literal}")


async def bootstrap(admin_url: str, settings: Settings) -> None:
    owner, owner_password = credentials(settings.migration_database_url)
    api, api_password = credentials(settings.database_url)
    if owner == api:
        raise SystemExit("MIGRATION_DATABASE_URL and DATABASE_URL must use different users")

    conn = await asyncpg.connect(to_dsn(admin_url))
    try:
        if not await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"):
            raise SystemExit("bootstrap needs a superuser connection")
        async with conn.transaction():
            await ensure_login(conn, owner, owner_password)
            await ensure_role(conn, APP_ROLE, f"NOLOGIN {SAFE}")
            await ensure_login(conn, api, api_password)
            owner_ident, api_ident, database = await conn.fetchrow(
                "SELECT quote_ident($1), quote_ident($2), quote_ident(current_database())",
                owner,
                api,
            )
            await conn.execute(f"GRANT {APP_ROLE} TO {api_ident}")
            # The database owner owns `public` too (via pg_database_owner, Postgres 15+).
            await conn.execute(f"ALTER DATABASE {database} OWNER TO {owner_ident}")
            await conn.execute(f"GRANT ALL ON SCHEMA public TO {owner_ident}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the owner and API database roles.")
    parser.add_argument("admin_url", help="superuser connection to the database to bootstrap")
    args = parser.parse_args()
    asyncio.run(bootstrap(args.admin_url, get_settings()))


if __name__ == "__main__":
    main()
