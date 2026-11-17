"""Matrícula: an enrolment fee charged once, when a membership on the plan starts (#355).

Kids' academies and clubs charge a one-time fee when someone joins. A plan may carry
one, `plan.enrolment_fee_clp`, null for none. The kinds a member joins and pays on
again carry it: monthly, prepaid, fixed-period and credits; a drop-in and a trial never
do (`plan_enrolment_fee_kind`).

Starting a membership on such a plan writes a cobro extra of the new category
`matricula` with one line, for that person, due on the day the plan starts
(`app.api.enrolment`). `extra_charge.membership_id` names the membership it is for, at
most one cobro each, so the fee is never charged twice for one start; a reactivation or
a plan change starts no membership and charges none. Paid, reminded and cancelled as
any cobro extra.

A downgrade keeps the matrícula cobros, with their lines and money, as `otro`, and
drops the columns and the category.

Revision ID: 0072
Revises: 0071
Create Date: 2026-11-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = ("rifa", "seminario", "equipamiento", "gasto_compartido", "otro")
WITH_FEE = ("monthly", "prepaid", "fixed_period", "credits")


def _list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _categories(categories: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE extra_charge DROP CONSTRAINT extra_charge_category_check")
    op.execute(
        "ALTER TABLE extra_charge ADD CONSTRAINT extra_charge_category_check"
        f" CHECK (category IN ({_list(categories)}))"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE plan ADD COLUMN enrolment_fee_clp bigint"
        " CONSTRAINT plan_enrolment_fee_positive CHECK (enrolment_fee_clp > 0)"
    )
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_enrolment_fee_kind"
        f" CHECK (enrolment_fee_clp IS NULL OR kind IN ({_list(WITH_FEE)}))"
    )
    _categories((*CATEGORIES, "matricula"))
    op.execute("ALTER TABLE extra_charge ADD COLUMN membership_id uuid")
    op.execute(
        "ALTER TABLE extra_charge ADD CONSTRAINT extra_charge_membership_fkey"
        " FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)"
    )
    op.execute(
        "ALTER TABLE extra_charge ADD CONSTRAINT extra_charge_membership_once"
        " UNIQUE (membership_id)"
    )
    # A matrícula is for a membership, and only a matrícula is.
    op.execute(
        "ALTER TABLE extra_charge ADD CONSTRAINT extra_charge_matricula_membership"
        " CHECK ((category = 'matricula') = (membership_id IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE extra_charge DROP CONSTRAINT extra_charge_matricula_membership")
    # Kept, with the money on them, as cobros of the category every other one falls in.
    # Every gym's, so past RLS for this statement alone.
    op.execute("ALTER TABLE extra_charge NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE extra_charge SET category = 'otro' WHERE category = 'matricula'")
    op.execute("ALTER TABLE extra_charge FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extra_charge DROP COLUMN membership_id")
    _categories(CATEGORIES)
    op.execute("ALTER TABLE plan DROP CONSTRAINT plan_enrolment_fee_kind")
    op.execute("ALTER TABLE plan DROP COLUMN enrolment_fee_clp")
