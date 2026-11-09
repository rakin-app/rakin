"""A ledger entry's `method` is cash, transfer or other, or none.

`method` says how the money arrived: a student's proof is a transfer, an admin records
cash, a transfer or anything else (#37). A charge or an adjustment has none. 0001 left
the column free text; a typo there would split a gym's cash total in two.

0002's trigger forbids changing `method` on an existing entry, so the check holds for
every row written after it, and every row before it already holds it (the seed writes
only `cash` and `transfer`).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app.schemas.ledger.Method
METHODS = ("cash", "transfer", "other")


def upgrade() -> None:
    methods = ", ".join(f"'{m}'" for m in METHODS)
    op.execute(
        f"ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_method CHECK (method IN ({methods}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_method")
