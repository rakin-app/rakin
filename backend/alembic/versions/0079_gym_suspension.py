"""The platform's panel suspends a gym and resumes it (#439).

- `gym.suspended_at` and `gym.suspended_reason`: since when, and why, the gym is
  suspended; both null for an active gym. Its data stays.
- `gym.jobs_owed_since`: set as a gym is resumed, to when its suspension began, and
  cleared once the nightly jobs have caught it up (`app.jobs.catch_up`).
- Sign-in leaves a suspended gym out where it decides belonging (0042's three
  lookups): `auth_people_by_email` sends nobody a link for it alone,
  `auth_gyms_of` starts no session in it, and `auth_live_session` stops a live one
  there at once, so its requests answer 401 (`app.auth.bind_session`).
- `auth_gym_by_slug` says whether the gym is `suspended`, for its host to show the
  notice; it still finds the gym, so the TLS `ask` still answers 200 and the notice
  is served over HTTPS. Its result type changes, so it is dropped and made again
  with 0040's grants and owner.
- `jobs_gym_ids()` leaves out a suspended gym, and a resumed one the jobs have not
  caught up yet; `jobs_resumed_gym_ids()` lists those, for the catch-up job.
- `platform_suspend_gym` and `platform_resume_gym`, with a session proved within 10
  minutes: each sets or clears the columns and logs `gym_suspended` or
  `gym_resumed`; a gym already so changes nothing and logs nothing. The time is the
  database's, as every platform function's (0076): none takes one from the API.
- `platform_gyms` (0077) and `platform_gym` (0078) say the gym's `status` and since
  when it is suspended, and why.

0042's lookups, 0077's `platform_gyms` and 0078's `platform_gym` are rebuilt from
their own text, patched by string replacement, as 0077 and 0078 do. Each patch asserts
it matches once, so those must not be reformatted or edited.

Revision ID: 0079
Revises: 0078
Create Date: 2026-11-18

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"
PLATFORM_ROLE = "rakin_platform"

# How recent a proof suspending and resuming ask for: `app.platform.session.FRESH`.
FRESH = "10 minutes"

OLD_ACTIONS = (
    "operator_granted",
    "operator_revoked",
    "operator_signed_in",
    "operator_signed_out",
    "gym_created",
    "owner_link_sent",
    "owner_link_failed",
    "gym_edited",
    "terms_recorded",
    "gym_renamed",
)
NEW_ACTIONS = ("gym_suspended", "gym_resumed")

COLUMNS = (
    "ALTER TABLE gym ADD COLUMN suspended_at timestamptz",
    "ALTER TABLE gym ADD COLUMN suspended_reason text"
    " CONSTRAINT gym_suspended_reason_length CHECK (char_length(suspended_reason) <= 500)",
    "ALTER TABLE gym ADD COLUMN jobs_owed_since timestamptz",
    # A reason only with a suspension.
    "ALTER TABLE gym ADD CONSTRAINT gym_suspended_reason_when"
    " CHECK (suspended_reason IS NULL OR suspended_at IS NOT NULL)",
)

AUTH_GRANTS = ("GRANT SELECT (suspended_at, jobs_owed_since) ON gym TO {role}",)
PLATFORM_GRANTS = (
    "GRANT SELECT (suspended_at, suspended_reason, jobs_owed_since) ON gym TO {role}",
    "GRANT UPDATE (suspended_at, suspended_reason, jobs_owed_since) ON gym TO {role}",
)


def _active(gym: str) -> str:
    """`gym` is not suspended."""
    return (
        f"NOT EXISTS (SELECT FROM public.gym x WHERE x.id = {gym} AND x.suspended_at IS NOT NULL)"
    )


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patched(sql: str, patches: Sequence[tuple[str, str]]) -> str:
    for before, after in patches:
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def lookups(*, suspension: bool) -> list[str]:
    """0042's three lookups; with `suspension`, each leaving a suspended gym out."""
    people, gyms_of, live = _migration("0042_roster_signs_in.py")._functions(roster=True)
    if not suspension:
        return [people, gyms_of, live]
    return [
        _patched(
            people,
            [
                (
                    "    ORDER BY g.person_id, g.created_at\n",
                    f"      AND {_active('g.gym_id')}\n    ORDER BY g.person_id, g.created_at\n",
                )
            ],
        ),
        _patched(
            gyms_of,
            [
                (
                    "    WHERE g.person_id = person AND lower(g.email) = lower(btrim(address))\n",
                    "    WHERE g.person_id = person AND lower(g.email) = lower(btrim(address))\n"
                    f"      AND {_active('g.gym_id')}\n",
                )
            ],
        ),
        _patched(
            live,
            [
                (
                    "      AND (s.gym_id IS NULL\n",
                    f"      AND (s.gym_id IS NULL OR {_active('s.gym_id')})\n"
                    "      AND (s.gym_id IS NULL\n",
                )
            ],
        ),
    ]


