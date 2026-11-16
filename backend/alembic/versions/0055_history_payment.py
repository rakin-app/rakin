"""Historial de pagos: what a student paid before Rakin, never read by billing (#295).

The third of the historical-data tickets (docs/design/historical-data.md, sections 2, 4
and 6). A payment the gym received before Rakin is not a ledger entry: the ledger dates
income by when it was recorded and hangs every entry off a membership's period, the
rows billing bills, lapses and mails from. So it is a row of its own:

- `history_payment`: the day it was paid, the amount, how (or null: old records often
  do not say), the month it paid for as its first day (or null), the plan as the gym
  called it then, a note, and where it came from: typed (`manual`) or imported
  (`import`, with `import_id`, the import's audit row, #297), by whom and when. No job,
  view or export reads it. The API keeps `paid_on` within 60 years of the gym's today
  and the month before the person's first membership (`covers_plan`): neither is a
  constant the table can hold.
- RLS as every tenant table, and for `rakin_app` the ledger's access (0006): an owner
  or admin of the gym reads, inserts as themselves (`created_by`) and deletes. No
  update: a typo is removed and typed again.
- Removing one is recorded in `audit_event` as `history_removed`, with the whole row in
  `detail` and the reason, under the policy 0051's `history_set` is written by. 0053's
  `history_imported` stays among the actions.
- `forget_gym_person` deletes the person's history payments with the rest, and counts
  them in `person_deleted` (`history_payments`) beside their `history_removed` rows.
  Neither is money in the ledger, so `forget_refusal` lets someone whose only money is
  history be deleted.

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-15

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# 0006's LEDGER_ACCESS: an owner or admin of the current gym.
LEDGER_ACCESS = (
    f"(gym_id = {CURRENT_GYM} AND EXISTS ("
    f"SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    " AND s.role IN ('owner', 'admin')))"
)

REMOVED = "history_removed"

# 0054's `forget_gym_person` (0051's, grades by person): its corrections leave out every
# history action, and beside its `history_set` it counts the removals and the payments.
COUNT_BEFORE = (
    "                AND action <> 'history_set'\n"
    "            ),\n"
    "            'history_set', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "                AND action = 'history_set'\n"
    "            ),\n"
)
COUNT_AFTER = (
    f"                AND action NOT IN ('history_set', '{REMOVED}')\n"
    "            ),\n"
    "            'history_set', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    "                AND action = 'history_set'\n"
    "            ),\n"
    f"            '{REMOVED}', (\n"
    "                SELECT count(*) FROM audit_event WHERE gym_id = gym AND person_id = $1\n"
    f"                AND action = '{REMOVED}'\n"
    "            ),\n"
    "            'history_payments', (\n"
    "                SELECT count(*) FROM history_payment WHERE gym_id = gym AND person_id = $1\n"
    "            ),\n"
)
DELETE_BEFORE = "        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;"
DELETE_AFTER = (
    "        DELETE FROM history_payment WHERE gym_id = gym AND person_id = $1;\n" + DELETE_BEFORE
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(payments: bool) -> str:
    """0054's function, replacing itself; with `payments`, it deletes and counts the
    person's history payments, and counts their removals apart from their corrections."""
    sql: str = _migration("0054_grades_by_person.py").forget_gym_person(by_person=True)
    if payments:
        for before, after in ((COUNT_BEFORE, COUNT_AFTER), (DELETE_BEFORE, DELETE_AFTER)):
            assert sql.count(before) == 1, before
            sql = sql.replace(before, after)
    return sql


def _audit_event(payments: bool) -> None:
    """`audit_event`'s actions and its insert policy for the app role, 0053's with
    `history_removed` or without."""
    m0048 = _migration("0048_correction_audit.py")
    m0051 = _migration("0051_person_history.py")
    actions, check = m0051._actions(history=True)
    actions = (*actions, _migration("0053_history_imported.py").IMPORTED)
    if payments:
        written = (*m0048.CORRECTIONS, *m0051.HISTORY)
        before, after = m0048._in(written), m0048._in((*written, REMOVED))
        assert check.count(before) == 1, before
        check = check.replace(before, after)
        actions = (*actions, REMOVED)
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
    op.execute("""
        CREATE TABLE history_payment (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL,
            person_id uuid NOT NULL,
            paid_on date NOT NULL,
            amount_clp bigint NOT NULL CHECK (amount_clp > 0),
            method text CHECK (method IN ('cash', 'transfer', 'other')),
            covers_month date CHECK (covers_month = date_trunc('month', covers_month)::date),
            plan_name text CHECK (char_length(plan_name) BETWEEN 1 AND 200),
            note text CHECK (char_length(note) BETWEEN 1 AND 500),
            source text NOT NULL CHECK (source IN ('manual', 'import')),
            import_id uuid REFERENCES audit_event (id),
            created_by uuid NOT NULL REFERENCES person (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT history_payment_import CHECK (
                (source = 'import') = (import_id IS NOT NULL)),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute(
        "CREATE INDEX history_payment_person ON history_payment (gym_id, person_id, paid_on)"
    )
    op.execute(
        "CREATE INDEX history_payment_import_idx ON history_payment (import_id)"
        " WHERE import_id IS NOT NULL"
    )
    op.execute(f"GRANT SELECT, INSERT, DELETE ON history_payment TO {APP_ROLE}")
    op.execute("ALTER TABLE history_payment ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE history_payment FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY history_payment_isolation ON history_payment TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY history_payment_read ON history_payment FOR SELECT TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS}"
    )
    op.execute(
        f"CREATE POLICY history_payment_write ON history_payment FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK ({LEDGER_ACCESS} AND created_by = {CURRENT_PERSON})"
    )
    op.execute(
        f"CREATE POLICY history_payment_remove ON history_payment FOR DELETE TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS}"
    )
    _audit_event(payments=True)
    op.execute(forget_gym_person(payments=True))


def downgrade() -> None:
    op.execute(forget_gym_person(payments=False))
    # The removals go with their action, past the policy that holds even the owner to
    # one gym (0044) and the trigger that keeps the log append-only (0048).
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM audit_event WHERE action = '{REMOVED}'")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _audit_event(payments=False)
    op.execute("DROP TABLE history_payment")
