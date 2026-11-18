"""The platform's panel edits a gym: its name, its titular's contact, the terms it
signed, and its slug, the old one redirecting for 90 days (#438).

- `gym_slug_alias`: a slug a gym had, and until when its host redirects to the gym's
  current one. While it is live no other gym can take it, through `gym_create` or a
  rename. Gym-scoped, with RLS forced as every gym's table; only `rakin_platform`
  writes it and only `rakin_auth` reads across gyms.
- `auth_gym_alias`: the current slug of the gym a live alias names, for the host's
  redirect (`app.hosts`) and Caddy's TLS `ask`. `SECURITY DEFINER`, owned by
  `rakin_auth`, as `auth_gym_by_slug` (0030) is; the API and the owner may call it.
- `platform_gym`: one gym as its edit screen shows it, the titular's contact, whether
  the titular ever signed in there, every signature of the terms and the live aliases.
- `platform_edit_gym`: the gym's name, and its titular's name, phone and email, a NULL
  leaving each as it is. The email only while the titular has never signed in to the
  gym, any `auth_session` row of theirs there; after, it raises `titular_handover`, as
  changing the address that signs in would hand the account over without #321. Logs
  `gym_edited` with the names of the fields that changed, never their values.
- `platform_record_terms`: `app.gyms.record_terms` from the panel: a version the gym
  signed already changes nothing and keeps the first date. Logs `terms_recorded` only
  when it recorded one.
- `platform_rename_gym`: a new slug, with a session proved within 10 minutes. Refuses
  one a gym has, or another gym's live alias (`gym_slug_taken`); keeps the old slug as
  an alias for 90 days; drops this gym's own alias of the new one, renaming back; logs
  `gym_renamed` with `{from, to}`.
- `platform_slug_taken` (0077) counts another gym's live alias as taken, and takes the
  gym being renamed, whose own aliases are not; `gym_create` (0077) refuses a live
  alias, answering the gym it redirects to.

`gym_create` is rebuilt from 0077's own text, patched by string replacement, as 0077
rebuilds 0076's `platform_gyms`. Each patch asserts it matches once, so 0077's
`CREATE` must not be reformatted or edited.

Revision ID: 0078
Revises: 0077
Create Date: 2026-11-18

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"
PLATFORM_ROLE = "rakin_platform"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# 0030's CHECK, which a gym's slug is held to.
SLUG_CHECK = "slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'"

# How long an old slug redirects, and is no other gym's to take.
ALIAS_DAYS = 90

# How recent a proof a rename asks for: `app.platform.session.FRESH`.
FRESH = "10 minutes"

OLD_ACTIONS = (
    "operator_granted",
    "operator_revoked",
    "operator_signed_in",
    "operator_signed_out",
    "gym_created",
    "owner_link_sent",
    "owner_link_failed",
)
NEW_ACTIONS = ("gym_edited", "terms_recorded", "gym_renamed")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


TABLE = (
    f"""
