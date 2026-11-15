"""Alumno desde and classes before Rakin: history kept on the person (#293).

The first of the historical-data tickets (docs/design/historical-data.md, sections 1, 2
and 6). Two facts about a person that predate the gym's Rakin, kept on `gym_person` and
never on a plan, so billing never reads them (the #271 lesson):

- `gym_person.member_since`: the day they first trained here. The ficha's "Alumno
  desde" is the earliest of it and their first membership's start, else the day the
  record was created. A membership's `started_on` is the day billing may bill from, so
  an earlier start there would bill every month since; this one is read by the ficha and
  the student's page, and by no job, view or export. Not after today and at most 60
  years back (`HISTORY_WINDOW_YEARS`), checked by the API: neither is immutable.
- `gym_person.prior_classes`: classes before Rakin, one number, added to the ficha's
  class total and nothing else.

Writing either is recorded in `audit_event` as `history_set` (0048's record), one row
per write with each field's before and after, under the policy corrections are written
by: the actor is the person acting, an owner or admin of the gym, and the person is the
gym's. `forget_gym_person` already deletes every row of the person it deletes; its
`person_deleted` row now counts these apart, as `history_set`, and `corrections` counts
the corrections alone.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-15

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

HISTORY = ("history_set",)

# 0049's `forget_gym_person`, whose `corrections` count this one narrows to corrections
# and beside which it counts the person's history rows.
COUNT_BEFORE = (
    "            'corrections', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "            ),\n"
)
COUNT_AFTER = (
    "            'corrections', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "                AND action <> 'history_set'\n"
    "            ),\n"
    "            'history_set', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "                AND action = 'history_set'\n"
    "            ),\n"
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(history: bool) -> str:
    """0049's function, replacing itself; with `history`, it counts the person's
    `history_set` rows apart from their corrections."""
    sql: str = _migration("0049_correction_purpose.py").forget_gym_person(standing=True)
    if history:
        assert sql.count(COUNT_BEFORE) == 1, COUNT_BEFORE
        sql = sql.replace(COUNT_BEFORE, COUNT_AFTER)
    return sql


def _actions(history: bool) -> tuple[tuple[str, ...], str]:
    """The actions `audit_event` takes, and the insert policy's check for the app role."""
    m0048 = _migration("0048_correction_audit.py")
    corrections: tuple[str, ...] = m0048.CORRECTIONS
    check: str = m0048.CORRECTION_INSERT
    if history:
        written = (*corrections, *HISTORY)
        before, after = m0048._in(corrections), m0048._in(written)
        assert check.count(before) == 1, before
        check = check.replace(before, after)
        return (*m0048.ACTIONS, *HISTORY), check
    return m0048.ACTIONS, check


def _audit_event(history: bool) -> None:
    actions, check = _actions(history)
    listed = ", ".join(f"'{a}'" for a in actions)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN ({listed}))"
    )
    op.execute("DROP POLICY audit_event_correct ON audit_event")
    op.execute(
        f"CREATE POLICY audit_event_correct ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {check}"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE gym_person ADD COLUMN member_since date,"
        " ADD COLUMN prior_classes integer NOT NULL DEFAULT 0"
        " CONSTRAINT gym_person_prior_classes CHECK (prior_classes >= 0)"
    )
    _audit_event(history=True)
    op.execute(forget_gym_person(history=True))


def downgrade() -> None:
    op.execute(forget_gym_person(history=False))
    # The history rows go with their action, past the policy that holds even the owner
    # to one gym (0044) and the trigger that keeps the log append-only (0048).
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM audit_event WHERE action = 'history_set'")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _audit_event(history=False)
    op.execute("ALTER TABLE gym_person DROP COLUMN prior_classes, DROP COLUMN member_since")
