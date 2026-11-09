"""`grade_event`: the promotion log, one row per rank awarded.

A promotion names a rank and, when the rank has them, a sub-rank, by the keys of the
gym's grading scheme (`gym.settings["grading"]`, #112); the labels are read from the
scheme when shown. It hangs off a membership, as the ledger does, and a person's
current rank is their latest award over every membership they hold in the gym, so it
outlives a plan change or a new membership. `awarded_on` is the gym-local day the rank
was given, which may be before the day it was recorded (`created_at`); `awarded_by` is
who recorded it.

Awarding a rank that becomes the person's current one also writes a `promoted` row to
`plan_event` (0013), in the same transaction, for the plan-event emails (#54).

Isolated by `gym_id` like every tenant table. A promotion is history: `rakin_app` may
read and add rows, never change or delete them. A mistake is corrected by awarding the
right rank, which becomes the current one.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE grade_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            membership_id uuid NOT NULL,
            rank_key text NOT NULL CHECK (btrim(rank_key) <> ''),
            sub_rank text CHECK (btrim(sub_rank) <> ''),
            awarded_on date NOT NULL,
            awarded_by uuid REFERENCES person (id),
            note text CHECK (char_length(note) <= 500),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX grade_event_membership_idx"
        " ON grade_event (membership_id, awarded_on DESC, created_at DESC)"
    )

    op.execute(f"GRANT SELECT, INSERT ON grade_event TO {APP_ROLE}")
    op.execute("ALTER TABLE grade_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE grade_event FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY grade_event_isolation ON grade_event"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE grade_event")
