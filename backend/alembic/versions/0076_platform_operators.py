"""Platform operators: who runs the gyms Rakin hosts, their sign-in, and their log (#436).

The platform's panel (`/plataforma` on the base host, #433) is the one place that
looks across gyms. Its people are not anyone's members, so they get tables of their
own, apart from `person` and every gym:

- `platform_operator`: who may use the panel. Written only by `python -m
  app.operators`, connected as the owner; `revoked_at` ends someone without losing who
  they were. `email` is stored lower-case.
- `operator_link` and `operator_session`: their sign-in links (with the code) and
  sessions, shaped as `auth_link` and `auth_session` are, keyed by the token's hash. A
  session lasts 8 hours from sign-in, whatever happens in it; `fresh_at` is when its
  operator last proved who they are, for the actions that ask for a recent proof.
- `platform_event`: the panel's log, append-only as `audit_event` is (0048), the owner
  included. `operator_id` is who acted, `NULL` for the command line (`detail.by =
  'cli'`). `gym_id` has no foreign key, so a row outlives a gym removed later. `detail`
  names slugs and the fields that changed, never anyone's data.

`rakin_app`, the API, gets no privilege on any of them. Everything it does goes through
`SECURITY DEFINER` functions owned by `rakin_platform` (`app.db_bootstrap`), which
bypasses RLS, as 0005's and 0030's are owned by `rakin_auth`. **Each function that
reads or writes a gym takes the operator's session hash and checks the session itself**
(`platform_operator_of`), so the gate holds in the database and not only in the API:
the API's role alone reads no gym but the one `app.gym_id` names.

- `platform_issue_link`: stores a link for a live operator's address and answers with
  who they are, for the email; for anyone else it stores nothing and answers no row.
  The API runs it after answering, as it looks people up for gyms.
- `platform_redeem_link`: spends a link, by its hash or its code's, and starts a session.
- `platform_live_session`, `platform_refresh`, `platform_end_session`: a session's
  operator, a fresh proof by code, signing out.
- `platform_gyms`: one row per gym, counts and dates only, for the list.

Every time these functions read or write is the database's `now()`, never one the API
passes: one clock, so a session cannot be live to one function and dead to the next.

Run `python -m app.db_bootstrap` before this migration: it creates `rakin_platform`.

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-18

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
PLATFORM_ROLE = "rakin_platform"

# How long a session lasts from sign-in: a working day, never extended.
SESSION_HOURS = 8

ACTIONS = ("operator_granted", "operator_revoked", "operator_signed_in", "operator_signed_out")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


TABLES = (
    """
