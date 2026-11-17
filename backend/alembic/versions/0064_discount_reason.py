"""A membership's discount with why, and each period billed with the discount it had (#25).

`membership.discount_pct` (0001) was billed but never set by anyone and said nothing
of why. Now an admin sets it on the ficha with a reason ("Hermanos", "Beca", or
anything else the gym gives one for), and the ledger shows it on each charge:

- `membership.discount_reason`, why it has the discount. There is none without a
  discount: clearing the discount clears it. A discount from before this migration has
  no reason; the API asks for one from now on.
- `billing_period.discount_pct` and `discount_reason`, the discount the period was
  billed at, as it was when it was written. A discount changed later bills the periods
  after it and leaves these as they were, so the ledger keeps saying what each charge
  was billed at. A trigger copies them from the membership as the period is written,
  so the billing job, a start, a drop-in visit (0061) and the seed all record it.

Existing periods take their membership's discount: nothing could change it before, so
it is the one they were billed at.

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("membership", "billing_period")

# Run as the period's writer, which may read its membership: RLS holds both to the gym.
STAMP = """
    CREATE FUNCTION billing_period_discount() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        SELECT m.discount_pct, m.discount_reason INTO NEW.discount_pct, NEW.discount_reason
        FROM membership m WHERE m.id = NEW.membership_id;
        RETURN NEW;
    END
    $$
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE membership ADD COLUMN discount_reason text,"
        " ADD CONSTRAINT membership_discount_reason"
        " CHECK (discount_reason IS NULL OR discount_pct > 0)"
    )
    op.execute(
        "ALTER TABLE billing_period"
        " ADD COLUMN discount_pct smallint NOT NULL DEFAULT 0"
        " CHECK (discount_pct BETWEEN 0 AND 100),"
        " ADD COLUMN discount_reason text"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE billing_period b SET discount_pct = m.discount_pct"
        " FROM membership m WHERE m.id = b.membership_id AND m.discount_pct > 0"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(STAMP)
    op.execute(
        "CREATE TRIGGER billing_period_discount BEFORE INSERT ON billing_period"
        " FOR EACH ROW EXECUTE FUNCTION billing_period_discount()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER billing_period_discount ON billing_period")
    op.execute("DROP FUNCTION billing_period_discount()")
    op.execute("ALTER TABLE billing_period DROP COLUMN discount_reason, DROP COLUMN discount_pct")
    op.execute(
        "ALTER TABLE membership DROP CONSTRAINT membership_discount_reason,"
        " DROP COLUMN discount_reason"
    )
