"""One transfer for several dependents: a proof backs one entry per period it pays (#66).

A guardian with two kids in the gym pays both in one transfer, and uploads one proof.
The claim splits it into a pending payment for each period it covers, every one
pointing at the same `proof_object_key`, so 0012's "one proof backs one entry" becomes
one entry per period or cobro line: the same upload still cannot be claimed twice for
the same thing, by a double tap or a replayed request. An entry with neither is the
same thing as another with neither (`NULLS NOT DISTINCT`), so the key backs one.

That a key already claimed is not claimed again for something else is the API's to
hold (`app.api.proofs`), since a split claims every period of it at once and a later
claim of the same key is the replay this index cannot see.

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX ledger_entry_proof_object_key")
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_proof_object_key ON ledger_entry"
        " (proof_object_key, coalesce(billing_period_id, extra_line_id)) NULLS NOT DISTINCT"
        " WHERE proof_object_key IS NOT NULL"
    )


def downgrade() -> None:
    # The ledger is append-only (0002): a key shared by several entries cannot be taken
    # off all but one, so a database holding one cannot go back, and the index refuses.
    op.execute("DROP INDEX ledger_entry_proof_object_key")
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_proof_object_key ON ledger_entry (proof_object_key)"
        " WHERE proof_object_key IS NOT NULL"
    )
