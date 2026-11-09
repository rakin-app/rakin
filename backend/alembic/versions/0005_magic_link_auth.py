"""Magic-link sign-in: hashed links and sessions, and the lookups behind them.

Both tables are keyed by `token_hash`, the SHA-256 of a secret only the browser (or
the email) holds, so finding a row needs the token it hashes.

- `auth_link` has no gym and no RLS: the API writes a link and spends it by hash.
- `auth_session.gym_id` is the gym the session acts in, none yet for a person in
  several gyms, who will pick one (#16). It is gym-scoped like every table with a
  `gym_id`: FORCEd RLS on the current gym, with inserts open, as on `person`, since
  a session starts before any gym is set.

Everything sign-in does before a gym is known has to look across gyms, and RLS is
FORCEd for the owner too. So it goes through `SECURITY DEFINER` functions owned by
`rakin_auth` (`app.db_bootstrap`), which bypasses RLS and may touch only what they
need: who an email address belongs to (by each gym's own `gym_person` record), which
gyms a person is in, a live session by hash (only while its person still belongs to
its gym), and ending one. The API may call them and gets back only what sign-in
needs.

Run `python -m app.db_bootstrap` before this migration: it creates `rakin_auth`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

TABLES = (
    """
CREATE TABLE auth_link (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    person_id uuid NOT NULL REFERENCES person (id),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE auth_session (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    person_id uuid NOT NULL REFERENCES person (id),
    gym_id uuid REFERENCES gym (id),
    expires_at timestamptz NOT NULL,
    ended_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
)

# Qualified names and a fixed search_path: a definer function must not resolve
# anything through a schema its caller controls.
DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

FUNCTIONS = {
    "auth_people_by_email(text)": f"""
CREATE FUNCTION auth_people_by_email(address text)
RETURNS TABLE (person_id uuid, name text, email text)
LANGUAGE sql STABLE {DEFINER} AS $$
    -- Each gym's own record of the person (0004), where they have a membership or
    -- staff row in that gym. One row per person: the oldest matching record.
    SELECT DISTINCT ON (g.person_id) g.person_id, g.name, g.email
    FROM public.gym_person g
    WHERE lower(g.email) = lower(btrim(address))
      AND (EXISTS (SELECT FROM public.membership m
                   WHERE m.person_id = g.person_id AND m.gym_id = g.gym_id)
           OR EXISTS (SELECT FROM public.staff s
                      WHERE s.person_id = g.person_id AND s.gym_id = g.gym_id))
    ORDER BY g.person_id, g.created_at
    LIMIT 10
$$
""",
    "auth_gyms_of(uuid)": f"""
CREATE FUNCTION auth_gyms_of(person uuid)
RETURNS SETOF uuid
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT gym_id FROM public.membership WHERE person_id = person
    UNION
    SELECT gym_id FROM public.staff WHERE person_id = person
$$
""",
    "auth_live_session(bytea, timestamptz)": f"""
CREATE FUNCTION auth_live_session(hash bytea, at timestamptz)
RETURNS TABLE (person_id uuid, gym_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT s.person_id, s.gym_id, s.expires_at
    FROM public.auth_session s
    WHERE s.token_hash = hash AND s.ended_at IS NULL AND s.expires_at > at
      -- Someone removed from the gym loses the session at once, not in 30 days.
      AND (s.gym_id IS NULL
           OR EXISTS (SELECT FROM public.membership m
                      WHERE m.person_id = s.person_id AND m.gym_id = s.gym_id)
           OR EXISTS (SELECT FROM public.staff st
                      WHERE st.person_id = s.person_id AND st.gym_id = s.gym_id))
$$
""",
    "auth_end_session(bytea, timestamptz)": f"""
CREATE FUNCTION auth_end_session(hash bytea, at timestamptz)
RETURNS void
LANGUAGE sql VOLATILE {DEFINER} AS $$
    UPDATE public.auth_session SET ended_at = at WHERE token_hash = hash AND ended_at IS NULL
$$
""",
}


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{AUTH_ROLE}'
                           AND rolbypassrls AND NOT rolsuper AND NOT rolcanlogin) THEN
                RAISE EXCEPTION '{AUTH_ROLE} is missing or wrong; run python -m app.db_bootstrap';
            END IF;
        END
        $$
    """)

    # asyncpg runs one statement per call.
    for statement in TABLES:
        op.execute(statement)
    op.execute("CREATE INDEX gym_person_email_lower_idx ON gym_person (lower(email))")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON auth_link, auth_session TO {APP_ROLE}")

    op.execute("ALTER TABLE auth_session ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auth_session FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY auth_session_isolation ON auth_session"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute("CREATE POLICY auth_session_insert ON auth_session FOR INSERT WITH CHECK (true)")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT ON gym_person, membership, staff TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON auth_session TO {AUTH_ROLE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    for signature, statement in FUNCTIONS.items():
        op.execute(statement)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(f"REVOKE SELECT ON gym_person, membership, staff FROM {AUTH_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {AUTH_ROLE}")
    op.execute("DROP INDEX gym_person_email_lower_idx")
    op.execute("DROP TABLE auth_session, auth_link")
