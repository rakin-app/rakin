"""A class registered after it happened, and attendance marked on another day (#407).

A gym that starts using Rakin partway through a month records the classes it held
before that: staff create a class on an earlier day and mark it like any other. Nothing
about the class says so to a member, but the gym's log (`audit_event`, 0044) does, so a
back-filled month can be told apart from one recorded live:

- `class_backfilled`: a class created on an earlier day than the day it was created,
  in the gym's timezone. It names nobody (`person_id` null); `detail` has the session,
  its class type and the day it is for.
- `attendance_backfilled`: someone marked present at a class on a day other than the
  class's own, a drop-in visitor added to one included. It names the person marked, so
  forgetting them (`forget_gym_person`, 0048) takes it with the rest of their rows;
  `detail` has the session, the membership and the class's day.

Whoever takes attendance writes them, a coach included: `rakin_app` inserts one under a
policy of its own, as themselves, now, holding `attendance` (`app_can`, 0067), and an
`attendance_backfilled` row about one of the gym's people. They are read as the rest of
the log is, and are not corrections of anyone's billing: the ficha's "Correcciones"
leaves them out (`app.api.corrections`).

Revision ID: 0070
Revises: 0069
Create Date: 2026-11-17

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0070"
down_revision: str | Sequence[str] | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

CLASS = "class_backfilled"
ATTENDANCE = "attendance_backfilled"

BACKFILL_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    " AND (SELECT app_can('attendance'))"
    f" AND (action = '{CLASS}'"
    f" OR (action = '{ATTENDANCE}'"
    f" AND EXISTS (SELECT FROM gym_person gp WHERE gp.gym_id = {CURRENT_GYM}"
    " AND gp.person_id = audit_event.person_id))))"
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraints(backfilled: bool) -> None:
    """0066's actions, and 0056's that name nobody, with this one's or without."""
    m0048 = _migration("0048_correction_audit.py")
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
    )
    nobody: tuple[str, ...] = ("person_deleted", m0056.IMPORTED, m0056.UNDONE)
    if backfilled:
        actions, nobody = (*actions, CLASS, ATTENDANCE), (*nobody, CLASS)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {m0048._in(actions)}),"
        " DROP CONSTRAINT audit_event_person,"
        " ADD CONSTRAINT audit_event_person CHECK ("
        f"(action IN {m0048._in(nobody)}) = (person_id IS NULL))"
    )


def upgrade() -> None:
    _constraints(backfilled=True)
    op.execute(
        f"CREATE POLICY audit_event_backfill ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {BACKFILL_INSERT}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_backfill ON audit_event")
    # The rows go with their actions, past the trigger that keeps the log append-only
    # (0048), and the policy that holds even the owner to one gym (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action IN ('{CLASS}', '{ATTENDANCE}')")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraints(backfilled=False)
