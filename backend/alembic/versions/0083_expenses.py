"""Gastos: what the gym spends, apart from billing (#314).

Rakin knew what members owe and pay, not what the gym spends. Now an expense is a date,
an amount, a category from the gym's own list, who was paid, how, a note and an
optional receipt (docs/design/expenses-and-officers.md, sections 10 and 12):

- `expense_category`, the gym's own list. Every gym starts with Arriendo, Luz, Agua,
  Gas, Internet y teléfono, Federación, Seguros, Sueldos y honorarios, Equipamiento,
  Eventos y competencias, Mantención y aseo and Otros: those here now from this
  migration, a new one from a trigger as it is created (as its roles come, 0065). A
  category is renamed, reordered or archived, never deleted, so last year's expenses
  still read theirs; `is_other` marks Otros, which cannot be archived.
- `expense`: `spent_on` (the day it was paid, which decides its month), `amount_clp`
  above zero, its category, `payee` and `method` (transferencia, efectivo, tarjeta,
  otro), a note, `receipt_object_key` under `receipts/<gym_id>/`, `created_by`; and
  `voided_at`, `voided_by`, `void_reason` once it is voided ("Anular"). A voided expense
  is kept, and no longer changes: a trigger refuses any update of it, and of who
  recorded any expense and when.
- Nothing in billing reads them: no billing table points at them, and no view, job or
  export joins them.
- RLS by permission, as 0067's tables are: `rakin_app` reads both with
  `expenses_read` and writes them with `expenses_write`, an expense only as recorded by
  the person acting. It has no DELETE on either. The owner (jobs, seed) is held to the
  gym it sets.
- `audit_event` takes `expense_changed` (an edit, with the changed fields before and
  after) and `expense_voided` (with the reason). They name no person: an expense names
  its payee in text. Whoever holds `expenses_write` writes them, as themselves, now,
  about one of the gym's expenses; `audit_event_read` already gives them to
  `expenses_read` alone (0067).

A downgrade drops the tables and the expense rows of the log.

Revision ID: 0083
Revises: 0082
Create Date: 2026-11-21

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

CHANGED = "expense_changed"
VOIDED = "expense_voided"
EXPENSE_ACTIONS = (CHANGED, VOIDED)

# The categories a gym starts with, in their order, each by a key its id derives from
# (`app.seed.build.default_expense_category_id`); the last is Otros.
DEFAULT_CATEGORIES = (
    ("arriendo", "Arriendo"),
    ("luz", "Luz"),
    ("agua", "Agua"),
    ("gas", "Gas"),
    ("internet", "Internet y teléfono"),
    ("federacion", "Federación"),
    ("seguros", "Seguros"),
    ("sueldos", "Sueldos y honorarios"),
    ("equipamiento", "Equipamiento"),
    ("eventos", "Eventos y competencias"),
    ("mantencion", "Mantención y aseo"),
    ("otros", "Otros"),
)
METHODS = ("transfer", "cash", "card", "other")


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0067 = _migration("0067_rls_by_permission.py")
M0071 = _migration("0071_equipo.py")
_in = M0071._in

CATEGORY = """
CREATE TABLE expense_category (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    name text NOT NULL CHECK (name = btrim(name) AND length(name) BETWEEN 1 AND 60),
    sort integer NOT NULL,
    is_other boolean NOT NULL DEFAULT false,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, gym_id),
    CONSTRAINT expense_category_other_kept CHECK (NOT (is_other AND archived_at IS NOT NULL))
)
"""

EXPENSE = f"""
CREATE TABLE expense (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    spent_on date NOT NULL,
    amount_clp bigint NOT NULL CHECK (amount_clp > 0),
    category_id uuid NOT NULL,
    payee text CHECK (payee = btrim(payee) AND length(payee) BETWEEN 1 AND 200),
    method text CHECK (method IN {_in(METHODS)}),
    note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
    receipt_object_key text UNIQUE
        CHECK (starts_with(receipt_object_key, 'receipts/' || gym_id::text || '/')),
    created_by uuid NOT NULL REFERENCES person (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    voided_at timestamptz,
    voided_by uuid REFERENCES person (id),
    void_reason text CHECK (length(void_reason) BETWEEN 1 AND 500),
    FOREIGN KEY (category_id, gym_id) REFERENCES expense_category (id, gym_id),
    CONSTRAINT expense_void CHECK (
        (voided_at IS NULL) = (voided_by IS NULL)
        AND (voided_at IS NULL) = (void_reason IS NULL))
)
"""

# A voided expense is the record of one that did not count, and stays as it was; who
# recorded an expense, and when, never changes.
KEPT = """
CREATE FUNCTION expense_kept() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF OLD.voided_at IS NOT NULL THEN
        RAISE EXCEPTION 'a voided expense is not changed' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.id <> OLD.id OR NEW.gym_id <> OLD.gym_id OR NEW.created_by <> OLD.created_by
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'who recorded an expense, and when, is kept'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$
"""

_DEFAULT_VALUES = ",\n                ".join(
    f"('{key}', '{name}', {sort}, {str(key == 'otros').lower()})"
    for sort, (key, name) in enumerate(DEFAULT_CATEGORIES, start=1)
)

# As whoever inserts the gym, with `app.gym_id` set to it for the inserts and put back
# after, so RLS holds them to that gym (0065's `add_preset_titles`). A gym that has
# categories already gets none. Each id is derived from the gym and the key, as 0028's
# block kinds are, so the seed can record expenses under them.
ADD_DEFAULTS = f"""
CREATE FUNCTION add_default_expense_categories(gym uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    previous text := current_setting('app.gym_id', true);
BEGIN
    PERFORM set_config('app.gym_id', gym::text, true);
    IF NOT EXISTS (SELECT FROM expense_category WHERE gym_id = gym) THEN
        INSERT INTO expense_category (id, gym_id, name, sort, is_other)
        SELECT md5(gym::text || '/expense_category/' || d.key)::uuid, gym, d.name, d.sort,
               d.is_other
        FROM (VALUES
                {_DEFAULT_VALUES}
             ) AS d (key, name, sort, is_other);
    END IF;
    PERFORM set_config('app.gym_id', coalesce(previous, ''), true);
END
$$
"""

GYM_DEFAULTS = """
CREATE FUNCTION gym_default_expense_categories() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM add_default_expense_categories(NEW.id);
    RETURN NULL;
END
$$
"""

# FORCEd RLS hides every gym from the owner running this, and `jobs_gym_ids()` (0011)
# lists them.
BACKFILL = """
DO $$
DECLARE
    g uuid;
BEGIN
    FOR g IN SELECT jobs_gym_ids() LOOP
        PERFORM add_default_expense_categories(g);
    END LOOP;
END
$$
"""

READ = M0067.access("expenses_read")
WRITE = M0067.access("expenses_write")
RECORDED_BY_ME = f"({WRITE} AND created_by = {CURRENT_PERSON})"

# Someone holding `expenses_write` in the current gym, as themselves, now, about one of
# the gym's expenses (which `expense_read` shows them).
EXPENSE_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action IN {_in(EXPENSE_ACTIONS)} AND {M0067.can('expenses_write')}"
    " AND EXISTS (SELECT FROM expense e WHERE e.gym_id = audit_event.gym_id"
    " AND e.id::text = audit_event.detail->>'expense_id'))"
)


def _constraints(expenses: bool) -> None:
    """0071's constraints, with the expense actions or without: they name nobody."""
    m0056 = _migration("0056_import_undone.py")
    actions: tuple[str, ...] = M0071._actions(team=True)
    unnamed: tuple[str, ...] = (
        "person_deleted",
        m0056.IMPORTED,
        m0056.UNDONE,
        M0071.M0070.CLASS,
        *M0071.TITLE_ACTIONS,
    )
    if expenses:
        actions = (*actions, *EXPENSE_ACTIONS)
        unnamed = (*unnamed, *EXPENSE_ACTIONS)
    person = f"(action IN {_in(unnamed)}) = (person_id IS NULL)"
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {_in(actions)}),"
        f" DROP CONSTRAINT audit_event_person, ADD CONSTRAINT audit_event_person CHECK ({person})"
    )


