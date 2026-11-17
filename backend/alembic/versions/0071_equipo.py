"""Equipo: the gym's roles and appointments are managed in the app, and audited (#311).

Equipo, in Ajustes, creates and edits the gym's roles and appoints people to them
(docs/design/expenses-and-officers.md, sections 3, 4 and 8). The tables are 0065's;
this adds what managing them needs:

- `staff_title_term` lets a term end on the day it starts. Such a term grants nothing
  (an appointment is current from `starts_on` to the day before `ends_on`), and is
  what an appointment ended on the day it was made, or before it started, becomes:
  kept, so Historial still shows a same-day change of role, rather than deleted.
- `gym.roles_chosen_at`: when the gym chose how its team is organised, in Equipo's
  first-run setup (a preset, or none). A gym created from now on has none until it
  chooses; every gym already here has been running on the Academia preset, so it has
  chosen.
- `audit_event` takes five team actions: `title_created` and `title_changed` (a role,
  so with no person), and `appointment_started`, `appointment_ended` and
  `appointment_corrected` (about the person appointed). Whoever holds `team_manage`
  writes them, as themselves and now, and only they read them: the money log stays
  `money_read`'s and an expense's `expenses_read`'s.
- `forget_gym_person` deletes a person's appointment rows with the rest of their log,
  as it did, and no longer counts them among the corrections of their billing.

A downgrade deletes the team's log rows and every term that ends on its first day.

Revision ID: 0071
Revises: 0070
Create Date: 2026-11-17

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0071"
down_revision: str | Sequence[str] | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# A role's rows name no person; an appointment's name the person appointed.
TITLE_ACTIONS = ("title_created", "title_changed")
APPOINTMENT_ACTIONS = ("appointment_started", "appointment_ended", "appointment_corrected")
TEAM_ACTIONS = (*TITLE_ACTIONS, *APPOINTMENT_ACTIONS)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0048 = _migration("0048_correction_audit.py")
M0067 = _migration("0067_rls_by_permission.py")
_in = M0048._in


M0070 = _migration("0070_backfilled_classes.py")


def _actions(team: bool) -> tuple[str, ...]:
    """The actions 0070 left `audit_event` taking, with the team's or without."""
    m0055 = _migration("0055_history_payment.py")
    m0056 = _migration("0056_import_undone.py")
    m0057 = _migration("0057_no_health_reasons.py")
    actions: tuple[str, ...] = (
        *_migration("0051_person_history.py")._actions(history=True)[0],
        m0056.IMPORTED,
        m0055.REMOVED,
        m0056.UNDONE,
        m0057.CLEARED,
        _migration("0066_discount_reason.py").CHANGED,
        M0070.CLASS,
        M0070.ATTENDANCE,
    )
    return (*actions, *TEAM_ACTIONS) if team else actions


def _constraints(team: bool) -> None:
    """0070's constraints, with the team's actions or without: a role's rows, like a
    deletion's, an import's and a back-filled class's, name nobody."""
    m0056 = _migration("0056_import_undone.py")
    unnamed: tuple[str, ...] = ("person_deleted", m0056.IMPORTED, m0056.UNDONE, M0070.CLASS)
    if team:
        unnamed = (*unnamed, *TITLE_ACTIONS)
    person = f"(action IN {_in(unnamed)}) = (person_id IS NULL)"
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {_in(_actions(team))}),"
        f" DROP CONSTRAINT audit_event_person, ADD CONSTRAINT audit_event_person CHECK ({person})"
    )


# Someone holding `team_manage` in the current gym, as themselves, now; an appointment's
# row about one of the gym's people. Which person and role they may touch is the API's
# rule (section 4), as for every other team write.
TEAM_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action IN {_in(TEAM_ACTIONS)} AND {M0067.can('team_manage')}"
    f" AND (person_id IS NULL OR EXISTS (SELECT FROM gym_person gp"
    f" WHERE gp.gym_id = {CURRENT_GYM} AND gp.person_id = audit_event.person_id)))"
)

TEAM_READ = (
    f"(gym_id = {CURRENT_GYM} AND CASE WHEN {M0067.EXPENSE_ACTIONS}"
    f" THEN {M0067.can('expenses_read')}"
    f" WHEN action IN {_in(TEAM_ACTIONS)} THEN {M0067.can('team_manage')}"
    f" ELSE {M0067.can('money_read')} END)"
)

COUNTED = "AND action NOT IN ('history_set', 'history_removed')"
NOT_COUNTED = f"{COUNTED} AND action NOT IN {_in(APPOINTMENT_ACTIONS)}"


def forget_gym_person(team: bool) -> str:
    """0065's function, replacing itself; with `team`, a person's appointment rows are
    not counted among their corrections."""
    sql: str = _migration("0065_permissions_behind_roles.py").forget_gym_person(appointments=True)
    if team:
        assert sql.count(COUNTED) == 1, COUNTED
        sql = sql.replace(COUNTED, NOT_COUNTED)
    return sql


# FORCEd RLS hides every gym from the owner running this, and `jobs_gym_ids()` (0011)
# lists them.
CHOSEN = """
    DO $$
    DECLARE
        g uuid;
    BEGIN
        FOR g IN SELECT jobs_gym_ids() LOOP
            PERFORM set_config('app.gym_id', g::text, true);
            UPDATE gym SET roles_chosen_at = created_at WHERE id = g;
        END LOOP;
        PERFORM set_config('app.gym_id', '', true);
    END
    $$
"""

# The same walk, to drop the terms a downgrade's CHECK would refuse.
SAME_DAY = """
    DO $$
    DECLARE
        g uuid;
    BEGIN
        FOR g IN SELECT jobs_gym_ids() LOOP
            PERFORM set_config('app.gym_id', g::text, true);
            DELETE FROM staff_title WHERE gym_id = g AND ends_on = starts_on;
        END LOOP;
        PERFORM set_config('app.gym_id', '', true);
    END
    $$
"""


def _term(same_day: bool) -> None:
    check = (
        "ends_on IS NULL OR ends_on >= starts_on"
        if same_day
        else ("ends_on IS NULL OR ends_on > starts_on")
    )
    op.execute(
        "ALTER TABLE staff_title DROP CONSTRAINT staff_title_term,"
        f" ADD CONSTRAINT staff_title_term CHECK ({check})"
    )


def upgrade() -> None:
    _term(same_day=True)
    op.execute("ALTER TABLE gym ADD COLUMN roles_chosen_at timestamptz")
    op.execute(CHOSEN)

    _constraints(team=True)
    op.execute(
        f"CREATE POLICY audit_event_team ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {TEAM_INSERT}"
    )
    op.execute(f"ALTER POLICY audit_event_read ON audit_event USING {TEAM_READ}")
    op.execute(forget_gym_person(team=True))


def downgrade() -> None:
    op.execute(forget_gym_person(team=False))
    op.execute(f"ALTER POLICY audit_event_read ON audit_event USING {M0067.AUDIT_READ}")
    op.execute("DROP POLICY audit_event_team ON audit_event")
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action IN {_in(TEAM_ACTIONS)}")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraints(team=False)

    op.execute("ALTER TABLE gym DROP COLUMN roles_chosen_at")
    op.execute(SAME_DAY)
    _term(same_day=False)
