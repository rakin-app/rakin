"""One way to create a gym, for the command line and the platform's panel (#437).

`gym_create` writes a new gym and its owner in one go, what `app.gyms create` wrote
from Python until now: the gym, its programs, its activity when a grading preset brings
one, the name of its free-practice block kind, its owner (`join_gym`, 0036) as the
staff that holds the account, and the Términos de encargo when they were signed (0075).
A slug a gym already has writes nothing and answers that gym, `created = false`; two
creations of one slug at once wait on a lock on it, so the second finds the first's
gym rather than failing on the slug's UNIQUE. The
values come computed from `app.gyms`, which knows the presets; the function only writes
them, so the two callers cannot drift.

It is `SECURITY DEFINER` and owned by the table owner, as `join_gym` is: FORCEd RLS
still holds it to the gym it sets in `app.gym_id`. EXECUTE goes to the owner, whose
command line calls it, and to `rakin_platform`, never to `rakin_app`.

- `platform_create_gym`: the panel's way in, owned by `rakin_platform` as every
  `platform_*` function is (0076). It checks the operator's session, calls `gym_create`
  and logs `gym_created` when it created one.
- `platform_slug_taken`: whether a gym has the slug, for the panel's live check.
- `platform_owner_link`: logs `owner_link_sent`, or `owner_link_failed`, once the API
  tried to email the gym's owner a sign-in link on its host.
- `platform_titular`: the slug and the titular's address of one gym, to send the link
  again.
- `platform_gyms` (0076) gains `owner_link_failed`: whether the latest link to the
  owner did not go, for the list to say so and offer to send it again. `rakin_platform`
  reads those three columns of `platform_event` for it.

`platform_gyms` is rebuilt from 0076's own text, patched by string replacement
(`platform_gyms(links=...)`), as 0049 rebuilds 0048's function. Each patch asserts it
matches once, so 0076's `platform_gyms` body must not be reformatted or edited: a
change there makes this migration fail when it is loaded.

Revision ID: 0077
Revises: 0076
Create Date: 2026-11-18

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
PLATFORM_ROLE = "rakin_platform"

# `app.domain.practice.KIND`: the block kind a gym practises freely in (0028).
PRACTICE_KIND = "sparring"

ACTIONS = ("operator_granted", "operator_revoked", "operator_signed_in", "operator_signed_out")
NEW_ACTIONS = ("gym_created", "owner_link_sent", "owner_link_failed")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# Everything a new gym is made of, in the order both functions take it.
VALUES = (
    "p_id uuid, p_slug text, p_name text, p_timezone text, p_settings jsonb,"
    " p_programs text[], p_activity_name text, p_preset text, p_practice_block text,"
    " p_owner_email text, p_owner_name text, p_owner_rut text, p_owner_phone text,"
    " p_terms_version text, p_signed_on date"
)
TYPES = (
    "uuid, text, text, text, jsonb, text[], text, text, text, text, text, text, text, text, date"
)
ARGUMENTS = (
    "p_id, p_slug, p_name, p_timezone, p_settings, p_programs, p_activity_name, p_preset,"
    " p_practice_block, p_owner_email, p_owner_name, p_owner_rut, p_owner_phone,"
    " p_terms_version, p_signed_on"
)

GYM_CREATE = f"gym_create({TYPES})"
PLATFORM_CREATE = f"platform_create_gym(bytea, text, {TYPES})"
SLUG_TAKEN = "platform_slug_taken(bytea, text)"
LINK = "platform_owner_link(bytea, uuid, boolean)"
TITULAR = "platform_titular(bytea, uuid)"
GYMS = "platform_gyms(bytea, text)"

EVENT_GRANT = "GRANT SELECT (gym_id, action, at) ON platform_event TO {role}"
EVENT_INDEX = (
    "CREATE INDEX platform_event_gym_idx ON platform_event (gym_id, at DESC)"
    " WHERE gym_id IS NOT NULL"
)

# `public` on the path, as `join_gym`'s: the trigger that gives a gym its block kinds
# (0028) names its tables unqualified, and runs with the caller's path.
CREATE = f"""
CREATE FUNCTION gym_create({VALUES})
RETURNS TABLE (id uuid, name text, created boolean)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
#variable_conflict use_column
DECLARE
    found_id uuid;
    found_name text;
    owner_id uuid;
