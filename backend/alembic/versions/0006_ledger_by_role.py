"""The API reads and writes the ledger only for an owner or admin of the current gym.

Roles are per gym (`staff.role`), and a coach must not see the ledger. `app.roles`
refuses them at the endpoint; this holds them to it at the database, so an endpoint
that forgot the check, or a later view or join over `ledger_entry`, still returns no
ledger rows to a coach.

The API sets `app.person_id` beside `app.gym_id` for every request (`app.tenancy`).
For `rakin_app`, `ledger_entry` now needs both: the row in the current gym, and that
person holding an owner or admin `staff` row there. A coach, a member, or no person
at all sees no entry and can write none.

The owner keeps the gym-only policy from 0001, still FORCEd: the seed, the nightly
jobs and one-off scripts act for no person, and set `app.gym_id` as before.

A view over `ledger_entry` (`v_balance`, `v_monthly_income`, #34) must be created
`WITH (security_invoker = true)`, or it reads as its owner and this policy does not
apply.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# The roles that see money; app.roles.LEDGER_ROLES.
LEDGER_ROLES = "'owner', 'admin'"

# `staff` is itself isolated to the current gym; the explicit `gym_id` test keeps this
# correct on its own and uses the primary key.
LEDGER_ACCESS = (
    f"(gym_id = {CURRENT_GYM} AND EXISTS ("
    f"SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    f" AND s.role IN ({LEDGER_ROLES})))"
)


def upgrade() -> None:
    op.execute("ALTER POLICY ledger_entry_isolation ON ledger_entry TO CURRENT_USER")
    op.execute(
        f"CREATE POLICY ledger_entry_by_role ON ledger_entry TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS} WITH CHECK {LEDGER_ACCESS}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY ledger_entry_by_role ON ledger_entry")
    op.execute("ALTER POLICY ledger_entry_isolation ON ledger_entry TO PUBLIC")
