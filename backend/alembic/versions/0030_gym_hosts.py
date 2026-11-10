"""Each gym on its own subdomain (#155): slugs that are host names, and the gym a host names.

A gym is served at `<slug>.<base domain>` (`app.hosts`), so its slug must be a DNS
label: lower-case letters, digits and hyphens, not starting or ending with a hyphen, at
most 63 characters. The names the app keeps for itself (`www`, `api` and so on) are
refused where gyms are created, not here, so the list can grow without a migration.

A request reaches its host's gym before anyone has signed in, and so does Caddy's
question of whether to get a certificate for a host, so the lookup cannot go through
RLS, which shows a role only the gym in `app.gym_id`. `auth_gym_by_slug(slug)` answers
it and nothing else: the gym's id and name, for a slug. It is `SECURITY DEFINER` and
owned by `rakin_auth`, like 0005's lookups, which reads only the three columns it
needs. The API may call it, and so may the owner this migration runs as, which
`python -m app.gyms create` connects as to find a gym it already made.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

# `app.hosts.SLUG`, which the command checks first so it can say what is wrong.
SLUG_CHECK = "slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'"

SIGNATURE = "auth_gym_by_slug(text)"

# Qualified names and a fixed search_path, as in 0005.
FUNCTION = """
CREATE FUNCTION auth_gym_by_slug(wanted text)
RETURNS TABLE (id uuid, name text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT g.id, g.name FROM public.gym g WHERE g.slug = wanted
$$
"""


def upgrade() -> None:
    op.execute(f"ALTER TABLE gym ADD CONSTRAINT gym_slug_is_a_host_label CHECK ({SLUG_CHECK})")

    op.execute(f"GRANT SELECT (name, slug) ON gym TO {AUTH_ROLE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(f"REVOKE SELECT (name, slug) ON gym FROM {AUTH_ROLE}")
    op.execute("ALTER TABLE gym DROP CONSTRAINT gym_slug_is_a_host_label")
