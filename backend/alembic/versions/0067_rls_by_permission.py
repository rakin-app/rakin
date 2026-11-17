"""RLS by permission: the database checks permissions, not role names (#309).

Every policy that held `rakin_app` to an owner or admin of the gym named the roles,
`s.role IN ('owner', 'admin')` in a subselect on `staff`, and one `ALL` policy served
reads and writes alike. Now one function answers what the person acting may do, and
each policy asks it for the permission the command needs
(docs/design/expenses-and-officers.md, section 7):

- `app_can(p)`: true when the person acting (`app.person_id`) holds the account in the
  current gym (`staff.account_holder`) or a current appointment to a role that carries
  `p`, current in the gym's timezone and half-open as `app.permissions` reads it. It runs
  as the invoker, under the same gym RLS the subselects it replaces ran under. A policy
  calls it as `(SELECT app_can('…'))`: the argument is a constant, so Postgres evaluates
  it once per query, as an initplan, not once per row.
- `ledger_entry`, `extra_charge` and `extra_line`: read with `money_read`, write with
  `money_write`, one policy per command `rakin_app` is granted. `charge_group` and
  `charge_group_member` are still read by anyone in the gym (0037), and written with
  `money_write`. `history_payment` (0055) the same as the ledger.
- `session_delete_by_role` (0033), restrictive, becomes `session_delete`: `gym_setup`.
- `audit_event`: a correction's row (0048, 0051, 0055) and a discount's (0066) are
  written with `money_write`, an import's (0053) with `gym_setup`, as the import itself
  is. The log is read with `money_read`, except an expense's rows (`expense_…`, #314),
  which need `expenses_read`: so a role that sees expenses but not income reads only
  those.
- `undo_import` (0056), which only the titular may run, reads the titular flag instead
  of `role = 'owner'`.

From here nothing in the database reads `staff.role`; the staff API still writes it,
until #313 drops it. A student's own policies (their entries, their dependents', their
proof claims) are about the person acting, not a role, and stay as they are. A downgrade
puts every policy back as it was.

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-17

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# What every role-keyed policy asked, word for word (0006, 0033, 0037, 0044, 0048, 0053,
# 0055, 0066), and the access 0006 built from it.
ROLE_CHECK = (
    f"EXISTS (SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM}"
    f" AND s.person_id = {CURRENT_PERSON} AND s.role IN ('owner', 'admin'))"
)
ROLE_ACCESS = f"(gym_id = {CURRENT_GYM} AND {ROLE_CHECK})"

# `app.permissions.CURRENT_APPOINTMENT`: an appointment `st` is current today in the
# gym's (`g`) timezone, and the day it ends on is the first without it.
APP_CAN = f"""
    CREATE FUNCTION app_can(p text) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public
    AS $$
        SELECT EXISTS (
            SELECT FROM staff s
            WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}
              AND (s.account_holder OR EXISTS (
                  SELECT FROM staff_title st
                  JOIN gym_title t ON t.id = st.title_id
                  JOIN gym g ON g.id = st.gym_id
                  WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
                    AND p = ANY (t.permissions)
                    AND st.starts_on <= (now() AT TIME ZONE g.timezone)::date
                    AND (st.ends_on IS NULL
                         OR (now() AT TIME ZONE g.timezone)::date < st.ends_on)))
        )
    $$
"""


def can(permission: str) -> str:
    """The person acting holds `permission`, evaluated once per query."""
    return f"(SELECT app_can('{permission}'))"


def access(permission: str) -> str:
    """A row of the current gym, for someone holding `permission`."""
    return f"(gym_id = {CURRENT_GYM} AND {can(permission)})"


def by_permission(check: str, permission: str) -> str:
    """`check`, an earlier migration's, asking for `permission` instead of the roles."""
    assert check.count(ROLE_CHECK) == 1, check
    return check.replace(ROLE_CHECK, can(permission))


# Who sees which of the gym's log: an expense's rows (#314) need `expenses_read`,
# every other row `money_read`. `action` is NOT NULL (0044), so every row is one or the other.
EXPENSE_ACTIONS = "starts_with(action, 'expense_')"
AUDIT_READ = (
    f"(gym_id = {CURRENT_GYM} AND CASE WHEN {EXPENSE_ACTIONS}"
    f" THEN {can('expenses_read')} ELSE {can('money_read')} END)"
)