CREATE TABLE gym_slug_alias (
    slug text PRIMARY KEY CHECK ({SLUG_CHECK}),
    gym_id uuid NOT NULL REFERENCES gym (id) ON DELETE CASCADE,
    until timestamptz NOT NULL
)
""",
    "CREATE INDEX gym_slug_alias_gym_idx ON gym_slug_alias (gym_id)",
    "ALTER TABLE gym_slug_alias ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE gym_slug_alias FORCE ROW LEVEL SECURITY",
    "CREATE POLICY gym_slug_alias_isolation ON gym_slug_alias"
    f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})",
)

# By column, as its grants on `gym` are: it reads nothing it is not given.
AUTH_GRANTS = ("GRANT SELECT (slug, gym_id, until) ON gym_slug_alias TO {role}",)

# What the edits write, and no more: 0076's grants read the rest.
PLATFORM_GRANTS = (
    "GRANT SELECT, INSERT, UPDATE, DELETE ON gym_slug_alias TO {role}",
    "GRANT UPDATE (name, slug) ON gym TO {role}",
    "GRANT SELECT (phone) ON gym_person TO {role}",
    "GRANT UPDATE (name, phone, email, updated_at) ON gym_person TO {role}",
    "GRANT INSERT (gym_id, version, signed_on) ON processor_terms TO {role}",
    "GRANT SELECT (person_id) ON auth_session TO {role}",
)

ALIAS = "auth_gym_alias(text)"
ALIAS_FUNCTION = """
CREATE FUNCTION auth_gym_alias(wanted text)
RETURNS TABLE (slug text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT g.slug
    FROM public.gym_slug_alias a
    JOIN public.gym g ON g.id = a.gym_id
    WHERE a.slug = wanted AND a.until > now()
$$
"""

# Qualified names and a fixed search_path, as in 0076.
DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

OLD_SLUG_TAKEN = "platform_slug_taken(bytea, text)"
SLUG_TAKEN = "platform_slug_taken(bytea, text, uuid)"
GYM = "platform_gym(bytea, uuid)"
EDIT = "platform_edit_gym(bytea, uuid, text, text, text, text)"
TERMS = "platform_record_terms(bytea, uuid, text, date)"
RENAME = "platform_rename_gym(bytea, uuid, text)"

FUNCTIONS = {
    SLUG_TAKEN: f"""
CREATE FUNCTION platform_slug_taken(session bytea, wanted text, renaming uuid DEFAULT NULL)
RETURNS boolean
LANGUAGE plpgsql STABLE {DEFINER} AS $$
BEGIN
    PERFORM public.platform_operator_of(session);
    -- A gym's slug, or another gym's that still redirects. The gym being renamed may
    -- go back to a slug of its own.
    RETURN EXISTS (
        SELECT FROM public.gym g
        WHERE g.slug = wanted AND g.id IS DISTINCT FROM renaming
    ) OR EXISTS (
        SELECT FROM public.gym_slug_alias a
        WHERE a.slug = wanted AND a.until > now() AND a.gym_id IS DISTINCT FROM renaming
    );
END
$$
""",
    GYM: f"""
CREATE FUNCTION platform_gym(session bytea, gym uuid)
RETURNS TABLE (
    id uuid,
    slug text,
    name text,
    titular_name text,
    titular_email text,
    titular_phone text,
    titular_signed_in boolean,
    terms jsonb,
    aliases jsonb
)
LANGUAGE plpgsql STABLE {DEFINER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM public.platform_operator_of(session);
    RETURN QUERY
    SELECT g.id, g.slug, g.name,
           holder.name, holder.email, holder.phone,
           coalesce(EXISTS (
               SELECT FROM public.auth_session x
               WHERE x.gym_id = g.id AND x.person_id = holder.person_id
           ), false),
           coalesce((
               SELECT jsonb_agg(jsonb_build_object('version', p.version, 'signed_on', p.signed_on)
                                ORDER BY p.signed_on DESC, p.recorded_at DESC)
               FROM public.processor_terms p WHERE p.gym_id = g.id
           ), '[]'::jsonb),
           coalesce((
               SELECT jsonb_agg(jsonb_build_object('slug', a.slug, 'until', a.until)
                                ORDER BY a.until DESC)
               FROM public.gym_slug_alias a WHERE a.gym_id = g.id AND a.until > now()
           ), '[]'::jsonb)
    FROM public.gym g
    LEFT JOIN LATERAL (
        SELECT gp.person_id, gp.name, gp.email, gp.phone
        FROM public.staff s
        JOIN public.gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
        WHERE s.gym_id = g.id AND s.account_holder
        LIMIT 1
    ) holder ON true
    WHERE g.id = gym;
END
$$
""",
    EDIT: f"""
CREATE FUNCTION platform_edit_gym(
    session bytea, gym uuid, new_name text, owner_name text, owner_phone text, owner_email text
)
RETURNS TABLE (slug text, fields text[])
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    found_name text;
    holder record;
    changed text[] := '{{}}';
BEGIN
    found_operator := public.platform_operator_of(session);
    SELECT g.slug, g.name INTO found_slug, found_name
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    PERFORM set_config('app.gym_id', gym::text, true);
    IF new_name IS NOT NULL AND new_name IS DISTINCT FROM found_name THEN
        UPDATE public.gym g SET name = new_name WHERE g.id = gym;
        changed := changed || 'name'::text;
    END IF;
    IF coalesce(owner_name, owner_phone, owner_email) IS NOT NULL THEN
        SELECT gp.person_id, gp.name, gp.phone, gp.email INTO holder
        FROM public.staff s
        JOIN public.gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
        WHERE s.gym_id = gym AND s.account_holder
        LIMIT 1
        FOR UPDATE OF gp;
        IF holder.person_id IS NULL THEN
            RAISE EXCEPTION 'the gym has no titular'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'no_titular';
        END IF;
        IF owner_name IS NOT NULL AND owner_name IS DISTINCT FROM holder.name THEN
            changed := changed || 'owner_name'::text;
        END IF;
        IF owner_phone IS NOT NULL AND owner_phone IS DISTINCT FROM holder.phone THEN
            changed := changed || 'owner_phone'::text;
        END IF;
        IF owner_email IS NOT NULL
           AND lower(owner_email) IS DISTINCT FROM lower(holder.email) THEN
            -- Once they signed in here, the address that signs in is theirs: a change
            -- of it is a handover (#321), never an edit.
            IF EXISTS (
                SELECT FROM public.auth_session x
                WHERE x.gym_id = gym AND x.person_id = holder.person_id
            ) THEN
                RAISE EXCEPTION 'the titular has signed in: a new address is a handover'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'titular_handover';
            END IF;
            changed := changed || 'owner_email'::text;
        END IF;
        -- Their record in this gym only: another gym's of the same person stays.
        UPDATE public.gym_person gp
        SET name = CASE WHEN 'owner_name' = ANY (changed) THEN owner_name ELSE gp.name END,
            phone = CASE WHEN 'owner_phone' = ANY (changed) THEN owner_phone ELSE gp.phone END,
            email = CASE WHEN 'owner_email' = ANY (changed) THEN owner_email ELSE gp.email END,
            updated_at = now()
        WHERE gp.gym_id = gym AND gp.person_id = holder.person_id
          AND changed && ARRAY['owner_name', 'owner_phone', 'owner_email'];
    END IF;
    IF cardinality(changed) > 0 THEN
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_edited', gym, jsonb_build_object(
            'slug', found_slug, 'fields', to_jsonb(changed)
        ));
    END IF;
    slug := found_slug;
    fields := changed;
    RETURN NEXT;
END
$$
""",
    TERMS: f"""
CREATE FUNCTION platform_record_terms(
    session bytea, gym uuid, p_version text, p_signed_on date
)
RETURNS boolean
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
DECLARE
    found_operator uuid;
    found_slug text;
    recorded boolean;
BEGIN
    found_operator := public.platform_operator_of(session);
    SELECT g.slug INTO found_slug FROM public.gym g WHERE g.id = gym;
    IF found_slug IS NULL THEN
        RETURN NULL;
    END IF;
    PERFORM set_config('app.gym_id', gym::text, true);
    -- A version signed already keeps its first date (`app.gyms.record_terms`).
    INSERT INTO public.processor_terms (gym_id, version, signed_on)
    VALUES (gym, p_version, p_signed_on)
    ON CONFLICT (gym_id, version) DO NOTHING
    RETURNING true INTO recorded;
    IF recorded THEN
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'terms_recorded', gym, jsonb_build_object(
            'slug', found_slug, 'terms_version', p_version
        ));
    END IF;
    RETURN coalesce(recorded, false);
