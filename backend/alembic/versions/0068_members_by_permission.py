"""The members' writes ask `members_manage`, as their endpoints now do (#310).

0067 kept two things on `money_write` that #310 hands to whoever manages the members
(docs/design/expenses-and-officers.md, section 1):

- `charge_group` and `charge_group_member`: a group is a named list of people (0037),
  which a cobro may target. Writing one is `members_manage`; reading stays the gym's.
  A cobro that targets it is still `money_write` (`extra_charge`).
- `audit_event_correct`: a `history_set` row (0051), which Dar de baja, Agregar exalumno
  and "Fecha de inicio y clases" write beside what they change, is `members_manage`.
  Every other action it lets `rakin_app` insert, the ledger's corrections and a history
  payment's removal, stays `money_write`. `action` is NOT NULL (0044), so each row is
  one or the other.

A downgrade puts both back as 0067 left them.

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-17

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0068"
down_revision: str | Sequence[str] | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0067 = _migration("0067_rls_by_permission.py")
GROUP_TABLES = ("charge_group", "charge_group_member")


def correct_check(members: bool) -> str:
    """`audit_event_correct`'s check as 0067 left it, or with `history_set` rows asking
    `members_manage`."""
    check: str = M0067.by_permission(
        _migration("0055_history_payment.py").correct_check(payments=True), "money_write"
    )
    if members:
        before = M0067.can("money_write")
        after = (
            f"CASE WHEN action = 'history_set' THEN {M0067.can('members_manage')} ELSE {before} END"
        )
        assert check.count(before) == 1, check
        check = check.replace(before, after)
    return check


def _policies(members: bool) -> None:
    permission = "members_manage" if members else "money_write"
    for table in GROUP_TABLES:
        _, _, commands = M0067.MONEY_TABLES[table]
        for command in commands:
            op.execute(f"DROP POLICY {table}_{command.lower()} ON {table}")
            op.execute(M0067._write_policy(table, command, M0067.access(permission)))
    op.execute(
        f"ALTER POLICY audit_event_correct ON audit_event WITH CHECK {correct_check(members)}"
    )


def upgrade() -> None:
    _policies(members=True)


def downgrade() -> None:
    _policies(members=False)
