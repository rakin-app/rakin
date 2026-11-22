"""Gastos recuperados con cobros extra: an expense names the cobro that recovers it (#318).

A gym often pays for something on the group's behalf, a trip or a seminar, and gets it
back through a Cobro extra (docs/design/expenses-and-officers.md, section 14):

- `expense.extra_charge_id`: the cobro extra that recovers the expense, if any. Many
  expenses may name one cobro (the bus and the hotel). The foreign key carries the gym,
  so an expense names only a cobro of its own gym.
- It points one way, from the expense to the cobro: no billing table points at the
  expenses, and nothing about the cobro, its lines or what any member owes reads it.
  Both stay gross; nothing nets.
- No policy changes: the column is the expense's, read with `expenses_read` and written
  with `expenses_write` (0083). A cobro is never deleted, so the key holds.

A downgrade drops the column.

Revision ID: 0086
Revises: 0085
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0086"
down_revision: str | Sequence[str] | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE expense ADD COLUMN extra_charge_id uuid,"
        " ADD CONSTRAINT expense_extra_charge_fk FOREIGN KEY (gym_id, extra_charge_id)"
        " REFERENCES extra_charge (gym_id, id)"
    )
    op.execute(
        "CREATE INDEX expense_extra_charge ON expense (extra_charge_id)"
        " WHERE extra_charge_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX expense_extra_charge")
    op.execute("ALTER TABLE expense DROP CONSTRAINT expense_extra_charge_fk")
    op.execute("ALTER TABLE expense DROP COLUMN extra_charge_id")