def _gym_isolated(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE} USING {READ}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")


def upgrade() -> None:
    op.execute(CATEGORY)
    op.execute(
        "CREATE UNIQUE INDEX expense_category_name ON expense_category (gym_id, lower(name))"
        " WHERE archived_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX expense_category_other ON expense_category (gym_id) WHERE is_other"
    )
    _gym_isolated("expense_category")
    op.execute(
        f"CREATE POLICY expense_category_insert ON expense_category FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {WRITE}"
    )
    op.execute(
        f"CREATE POLICY expense_category_update ON expense_category FOR UPDATE TO {APP_ROLE}"
        f" USING {WRITE} WITH CHECK {WRITE}"
    )

    op.execute(EXPENSE)
    op.execute("CREATE INDEX expense_gym_spent_on ON expense (gym_id, spent_on DESC)")
    op.execute("CREATE INDEX expense_category_idx ON expense (category_id)")
    _gym_isolated("expense")
    op.execute(
        f"CREATE POLICY expense_insert ON expense FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {RECORDED_BY_ME}"
    )
    op.execute(
        f"CREATE POLICY expense_update ON expense FOR UPDATE TO {APP_ROLE}"
        f" USING {WRITE} WITH CHECK {WRITE}"
    )
    op.execute(KEPT)
    op.execute(
        "CREATE TRIGGER expense_kept BEFORE UPDATE ON expense"
        " FOR EACH ROW EXECUTE FUNCTION expense_kept()"
    )

    op.execute(ADD_DEFAULTS)
    op.execute(GYM_DEFAULTS)
    op.execute(
        "CREATE TRIGGER gym_default_expense_categories AFTER INSERT ON gym"
        " FOR EACH ROW EXECUTE FUNCTION gym_default_expense_categories()"
    )
    op.execute(BACKFILL)

    _constraints(expenses=True)
    op.execute(
        f"CREATE POLICY audit_event_expense ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {EXPENSE_INSERT}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_expense ON audit_event")
    # The rows go with their action, past the trigger that keeps the log append-only
    # (0048), and the policy that holds even the owner to one gym (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action IN {_in(EXPENSE_ACTIONS)}")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraints(expenses=False)

    op.execute("DROP TRIGGER gym_default_expense_categories ON gym")
    op.execute("DROP FUNCTION gym_default_expense_categories()")
    op.execute("DROP FUNCTION add_default_expense_categories(uuid)")
    op.execute("DROP TABLE expense")
    op.execute("DROP FUNCTION expense_kept()")
    op.execute("DROP TABLE expense_category")