BEGIN
    -- One creation of a slug at a time, to the end of the transaction. The look below is
    -- a statement of its own, so it reads what a creation that held the lock committed.
    PERFORM pg_advisory_xact_lock(hashtextextended('gym_slug:' || p_slug, 0));
    -- Live slugs only: #438's renamed slugs, kept 90 days, are to be taken here too.
    SELECT g.id, g.name INTO found_id, found_name FROM auth_gym_by_slug(p_slug) g;
    IF found_id IS NOT NULL THEN
        id := found_id;
        name := found_name;
        created := false;
        RETURN NEXT;
        RETURN;
    END IF;
    -- RLS is forced, so the owner writes only in the gym `app.gym_id` names.
    PERFORM set_config('app.gym_id', p_id::text, true);
    -- The block kinds come with the row (0028's trigger).
    INSERT INTO gym (id, name, slug, timezone, settings)
    VALUES (p_id, p_name, p_slug, p_timezone, p_settings);
    INSERT INTO program (gym_id, name)
    SELECT p_id, program.name FROM unnest(p_programs) WITH ORDINALITY AS program (name, n)
    ORDER BY program.n;
    IF p_activity_name IS NOT NULL THEN
        INSERT INTO gym_activity (gym_id, name, uses_grades, preset)
        VALUES (p_id, p_activity_name, true, p_preset);
    END IF;
    -- The practice's kind, as its activity names it, else "Práctica libre" (#346).
    UPDATE block_kind SET name = p_practice_block
    WHERE block_kind.id = block_kind_default_id(p_id, '{PRACTICE_KIND}');
    SELECT j.person_id INTO owner_id
    FROM join_gym(p_owner_rut, p_owner_email, p_owner_name, p_owner_phone, NULL) j;
    -- The owner holds the account (0065); the gym's roles came with its row.
    INSERT INTO staff (gym_id, person_id, role, account_holder)
    VALUES (p_id, owner_id, 'owner', true);
    IF p_terms_version IS NOT NULL THEN
        INSERT INTO processor_terms (gym_id, version, signed_on)
        VALUES (p_id, p_terms_version, p_signed_on);
    END IF;
    id := p_id;
    name := p_name;
    created := true;
    RETURN NEXT;
END
$$
"""

# Qualified names and a fixed search_path, as in 0076.
DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

FUNCTIONS = {
    PLATFORM_CREATE: f"""
CREATE FUNCTION platform_create_gym(session bytea, grading text, {VALUES})
RETURNS TABLE (id uuid, name text, created boolean)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    made record;
BEGIN
    found_operator := public.platform_operator_of(session);
    SELECT g.id, g.name, g.created INTO made FROM public.gym_create({ARGUMENTS}) g;
    IF made.created THEN
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_created', made.id, jsonb_build_object(
            'slug', p_slug, 'grading', grading, 'terms_version', p_terms_version
        ));
    END IF;
    id := made.id;
    name := made.name;
    created := made.created;
    RETURN NEXT;
END
$$
""",
    SLUG_TAKEN: f"""
CREATE FUNCTION platform_slug_taken(session bytea, wanted text)
RETURNS boolean
LANGUAGE plpgsql STABLE {DEFINER} AS $$
BEGIN
    PERFORM public.platform_operator_of(session);
    -- Live slugs only: #438 extends this to the renamed ones it keeps.
    RETURN EXISTS (SELECT FROM public.gym g WHERE g.slug = wanted);
END
$$
""",
    LINK: f"""
