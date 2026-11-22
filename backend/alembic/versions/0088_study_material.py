"""Material de estudio: notes and links a coach shares on a class, for an audience (#537).

A coach puts study material on a class, "like global notes" where a note to one student
is personal (#259). Material is a title, an optional plain text and up to ten `https`
links; no files, no embeds, nothing fetched by the server:

- `study_material`: on one session (`session_id`), or on a recurring class from a date on
  (`starts_on`), its slots in `study_material_slot`. Exactly one of the two. Its
  `audience`, chosen when it is shared and shown on it: `attendees` (who was marked
  present at the session it shows on), `program` (every member with a live membership,
  active, trial or frozen, on a plan of the class's program or one open to any class: the
  roster's rule), or `plans` (a live membership on one of `study_material_plan`'s plans).
  `created_by`, `updated_at` / `updated_by` after an edit, and `removed_at` /
  `removed_by` once removed: removal hides it, and nothing deletes it.
- `study_material_slot`: the slots a recurring material shows on. Its own slot, and each
  slot that takes the class over from a date on when the schedule is changed "desde"
  (`app.api.schedule`), so a material keeps showing on the classes after the change and
  on those before it. It shows on a slot's classes whose date is `starts_on` or later.
- `study_material_class_for(..., person)`: the class type through which a material
  reaches `person`, or null when it does not. A recurring material reaches its program
  or plans once its date has come in the gym's timezone; one for who attended, through a
  class from its date on, not cancelled. The class is the one they attended, or the
  newest the material is on that their plan covers, so after a change of the class
  "desde" the student page names the class that let them in.
- `study_material_reaches(...)`: whether it reaches the person acting or one of the
  dependents they are guardian of (0010). `/api/me/material` asks it too, so a coach who
  also trains reads as a student there.
- `app_on_team()`: the person acting is the titular or holds a current appointment, as
  `app.permissions.STANDING_IN_GYM` reads it.
- `study_material_follow(old, new)`: a change of the schedule "desde" gives the new slot
  the old one's material. Whoever manages the classes (`gym_setup`) changes the
  schedule, and may not hold `attendance`, which writing the links takes; so it is
  `SECURITY DEFINER`, owned by the table owner and held to the current gym by its
  forced RLS, and does nothing for anyone without `gym_setup`.
- `study_material_slot_gone(slot)`: deleting a slot takes its links with it, so the live
  material on that slot alone is removed first, by whoever deletes it, with a
  `study_material_removed` row; the same definer, for the same reason.

RLS: `rakin_app` reads a material when the person acting is on the team, or it is not
removed and reaches them; another gym's, never. The link tables hold ids alone and are
read across the gym, so the function can ask them. Whoever holds `attendance` writes
them; which classes they may touch (their own, or any with `gym_setup` too) is the
API's rule, as for the timer (0028). `rakin_app` has no DELETE on `study_material`.

`audit_event` takes `study_material_changed` (the changed fields before and after) and
`study_material_removed`. They name nobody. Whoever writes material writes them, as
themselves, now, about one of the gym's materials; they are read as the rest of the log.

A downgrade drops the tables and the material rows of the log.

Revision ID: 0088
Revises: 0087
Create Date: 2026-11-22

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0088"
down_revision: str | Sequence[str] | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

CHANGED = "study_material_changed"
REMOVED = "study_material_removed"
MATERIAL_ACTIONS = (CHANGED, REMOVED)

AUDIENCES = ("attendees", "program", "plans")
# The memberships that are someone's in a program or on a plan.
LIVE = ("active", "trial", "frozen")
MAX_LINKS = 10


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0067 = _migration("0067_rls_by_permission.py")
M0071 = _migration("0071_equipo.py")
M0083 = _migration("0083_expenses.py")
_in = M0071._in

# Each link an `https` address with a host, no spaces, at most 2000 characters.
LINKS_VALID = f"""
CREATE FUNCTION study_material_links_valid(links text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT cardinality(links) <= {MAX_LINKS} AND coalesce(bool_and(
        l ~ '^https://[^/?#[:space:]]+[^[:space:]]*$' AND length(l) <= 2000), true)
    FROM unnest(links) AS l
$$
"""

MATERIAL = f"""
CREATE TABLE study_material (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    session_id uuid,
    starts_on date,
    title text NOT NULL CHECK (title = btrim(title) AND length(title) BETWEEN 1 AND 120),
    body text CHECK (btrim(body) <> '' AND length(body) <= 5000),
    links text[] NOT NULL DEFAULT '{{}}' CHECK (study_material_links_valid(links)),
    audience text NOT NULL CHECK (audience IN {_in(AUDIENCES)}),
    created_by uuid NOT NULL REFERENCES person (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    updated_by uuid REFERENCES person (id),
    removed_at timestamptz,
    removed_by uuid REFERENCES person (id),
    UNIQUE (id, gym_id),
    FOREIGN KEY (gym_id, session_id) REFERENCES session (gym_id, id) ON DELETE CASCADE,
    CONSTRAINT study_material_on_one CHECK ((session_id IS NULL) <> (starts_on IS NULL)),
    CONSTRAINT study_material_updated CHECK ((updated_at IS NULL) = (updated_by IS NULL)),
    CONSTRAINT study_material_removed CHECK ((removed_at IS NULL) = (removed_by IS NULL))
)
"""

SLOT = """
CREATE TABLE study_material_slot (
    gym_id uuid NOT NULL REFERENCES gym (id),
    material_id uuid NOT NULL,
    slot_id uuid NOT NULL,
    PRIMARY KEY (material_id, slot_id),
    FOREIGN KEY (material_id, gym_id) REFERENCES study_material (id, gym_id) ON DELETE CASCADE,
    FOREIGN KEY (gym_id, slot_id) REFERENCES schedule_slot (gym_id, id) ON DELETE CASCADE
)
"""

PLAN = """
CREATE TABLE study_material_plan (
    gym_id uuid NOT NULL REFERENCES gym (id),
    material_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    PRIMARY KEY (material_id, plan_id),
    FOREIGN KEY (material_id, gym_id) REFERENCES study_material (id, gym_id) ON DELETE CASCADE,
    FOREIGN KEY (gym_id, plan_id) REFERENCES plan (gym_id, id)
)
"""

# `app.permissions.STANDING_IN_GYM`, as a yes or no.
ON_TEAM = f"""
CREATE FUNCTION app_on_team() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (
        SELECT FROM staff s
        WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}
          AND (s.account_holder OR EXISTS (
              SELECT FROM staff_title st
              JOIN gym g ON g.id = st.gym_id
              WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
                AND st.starts_on <= (now() AT TIME ZONE g.timezone)::date
                AND (st.ends_on IS NULL OR (now() AT TIME ZONE g.timezone)::date < st.ends_on)))
    )
$$
"""

# As the invoker, under the gym's RLS on every table it reads. The class type through
# which a material reaches `person`, or null when it does not: for who attended, the
# class they attended, the latest; for a program, the newest class it is on whose
# program their plan covers; for plans, the newest class it is on.
CLASS_FOR = f"""
CREATE FUNCTION study_material_class_for(
    material uuid, on_session uuid, from_day date, audience text, person uuid
) RETURNS uuid
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    WITH live AS (
        SELECT m.plan_id, pl.program_id FROM membership m
        JOIN plan pl ON pl.id = m.plan_id
        WHERE m.person_id = person AND m.status IN {_in(LIVE)}
    ),
    -- The class types it is on, newest first: its session's, or its slots'.
    classes AS (
        SELECT s.class_type_id, NULL::date AS since FROM session s WHERE s.id = on_session
        UNION ALL
        SELECT sl.class_type_id, sl.valid_from FROM study_material_slot ms
        JOIN schedule_slot sl ON sl.id = ms.slot_id
        WHERE ms.material_id = material
    ),
    -- A recurring one reaches a program or plans once its day has come.
    begun AS (
        SELECT from_day IS NULL OR from_day <= (now() AT TIME ZONE g.timezone)::date AS yes
        FROM gym g WHERE g.id = {CURRENT_GYM}
    )
    SELECT CASE audience
        WHEN 'attendees' THEN (
            SELECT s.class_type_id FROM attendance a
            JOIN membership m ON m.id = a.membership_id
            JOIN session s ON s.id = a.session_id
            WHERE m.person_id = person
              AND (s.id = on_session
                   OR (s.slot_id IN (SELECT ms.slot_id FROM study_material_slot ms
                                     WHERE ms.material_id = material)
                       AND s.slot_date >= from_day AND s.cancelled_at IS NULL))
            ORDER BY s.starts_at DESC, s.id LIMIT 1)
        WHEN 'program' THEN (
            SELECT c.class_type_id FROM classes c
            JOIN class_type t ON t.id = c.class_type_id
            WHERE (SELECT yes FROM begun) AND EXISTS (
                SELECT FROM live
                WHERE live.program_id IS NULL OR live.program_id = t.program_id)
            ORDER BY c.since DESC NULLS FIRST, c.class_type_id LIMIT 1)
        WHEN 'plans' THEN (
            SELECT c.class_type_id FROM classes c
            WHERE (SELECT yes FROM begun) AND EXISTS (
                SELECT FROM live JOIN study_material_plan p ON p.plan_id = live.plan_id
                WHERE p.material_id = material)
            ORDER BY c.since DESC NULLS FIRST, c.class_type_id LIMIT 1)
    END
$$
"""
CLASS_FOR_SIGNATURE = "study_material_class_for(uuid, uuid, date, text, uuid)"

# Whether it reaches the person acting, or one of the dependents they are guardian of.
REACHES = f"""
CREATE FUNCTION study_material_reaches(
    material uuid, on_session uuid, from_day date, audience text
) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (
        SELECT FROM (
            SELECT {CURRENT_PERSON} AS person_id
            UNION
            SELECT l.dependent_person_id FROM guardian_link l
            WHERE l.guardian_person_id = {CURRENT_PERSON}
        ) me
        WHERE study_material_class_for(material, on_session, from_day, audience, me.person_id)
              IS NOT NULL
    )
$$
"""

# A slot deleted takes its links with it: the live material on that slot alone is
# removed first, as by whoever deletes it, with its row in the log, so what the tables
# hold matches what anyone sees. As `study_material_follow`, for `gym_setup` alone.
SLOT_GONE = f"""
CREATE FUNCTION study_material_slot_gone(gone_slot uuid) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    WITH removed AS (
        UPDATE study_material m SET removed_at = now(), removed_by = {CURRENT_PERSON}
        WHERE m.removed_at IS NULL AND (SELECT app_can('gym_setup'))
          AND EXISTS (SELECT FROM study_material_slot ms
                      WHERE ms.material_id = m.id AND ms.slot_id = gone_slot)
          AND NOT EXISTS (SELECT FROM study_material_slot ms
                          WHERE ms.material_id = m.id AND ms.slot_id <> gone_slot)
        RETURNING m.id, m.gym_id, m.title
    )
    INSERT INTO audit_event (gym_id, at, actor_id, action, detail)
    SELECT gym_id, now(), {CURRENT_PERSON}, '{REMOVED}',
           jsonb_build_object('material_id', id::text, 'title', title, 'slot_deleted', true)
    FROM removed
$$
"""
SLOT_GONE_SIGNATURE = "study_material_slot_gone(uuid)"

# `pg_temp` last, so no temporary table stands in for one of these.
FOLLOW = """
CREATE FUNCTION study_material_follow(old_slot uuid, new_slot uuid) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    INSERT INTO study_material_slot (gym_id, material_id, slot_id)
    SELECT ms.gym_id, ms.material_id, s.id FROM study_material_slot ms
    JOIN schedule_slot s ON s.id = new_slot AND s.gym_id = ms.gym_id
    WHERE ms.slot_id = old_slot AND (SELECT app_can('gym_setup'))
    ON CONFLICT DO NOTHING
$$
"""
FOLLOW_SIGNATURE = "study_material_follow(uuid, uuid)"

READ = (
    f"(gym_id = {CURRENT_GYM} AND ((SELECT app_on_team()) OR (removed_at IS NULL"
    " AND study_material_reaches(id, session_id, starts_on, audience))))"
)
WRITE = M0067.access("attendance")
SHARED_BY_ME = f"({WRITE} AND created_by = {CURRENT_PERSON})"

# Whoever writes material, as themselves, now, about one of the gym's materials.
MATERIAL_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action IN {_in(MATERIAL_ACTIONS)} AND {M0067.can('attendance')}"
    " AND EXISTS (SELECT FROM study_material m WHERE m.gym_id = audit_event.gym_id"
    " AND m.id::text = audit_event.detail->>'material_id'))"
)


def _constraints(material: bool) -> None:
    """0083's constraints, with the material's actions or without: they name nobody."""
    m0056 = _migration("0056_import_undone.py")
    actions: tuple[str, ...] = (*M0071._actions(team=True), *M0083.EXPENSE_ACTIONS)
    unnamed: tuple[str, ...] = (
        "person_deleted",
        m0056.IMPORTED,
        m0056.UNDONE,
        M0071.M0070.CLASS,
        *M0071.TITLE_ACTIONS,
        *M0083.EXPENSE_ACTIONS,
    )
    if material:
        actions = (*actions, *MATERIAL_ACTIONS)
        unnamed = (*unnamed, *MATERIAL_ACTIONS)
    person = f"(action IN {_in(unnamed)}) = (person_id IS NULL)"
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {_in(actions)}),"
        f" DROP CONSTRAINT audit_event_person, ADD CONSTRAINT audit_event_person CHECK ({person})"
    )


def _gym_isolated(table: str, read: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE} USING {read}")


def upgrade() -> None:
    op.execute(LINKS_VALID)
    op.execute(MATERIAL)
    op.execute("CREATE INDEX study_material_session ON study_material (session_id)")
    op.execute("CREATE INDEX study_material_gym_created ON study_material (gym_id, created_at)")
    op.execute(SLOT)
    op.execute("CREATE INDEX study_material_slot_slot ON study_material_slot (slot_id)")
    op.execute(PLAN)
    op.execute(ON_TEAM)
    op.execute(CLASS_FOR)
    op.execute(REACHES)

    _gym_isolated("study_material", READ)
    op.execute(
        f"CREATE POLICY study_material_insert ON study_material FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {SHARED_BY_ME}"
    )
    op.execute(
        f"CREATE POLICY study_material_update ON study_material FOR UPDATE TO {APP_ROLE}"
        f" USING {WRITE} WITH CHECK {WRITE}"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON study_material TO {APP_ROLE}")
    for table in ("study_material_slot", "study_material_plan"):
        _gym_isolated(table, f"(gym_id = {CURRENT_GYM})")
        op.execute(
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT TO {APP_ROLE} WITH CHECK {WRITE}"
        )
        op.execute(
            f"CREATE POLICY {table}_delete ON {table} FOR DELETE TO {APP_ROLE} USING {WRITE}"
        )
        op.execute(f"GRANT SELECT, INSERT, DELETE ON {table} TO {APP_ROLE}")

    for definer, signature in ((FOLLOW, FOLLOW_SIGNATURE), (SLOT_GONE, SLOT_GONE_SIGNATURE)):
        op.execute(definer)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")

    _constraints(material=True)
    op.execute(
        f"CREATE POLICY audit_event_material ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {MATERIAL_INSERT}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_material ON audit_event")
    # The rows go with their action, past the trigger that keeps the log append-only
    # (0048), and the policy that holds even the owner to one gym (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action IN {_in(MATERIAL_ACTIONS)}")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraints(material=False)

    op.execute(f"DROP FUNCTION {SLOT_GONE_SIGNATURE}")
    op.execute(f"DROP FUNCTION {FOLLOW_SIGNATURE}")
    op.execute("DROP TABLE study_material_plan")
    op.execute("DROP TABLE study_material_slot")
    op.execute("DROP TABLE study_material")
    op.execute("DROP FUNCTION study_material_reaches(uuid, uuid, date, text)")
    op.execute(f"DROP FUNCTION {CLASS_FOR_SIGNATURE}")
    op.execute("DROP FUNCTION app_on_team()")
    op.execute("DROP FUNCTION study_material_links_valid(text[])")
