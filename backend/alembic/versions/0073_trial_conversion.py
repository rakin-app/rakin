"""Trial → conversion (#27): a paid plan names the trial it converted.

`membership.converted_from` is the trial a paid plan (monthly, prepaid, fixed period, a
credits pack) converted: the person's latest trial, not voided, with no paid plan of
theirs started since. Each trial converts once, so the column is unique among the paid
plans not voided: a plan voided as started by mistake gives its trial back.

The backfill links the plans already here by that rule, each paid plan the first one
after its trial, no other trial between them. A cancelled plan keeps every column
(0009's trigger), so the trigger is off while the backfill writes; it writes this
column alone.

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073"
down_revision: str | Sequence[str] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("membership", "plan")

PAID = "('monthly', 'prepaid', 'fixed_period', 'credits')"

BACKFILL = f"""
    WITH pairs AS (
        SELECT DISTINCT ON (t.id) t.id AS trial_id, p.id AS paid_id
        FROM membership t
        JOIN plan tp ON tp.id = t.plan_id AND tp.kind = 'trial'
        JOIN membership p ON p.gym_id = t.gym_id AND p.person_id = t.person_id
             AND p.created_at > t.created_at AND p.voided_at IS NULL
        JOIN plan pp ON pp.id = p.plan_id AND pp.kind IN {PAID}
        WHERE t.voided_at IS NULL
          AND NOT EXISTS (
              SELECT FROM membership t2 JOIN plan tp2 ON tp2.id = t2.plan_id
              WHERE tp2.kind = 'trial' AND t2.gym_id = t.gym_id
                AND t2.person_id = t.person_id AND t2.voided_at IS NULL
                AND t2.created_at > t.created_at AND t2.created_at < p.created_at
          )
        ORDER BY t.id, p.created_at, p.id
    )
    UPDATE membership m SET converted_from = pairs.trial_id
    FROM pairs WHERE m.id = pairs.paid_id
"""


def upgrade() -> None:
    op.execute("ALTER TABLE membership ADD COLUMN converted_from uuid REFERENCES membership (id)")
    op.execute(
        "CREATE UNIQUE INDEX membership_converted_from_key ON membership (converted_from)"
        " WHERE voided_at IS NULL"
    )
    # Every gym's memberships and plans, past the policies that hold even the owner to
    # one gym (0001).
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership DISABLE TRIGGER membership_cancelled_is_final")
    op.execute(BACKFILL)
    op.execute("ALTER TABLE membership ENABLE TRIGGER membership_cancelled_is_final")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP INDEX membership_converted_from_key")
    op.execute("ALTER TABLE membership DROP COLUMN converted_from")
