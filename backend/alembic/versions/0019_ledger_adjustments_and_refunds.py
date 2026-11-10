"""Manual adjustments and refunds as ledger entries (#38).

An admin corrects what a billing period owes with an `adjustment` on it, and gives
money back with a `refund` of a payment. Both are new entries; nothing already in the
ledger changes (0002).

- An adjustment's sign says which way it goes: positive is in the member's favour and
  counts towards the period as a payment does, negative is owed on top of the period's
  amount due. Every other entry stays positive, its kind saying which way it goes.
  `ledger_entry_amount_sign` holds the table to that; until now nothing did.
- A refund names the payment it gives back (`refund_of`), on the same membership, and
  carries that payment's period: what it gives back no longer counts towards the
  period (`app.domain.billing.settled_amount`). `ledger_entry_refund_of` keeps the
  column to refunds and every refund to a payment it references.
- `v_overdue` (0014) counts a refund against the period it was paid towards, as every
  other settlement in the app now does. `v_balance` already counted refunds as owed
  and settling adjustments by their amount, so a negative one is owed: it is unchanged.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Today in the gym's timezone; `now()` is the transaction's start.
GYM_TODAY = "(now() AT TIME ZONE g.timezone)::date"


def v_overdue(kinds: str, settled: str) -> str:
    """0014's `v_overdue`, summing `settled` of each validated entry `e` of `kinds`."""
    return f"""
SELECT bp.gym_id, bp.id AS billing_period_id, bp.membership_id, m.person_id,
       m.status AS membership_status, bp.period_start, bp.period_end, bp.due_date,
       bp.amount_due_clp, s.paid_clp, bp.amount_due_clp - s.paid_clp AS outstanding_clp,
       {GYM_TODAY} - bp.due_date AS days_overdue
FROM billing_period bp
JOIN membership m ON m.id = bp.membership_id
JOIN gym g ON g.id = bp.gym_id
CROSS JOIN LATERAL (
    SELECT coalesce(sum({settled}), 0)::bigint AS paid_clp
    FROM ledger_entry e
    WHERE e.billing_period_id = bp.id AND e.status = 'validated'
      AND e.kind IN ({kinds})
) s
WHERE EXISTS (
    SELECT FROM ledger_entry c
    WHERE c.billing_period_id = bp.id AND c.kind = 'charge' AND c.status = 'validated'
)
  AND bp.due_date < {GYM_TODAY}
  AND s.paid_clp < bp.amount_due_clp
"""


# app.domain.billing.SETTLING_KINDS and `settled_amount("e")`, before and after.
BEFORE = v_overdue("'payment', 'adjustment'", "e.amount_clp")
AFTER = v_overdue(
    "'payment', 'adjustment', 'refund'",
    "CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END",
)

# `security_invoker` as 0014 created it: the view reads as whoever queries it.
REPLACE_VIEW = "CREATE OR REPLACE VIEW v_overdue WITH (security_invoker = true) AS"


def upgrade() -> None:
    op.execute("ALTER TABLE ledger_entry ADD COLUMN refund_of uuid")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_membership_entry"
        " UNIQUE (membership_id, id)"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_refund_of_fkey"
        " FOREIGN KEY (membership_id, refund_of) REFERENCES ledger_entry (membership_id, id)"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_refund_of"
        " CHECK ((kind = 'refund') = (refund_of IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_amount_sign"
        " CHECK (amount_clp > 0 OR (kind = 'adjustment' AND amount_clp <> 0))"
    )
    op.execute(
        "CREATE INDEX ledger_entry_refund_of_idx ON ledger_entry (refund_of)"
        " WHERE refund_of IS NOT NULL"
    )
    op.execute(f"{REPLACE_VIEW} {AFTER}")


def downgrade() -> None:
    op.execute(f"{REPLACE_VIEW} {BEFORE}")
    op.execute("DROP INDEX ledger_entry_refund_of_idx")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_amount_sign")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_refund_of")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_refund_of_fkey")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_membership_entry")
    op.execute("ALTER TABLE ledger_entry DROP COLUMN refund_of")
