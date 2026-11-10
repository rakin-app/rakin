"""`v_monthly_income` net of refunds (#126).

0014's view summed the validated payments of each gym-local month, so a refund (0021)
did not reduce what the month collected. It now counts the validated payments less
the validated refunds, each by the month it was validated in: a refund counts in the
month it was made, not the month of the payment it gives back. A month with only
refunds has a row, its income negative.

`income_clp` is that net figure and `payments` still counts the payments; the new
`refunds_clp` and `refunds` are the month's refunds, which "Cobrado" shows beside it.
The columns 0014 had keep their names, types and order, so the view is replaced in
place; going back drops the two new ones, which `CREATE OR REPLACE VIEW` cannot, so
the downgrade recreates 0014's view with its grant and comment.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

# `security_invoker` as 0014 created it: the view reads as whoever queries it.
OPTIONS = "WITH (security_invoker = true)"

MONTH = "date_trunc('month', e.validated_at AT TIME ZONE g.timezone)::date AS month"

BEFORE = f"""
SELECT e.gym_id, {MONTH},
       sum(e.amount_clp)::bigint AS income_clp, count(*) AS payments
FROM ledger_entry e
JOIN gym g ON g.id = e.gym_id
WHERE e.kind = 'payment' AND e.status = 'validated'
GROUP BY e.gym_id, month
"""

AFTER = f"""
SELECT e.gym_id, {MONTH},
       sum(CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END)::bigint
           AS income_clp,
       count(*) FILTER (WHERE e.kind = 'payment') AS payments,
       coalesce(sum(e.amount_clp) FILTER (WHERE e.kind = 'refund'), 0)::bigint
           AS refunds_clp,
       count(*) FILTER (WHERE e.kind = 'refund') AS refunds
FROM ledger_entry e
JOIN gym g ON g.id = e.gym_id
WHERE e.kind IN ('payment', 'refund') AND e.status = 'validated'
GROUP BY e.gym_id, month
"""

COMMENT_BEFORE = (
    "Validated payments per gym and gym-local month. The gym's income only for an"
    " owner or admin: RLS gives anyone else the sum of the payments they may read."
)
COMMENT_AFTER = (
    "Validated payments less validated refunds per gym and gym-local month, each by the"
    " month it was validated in. The gym's income only for an owner or admin: RLS gives"
    " anyone else the sum of the entries they may read."
)


def comment(text: str) -> str:
    quoted = text.replace("'", "''")
    return f"COMMENT ON VIEW v_monthly_income IS '{quoted}'"


def upgrade() -> None:
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {AFTER}")
    op.execute(comment(COMMENT_AFTER))


def downgrade() -> None:
    op.execute("DROP VIEW v_monthly_income")
    op.execute(f"CREATE VIEW v_monthly_income {OPTIONS} AS {BEFORE}")
    op.execute(f"GRANT SELECT ON v_monthly_income TO {APP_ROLE}")
    op.execute(comment(COMMENT_BEFORE))
