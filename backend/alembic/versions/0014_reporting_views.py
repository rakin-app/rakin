"""Reporting views over the ledger: `v_overdue`, `v_balance`, `v_monthly_income`.

Derived views, not tables (docs/technical.md#domain-model). Each is created
`WITH (security_invoker = true)`, so it reads as the role querying it and every table
it reads keeps its own RLS: the gym in `app.gym_id` (0001), and for `rakin_app` the
ledger only for an owner or admin (0006) or a person's own and their dependents'
entries (0010). Without it a view reads as its owner and those policies would not
apply.

Each view's rows exist only through `ledger_entry` rows the reader can see, so
whoever may not read an entry gets no row from it rather than a wrong total: a coach sees
none of the three, where a view driven by `billing_period` or `membership` (which a
coach may read) would show them every period as unpaid and every balance as zero.

Amounts in the ledger are positive and the kind says which way they go
(`app.domain.ledger`). Only validated entries count.

- `v_overdue`: one row per billing period whose due date is past in the gym's
  timezone and whose validated payments and adjustments (`app.domain.billing`'s
  `SETTLING_KINDS`) do not cover its amount due. It lists only a period whose
  validated charge the reader can see, which the `billing_periods` job writes with
  every period it bills; a period discounted to nothing has none and is never
  overdue. It is an `EXISTS`, not a join, so a second charge on a period could not
  list it twice. It carries
  the membership's status, so a reader that counts only Active members, as the
  owner's dashboard does, filters on it. A period due today is not yet overdue.
- `v_balance`: one row per membership with any ledger entry it can read: charges and
  refunds less payments and the adjustments settling a period. Positive is owed,
  negative is credit. A validated adjustment with no period is the credit an
  overpayment carries forward (`app.api.ledger`): its payment already counts the
  whole amount paid, so the credit is not subtracted twice.
- `v_monthly_income`: per gym and calendar month in the gym's timezone, the sum and
  count of validated payments, by the month each was validated in. It is the gym's
  income only for an owner or admin, who read every entry: a member gets the sum
  of their own and their dependents' payments under the same name. Its
  `COMMENT ON VIEW` says so.

`v_inactive` (last attendance more than N days ago) waits for the attendance table,
#41, which creates it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

# app.domain.billing.SETTLING_KINDS
SETTLING_KINDS = "'payment', 'adjustment'"

# Today in the gym's timezone; `now()` is the transaction's start.
GYM_TODAY = "(now() AT TIME ZONE g.timezone)::date"

VIEWS = {
    "v_overdue": f"""
SELECT bp.gym_id, bp.id AS billing_period_id, bp.membership_id, m.person_id,
       m.status AS membership_status, bp.period_start, bp.period_end, bp.due_date,
       bp.amount_due_clp, s.paid_clp, bp.amount_due_clp - s.paid_clp AS outstanding_clp,
       {GYM_TODAY} - bp.due_date AS days_overdue
FROM billing_period bp
JOIN membership m ON m.id = bp.membership_id
JOIN gym g ON g.id = bp.gym_id
CROSS JOIN LATERAL (
    SELECT coalesce(sum(e.amount_clp), 0)::bigint AS paid_clp
    FROM ledger_entry e
    WHERE e.billing_period_id = bp.id AND e.status = 'validated'
      AND e.kind IN ({SETTLING_KINDS})
) s
WHERE EXISTS (
    SELECT FROM ledger_entry c
    WHERE c.billing_period_id = bp.id AND c.kind = 'charge' AND c.status = 'validated'
)
  AND bp.due_date < {GYM_TODAY}
  AND s.paid_clp < bp.amount_due_clp
""",
    "v_balance": """
SELECT e.gym_id, e.membership_id,
       sum(CASE
               WHEN e.kind IN ('charge', 'refund') THEN e.amount_clp
               WHEN e.kind = 'payment' THEN -e.amount_clp
               WHEN e.kind = 'adjustment' AND e.billing_period_id IS NOT NULL
                   THEN -e.amount_clp
               ELSE 0
           END)::bigint AS balance_clp
FROM ledger_entry e
WHERE e.status = 'validated'
GROUP BY e.gym_id, e.membership_id
""",
    "v_monthly_income": """
SELECT e.gym_id, date_trunc('month', e.validated_at AT TIME ZONE g.timezone)::date AS month,
       sum(e.amount_clp)::bigint AS income_clp, count(*) AS payments
FROM ledger_entry e
JOIN gym g ON g.id = e.gym_id
WHERE e.kind = 'payment' AND e.status = 'validated'
GROUP BY e.gym_id, month
""",
}

COMMENTS = {
    "v_monthly_income": (
        "Validated payments per gym and gym-local month. The gym's income only for an"
        " owner or admin: RLS gives anyone else the sum of the payments they may read."
    ),
}


def upgrade() -> None:
    for name, query in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {query}")
        op.execute(f"GRANT SELECT ON {name} TO {APP_ROLE}")
    for name, comment in COMMENTS.items():
        quoted = comment.replace("'", "''")
        op.execute(f"COMMENT ON VIEW {name} IS '{quoted}'")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
