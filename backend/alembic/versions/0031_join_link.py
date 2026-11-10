"""The join link: a gym shares one link, people fill in their details, staff approve (#154).

- `join_link` is a gym's one link, at most one per gym: its random `token`, the
  program it pre-selects (`program_id`, optional) and the last day it works
  (`expires_on`, a day in the gym's timezone, optional). Regenerating gives the row a
  new token, so the old one stops working; revoking deletes the row. The token is
  stored as is, not hashed: it is meant to be shared, and the staff screen shows the
  link again whenever it is asked.
- `join_request` is what someone sent through the link, waiting for staff: their
  details, a guardian's when the birth date makes them a minor, and when they
  consented. It is not a person: approving one writes the person through the paths
  that already add people, and deletes the request; rejecting deletes it. The
  nightly `join_requests` job deletes any left for 30 days.

Both are gym-scoped like every table with a `gym_id`: FORCEd RLS on the current gym.

The public form knows only a token, not a gym, so `join_link_gym(token)` answers which
gym it belongs to and nothing else. It is a `SECURITY DEFINER` function owned by
`rakin_auth`, as the sign-in lookups are (0005), which may read only those two columns.
Everything else the form does, it does with `app.gym_id` set to that gym, held to RLS
like any request.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

SIGNATURE = "join_link_gym(text)"

# Qualified names and a fixed search_path, as in 0005.
FUNCTION = """
CREATE FUNCTION join_link_gym(link_token text)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT gym_id FROM public.join_link WHERE token = link_token
$$
"""


def _isolate(table: str, grants: str) -> None:
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table}"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE join_link (
            gym_id uuid PRIMARY KEY REFERENCES gym (id),
            token text NOT NULL UNIQUE CHECK (length(token) >= 20),
            program_id uuid,
            expires_on date,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (gym_id, program_id) REFERENCES program (gym_id, id)
        )
    """)
    _isolate("join_link", "SELECT, INSERT, UPDATE, DELETE")

    op.execute("""
        CREATE TABLE join_request (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            first_name text NOT NULL CHECK (btrim(first_name) <> ''),
            last_name text NOT NULL CHECK (btrim(last_name) <> ''),
            rut text NOT NULL,
            phone text,
            email text,
            dob date NOT NULL,
            guardian_name text,
            guardian_phone text,
            guardian_email text,
            program_id uuid,
            consented_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (gym_id, program_id) REFERENCES program (gym_id, id),
            -- Someone with a guardian has all of the guardian's details; anyone else
            -- has their own phone and email.
            CHECK (
                (guardian_name IS NULL) = (guardian_phone IS NULL)
                AND (guardian_name IS NULL) = (guardian_email IS NULL)
                AND (guardian_name IS NOT NULL OR (phone IS NOT NULL AND email IS NOT NULL))
            )
        )
    """)
    op.execute("CREATE INDEX join_request_gym_created_idx ON join_request (gym_id, created_at)")
    _isolate("join_request", "SELECT, INSERT, DELETE")

    op.execute(f"GRANT SELECT (token, gym_id) ON join_link TO {AUTH_ROLE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(f"REVOKE SELECT (token, gym_id) ON join_link FROM {AUTH_ROLE}")
    op.execute("DROP TABLE join_request")
    op.execute("DROP TABLE join_link")
