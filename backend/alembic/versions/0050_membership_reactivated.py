"""`membership.reactivated_at`: when a lapsed plan was last brought back by hand (#284).

"Reactivar plan" (`POST /api/memberships/{id}/reactivate`) returns a lapsed membership
to Active, billing the periods since the lapse at once when it bills from where it left
off. Those periods fell due while it was lapsed, so the nightly `lapse` job would lapse
it again that night. A reactivated membership is not due before the day it was
reactivated, as one created with a start already past due is not due before the day it
was created (#271): it lapses after `max(due date, created on, reactivated on) + grace`,
giving the owner the whole grace from then to record the payment.

Null on a membership never reactivated. The reactivation itself is recorded in
`audit_event` (`membership_reactivated`, 0048), with who, why and from when it bills.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-15

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE membership ADD COLUMN reactivated_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE membership DROP COLUMN reactivated_at")
