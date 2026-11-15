"""Why someone left: `gym_person.left_reason` (#294).

The second of the historical-data tickets (docs/design/historical-data.md, sections 1, 4
and 7). Dar de baja asks "Motivo", and "Agregar exalumno" adds someone who already left
with theirs: free text, at most 200 characters, null when not said. It may be health
data ("lesión"), so the API shows it to the owner and admins only, never to a coach.

Writing it is recorded as `history_set` (0051), whose rows `forget_gym_person` already
deletes with the person and counts in `person_deleted`.

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-15

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE gym_person ADD COLUMN left_reason text"
        " CONSTRAINT gym_person_left_reason CHECK (char_length(left_reason) <= 200)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE gym_person DROP COLUMN left_reason")
