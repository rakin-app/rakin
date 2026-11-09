"""Plan events: what happened to a membership, for comms to tell the member.

`plan_event` is an outbox. Whatever changes a membership's state writes one row in
the same transaction as the change, so the event exists exactly when the change
committed: the nightly `lapse` job writes `lapsed` (#32), and a freeze (#26) and a
promotion (#48) will write theirs. The plan-event emails (#54, docs/technical.md
"Communications") read it and send; how they mark a row sent is theirs to add.

`occurred_on` is the gym-local date of the change, the job's run date for a lapse.
`(membership_id, kind, occurred_on)` is unique, so a job run again on its date writes
no second event.

Isolated by `gym_id` like every tenant table. `rakin_app` may read and add events,
for the API's own state changes; an event is history, so it is never updated or
deleted.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE plan_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            membership_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('frozen', 'unfrozen', 'lapsed', 'promoted')),
            occurred_on date NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (membership_id, kind, occurred_on),
            FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
        )
    """)
    op.execute("CREATE INDEX plan_event_gym_created_idx ON plan_event (gym_id, created_at)")

    op.execute(f"GRANT SELECT, INSERT ON plan_event TO {APP_ROLE}")
    op.execute("ALTER TABLE plan_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plan_event FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY plan_event_isolation ON plan_event"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE plan_event")
