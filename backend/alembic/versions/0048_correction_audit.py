"""Corrections record who, why, and before and after (#277).

`audit_event` (0044), the gym's log, becomes the record of every correction of a
student's billing, so one query answers "what was changed on this student"
(docs/design/billing-corrections.md, section 3).

- New actions: `ledger_corrected` (an adjustment or a void, a plan's voids included),
  and `due_date_changed`, `membership_reactivated` and `cancel_undone`, which later
  tickets write.
- `audit_event.person_id`: whose billing a correction changed. A person's deletion
  keeps nothing about them, so its row has none, and every correction has one.
- `detail` holds what the correction touched and the figures, read under the same
  locks as the correction: `purpose`, `membership_id`, `billing_period_id`,
  `entry_ids`, and `before` / `after` with `outstanding_clp` and `balance_clp`.
- `rakin_app` inserts a correction's row under a policy: the actor is the person
  acting (`app.person_id`), an owner or admin of the current gym, the person is one of
  the gym's, and the time is the transaction's. A coach writes none and reads none.
- Nothing updates or deletes a row, the owner role included, except
  `forget_gym_person` deleting the corrections of the person it deletes, under the
  `app.forget_person` it already sets for their ledger (0044). It counts them in the
  `person_deleted` row's detail, as `corrections`.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-15

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"
FORGET_PERSON = "NULLIF(current_setting('app.forget_person', true), '')::uuid"

CORRECTIONS = ("ledger_corrected", "due_date_changed", "membership_reactivated", "cancel_undone")
ACTIONS = ("person_deleted", *CORRECTIONS)


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


CORRECTION_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action IN {_in(CORRECTIONS)}"
    f" AND EXISTS (SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM}"
    f" AND s.person_id = {CURRENT_PERSON} AND s.role IN ('owner', 'admin'))"
    f" AND EXISTS (SELECT FROM gym_person gp WHERE gp.gym_id = {CURRENT_GYM}"
    " AND gp.person_id = audit_event.person_id))"
)

APPEND_ONLY = f"""
    CREATE FUNCTION audit_event_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.person_id IS NOT NULL AND OLD.person_id = {FORGET_PERSON} THEN
                RETURN OLD;
            END IF;
        END IF;
        RAISE EXCEPTION 'audit_event rows cannot change or be deleted'
            USING ERRCODE = 'restrict_violation';
    END
    $$
"""

# 0044's `forget_gym_person`, which these turn into this one's: count the person's
# corrections, then delete them while `app.forget_person` names them.
COUNT_BEFORE = "            'refunded_clp', ("
COUNT_AFTER = (
    "            'corrections', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "            ),\n" + COUNT_BEFORE
)
DELETE_BEFORE = "        PERFORM set_config('app.forget_person', '', true);"
DELETE_AFTER = (
    "        DELETE FROM audit_event WHERE gym_id = gym AND person_id = $1;\n" + DELETE_BEFORE
)


def _migration_0044() -> ModuleType:
    """0044, whose `forget_gym_person` this one extends and a downgrade puts back."""
    path = Path(__file__).with_name("0044_void_and_forget.py")
    spec = importlib.util.spec_from_file_location("migration_0044", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(corrections: bool) -> str:
    """0044's function, replacing itself; with `corrections`, it deletes and counts the
    person's correction rows."""
    sql: str = _migration_0044().FORGET.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if corrections:
        for before, after in ((COUNT_BEFORE, COUNT_AFTER), (DELETE_BEFORE, DELETE_AFTER)):
            assert sql.count(before) == 1, before
            sql = sql.replace(before, after)
    return sql


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audit_event ADD COLUMN person_id uuid REFERENCES person (id),"
        " DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {_in(ACTIONS)}),"
        " ADD CONSTRAINT audit_event_person CHECK ("
        "(action = 'person_deleted') = (person_id IS NULL))"
    )
    op.execute(
        "CREATE INDEX audit_event_person_idx ON audit_event (gym_id, person_id, at DESC)"
        " WHERE person_id IS NOT NULL"
    )
    op.execute(f"GRANT INSERT ON audit_event TO {APP_ROLE}")
    op.execute(
        f"CREATE POLICY audit_event_correct ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CORRECTION_INSERT}"
    )
    op.execute(APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON audit_event"
        " FOR EACH ROW EXECUTE FUNCTION audit_event_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_event"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_event_append_only()"
    )
    op.execute(forget_gym_person(corrections=True))


def downgrade() -> None:
    op.execute(forget_gym_person(corrections=False))
    op.execute("DROP TRIGGER audit_event_no_truncate ON audit_event")
    op.execute("DROP TRIGGER audit_event_append_only ON audit_event")
    op.execute("DROP FUNCTION audit_event_append_only()")
    op.execute("DROP POLICY audit_event_correct ON audit_event")
    op.execute(f"REVOKE INSERT ON audit_event FROM {APP_ROLE}")
    # The corrections go with their actions: 0044's log held deletions only. Every
    # gym's, past the policy that holds even the owner to one (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM audit_event WHERE action <> 'person_deleted'")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute("DROP INDEX audit_event_person_idx")
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_person,"
        " DROP CONSTRAINT audit_event_action_check,"
        " ADD CONSTRAINT audit_event_action_check CHECK (action IN ('person_deleted')),"
        " DROP COLUMN person_id"
    )
