"""Sessions can be cancelled, and an owner or admin can delete one.

A class that won't happen is cancelled, not deleted: `cancelled_at` is when, null for
one that stands. It stays on the day's list, shown as cancelled, and is out of
everything that counts classes (#163). Cancelling is refused once attendance has been
taken, and the API holds attendance and the timer to that too, so a cancelled class
has neither.

A class made by mistake is deleted, with its attendance (credits given back) and its
timer blocks: `rakin_app` may now delete a session, and only for an owner or admin of
its gym. The policy is RESTRICTIVE, so it narrows the gym-only `session_isolation`
(0020) for deletes and leaves reads and writes as they were, the way 0006 holds the
ledger to the same roles. A coach's request that reached the delete would remove no
row.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# app.roles.ADMIN_ROLES.
ADMIN_ROLES = "'owner', 'admin'"

ADMIN_ACCESS = (
    f"(gym_id = {CURRENT_GYM} AND EXISTS ("
    f"SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    f" AND s.role IN ({ADMIN_ROLES})))"
)


def upgrade() -> None:
    op.execute("ALTER TABLE session ADD COLUMN cancelled_at timestamptz")
    op.execute(f"GRANT DELETE ON session TO {APP_ROLE}")
    op.execute(
        f"CREATE POLICY session_delete_by_role ON session AS RESTRICTIVE FOR DELETE"
        f" TO {APP_ROLE} USING {ADMIN_ACCESS}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY session_delete_by_role ON session")
    op.execute(f"REVOKE DELETE ON session FROM {APP_ROLE}")
    op.execute("ALTER TABLE session DROP COLUMN cancelled_at")
