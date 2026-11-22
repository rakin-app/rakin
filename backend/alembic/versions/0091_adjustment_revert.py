"""Revertir ajuste and Condonar deuda: a revert names the adjustment it undoes (#282).

docs/design/billing-corrections.md, section 2 (`revert`, `write_off`). 0049 already
holds both purposes to their kind and sign (a write-off in the member's favour, on a
period), and 0087 lets an entry be reverted once (`ledger_entry_one_revert`). What no
check can see is the other row: `ledger_entry_revert` holds a revert to an adjustment
of its own membership and period (a carried credit's has none, #281) and of minus its
amount, which is itself no correction but a write-off: a void is restored, and a
restore, a revert, a move or a mistake is undone by its own inverse (guard 7).

A write-off needs nothing here: "Esperado" reads standing voids only, so it keeps a
period written off, and the book's "Condonado" sums the write-offs of the month.

Revision ID: 0091
Revises: 0090
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVERT_TRIGGER = """
    CREATE FUNCTION ledger_entry_revert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT FROM ledger_entry a
            WHERE a.id = NEW.corrects AND a.kind = 'adjustment'
              AND a.membership_id IS NOT DISTINCT FROM NEW.membership_id
              AND a.billing_period_id IS NOT DISTINCT FROM NEW.billing_period_id
              AND a.amount_clp = -NEW.amount_clp
              AND (a.purpose IS NULL OR a.purpose = 'write_off')
        ) THEN
            RAISE EXCEPTION 'revert %: % is not an adjustment of % on its period',
                NEW.id, NEW.corrects, -NEW.amount_clp
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NULL;
    END
    $$
"""


def upgrade() -> None:
    op.execute(REVERT_TRIGGER)
    op.execute(
        "CREATE CONSTRAINT TRIGGER ledger_entry_revert AFTER INSERT ON ledger_entry"
        " FOR EACH ROW WHEN (NEW.purpose = 'revert')"
        " EXECUTE FUNCTION ledger_entry_revert()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER ledger_entry_revert ON ledger_entry")
    op.execute("DROP FUNCTION ledger_entry_revert()")