CREATE FUNCTION platform_owner_link(session bytea, gym uuid, sent boolean)
RETURNS void
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
DECLARE
    found_operator uuid;
    found_slug text;
BEGIN
    found_operator := public.platform_operator_of(session);
    SELECT g.slug INTO STRICT found_slug FROM public.gym g WHERE g.id = gym;
    INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
    VALUES (
        found_operator,
        CASE WHEN sent THEN 'owner_link_sent' ELSE 'owner_link_failed' END,
        gym,
        jsonb_build_object('slug', found_slug)
    );
END
$$
""",
    TITULAR: f"""
CREATE FUNCTION platform_titular(session bytea, gym uuid)
RETURNS TABLE (slug text, email text)
LANGUAGE plpgsql STABLE {DEFINER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM public.platform_operator_of(session);
    RETURN QUERY
    SELECT g.slug, holder.email
    FROM public.gym g
    LEFT JOIN LATERAL (
        SELECT gp.email
        FROM public.staff s
        JOIN public.gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
        WHERE s.gym_id = g.id AND s.account_holder
        LIMIT 1
    ) holder ON true
    WHERE g.id = gym;
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


# What the latest link to the gym's owner came to, sent or not.
LATEST_LINK = """    LEFT JOIN LATERAL (
        SELECT e.action = 'owner_link_failed' AS failed
        FROM public.platform_event e
        WHERE e.gym_id = g.id AND e.action IN ('owner_link_sent', 'owner_link_failed')
        ORDER BY e.at DESC
        LIMIT 1
    ) link ON true
    ORDER BY g.name, g.slug;"""


def platform_gyms(*, links: bool) -> str:
    """0076's `platform_gyms`; with `links`, each gym's `owner_link_failed` too."""
    sql: str = _migration("0076_platform_operators.py").FUNCTIONS[GYMS]
    if not links:
        return sql
    for before, after in (
        ("    status text\n)", "    status text,\n    owner_link_failed boolean\n)"),
        (
            "           'active'::text\n",
            "           'active'::text,\n           coalesce(link.failed, false)\n",
        ),
        ("    ORDER BY g.name, g.slug;", LATEST_LINK),
    ):
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def _gyms(*, links: bool) -> None:
    op.execute(f"DROP FUNCTION {GYMS}")
    op.execute(platform_gyms(links=links))
    op.execute(f"REVOKE ALL ON FUNCTION {GYMS} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {GYMS} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {GYMS} OWNER TO {PLATFORM_ROLE}")


def _actions(actions: Sequence[str], *, valid: bool = True) -> None:
    op.execute("ALTER TABLE platform_event DROP CONSTRAINT platform_event_action_check")
    op.execute(
        "ALTER TABLE platform_event ADD CONSTRAINT platform_event_action_check"
        f" CHECK (action IN {_in(actions)}){'' if valid else ' NOT VALID'}"
    )


def upgrade() -> None:
    _actions((*ACTIONS, *NEW_ACTIONS))
    op.execute(EVENT_GRANT.format(role=PLATFORM_ROLE))
    op.execute(EVENT_INDEX)

    # Owned by whoever runs the migrations, the table owner, as `join_gym` is.
    op.execute(CREATE)
    op.execute(f"REVOKE ALL ON FUNCTION {GYM_CREATE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {GYM_CREATE} TO {PLATFORM_ROLE}")

    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in FUNCTIONS.items():
        op.execute(statement)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")
    _gyms(links=True)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    _gyms(links=False)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")
    for signature in (*FUNCTIONS, GYM_CREATE):
        op.execute(f"DROP FUNCTION {signature}")
    op.execute("DROP INDEX platform_event_gym_idx")
    op.execute(
        EVENT_GRANT.replace("GRANT", "REVOKE", 1)
        .replace(" TO ", " FROM ")
        .format(role=PLATFORM_ROLE)
    )
    # The log keeps its rows, these included: the old CHECK holds new rows only.
    _actions(ACTIONS, valid=False)
