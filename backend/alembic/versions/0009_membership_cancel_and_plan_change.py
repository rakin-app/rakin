"""A cancelled membership carries its reason and is final; a plan change waits for its day.

`cancel_reason` and `cancelled_at` are set exactly when `status = 'cancelled'`. Rows
cancelled before this migration get the reason `sin motivo registrado` and the time
of the migration, since neither was ever recorded.

Cancelled is terminal (docs/technical.md#core-state-machines): a trigger refuses any
`UPDATE` of a cancelled row, for every role, the owner and superusers included, as 0002
does for the ledger. Violations raise `restrict_violation` (SQLSTATE 23001).

A plan change takes effect next period (proration is v2): `next_plan_id` is the plan
and `next_plan_from` the first day it applies, the start of the first period not yet
billed. Billing (#31) prices a period starting on or after that day at `next_plan_id`,
and moves it into `plan_id` then, recomputing `anchor_day` as
`app.domain.membership.anchor_day(new_terms, next_plan_from)`: the 1st or that day on a
monthly plan, null on a prepaid one. Both are set or both null, and a cancelled membership
has none pending.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNRECORDED = "sin motivo registrado"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE membership"
        " ADD COLUMN cancel_reason text CHECK (length(cancel_reason) BETWEEN 1 AND 500),"
        " ADD COLUMN cancelled_at timestamptz,"
        " ADD COLUMN next_plan_id uuid,"
        " ADD COLUMN next_plan_from date,"
        " ADD CONSTRAINT membership_next_plan_fkey"
        " FOREIGN KEY (gym_id, next_plan_id) REFERENCES plan (gym_id, id)"
    )

    # The owner is held to FORCEd RLS; lifted for the backfill only, inside the
    # migration's transaction.
    op.execute("ALTER TABLE membership NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"UPDATE membership SET cancel_reason = '{UNRECORDED}', cancelled_at = now()"
        " WHERE status = 'cancelled'"
    )
    op.execute("ALTER TABLE membership FORCE ROW LEVEL SECURITY")

    op.execute(
        "ALTER TABLE membership"
        " ADD CONSTRAINT membership_cancelled_with_reason CHECK ("
        "(status = 'cancelled') = (cancel_reason IS NOT NULL)"
        " AND (status = 'cancelled') = (cancelled_at IS NOT NULL)),"
        " ADD CONSTRAINT membership_next_plan_dated CHECK ("
        "(next_plan_id IS NULL) = (next_plan_from IS NULL)"
        " AND (status <> 'cancelled' OR next_plan_id IS NULL))"
    )

    op.execute("""
        CREATE FUNCTION membership_cancelled_is_final() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'a cancelled membership cannot change'
                USING ERRCODE = 'restrict_violation';
        END
        $$
    """)
    op.execute(
        "CREATE TRIGGER membership_cancelled_is_final BEFORE UPDATE ON membership"
        " FOR EACH ROW WHEN (OLD.status = 'cancelled')"
        " EXECUTE FUNCTION membership_cancelled_is_final()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER membership_cancelled_is_final ON membership")
    op.execute("DROP FUNCTION membership_cancelled_is_final()")
    op.execute(
        "ALTER TABLE membership"
        " DROP CONSTRAINT membership_next_plan_dated,"
        " DROP CONSTRAINT membership_cancelled_with_reason,"
        " DROP CONSTRAINT membership_next_plan_fkey,"
        " DROP COLUMN next_plan_from,"
        " DROP COLUMN next_plan_id,"
        " DROP COLUMN cancelled_at,"
        " DROP COLUMN cancel_reason"
    )
