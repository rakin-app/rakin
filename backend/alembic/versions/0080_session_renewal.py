"""A session lasts while it is used (#491).

It used to end 30 days after sign-in, however often it was used. Now it ends 35 days
after its last use, and 180 days after sign-in regardless (`app.magiclink.service`):
each use carries `expires_at` on, at most once a day.

- `auth_live_session` also returns the session's `created_at`, its sign-in, which
  bounds how far it may be carried on. Its result type changes, so it is dropped and
  made again from 0079's text, with 0005's grants and owner.
- `auth_renew_session(hash, until, at)` moves a live session's `expires_at` on to
  `until`, never back, and says whether it did. The app reads and ends a session
  before any gym is set, so it renews it the same way, as `rakin_auth`.

Sessions already started keep their `expires_at`; their next use renews them.

0079's lookup is rebuilt from its own text, patched by string replacement, as 0079
does. Each patch asserts it matches once, so that text must not be reformatted.

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-19

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0080"
down_revision: str | Sequence[str] | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

LIVE = "auth_live_session(bytea, timestamptz)"
RENEW = "auth_renew_session(bytea, timestamptz, timestamptz)"

RENEW_FUNCTION = f"""
CREATE FUNCTION auth_renew_session(hash bytea, until timestamptz, at timestamptz)
RETURNS boolean
LANGUAGE sql VOLATILE {DEFINER} AS $$
    WITH renewed AS (
        UPDATE public.auth_session SET expires_at = until
        WHERE token_hash = hash AND ended_at IS NULL AND expires_at > at
          AND expires_at < until
        RETURNING 1
    )
    SELECT EXISTS (SELECT FROM renewed)
$$
"""


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_session(*, signed_in: bool) -> str:
    """0079's `auth_live_session`; with `signed_in`, returning `created_at` too."""
    sql: str = _migration("0079_gym_suspension.py").lookups(suspension=True)[2]
    if not signed_in:
        return sql
    patches = (
        (
            "expires_at timestamptz)\n",
            "expires_at timestamptz,\n                created_at timestamptz)\n",
        ),
        ("s.expires_at\n    FROM", "s.expires_at, s.created_at\n    FROM"),
    )
    for before, after in patches:
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def _create(signature: str, statement: str) -> None:
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {AUTH_ROLE}")


def upgrade() -> None:
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"DROP FUNCTION {LIVE}")
    _create(LIVE, live_session(signed_in=True))
    _create(RENEW, RENEW_FUNCTION)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"DROP FUNCTION {RENEW}")
    op.execute(f"DROP FUNCTION {LIVE}")
    _create(LIVE, live_session(signed_in=False))
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")