END
$$
""",
    RENAME: f"""
CREATE FUNCTION platform_rename_gym(session bytea, gym uuid, new_slug text)
RETURNS TABLE (old_slug text, until timestamptz)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    kept_until timestamptz := now() + interval '{ALIAS_DAYS} days';
BEGIN
    -- What cannot be undone asks for a recent proof (`require_fresh`).
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug INTO found_slug FROM public.gym g WHERE g.id = gym;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    IF found_slug = new_slug THEN
        old_slug := found_slug;
        until := NULL;
        RETURN NEXT;
        RETURN;
    END IF;
    -- The locks `gym_create` takes on a slug, both in one order, so a creation of
    -- either slug waits for the rename and then finds it.
    PERFORM pg_advisory_xact_lock(hashtextextended('gym_slug:' || s, 0))
    FROM unnest(ARRAY[found_slug, new_slug]) s ORDER BY s;
    PERFORM FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF EXISTS (SELECT FROM public.gym g WHERE g.slug = new_slug)
       OR EXISTS (
           SELECT FROM public.gym_slug_alias a
           WHERE a.slug = new_slug AND a.until > now() AND a.gym_id <> gym
       ) THEN
        RAISE EXCEPTION 'a gym has this slug, or redirects from it'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'gym_slug_taken';
    END IF;
    PERFORM set_config('app.gym_id', gym::text, true);
    UPDATE public.gym g SET slug = new_slug WHERE g.id = gym;
    -- Renaming back, the gym's own alias of the slug goes; one lapsed of another
    -- gym's goes too, as nothing redirects from it any more.
    DELETE FROM public.gym_slug_alias a
    WHERE a.slug = new_slug AND (a.gym_id = gym OR a.until <= now());
    INSERT INTO public.gym_slug_alias (slug, gym_id, until)
    VALUES (found_slug, gym, kept_until)
    ON CONFLICT (slug) DO UPDATE SET gym_id = EXCLUDED.gym_id, until = EXCLUDED.until;
    INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
    VALUES (found_operator, 'gym_renamed', gym, jsonb_build_object(
        'from', found_slug, 'to', new_slug
    ));
    old_slug := found_slug;
    until := kept_until;
    RETURN NEXT;
