"""Pagado hasta: money paid before Rakin is not income of the month it is recorded (#286).

"Pagado hasta…" settles the months a member paid before the gym used Rakin, each with a
payment, so billing knows they are paid. That money arrived long ago: the owner's rule
is that it is no income of the month it is typed in. So the payment is marked
`purpose = 'paid_before'`, not by its note alone.

- `ledger_entry_purpose` (0049) takes `paid_before`: a validated payment on a period,
  correcting nothing. It still settles its period (`v_balance`, "Pagado hasta" and
  billing count it as any payment), and it is in no income figure.
- `v_monthly_income` leaves it out, and with it every entry that corrects it later: a
  refund of it, the payment undone as recorded by mistake, or moved (`refund_of` or
  `corrects` naming it). Cobrado, Finanzas Entradas and the accountant export read the
  view. Resumen del mes reads `app.month_figures.stands`, which counts only a payment
  with no purpose.

A downgrade refuses while one is in the ledger, and puts 0089's view and 0049's check
back.

Revision ID: 0093
Revises: 0092
Create Date: 2026-11-22

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0093"
down_revision: str | Sequence[str] | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPTIONS = "WITH (security_invoker = true)"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PURPOSE = _migration("0049_correction_purpose.py")
MOVE = _migration("0089_payment_move.py")

# A payment paid before Rakin, or an entry correcting one, for `e`, a `ledger_entry`.
PAID_BEFORE = (
    "(e.purpose IS NOT DISTINCT FROM 'paid_before' OR EXISTS (SELECT FROM ledger_entry b"
    " WHERE b.id IN (e.refund_of, e.corrects) AND b.purpose = 'paid_before'))"
)

WHERE_BEFORE = MOVE.WHERE_AFTER
WHERE_AFTER = WHERE_BEFORE.replace("\n", f" AND NOT {PAID_BEFORE}\n")


def income(paid_before: bool) -> str:
    """0089's view; with `paid_before`, without the money paid before Rakin."""
    sql: str = MOVE.income(moves=True)
    if paid_before:
        assert sql.count(WHERE_BEFORE) == 1, WHERE_BEFORE
        sql = sql.replace(WHERE_BEFORE, WHERE_AFTER)
    return sql


COMMENT_AFTER = (
    MOVE.COMMENT_AFTER + " A payment of months paid before Rakin (purpose paid_before) is in"
    " none of it, nor what corrects it: that money was not received in the month."
)

CHECK_BEFORE = "            WHEN 'mistake' THEN kind = 'refund'\n"
CHECK_AFTER = CHECK_BEFORE + (
    "            WHEN 'paid_before' THEN kind = 'payment' AND billing_period_id IS NOT NULL\n"
)
PURPOSES_BEFORE = PURPOSE._in(PURPOSE.PURPOSES)
PURPOSES_AFTER = PURPOSE._in((*PURPOSE.PURPOSES, "paid_before"))


def purpose_check(paid_before: bool) -> str:
    """0049's check; with `paid_before`, taking a payment paid before Rakin."""
    sql: str = PURPOSE.PURPOSE_CHECK
    if paid_before:
        assert sql.count(CHECK_BEFORE) == 1 and sql.count(PURPOSES_BEFORE) == 1
        sql = sql.replace(CHECK_BEFORE, CHECK_AFTER).replace(PURPOSES_BEFORE, PURPOSES_AFTER)
    return sql


def upgrade() -> None:
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_purpose")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_purpose"
        f" {purpose_check(paid_before=True)}"
    )
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {income(paid_before=True)}")
    op.execute(MOVE.MISTAKE.comment(COMMENT_AFTER))


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_entry NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM ledger_entry WHERE purpose = 'paid_before') THEN
                RAISE EXCEPTION 'the ledger holds payments paid before Rakin, which 0092 counts'
                    USING HINT = 'entries cannot be deleted: stay on 0093';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {income(paid_before=False)}")
    op.execute(MOVE.MISTAKE.comment(MOVE.COMMENT_AFTER))
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_purpose")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_purpose"
        f" {purpose_check(paid_before=False)}"
    )
