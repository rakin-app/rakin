"""A member reads their own history payments, and their dependents' (#371).

`history_payment` (0055) was read only with `money_read` (0067). "Mis datos" shows a
member everything the gym holds on them, the payments recorded from before the gym used
Rakin included, so `rakin_app` gains `history_payment_own`: the rows of the person
acting and of their dependents, as `ledger_entry_own` (0010, 0037) and
`extra_line_own` (0037) read them. Reading only: writing stays `money_write`'s.

Revision ID: 0098
Revises: 0097
Create Date: 2026-11-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# 0037's `me_and_mine('person_id')`: the person acting or one of their dependents.
OWN = f"""(gym_id = {CURRENT_GYM} AND (person_id = {CURRENT_PERSON}
    OR person_id IN (SELECT g.dependent_person_id FROM guardian_link g
                     WHERE g.gym_id = {CURRENT_GYM}
                       AND g.guardian_person_id = {CURRENT_PERSON})))"""


def upgrade() -> None:
    op.execute(
        f"CREATE POLICY history_payment_own ON history_payment FOR SELECT TO {APP_ROLE} USING {OWN}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY history_payment_own ON history_payment")
