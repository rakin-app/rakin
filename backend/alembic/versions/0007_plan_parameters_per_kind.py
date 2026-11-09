"""Each plan kind carries exactly its own parameters, and a plan is never deleted.

Five kinds, parameters per kind (docs/technical.md#sport-agnostic-design):

| kind    | parameters                              |
| ------- | --------------------------------------- |
| monthly | price, anchor (signup day or the 1st)   |
| prepaid | price, period_months                    |
| credits | price, credits, credit_expiry_days      |
| dropin  | price                                   |
| trial   | free classes or free days (or both)     |

`anchor` is new: `signup` bills on the day of the month the member joined, `first` on
the 1st. A membership copies it into `anchor_day` when it starts. Existing monthly
plans get `signup`, which is how the seed already bills them.

A trial's free classes and free days live in `credits` and `credit_expiry_days`, the
columns a credits plan uses for the same two things: classes it allows, days it lasts.
The membership already counts a trial's free classes in `credits_remaining`
(`app.domain.membership`). The API names them `free_classes` and `free_days`. A trial
is free, so its `price_clp` is 0.

One check replaces 0001's two partial ones: a kind's own parameters are set, and every
other kind's are null, so a row cannot say two things at once.

A plan is deactivated (`active = false`), never deleted: memberships, billing periods
and the ledger point at it for as long as the gym keeps its history. `rakin_app` was
never granted `DELETE` on it; a trigger now holds every role to that, the owner and
superusers included, as 0002 does for the ledger. Violations raise
`restrict_violation` (SQLSTATE 23001).

The downgrade drops `anchor` and puts 0001's checks back; a trial keeps its values.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every kind's parameters, and which of them the kind needs set.
PARAMETERS = ("anchor", "period_months", "credits", "credit_expiry_days")
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


def _per_kind() -> str:
    cases = []
    for kind, required in REQUIRED.items():
        others = [f"{p} IS NULL" for p in PARAMETERS if p not in OWN[kind]]
        cases.append(f"WHEN '{kind}' THEN {' AND '.join([required, *others])}")
    return f"CASE kind {' '.join(cases)} END"


HINT = "deactivate the plan instead: active = false"


def upgrade() -> None:
    op.execute("ALTER TABLE plan ADD COLUMN anchor text CHECK (anchor IN ('signup', 'first'))")

    # The owner is held to FORCEd RLS; lifted for the backfill only, inside the
    # migration's transaction.
    op.execute("ALTER TABLE plan NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE plan SET anchor = 'signup' WHERE kind = 'monthly'")
    op.execute("ALTER TABLE plan FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_check, DROP CONSTRAINT plan_check1")
    op.execute(f"ALTER TABLE plan ADD CONSTRAINT plan_parameters_per_kind CHECK ({_per_kind()})")

    op.execute(f"""
        CREATE FUNCTION plan_never_deleted() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'plans cannot be deleted'
                USING ERRCODE = 'restrict_violation', HINT = '{HINT}';
        END
        $$
    """)
    op.execute(
        "CREATE TRIGGER plan_never_deleted BEFORE DELETE ON plan"
        " FOR EACH ROW EXECUTE FUNCTION plan_never_deleted()"
    )
    op.execute(
        "CREATE TRIGGER plan_no_truncate BEFORE TRUNCATE ON plan"
        " FOR EACH STATEMENT EXECUTE FUNCTION plan_never_deleted()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER plan_no_truncate ON plan")
    op.execute("DROP TRIGGER plan_never_deleted ON plan")
    op.execute("DROP FUNCTION plan_never_deleted()")
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_parameters_per_kind")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_check"
        " CHECK (kind <> 'prepaid' OR period_months IS NOT NULL),"
        " ADD CONSTRAINT plan_check1 CHECK (kind <> 'credits' OR credits IS NOT NULL)"
    )
    op.execute("ALTER TABLE plan DROP COLUMN anchor")