END
$$
""",
}


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A slug that still redirects is taken too: the gym it redirects to is the answer, as
# a gym's own slug answers that gym.
LIVE_ALIAS = """    SELECT g.id, g.name INTO found_id, found_name FROM auth_gym_by_slug(p_slug) g;
    IF found_id IS NULL THEN
        SELECT g.id, g.name INTO found_id, found_name
        FROM auth_gym_alias(p_slug) a, auth_gym_by_slug(a.slug) g;
    END IF;
"""


def gym_create(*, aliases: bool) -> str:
    """0077's `gym_create`, as `CREATE OR REPLACE`; with `aliases`, refusing a live one."""
    old = _migration("0077_gym_create.py")
    sql: str = old.CREATE.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if not aliases:
        return sql
    for before, after in (
        (
            "    -- Live slugs only: #438's renamed slugs, kept 90 days, are to be taken"
            " here too.\n",
            "    -- A gym's slug, or one that still redirects to a gym (0078).\n",
        ),
        (
            "    SELECT g.id, g.name INTO found_id, found_name FROM auth_gym_by_slug(p_slug) g;\n",
            LIVE_ALIAS,
        ),
    ):
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def _actions(actions: Sequence[str], *, valid: bool = True) -> None:
    op.execute("ALTER TABLE platform_event DROP CONSTRAINT platform_event_action_check")
    op.execute(
        "ALTER TABLE platform_event ADD CONSTRAINT platform_event_action_check"
        f" CHECK (action IN {_in(actions)}){'' if valid else ' NOT VALID'}"
    )


def _revoke(grant: str, role: str) -> str:
    return grant.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM ").format(role=role)


def upgrade() -> None:
    _actions((*OLD_ACTIONS, *NEW_ACTIONS))
    # asyncpg runs one statement per call.
    for statement in TABLE:
        op.execute(statement)
    for grant in AUTH_GRANTS:
        op.execute(grant.format(role=AUTH_ROLE))
    for grant in PLATFORM_GRANTS:
        op.execute(grant.format(role=PLATFORM_ROLE))

    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(ALIAS_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {ALIAS} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ALIAS} TO {APP_ROLE}")
    # The owner's `gym_create` asks it, as it asks `auth_gym_by_slug`.
    op.execute(f"GRANT EXECUTE ON FUNCTION {ALIAS} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {ALIAS} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    # Owned by the owner still: a replace keeps the owner and the grants.
    op.execute(gym_create(aliases=True))

    op.execute(f"DROP FUNCTION {OLD_SLUG_TAKEN}")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in FUNCTIONS.items():
        op.execute(statement)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    old = _migration("0077_gym_create.py")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(old.FUNCTIONS[OLD_SLUG_TAKEN])
    op.execute(f"REVOKE ALL ON FUNCTION {OLD_SLUG_TAKEN} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {OLD_SLUG_TAKEN} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {OLD_SLUG_TAKEN} OWNER TO {PLATFORM_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")

    op.execute(gym_create(aliases=False))
    op.execute(f"DROP FUNCTION {ALIAS}")
    for grant in PLATFORM_GRANTS:
        op.execute(_revoke(grant, PLATFORM_ROLE))
    for grant in AUTH_GRANTS:
        op.execute(_revoke(grant, AUTH_ROLE))
    op.execute("DROP TABLE gym_slug_alias")
    # The log keeps its rows, these included: the old CHECK holds new rows only.
    _actions(OLD_ACTIONS, valid=False)
