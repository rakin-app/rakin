"""`membership_freeze`: a membership paused for a while, and why (#26).

One row per freeze, written with the membership's move to Frozen. `from_date` is its
first day and `to_date` the day it ends, when the nightly `freezes` job returns the
membership to Active; both are gym-local dates. The due date has moved by the days
in between by then: the freeze moves it as it starts (`app.domain.membership.freeze`).
`reason` is what the admin wrote, and `created_by` the staff member who wrote it.

A freeze is history, like the ledger beside which it is listed: `rakin_app` may read
and add freezes, never change or delete them. Isolated by `gym_id` like every tenant
table.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE membership_freeze (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            membership_id uuid NOT NULL,
            from_date date NOT NULL,
            to_date date NOT NULL,
            reason text NOT NULL CHECK (btrim(reason) <> ''),
            created_by uuid REFERENCES person (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (to_date > from_date),
            UNIQUE (membership_id, from_date),
            FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX membership_freeze_gym_dates_idx"
        " ON membership_freeze (gym_id, from_date, to_date)"
    )

    op.execute(f"GRANT SELECT, INSERT ON membership_freeze TO {APP_ROLE}")
    op.execute("ALTER TABLE membership_freeze ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership_freeze FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY membership_freeze_isolation ON membership_freeze"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE membership_freeze")
