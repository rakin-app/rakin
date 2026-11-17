"""Permissions behind the roles: gym-defined roles, appointments, and the titular (#308).

What a person may do in a gym stops being a role's name and becomes a set of
permissions (docs/design/expenses-and-officers.md, sections 1 to 3 and 7):

- `gym_title`: a role the gym defines, a name and the permissions it carries. Its name
  is unique per gym among the unarchived ones; its permissions are the known codes,
  with what each implies stored beside it (`money_write` lists `money_read` too,
  `expenses_write` `expenses_read`, `members_manage` `members_add`), so a check is one
  membership test. `system` is NULL for the gym's own roles; #320 adds the one Rakin
  keeps itself.
- `staff_title`: an appointment, a person holding a role from `starts_on` to the day
  before `ends_on` (half-open; NULL is open). It keeps the role's name as it was when
  appointed, so renaming a role later does not rewrite who held it.
- `staff.account_holder`: the titular, who holds the account and every permission.
  Never two in a gym (a partial unique index; a swap clears the old flag before setting
  the new one), and never none: a constraint trigger, deferred to the commit, refuses a
  gym whose staff has no titular. A partial unique index cannot be deferred; only a
  constraint can.

Every gym gets the Academia preset when it is created, as its block kinds (0028):
Administrador, with what today's admin does, and Coach, with what today's coach does.
Each preset role's id is derived from the gym (`gym_title_preset_id`), so the staff API
and the seed name it without reading its name. The gyms already here get it now, and
today's roles move onto it: each `admin` and `coach` row an open appointment from the
day it was created, in the gym's timezone, and each `owner` row the titular flag. So
nobody can do anything more or less than before.

`staff.role` stays, written by the staff API alongside the appointments, because every
role-keyed policy still reads it until #309. `forget_gym_person` deletes the person's
appointments with the rest. Both tables are held to the gym by RLS; `rakin_app` may add
and change rows of both and delete appointments; the staff API deletes only appointments
that have not started yet, and ends the others.

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-16

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# `app.permissions.Permission`, as this revision knows it.
PERMISSIONS = (
    "money_read",
    "money_write",
    "expenses_read",
    "expenses_write",
    "members_manage",
    "members_add",
    "attendance",
    "gym_setup",
    "team_manage",
)
# What holding the first brings with it: `app.permissions.IMPLIES`.
IMPLIES = (
    ("money_write", "money_read"),
    ("expenses_write", "expenses_read"),
    ("members_manage", "members_add"),
)


def _array(codes: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{c}'" for c in codes) + "]::text[]"


# `app.permissions.PRESETS`: (preset, key, name, permissions, public, sort).
PRESET_TITLES = (
    (
        "academia",
        "administrador",
        "Administrador",
        (
            "money_read",
            "money_write",
            "members_manage",
            "members_add",
            "attendance",
            "gym_setup",
            "team_manage",
        ),
        False,
        1,
    ),
    ("academia", "coach", "Coach", ("attendance", "members_add"), True, 2),
)
PRESET_VALUES = ",\n                ".join(
    f"('{preset}', '{key}', '{name}', {_array(codes)}, {str(public).lower()}, {sort})"
    for preset, key, name, codes, public, sort in PRESET_TITLES
)

IMPLIED = " AND ".join(
    f"(NOT permissions @> ARRAY['{a}'] OR permissions @> ARRAY['{b}'])" for a, b in IMPLIES
)

GYM_TITLE = f"""
    CREATE TABLE gym_title (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gym_id uuid NOT NULL REFERENCES gym (id),
        name text NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 60),
        permissions text[] NOT NULL DEFAULT '{{}}',
        public boolean NOT NULL DEFAULT false,
        preset text,
        system text CHECK (system IN ('read_only_handover')),
        sort integer NOT NULL DEFAULT 0,
        archived_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (gym_id, id),
        CONSTRAINT gym_title_known_permissions CHECK (permissions <@ {_array(PERMISSIONS)}),
        CONSTRAINT gym_title_implied_permissions CHECK ({IMPLIED})
    )