BY_SLUG = "auth_gym_by_slug(text)"
BY_SLUG_FUNCTION = """
CREATE FUNCTION auth_gym_by_slug(wanted text)
RETURNS TABLE (id uuid, name text, theme text, logo_version text, suspended boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT g.id, g.name, g.theme, g.logo_version, g.suspended_at IS NOT NULL
    FROM public.gym g WHERE g.slug = wanted
$$
"""

JOBS_IDS = "jobs_gym_ids()"
RESUMED_IDS = "jobs_resumed_gym_ids()"


def jobs_gym_ids(*, suspension: bool) -> str:
    """0011's `jobs_gym_ids`; with `suspension`, the gyms the jobs work on today."""
    where = " WHERE suspended_at IS NULL AND jobs_owed_since IS NULL" if suspension else ""
    return f"""
CREATE OR REPLACE FUNCTION jobs_gym_ids()
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT id FROM public.gym{where} ORDER BY id
$$
"""


RESUMED_FUNCTION = """
CREATE FUNCTION jobs_resumed_gym_ids()
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT id FROM public.gym
    WHERE suspended_at IS NULL AND jobs_owed_since IS NOT NULL
    ORDER BY id
$$
"""

# Qualified names and a fixed search_path, as in 0076.
DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

SUSPEND = "platform_suspend_gym(bytea, uuid, text)"
RESUME = "platform_resume_gym(bytea, uuid)"

FUNCTIONS = {
    SUSPEND: f"""
CREATE FUNCTION platform_suspend_gym(session bytea, gym uuid, reason text)
RETURNS TABLE (slug text, changed boolean)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    since timestamptz;
BEGIN
    -- What shuts a gym out asks for a recent proof (`require_fresh`).
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug, g.suspended_at INTO found_slug, since
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    slug := found_slug;
    changed := since IS NULL;
    IF changed THEN
        UPDATE public.gym g SET suspended_at = now(), suspended_reason = reason WHERE g.id = gym;
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_suspended', gym, jsonb_build_object(
            'slug', found_slug, 'reason', reason
        ));
    END IF;
    RETURN NEXT;
END
$$
""",
    RESUME: f"""
CREATE FUNCTION platform_resume_gym(session bytea, gym uuid)
RETURNS TABLE (slug text, changed boolean)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    since timestamptz;
BEGIN
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug, g.suspended_at INTO found_slug, since
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    slug := found_slug;
    changed := since IS NOT NULL;
    IF changed THEN
        -- The jobs owe it every day since it was suspended (`app.jobs.catch_up`): the
        -- earliest, if it was suspended again before they caught it up.
        UPDATE public.gym g
        SET suspended_at = NULL, suspended_reason = NULL,
            jobs_owed_since = coalesce(g.jobs_owed_since, since)
        WHERE g.id = gym;
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_resumed', gym, jsonb_build_object('slug', found_slug));
    END IF;
    RETURN NEXT;
END
$$
""",
}

GYMS = "platform_gyms(bytea, text)"
GYM = "platform_gym(bytea, uuid)"


def platform_gyms(*, suspension: bool) -> str:
    """0077's `platform_gyms`; with `suspension`, each gym's status and since when."""
    sql: str = _migration("0077_gym_create.py").platform_gyms(links=True)
    if not suspension:
        return sql
    return _patched(
        sql,
        [
            (
                "    owner_link_failed boolean\n)",
                "    owner_link_failed boolean,\n    suspended_at timestamptz\n)",
            ),
            (
                "           'active'::text,\n",
                "           CASE WHEN g.suspended_at IS NULL THEN 'active' ELSE 'suspended' END,\n",
            ),
            (
                "           coalesce(link.failed, false)\n",
                "           coalesce(link.failed, false),\n           g.suspended_at\n",
            ),
        ],
    )


