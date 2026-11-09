"""The nightly jobs list every gym's id through one lookup.

The jobs run as the table owner, which FORCEd RLS holds to the gym in `app.gym_id`
(0001), `gym` itself included: with none set it sees no gym, so it cannot find out
which gyms to set. `jobs_gym_ids()` answers that and nothing else. It is a
`SECURITY DEFINER` function owned by `rakin_auth`, the role that bypasses RLS for the
sign-in lookups (0005), and returns only ids; everything else a job does it does with
`app.gym_id` set to one of them, held to RLS as before.

Only the owner may call it: `rakin_app` acts for one gym and has no use for the list.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTH_ROLE = "rakin_auth"

SIGNATURE = "jobs_gym_ids()"

# Qualified names and a fixed search_path, as in 0005.
FUNCTION = """
CREATE FUNCTION jobs_gym_ids()
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT id FROM public.gym ORDER BY id
$$
"""


def upgrade() -> None:
    op.execute(f"GRANT SELECT (id) ON gym TO {AUTH_ROLE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    # The owner running this migration, which the jobs connect as.
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(f"REVOKE SELECT (id) ON gym FROM {AUTH_ROLE}")