# Each money table `rakin_app` read and wrote under one `<table>_by_role` policy (0006,
# 0037): the permission it now reads with (None: the gym's `<table>_read` from 0037
# stays), the one it writes with, and the commands it is granted to write.
MONEY_TABLES: dict[str, tuple[str | None, str, tuple[str, ...]]] = {
    "ledger_entry": ("money_read", "money_write", ("INSERT", "UPDATE")),
    "extra_charge": ("money_read", "money_write", ("INSERT", "UPDATE")),
    "extra_line": ("money_read", "money_write", ("INSERT", "UPDATE")),
    "charge_group": (None, "money_write", ("INSERT", "UPDATE", "DELETE")),
    "charge_group_member": (None, "money_write", ("INSERT", "DELETE")),
}


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_policy(table: str, command: str, expression: str) -> str:
    clauses = {
        "INSERT": f"WITH CHECK {expression}",
        "UPDATE": f"USING {expression} WITH CHECK {expression}",
        "DELETE": f"USING {expression}",
    }
    return (
        f"CREATE POLICY {table}_{command.lower()} ON {table} FOR {command} TO {APP_ROLE}"
        f" {clauses[command]}"
    )


def undo_import(account_holder: bool) -> str:
    """0056's `undo_import`, replacing itself; with `account_holder`, the titular runs it
    rather than the `owner` role."""
    sql: str = _migration("0056_import_undone.py").UNDO_IMPORT
    sql = sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if account_holder:
        before = "AND person_id = actor AND role = 'owner'"
        assert sql.count(before) == 1, before
        sql = sql.replace(before, "AND person_id = actor AND account_holder")
    return sql


def _audit_and_history(permissions: bool) -> None:
    """The policies an earlier migration made for one command, altered in place."""
    correct: str = _migration("0055_history_payment.py").correct_check(payments=True)
    imported: str = _migration("0053_history_imported.py").import_check()
    discount: str = _migration("0066_discount_reason.py").DISCOUNT_INSERT
    history_write = f"({ROLE_ACCESS} AND created_by = {CURRENT_PERSON})"
    if permissions:
        correct = by_permission(correct, "money_write")
        imported = by_permission(imported, "gym_setup")
        discount = by_permission(discount, "money_write")
        history_write = by_permission(history_write, "money_write")
    read = AUDIT_READ if permissions else ROLE_ACCESS
    ledger_read = access("money_read") if permissions else ROLE_ACCESS
    ledger_write = access("money_write") if permissions else ROLE_ACCESS
    op.execute(f"ALTER POLICY audit_event_read ON audit_event USING {read}")
    op.execute(f"ALTER POLICY audit_event_correct ON audit_event WITH CHECK {correct}")
    op.execute(f"ALTER POLICY audit_event_import ON audit_event WITH CHECK {imported}")
    op.execute(f"ALTER POLICY audit_event_discount ON audit_event WITH CHECK {discount}")
    op.execute(f"ALTER POLICY history_payment_read ON history_payment USING {ledger_read}")
    op.execute(f"ALTER POLICY history_payment_write ON history_payment WITH CHECK {history_write}")
    op.execute(f"ALTER POLICY history_payment_remove ON history_payment USING {ledger_write}")


def upgrade() -> None:
    op.execute(APP_CAN)

    for table, (read, write, commands) in MONEY_TABLES.items():
        op.execute(f"DROP POLICY {table}_by_role ON {table}")
        if read is not None:
            op.execute(
                f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE}"
                f" USING {access(read)}"
            )
        for command in commands:
            op.execute(_write_policy(table, command, access(write)))

    op.execute("ALTER POLICY session_delete_by_role ON session RENAME TO session_delete")
    op.execute(f"ALTER POLICY session_delete ON session USING {access('gym_setup')}")

    _audit_and_history(permissions=True)
    op.execute(undo_import(account_holder=True))


def downgrade() -> None:
    op.execute(undo_import(account_holder=False))
    _audit_and_history(permissions=False)

    op.execute(f"ALTER POLICY session_delete ON session USING {ROLE_ACCESS}")
    op.execute("ALTER POLICY session_delete ON session RENAME TO session_delete_by_role")

    for table, (read, _, commands) in MONEY_TABLES.items():
        for command in commands:
            op.execute(f"DROP POLICY {table}_{command.lower()} ON {table}")
        if read is not None:
            op.execute(f"DROP POLICY {table}_read ON {table}")
        op.execute(
            f"CREATE POLICY {table}_by_role ON {table} TO {APP_ROLE}"
            f" USING {ROLE_ACCESS} WITH CHECK {ROLE_ACCESS}"
        )

    op.execute("DROP FUNCTION app_can(text)")
