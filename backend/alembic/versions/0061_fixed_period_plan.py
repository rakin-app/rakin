"""Fixed-period plans: a season, a year or a term with the same dates for every member (#351).

A rowing club charges its dues for the season, 1 March to 31 December, whoever joins
when; a kids' academy by term. A sixth plan kind, `fixed_period`, is prepaid for
`period_start` to `period_end`, two new columns that every other kind leaves null. Its
members owe one period with those dates (`app.domain.billing`), and move to the next
period's plan, a copy with the dates moved on, by a plan change.

`plan_parameters_per_kind` (0007) is rebuilt with the new kind and columns; the kind
check (0001) with the new kind.

A downgrade makes every fixed-period plan a prepaid one of the months its period
spans, at least one, and drops the dates.

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("monthly", "prepaid", "credits", "dropin", "trial")

# Every kind's parameters, and which of them the kind needs set (as 0007, plus the new
# kind and its columns).
PARAMETERS = ("anchor", "period_months", "credits", "credit_expiry_days")
DATES = ("period_start", "period_end")
REQUIRED = {
    "monthly": "anchor IS NOT NULL",
    "prepaid": "period_months IS NOT NULL",
    "credits": "credits IS NOT NULL AND credit_expiry_days IS NOT NULL",
    "dropin": "true",
    "trial": "price_clp = 0 AND (credits IS NOT NULL OR credit_expiry_days IS NOT NULL)",
}
OWN = {
    "monthly": ("anchor",),
    "prepaid": ("period_months",),
    "credits": ("credits", "credit_expiry_days"),
    "dropin": (),
    "trial": ("credits", "credit_expiry_days"),
}


def _per_kind(
    required: dict[str, str], own: dict[str, tuple[str, ...]], parameters: tuple[str, ...]
) -> str:
    cases = []
    for kind, needs in required.items():
        others = [f"{p} IS NULL" for p in parameters if p not in own[kind]]
        cases.append(f"WHEN '{kind}' THEN {' AND '.join([needs, *others])}")
    return f"CASE kind {' '.join(cases)} END"


def _kinds(kinds: tuple[str, ...]) -> str:
    return ", ".join(f"'{kind}'" for kind in kinds)


def upgrade() -> None:
    op.execute("ALTER TABLE plan ADD COLUMN period_start date, ADD COLUMN period_end date")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_period_ordered CHECK (period_end >= period_start)"
    )
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_kind_check")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_kind_check"
        f" CHECK (kind IN ({_kinds((*KINDS, 'fixed_period'))}))"
    )
    required = {**REQUIRED, "fixed_period": "period_start IS NOT NULL AND period_end IS NOT NULL"}
    own = {**OWN, "fixed_period": DATES}
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_parameters_per_kind")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_parameters_per_kind"
        f" CHECK ({_per_kind(required, own, (*PARAMETERS, *DATES))})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_parameters_per_kind")
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_kind_check")
    # Every gym's, so past RLS for this statement alone.
    op.execute("ALTER TABLE plan NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE plan SET kind = 'prepaid', period_months = greatest(1,"
        " (extract(year FROM period_end) - extract(year FROM period_start)) * 12"
        " + extract(month FROM period_end) - extract(month FROM period_start) + 1)"
        " WHERE kind = 'fixed_period'"
    )
    op.execute("ALTER TABLE plan FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plan DROP COLUMN period_start, DROP COLUMN period_end")
    op.execute(f"ALTER TABLE plan ADD CONSTRAINT plan_kind_check CHECK (kind IN ({_kinds(KINDS)}))")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_parameters_per_kind"
        f" CHECK ({_per_kind(REQUIRED, OWN, PARAMETERS)})"
    )
