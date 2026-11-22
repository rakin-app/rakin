"""Mover vencimiento: a period's amount due never changes (#283).

docs/design/billing-corrections.md, sections 2 ("What changes in rows") and 4 (guard 2).
A period's `amount_due_clp` and the `charge` entry the billing job writes beside it must
agree, or the ficha's "debe" and the balance on a receipt disagree: amounts change only
by adjustments, which are entries. `billing_period_amount_fixed` refuses an `UPDATE`
that changes it, for every role, the owner included. A period's dates still move, by a
freeze (`shift_billing_periods`, 0027) and, its due date alone, by "Mover vencimiento"
(`PATCH /api/ledger/periods/{id}/due-date`), which records a `due_date_changed` audit
row (0048).

Revision ID: 0090
Revises: 0089
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0090"
down_revision: str | Sequence[str] | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AMOUNT_FIXED = """
    CREATE FUNCTION billing_period_amount_fixed() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'a billing period''s amount due cannot change: adjust it instead'
            USING ERRCODE = 'restrict_violation';
    END
    $$
"""


def upgrade() -> None:
    op.execute(AMOUNT_FIXED)
    op.execute(
        "CREATE TRIGGER billing_period_amount_fixed BEFORE UPDATE OF amount_due_clp"
        " ON billing_period FOR EACH ROW"
        " WHEN (NEW.amount_due_clp IS DISTINCT FROM OLD.amount_due_clp)"
        " EXECUTE FUNCTION billing_period_amount_fixed()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER billing_period_amount_fixed ON billing_period")
    op.execute("DROP FUNCTION billing_period_amount_fixed()")