"""

STAFF_TITLE = """
    CREATE TABLE staff_title (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gym_id uuid NOT NULL,
        person_id uuid NOT NULL,
        title_id uuid NOT NULL,
        title_name text NOT NULL CHECK (btrim(title_name) <> ''),
        starts_on date NOT NULL,
        ends_on date,
        public_contact text CHECK (public_contact IN ('email', 'phone')),
        handover_id uuid,
        created_by uuid REFERENCES person (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        ended_by uuid REFERENCES person (id),
        ended_at timestamptz,
        CONSTRAINT staff_title_term CHECK (ends_on IS NULL OR ends_on > starts_on),
        FOREIGN KEY (gym_id, title_id) REFERENCES gym_title (gym_id, id),
        FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
    )
"""

PRESET_ID = """
    CREATE FUNCTION gym_title_preset_id(gym uuid, preset text, key text) RETURNS uuid
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT md5(gym::text || '/gym_title/' || preset || '/' || key)::uuid $$
"""

# As whoever inserts the gym, with `app.gym_id` set to it for the inserts and put back
# after, so RLS holds them to that gym (0028's `add_default_block_kinds`). A role the gym
# already has, by id or by name, is not added twice.
ADD_PRESET = f"""
    CREATE FUNCTION add_preset_titles(gym uuid, which text) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE
        previous text := current_setting('app.gym_id', true);
    BEGIN
        PERFORM set_config('app.gym_id', gym::text, true);
        INSERT INTO gym_title (id, gym_id, name, permissions, public, preset, sort)
        SELECT gym_title_preset_id(gym, d.preset, d.key), gym, d.name, d.permissions,
               d.public, d.preset, d.sort
        FROM (VALUES
                {PRESET_VALUES}
             ) AS d (preset, key, name, permissions, public, sort)
        WHERE d.preset = which
        ON CONFLICT DO NOTHING;
        PERFORM set_config('app.gym_id', coalesce(previous, ''), true);
    END
    $$
"""

GYM_DEFAULT_TITLES = """
    CREATE FUNCTION gym_default_titles() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM add_preset_titles(NEW.id, 'academia');
        RETURN NULL;
    END
    $$
"""

# Owned by `rakin_auth`, which RLS does not hold, so the check sees the gym's whole
# staff whatever `app.gym_id` says at commit. A gym with no staff left (one being torn
# down) has nothing to check.
HOLDER_CHECK_SIGNATURE = "staff_account_holder_check()"
HOLDER_CHECK = f"""
    CREATE FUNCTION {HOLDER_CHECK_SIGNATURE} RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE
        gym uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.gym_id ELSE NEW.gym_id END;
    BEGIN
        IF EXISTS (SELECT FROM public.staff s WHERE s.gym_id = gym)
           AND NOT EXISTS (SELECT FROM public.staff s WHERE s.gym_id = gym AND s.account_holder)
        THEN
            RAISE EXCEPTION 'gym % would have no account holder', gym
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NULL;
    END
    $$
"""

# Today's roles onto the Academia preset, gym by gym: FORCEd RLS hides every gym from
# the owner running this, and `jobs_gym_ids()` (0011) lists them.
BACKFILL = """
    DO $$
    DECLARE
        g uuid;
    BEGIN
        FOR g IN SELECT jobs_gym_ids() LOOP
            PERFORM add_preset_titles(g, 'academia');
            PERFORM set_config('app.gym_id', g::text, true);
            UPDATE staff SET account_holder = true WHERE gym_id = g AND role = 'owner';
            INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)
            SELECT s.gym_id, s.person_id, t.id, t.name,
                   (s.created_at AT TIME ZONE gy.timezone)::date
            FROM staff s
            JOIN gym gy ON gy.id = s.gym_id
            JOIN gym_title t ON t.id = gym_title_preset_id(
                s.gym_id, 'academia',
                CASE s.role WHEN 'admin' THEN 'administrador' ELSE 'coach' END)
            WHERE s.gym_id = g AND s.role IN ('admin', 'coach');
        END LOOP;
        PERFORM set_config('app.gym_id', '', true);
    END
    $$
"""

DELETE_BEFORE = "        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;"
DELETE_AFTER = (
    "        DELETE FROM staff_title WHERE gym_id = gym AND person_id = $1;\n" + DELETE_BEFORE
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(appointments: bool) -> str:
    """0062's function, replacing itself; with `appointments`, it deletes the person's
    appointments."""
    sql: str = _migration("0062_requirements.py").forget_gym_person(requirements=True)
    if appointments:
        assert sql.count(DELETE_BEFORE) == 1, DELETE_BEFORE
        sql = sql.replace(DELETE_BEFORE, DELETE_AFTER)
    return sql


def upgrade() -> None:
    op.execute("ALTER TABLE staff ADD COLUMN account_holder boolean NOT NULL DEFAULT false")
    op.execute("CREATE UNIQUE INDEX staff_account_holder ON staff (gym_id) WHERE account_holder")

    op.execute(GYM_TITLE)
    op.execute(
        "CREATE UNIQUE INDEX gym_title_name ON gym_title (gym_id, lower(name))"
        " WHERE archived_at IS NULL"
    )
    op.execute(STAFF_TITLE)
    op.execute("CREATE INDEX staff_title_person ON staff_title (gym_id, person_id, starts_on)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON gym_title TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON staff_title TO {APP_ROLE}")
    for table in ("gym_title", "staff_title"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_isolation ON {table}"
            f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
        )

    op.execute(PRESET_ID)
    op.execute(ADD_PRESET)
    op.execute(GYM_DEFAULT_TITLES)
    op.execute(
        "CREATE TRIGGER gym_default_titles AFTER INSERT ON gym"
        " FOR EACH ROW EXECUTE FUNCTION gym_default_titles()"
    )

    op.execute(HOLDER_CHECK)
    op.execute(
        "CREATE CONSTRAINT TRIGGER staff_account_holder"
        " AFTER INSERT OR UPDATE OF account_holder, gym_id OR DELETE ON staff"
        f" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {HOLDER_CHECK_SIGNATURE}"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {HOLDER_CHECK_SIGNATURE} FROM PUBLIC")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer (0011).
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"ALTER FUNCTION {HOLDER_CHECK_SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    op.execute(BACKFILL)
    op.execute(forget_gym_person(appointments=True))


def downgrade() -> None:
    op.execute(forget_gym_person(appointments=False))
    op.execute("DROP TRIGGER staff_account_holder ON staff")
    op.execute(f"DROP FUNCTION {HOLDER_CHECK_SIGNATURE}")
    op.execute("DROP TRIGGER gym_default_titles ON gym")
    op.execute("DROP FUNCTION gym_default_titles()")
    op.execute("DROP FUNCTION add_preset_titles(uuid, text)")
    op.execute("DROP FUNCTION gym_title_preset_id(uuid, text, text)")
    op.execute("DROP TABLE staff_title, gym_title")
    op.execute("DROP INDEX staff_account_holder")
    op.execute("ALTER TABLE staff DROP COLUMN account_holder")
