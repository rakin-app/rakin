"""When someone was dado de baja: `gym_person.left_at` (#549).

"Deshacer baja" undoes a Dar de baja made by mistake in one step, the person back on the
list and their plan as it was, but only for a plan that same Dar de baja ended.
`left_on` cannot say which: it is the day the gym says they left, which may be long
before the day it was typed in. So `POST /api/people/{id}/leave` stamps `left_at` with
its transaction's `now()`, the very value it writes in `cancelled_at` on each plan it
ends; a return clears it.

Backfilled for someone who left before this, where it can be known for sure: their
record's `updated_at` is still the leave's `now()` when no later write touched it, and
it equals `cancelled_at` on a plan ended `dado de baja`. Anyone else keeps it null, and
"Reactivar" is their way back, as before.

Revision ID: 0095
Revises: 0094
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0095"
down_revision: str | Sequence[str] | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Gym by gym, as RLS holds the owner running this to one (`migration_gym_ids`, 0084).
BACKFILL = """
DO $$
DECLARE
    g uuid;
BEGIN
    FOR g IN SELECT migration_gym_ids() LOOP
        PERFORM set_config('app.gym_id', g::text, true);
        UPDATE gym_person gp SET left_at = gp.updated_at
        WHERE gp.left_on IS NOT NULL AND EXISTS (
            SELECT FROM membership m
            WHERE m.gym_id = gp.gym_id AND m.person_id = gp.person_id
              AND m.status = 'cancelled' AND m.cancel_reason = 'dado de baja'
              AND m.cancelled_at = gp.updated_at
        );
    END LOOP;
    PERFORM set_config('app.gym_id', '', true);
END
$$
"""


def upgrade() -> None:
    op.execute("ALTER TABLE gym_person ADD COLUMN left_at timestamptz")
    op.execute(BACKFILL)


def downgrade() -> None:
    op.execute("ALTER TABLE gym_person DROP COLUMN left_at")
