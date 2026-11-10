"""Sessions: one row per class actually held.

A session is a class of one of the gym's class types (migration 0016), started at
`starts_at` and taught by `coach_id`, with the topic and notes the coach writes after
class (docs/technical.md#domain-model). There is no timetable behind it: a coach
starts a session when the class begins, so the day's sessions are the ones whose
`starts_at` falls on that day in the gym's timezone. Attendance (#44) will point at
it, by `(gym_id, id)`.

The class type and the coach are referenced with `gym_id` in the key, so a row cannot
name another gym's class type or person even past RLS. The coach is a `gym_person`
rather than a `staff` row: a staff row is deleted when someone stops teaching, and the
sessions they taught keep their coach. That the coach is staff when a session is
started or reassigned is the API's check.

A topic or notes are absent (null) rather than blank. A session is never deleted:
`rakin_app` may read, add and change them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            class_type_id uuid NOT NULL,
            starts_at timestamptz NOT NULL,
            coach_id uuid NOT NULL,
            topic text CHECK (btrim(topic) <> ''),
            notes text CHECK (btrim(notes) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id),
            FOREIGN KEY (gym_id, class_type_id) REFERENCES class_type (gym_id, id),
            FOREIGN KEY (gym_id, coach_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute("CREATE INDEX session_starts_at_idx ON session (gym_id, starts_at)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON session TO {APP_ROLE}")
    op.execute("ALTER TABLE session ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY session_isolation ON session"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE session")
