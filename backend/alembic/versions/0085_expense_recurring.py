"""Gastos fijos: rent and bills as monthly templates, recorded by a person (#315).

Rent, internet and the power bill come every month. A gym saves them as templates, and
Gastos lists, for the month it shows, the ones not yet recorded
(docs/design/expenses-and-officers.md, sections 11 and 12):

- `expense_recurring`: a category, a payee and a method, `amount_clp` and
  `amount_kind` (`fixed`: rent, internet, recorded at its amount; `estimated`: power,
  water, gas, where the amount is last bill's and only a hint), the day of the month it
  is usually paid, and `active` (a paused template is listed nowhere).
- `expense.recurring_id`: the template an expense was recorded from. One template has
  at most one expense that counts in a month (`expense_recurring_month`), so a double
  tap, or two people at once, record it once; a voided one frees the month again.
- `expense_skip` ("No este mes"): a template the gym will not pay this month, hidden
  until the next. Taking a skip back deletes its row, the one DELETE here.
- Nothing writes an expense from a template by itself: no trigger, job or default
  does. Each is recorded by a request of a person holding `expenses_write`.
- RLS as 0083's tables: `rakin_app` reads with `expenses_read` and writes with
  `expenses_write`, a template as created by the person acting; the owner (jobs, seed)
  is held to the gym it sets. Nothing in billing reads them.

A downgrade drops both tables and the column.

Revision ID: 0085
Revises: 0084
Create Date: 2026-11-21

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0085"
down_revision: str | Sequence[str] | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

AMOUNT_KINDS = ("fixed", "estimated")


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0067 = _migration("0067_rls_by_permission.py")
M0083 = _migration("0083_expenses.py")
_in = M0083._in

RECURRING = f"""
CREATE TABLE expense_recurring (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    category_id uuid NOT NULL,
    payee text CHECK (payee = btrim(payee) AND length(payee) BETWEEN 1 AND 200),
    method text CHECK (method IN {_in(M0083.METHODS)}),
    amount_clp bigint NOT NULL CHECK (amount_clp > 0),
    amount_kind text NOT NULL CHECK (amount_kind IN {_in(AMOUNT_KINDS)}),
    day_of_month smallint NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    active boolean NOT NULL DEFAULT true,
    created_by uuid NOT NULL REFERENCES person (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    UNIQUE (id, gym_id),
    FOREIGN KEY (category_id, gym_id) REFERENCES expense_category (id, gym_id)
)
"""

SKIP = """
CREATE TABLE expense_skip (
    gym_id uuid NOT NULL,
    recurring_id uuid NOT NULL,
    month date NOT NULL CHECK (extract(day FROM month) = 1),
    created_by uuid NOT NULL REFERENCES person (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recurring_id, month),
    FOREIGN KEY (recurring_id, gym_id) REFERENCES expense_recurring (id, gym_id)
)
"""

# Who created a template, and when, never changes.
RECURRING_KEPT = """
CREATE FUNCTION expense_recurring_kept() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.gym_id <> OLD.gym_id OR NEW.created_by <> OLD.created_by
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'who created a template, and when, is kept'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$
"""

# The month an expense counts in, as an immutable expression an index can hold: a
# `date` cast to `timestamp` (not `timestamptz`) truncates the same in every timezone.
MONTH_OF = "date_trunc('month', spent_on::timestamp)"

READ = M0067.access("expenses_read")
WRITE = M0067.access("expenses_write")
CREATED_BY_ME = f"({WRITE} AND created_by = {CURRENT_PERSON})"


def _gym_isolated(table: str, grants: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE} USING {READ}")
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")


def upgrade() -> None:
    op.execute(RECURRING)
    op.execute("CREATE INDEX expense_recurring_gym ON expense_recurring (gym_id)")
    _gym_isolated("expense_recurring", "SELECT, INSERT, UPDATE")
    op.execute(
        f"CREATE POLICY expense_recurring_insert ON expense_recurring FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CREATED_BY_ME}"
    )
    op.execute(
        f"CREATE POLICY expense_recurring_update ON expense_recurring FOR UPDATE TO {APP_ROLE}"
        f" USING {WRITE} WITH CHECK {WRITE}"
    )
    op.execute(RECURRING_KEPT)
    op.execute(
        "CREATE TRIGGER expense_recurring_kept BEFORE UPDATE ON expense_recurring"
        " FOR EACH ROW EXECUTE FUNCTION expense_recurring_kept()"
    )

    op.execute(SKIP)
    _gym_isolated("expense_skip", "SELECT, INSERT, DELETE")
    op.execute(
        f"CREATE POLICY expense_skip_insert ON expense_skip FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CREATED_BY_ME}"
    )
    op.execute(
        f"CREATE POLICY expense_skip_delete ON expense_skip FOR DELETE TO {APP_ROLE} USING {WRITE}"
    )

    op.execute(
        "ALTER TABLE expense ADD COLUMN recurring_id uuid,"
        " ADD CONSTRAINT expense_recurring_fk FOREIGN KEY (recurring_id, gym_id)"
        " REFERENCES expense_recurring (id, gym_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX expense_recurring_month ON expense (recurring_id, ({MONTH_OF}))"
        " WHERE recurring_id IS NOT NULL AND voided_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX expense_recurring_month")
    op.execute("ALTER TABLE expense DROP CONSTRAINT expense_recurring_fk")
    op.execute("ALTER TABLE expense DROP COLUMN recurring_id")
    op.execute("DROP TABLE expense_skip")
    op.execute("DROP TABLE expense_recurring")
    op.execute("DROP FUNCTION expense_recurring_kept()")