CREATE TABLE platform_operator (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE CHECK (email = lower(btrim(email)) AND email LIKE '_%@_%'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
)
""",
    """
CREATE TABLE operator_link (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    operator_id uuid NOT NULL REFERENCES platform_operator (id),
    code_hash bytea CHECK (octet_length(code_hash) = 32),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX operator_link_code_idx ON operator_link (code_hash) WHERE code_hash IS NOT NULL",
    """
CREATE TABLE operator_session (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    operator_id uuid NOT NULL REFERENCES platform_operator (id),
    created_at timestamptz NOT NULL,
    fresh_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    ended_at timestamptz
)
""",
    "CREATE INDEX operator_session_operator_idx ON operator_session (operator_id)"
    " WHERE ended_at IS NULL",
    f"""
CREATE TABLE platform_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    at timestamptz NOT NULL DEFAULT now(),
    operator_id uuid REFERENCES platform_operator (id),
    action text NOT NULL CHECK (action IN {_in(ACTIONS)}),
    gym_id uuid,
    detail jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    CHECK (operator_id IS NOT NULL OR (detail ->> 'by') IS NOT DISTINCT FROM 'cli')
)
""",
    "CREATE INDEX platform_event_at_idx ON platform_event (at DESC)",
    """
CREATE FUNCTION platform_event_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'platform_event rows cannot change or be deleted'
        USING ERRCODE = 'restrict_violation';
END
$$
""",
    "CREATE TRIGGER platform_event_append_only BEFORE UPDATE OR DELETE ON platform_event"
    " FOR EACH ROW EXECUTE FUNCTION platform_event_append_only()",
    "CREATE TRIGGER platform_event_no_truncate BEFORE TRUNCATE ON platform_event"
    " FOR EACH STATEMENT EXECUTE FUNCTION platform_event_append_only()",
)

# What `rakin_platform` reads and writes, and no more: the gyms' columns are those the
# list counts or shows.
GRANTS = (
    "GRANT SELECT ON platform_operator TO {role}",
    "GRANT SELECT, INSERT, UPDATE ON operator_link, operator_session TO {role}",
    "GRANT INSERT ON platform_event TO {role}",
    "GRANT SELECT (id, slug, name, timezone, created_at) ON gym TO {role}",
    "GRANT SELECT (gym_id, person_id, account_holder) ON staff TO {role}",
    "GRANT SELECT (gym_id, person_id, name, email) ON gym_person TO {role}",
    "GRANT SELECT (gym_id, version, signed_on, recorded_at) ON processor_terms TO {role}",
    "GRANT SELECT (gym_id, person_id, status) ON membership TO {role}",
    "GRANT SELECT (gym_id, marked_at) ON attendance TO {role}",
    "GRANT SELECT (gym_id, created_at) ON ledger_entry TO {role}",
    "GRANT SELECT (gym_id, created_at) ON auth_session TO {role}",
)

# Qualified names and a fixed search_path, as in 0005.
DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

# The gate every function that touches a gym passes first: the operator of a live
# session, one whose proof is at most `fresh` old when given; else it raises. Not a
# definer and not the API's to call: it runs as the definer functions that call it.
GATE = (
    "platform_operator_of(bytea, interval)",
    """
CREATE FUNCTION platform_operator_of(session bytea, fresh interval DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    found_operator uuid;
    proved timestamptz;
BEGIN
    SELECT s.operator_id, s.fresh_at INTO found_operator, proved
    FROM public.operator_session s
    JOIN public.platform_operator o ON o.id = s.operator_id
    WHERE s.token_hash = session AND s.ended_at IS NULL AND s.expires_at > now()
      AND o.revoked_at IS NULL;
    IF found_operator IS NULL THEN
        RAISE EXCEPTION 'no live operator session' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF fresh IS NOT NULL AND proved < now() - fresh THEN
        RAISE EXCEPTION 'the operator session is not fresh'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN found_operator;
END
$$
""",
)

FUNCTIONS = {
    "platform_issue_link(text, bytea, bytea, timestamptz)": f"""
CREATE FUNCTION platform_issue_link(
    address text, link_hash bytea, code bytea, expires timestamptz
)
RETURNS TABLE (operator_id uuid, name text)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_name text;
BEGIN
    SELECT o.id, o.name INTO found_operator, found_name
    FROM public.platform_operator o
    WHERE o.email = lower(btrim(address)) AND o.revoked_at IS NULL;
    IF found_operator IS NULL THEN
        RETURN;
    END IF;
    -- Asking again ends every earlier code, as for a gym's links (0047).
    UPDATE public.operator_link SET code_hash = NULL
    WHERE operator_id = found_operator AND code_hash IS NOT NULL;
    INSERT INTO public.operator_link (token_hash, operator_id, code_hash, expires_at)
    VALUES (link_hash, found_operator, code, expires);
    operator_id := found_operator;
    name := found_name;
    RETURN NEXT;
END
$$
""",
    "platform_redeem_link(bytea, bytea, bytea)": f"""
CREATE FUNCTION platform_redeem_link(
    link_hash bytea, code bytea, session bytea
)
RETURNS boolean
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
DECLARE
    spent bytea;
    found_operator uuid;
BEGIN
    IF (link_hash IS NULL) = (code IS NULL) THEN
        RAISE EXCEPTION 'a link or a code, one of them';
    END IF;
    -- Of two redemptions at once, the second waits on the row lock, then finds it used.
    SELECT l.token_hash, l.operator_id INTO spent, found_operator
    FROM public.operator_link l
    JOIN public.platform_operator o ON o.id = l.operator_id
    WHERE (l.token_hash = link_hash OR l.code_hash = code)
      AND l.used_at IS NULL AND l.expires_at > now() AND o.revoked_at IS NULL
    ORDER BY l.created_at DESC
    LIMIT 1
    FOR UPDATE OF l;
    IF spent IS NULL THEN
        RETURN false;
    END IF;
    -- Spending the link spends its code, and the other way round.
    UPDATE public.operator_link SET used_at = now(), code_hash = NULL WHERE token_hash = spent;
    INSERT INTO public.operator_session (token_hash, operator_id, created_at, fresh_at, expires_at)
    VALUES (session, found_operator, now(), now(), now() + interval '{SESSION_HOURS} hours');
    INSERT INTO public.platform_event (operator_id, action)
    VALUES (found_operator, 'operator_signed_in');
    RETURN true;
END
$$
""",
    "platform_live_session(bytea)": f"""
CREATE FUNCTION platform_live_session(session bytea)
RETURNS TABLE (
    operator_id uuid, email text, name text, fresh_at timestamptz, expires_at timestamptz
)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT o.id, o.email, o.name, s.fresh_at, s.expires_at
    FROM public.operator_session s
    JOIN public.platform_operator o ON o.id = s.operator_id
    WHERE s.token_hash = session AND s.ended_at IS NULL AND s.expires_at > now()
      -- Revoked, the operator loses the session at once, not in 8 hours.
      AND o.revoked_at IS NULL
$$
""",
    "platform_refresh(bytea, bytea)": f"""
CREATE FUNCTION platform_refresh(session bytea, code bytea)
RETURNS boolean
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
DECLARE
    found_operator uuid;
    spent bytea;
BEGIN
    found_operator := public.platform_operator_of(session);
    SELECT l.token_hash INTO spent
    FROM public.operator_link l
    WHERE l.code_hash = code AND l.operator_id = found_operator
      AND l.used_at IS NULL AND l.expires_at > now()
    ORDER BY l.created_at DESC
    LIMIT 1
    FOR UPDATE OF l;
    IF spent IS NULL THEN
        RETURN false;
    END IF;
    UPDATE public.operator_link SET used_at = now(), code_hash = NULL WHERE token_hash = spent;
    UPDATE public.operator_session SET fresh_at = now() WHERE token_hash = session;
    RETURN true;
END
$$
""",
    "platform_end_session(bytea)": f"""
CREATE FUNCTION platform_end_session(session bytea)
RETURNS void
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
DECLARE
    found_operator uuid;
BEGIN
    UPDATE public.operator_session SET ended_at = now()
    WHERE token_hash = session AND ended_at IS NULL
    RETURNING operator_id INTO found_operator;
    IF found_operator IS NOT NULL THEN
        INSERT INTO public.platform_event (operator_id, action)
        VALUES (found_operator, 'operator_signed_out');
    END IF;
END
$$
""",
    "platform_gyms(bytea, text)": f"""
CREATE FUNCTION platform_gyms(session bytea, current_terms text)
RETURNS TABLE (
    id uuid,
    slug text,
    name text,
    timezone text,
    created_at timestamptz,
    titular_name text,
    titular_email text,
    terms_version text,
    terms_signed_on date,
    terms_current boolean,
    members bigint,
    staff bigint,
    last_activity timestamptz,
    status text
)
LANGUAGE plpgsql STABLE {DEFINER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM public.platform_operator_of(session);
    RETURN QUERY
    SELECT g.id, g.slug, g.name, g.timezone, g.created_at,
           holder.name, holder.email,
           terms.version, terms.signed_on, coalesce(terms.version = current_terms, false),
           (SELECT count(DISTINCT m.person_id) FROM public.membership m
            WHERE m.gym_id = g.id AND m.status IN ('active', 'frozen')),
           (SELECT count(*) FROM public.staff s WHERE s.gym_id = g.id),
           -- GREATEST skips a NULL: a gym with no classes yet still has its sign-ins.
           GREATEST(
               (SELECT max(a.marked_at) FROM public.attendance a WHERE a.gym_id = g.id),
               (SELECT max(e.created_at) FROM public.ledger_entry e WHERE e.gym_id = g.id),
               (SELECT max(x.created_at) FROM public.auth_session x WHERE x.gym_id = g.id)
           ),
           'active'::text
    FROM public.gym g
    LEFT JOIN LATERAL (
        SELECT gp.name, gp.email
        FROM public.staff s
        JOIN public.gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
        WHERE s.gym_id = g.id AND s.account_holder
        LIMIT 1
    ) holder ON true
    -- The terms in force: the latest signed (0075).
    LEFT JOIN LATERAL (
        SELECT p.version, p.signed_on
        FROM public.processor_terms p
        WHERE p.gym_id = g.id
        ORDER BY p.signed_on DESC, p.recorded_at DESC
        LIMIT 1
    ) terms ON true
    ORDER BY g.name, g.slug;
END
$$
""",
}


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}'
                           AND rolbypassrls AND NOT rolsuper AND NOT rolcanlogin) THEN
                RAISE EXCEPTION '{PLATFORM_ROLE} is missing or wrong;'
                    ' run python -m app.db_bootstrap';
            END IF;
        END
        $$
    """)

    # asyncpg runs one statement per call.
    for statement in TABLES:
        op.execute(statement)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}")
    for grant in GRANTS:
        op.execute(grant.format(role=PLATFORM_ROLE))

    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    signature, statement = GATE
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")
    for signature, statement in FUNCTIONS.items():
        op.execute(statement)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def downgrade() -> None:
    for signature in (*FUNCTIONS, GATE[0]):
        op.execute(f"DROP FUNCTION {signature}")
    for grant in GRANTS[3:]:
        op.execute(
            grant.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM ").format(role=PLATFORM_ROLE)
        )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PLATFORM_ROLE}")
    op.execute("DROP TABLE platform_event, operator_session, operator_link, platform_operator")
    op.execute("DROP FUNCTION platform_event_append_only()")
