"""Gastos: every gym has its expense categories, a suspended one included (#525).

0083 gave the gyms already here their default categories through `jobs_gym_ids()`,
which since 0079 lists only the gyms the nightly jobs work on today: not a suspended
gym, nor a resumed one the jobs have not caught up on. Such a gym got none, and an
expense cannot be recorded without one. This gives every gym its defaults;
`add_default_expense_categories` skips a gym that has categories already, so the gyms
0083 reached, and every gym created since (the `gym` insert trigger), are left as they
are.

A backfill wants every gym, and the jobs' list is the wrong one for it. So this adds
`migration_gym_ids()`: every gym's id, suspended or not, for the owner running a
migration, which FORCEd RLS holds to the gym in `app.gym_id` and so cannot list them
itself. It is `SECURITY DEFINER` and owned by `rakin_auth`, as 0011's `jobs_gym_ids()`
is, returns only ids, and only the owner may call it. It stays, for the next backfill.

The other per-gym backfills, 0028's block kinds, 0065's preset titles and 0071's
team, ran before 0079 narrowed `jobs_gym_ids()`, when it still listed every gym: they
have no such gap.

A downgrade drops `migration_gym_ids()` and leaves the categories: 0083's downgrade
drops them all.

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-21

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTH_ROLE = "rakin_auth"

SIGNATURE = "migration_gym_ids()"

# Qualified names and a fixed search_path, as in 0011. `rakin_auth` reads `gym.id`
# already (0011).
FUNCTION = """
CREATE FUNCTION migration_gym_ids()
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT id FROM public.gym ORDER BY id
$$
"""

BACKFILL = """
DO $$
DECLARE
    g uuid;
BEGIN
    FOR g IN SELECT migration_gym_ids() LOOP
        PERFORM add_default_expense_categories(g);
    END LOOP;
END
$$
"""


def upgrade() -> None:
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer (0011).
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    # The owner running this migration.
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    op.execute(BACKFILL)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
