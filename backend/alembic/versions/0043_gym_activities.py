"""Gym activities: what the gym teaches, and whether any of it uses grades (#245).

A `gym_activity` is one discipline the gym teaches ("BJJ", "Ballet", "Escalada"), from
the app's presets or named by the gym, unique in the gym with case ignored. Its
`uses_grades` says whether it grades students (belts, levels): the grading screens,
filters and ranks show only in a gym where at least one of its activities does. The
grading scheme itself stays one per gym, in `gym.settings["grading"]`, shared by the
gym's graded activities.

A class type may belong to an activity (`class_type.activity_id`), so a multisport
gym's "Fundamentos" can be BJJ's; none is fine. Removing an activity leaves its class
types with none. The key holds `gym_id`, as attendance's do, so a class type cannot
name another gym's activity even past RLS.

Existing gyms: one that has a grading scheme with ranks, or any recorded rank
(`grade_event`), gets one activity, "BJJ", with grades on, so it looks as it did.
Every other gym gets none, and no belts until it picks an activity that uses them.

`rakin_app` may read, add, change and delete activities.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-12

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# A scheme with a rank on either ladder; a key with empty ladders is no scheme.
HAS_SCHEME = """
    EXISTS (
        SELECT FROM jsonb_each(g.settings -> 'grading') AS l (key, ladder)
        WHERE l.key IN ('ranks', 'kids_ladder')
          -- A CASE, so a ladder that is no array is never measured.
          AND CASE WHEN jsonb_typeof(l.ladder) = 'array'
                   THEN jsonb_array_length(l.ladder) > 0 ELSE false END
    )
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE gym_activity (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            uses_grades boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX gym_activity_name_key ON gym_activity (gym_id, lower(name))")

    op.execute("ALTER TABLE class_type ADD COLUMN activity_id uuid")
    op.execute("""
        ALTER TABLE class_type ADD CONSTRAINT class_type_activity_fkey
            FOREIGN KEY (gym_id, activity_id) REFERENCES gym_activity (gym_id, id)
            ON DELETE SET NULL (activity_id)
    """)
    op.execute("CREATE INDEX class_type_activity_idx ON class_type (activity_id)")

    # The gyms that grade today keep their belts: before `gym_activity`'s RLS is on, with
    # the two tables read lifted out of it for the owner that runs this.
    op.execute("ALTER TABLE gym NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE grade_event NO FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        INSERT INTO gym_activity (gym_id, name, uses_grades)
        SELECT g.id, 'BJJ', true FROM gym g
        WHERE {HAS_SCHEME} OR EXISTS (SELECT FROM grade_event e WHERE e.gym_id = g.id)
    """)
    op.execute("ALTER TABLE grade_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gym FORCE ROW LEVEL SECURITY")

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON gym_activity TO {APP_ROLE}")
    op.execute("ALTER TABLE gym_activity ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gym_activity FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY gym_activity_isolation ON gym_activity"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE class_type DROP COLUMN activity_id")
    op.execute("DROP TABLE gym_activity")