def platform_gym(*, suspension: bool) -> str:
    """0078's `platform_gym`; with `suspension`, since when it is suspended, and why."""
    sql: str = _migration("0078_gym_slug_alias.py").FUNCTIONS[GYM]
    if not suspension:
        return sql
    return _patched(
        sql,
        [
            (
                "    aliases jsonb\n)",
                "    aliases jsonb,\n    suspended_at timestamptz,\n    suspended_reason text\n)",
            ),
            (
                "           ), '[]'::jsonb)\n    FROM public.gym g\n",
                "           ), '[]'::jsonb),\n           g.suspended_at, g.suspended_reason\n"
                "    FROM public.gym g\n",
            ),
        ],
    )


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _actions(actions: Sequence[str], *, valid: bool = True) -> None:
    op.execute("ALTER TABLE platform_event DROP CONSTRAINT platform_event_action_check")
    op.execute(
        "ALTER TABLE platform_event ADD CONSTRAINT platform_event_action_check"
        f" CHECK (action IN {_in(actions)}){'' if valid else ' NOT VALID'}"
    )


def _revoke(grant: str, role: str) -> str:
    return grant.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM ").format(role=role)


def _by_slug(statement: str) -> None:
    """`auth_gym_by_slug` made again from `statement`, with 0040's grants and owner."""
    op.execute(f"DROP FUNCTION {BY_SLUG}")
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {BY_SLUG} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {BY_SLUG} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {BY_SLUG} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {BY_SLUG} OWNER TO {AUTH_ROLE}")


def _platform(signature: str, statement: str) -> None:
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")


def upgrade() -> None:
    _actions((*OLD_ACTIONS, *NEW_ACTIONS))
    # asyncpg runs one statement per call.
    for statement in COLUMNS:
        op.execute(statement)
    for grant in AUTH_GRANTS:
        op.execute(grant.format(role=AUTH_ROLE))
    for grant in PLATFORM_GRANTS:
        op.execute(grant.format(role=PLATFORM_ROLE))

    # Same signatures: a replace keeps their owner, `rakin_auth`, and their grants.
    for statement in lookups(suspension=True):
        op.execute(statement)
    op.execute(jobs_gym_ids(suspension=True))

    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    _by_slug(BY_SLUG_FUNCTION)
    op.execute(RESUMED_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {RESUMED_IDS} FROM PUBLIC")
    # The owner running this migration, which the jobs connect as (0011).
    op.execute(f"GRANT EXECUTE ON FUNCTION {RESUMED_IDS} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {RESUMED_IDS} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in FUNCTIONS.items():
        _platform(signature, statement)
    for signature, statement in (
        (GYMS, platform_gyms(suspension=True)),
        (GYM, platform_gym(suspension=True)),
    ):
        op.execute(f"DROP FUNCTION {signature}")
        _platform(signature, statement)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in (
        (GYMS, platform_gyms(suspension=False)),
        (GYM, platform_gym(suspension=False)),
    ):
        op.execute(f"DROP FUNCTION {signature}")
        _platform(signature, statement)
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")

    op.execute(f"DROP FUNCTION {RESUMED_IDS}")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    _by_slug(
        _migration("0040_gym_logo.py").FUNCTION.format(
            logo=", logo_version text", select=", g.logo_version"
        )
    )
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")
    op.execute(jobs_gym_ids(suspension=False))
    for statement in lookups(suspension=False):
        op.execute(statement)

    for grant in PLATFORM_GRANTS:
        op.execute(_revoke(grant, PLATFORM_ROLE))
    for grant in AUTH_GRANTS:
        op.execute(_revoke(grant, AUTH_ROLE))
    op.execute("ALTER TABLE gym DROP CONSTRAINT gym_suspended_reason_when")
    for column in ("jobs_owed_since", "suspended_reason", "suspended_at"):
        op.execute(f"ALTER TABLE gym DROP COLUMN {column}")
    # The log keeps its rows, these included: the old CHECK holds new rows only.
    _actions(OLD_ACTIONS, valid=False)
