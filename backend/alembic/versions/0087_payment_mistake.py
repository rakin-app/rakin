"""Anular pago registrado por error: a payment undone is a correction, not a refund (#281).

docs/design/billing-corrections.md, section 2 (`mistake`). A payment recorded by
mistake is undone with a refund of what is left of it, `purpose = 'mistake'`, naming
the payment both as `refund_of` (so what is left of it to refund goes down, as a
refund takes it) and as `corrects`. 0049 already holds it to `kind = 'refund'`.

- `v_monthly_income` reports it apart, in `corrected_clp` and its count `corrections`:
  "Cobrado" (`income_clp`) still nets it in the month it is made, as it nets a refund,
  but "Reembolsos" (`refunds_clp`, `refunds`) leaves it out, since no money left.
- `ledger_entry_mistake` holds its `corrects` to its `refund_of`, and
  `ledger_entry_one_mistake` lets a payment be undone once. The credit an overpaid
  payment carried is reverted with it (`purpose = 'revert'`), once:
  `ledger_entry_one_revert`.

`forget_refusal` needs nothing: it nets every refund against the payments (0044), so
a mistaken payment already counts as given back.

A downgrade puts 0037's view back, and refuses while a payment undone is in the
ledger: 0086's view would report it as a refund, and an entry cannot be deleted.

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0087"
down_revision: str | Sequence[str] | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
OPTIONS = "WITH (security_invoker = true)"

NET = "CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END"
MISTAKE = "e.purpose = 'mistake'"


def income(corrections: bool) -> str:
    """0037's view; with `corrections`, its refunds without the payments undone, which
    it reports after its own columns."""
    refund = f"e.kind = 'refund' AND {MISTAKE} IS NOT TRUE" if corrections else "e.kind = 'refund'"
    added = (
        f""",
       coalesce(sum(e.amount_clp) FILTER (WHERE {MISTAKE}), 0)::bigint AS corrected_clp,
       count(*) FILTER (WHERE {MISTAKE}) AS corrections"""
        if corrections
        else ""
    )
    return f"""SELECT e.gym_id,
       date_trunc('month', e.validated_at AT TIME ZONE g.timezone)::date AS month,
       sum({NET})::bigint AS income_clp,
       count(*) FILTER (WHERE e.kind = 'payment') AS payments,
       coalesce(sum(e.amount_clp) FILTER (WHERE {refund}), 0)::bigint AS refunds_clp,
       count(*) FILTER (WHERE {refund}) AS refunds,
       coalesce(sum({NET}) FILTER (WHERE e.extra_line_id IS NOT NULL), 0)::bigint
           AS extra_income_clp{added}
FROM ledger_entry e
JOIN gym g ON g.id = e.gym_id
WHERE e.kind IN ('payment', 'refund') AND e.status = 'validated'
GROUP BY e.gym_id, month
"""


COMMENT_BEFORE = (
    "Validated payments less validated refunds per gym and gym-local month, each by the"
    " month it was validated in. The gym's income only for an owner or admin: RLS gives"
    " anyone else the sum of the entries they may read."
    " extra_income_clp is the part of it on cobro extra lines."
)
COMMENT_AFTER = (
    COMMENT_BEFORE + " refunds_clp leaves out the payments undone as recorded by mistake"
    " (purpose mistake), which income_clp nets and corrected_clp reports."
)


def comment(text: str) -> str:
    quoted = text.replace("'", "''")
    return f"COMMENT ON VIEW v_monthly_income IS '{quoted}'"


def upgrade() -> None:
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {income(corrections=True)}")
    op.execute(comment(COMMENT_AFTER))
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_mistake"
        " CHECK (purpose IS DISTINCT FROM 'mistake' OR corrects = refund_of)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_one_mistake ON ledger_entry (corrects)"
        " WHERE purpose = 'mistake'"
    )
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_one_revert ON ledger_entry (corrects)"
        " WHERE purpose = 'revert'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_entry NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM ledger_entry WHERE purpose IN ('mistake', 'revert')) THEN
                RAISE EXCEPTION 'the ledger holds payments undone 0086 has no place for'
                    USING HINT = 'entries cannot be deleted: stay on 0087';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY")
    op.execute("DROP INDEX ledger_entry_one_revert")
    op.execute("DROP INDEX ledger_entry_one_mistake")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_mistake")
    # `CREATE OR REPLACE VIEW` cannot drop a column.
    op.execute("DROP VIEW v_monthly_income")
    op.execute(f"CREATE VIEW v_monthly_income {OPTIONS} AS {income(corrections=False)}")
    op.execute(f"GRANT SELECT ON v_monthly_income TO {APP_ROLE}")
    op.execute(comment(COMMENT_BEFORE))
