"""Class tags: a gym's recurring focuses, on its classes and its schedule (#243).

A `class_tag` is one of the gym's names for what classes keep coming back to ("Pasaje
de guardia", "Fuerza", "Fuerza de dedos"). Its name is unique in the gym, case
ignored. An archived one stays on the classes that have it, and still counts in their
hours, but is put on no class from then on: that is the API's check, and here
`schedule_sessions()` leaves it off the classes it makes.

`session_tag` is one tag on one class, and `schedule_slot_tag` one of a slot's default
tags. A class the schedule makes starts with its slot's tags, as it starts with its
topic (0035); from then on the class's tags are its own. Both reference the gym's rows
with `gym_id` in the key, as attendance does, so a row cannot put one gym's tag on
another gym's class even past RLS. Deleting a class or a slot takes its tags with it.

`rakin_app` may read, add and change tags but never delete one, since classes keep
them; it may add and remove a class's or a slot's tags.

`schedule_sessions()` is 0035's, and also gives each class it makes its slot's
tags that are not archived. Its signature and what it returns stay as they were.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

FUNCTION = """
CREATE OR REPLACE FUNCTION schedule_sessions(
    first_day date, last_day date, only_slot uuid DEFAULT NULL, refill boolean DEFAULT false
)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_temp AS $$
DECLARE
    made integer;
BEGIN
    WITH added AS (
        INSERT INTO session (
            gym_id, class_type_id, starts_at, duration_minutes, coach_id, topic,
            slot_id, slot_date
        )
        SELECT s.gym_id, s.class_type_id, (d.day + s.start_time) AT TIME ZONE g.timezone,
               s.duration_minutes, s.coach_id, s.topic, s.id, d.day
        FROM schedule_slot s
        JOIN gym g ON g.id = s.gym_id
        JOIN class_type c ON c.id = s.class_type_id AND c.active
        CROSS JOIN LATERAL (
            SELECT day::date AS day FROM generate_series(
                greatest(
                    first_day, s.valid_from,
                    CASE WHEN refill THEN NULL ELSE s.generated_until + 1 END
                ),
                least(last_day, s.valid_to),
                interval '1 day'
            ) AS day
        ) d
        WHERE (only_slot IS NULL OR s.id = only_slot)
          AND extract(isodow FROM d.day)::smallint = ANY (s.weekdays)
          AND NOT EXISTS (SELECT FROM closed_day x WHERE x.gym_id = s.gym_id AND x.day = d.day)
          AND (d.day + s.start_time) AT TIME ZONE g.timezone > now()
        ON CONFLICT (slot_id, slot_date) DO NOTHING
        RETURNING id, gym_id, slot_id
    ),
    tagged AS (
        INSERT INTO session_tag (gym_id, session_id, tag_id)
        SELECT a.gym_id, a.id, st.tag_id
        FROM added a
        JOIN schedule_slot_tag st ON st.slot_id = a.slot_id
        JOIN class_tag t ON t.id = st.tag_id AND NOT t.archived
    )
    SELECT count(*) INTO made FROM added;

    -- A refill of a range that starts past the day after `generated_until` (a reopened
    -- day, say) leaves a gap the nightly run has yet to make, so it moves nothing.
    UPDATE schedule_slot SET generated_until = greatest(generated_until, last_day)
    WHERE (only_slot IS NULL OR id = only_slot)
      AND (generated_until IS NULL OR generated_until < last_day)
      AND (NOT refill OR generated_until IS NULL OR first_day <= generated_until + 1);
    RETURN made;
END
$$
"""

# 0035's, as it was.
PREVIOUS_FUNCTION = """
CREATE OR REPLACE FUNCTION schedule_sessions(
    first_day date, last_day date, only_slot uuid DEFAULT NULL, refill boolean DEFAULT false
)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_temp AS $$
DECLARE
    made integer;
BEGIN
    INSERT INTO session (
        gym_id, class_type_id, starts_at, duration_minutes, coach_id, topic,
        slot_id, slot_date
    )
    SELECT s.gym_id, s.class_type_id, (d.day + s.start_time) AT TIME ZONE g.timezone,
           s.duration_minutes, s.coach_id, s.topic, s.id, d.day
    FROM schedule_slot s
    JOIN gym g ON g.id = s.gym_id
    JOIN class_type c ON c.id = s.class_type_id AND c.active
    CROSS JOIN LATERAL (
        SELECT day::date AS day FROM generate_series(
            greatest(
                first_day, s.valid_from,
                CASE WHEN refill THEN NULL ELSE s.generated_until + 1 END
            ),
            least(last_day, s.valid_to),
            interval '1 day'
        ) AS day
    ) d
    WHERE (only_slot IS NULL OR s.id = only_slot)
      AND extract(isodow FROM d.day)::smallint = ANY (s.weekdays)
      AND NOT EXISTS (SELECT FROM closed_day x WHERE x.gym_id = s.gym_id AND x.day = d.day)
      AND (d.day + s.start_time) AT TIME ZONE g.timezone > now()
    ON CONFLICT (slot_id, slot_date) DO NOTHING;
    GET DIAGNOSTICS made = ROW_COUNT;

    -- A refill of a range that starts past the day after `generated_until` (a reopened
    -- day, say) leaves a gap the nightly run has yet to make, so it moves nothing.
    UPDATE schedule_slot SET generated_until = greatest(generated_until, last_day)
    WHERE (only_slot IS NULL OR id = only_slot)
      AND (generated_until IS NULL OR generated_until < last_day)
      AND (NOT refill OR generated_until IS NULL OR first_day <= generated_until + 1);
    RETURN made;
END
$$
"""


def _isolate(table: str, grants: str) -> None:
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table}"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE class_tag (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            archived boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX class_tag_name_key ON class_tag (gym_id, lower(name))")
    _isolate("class_tag", "SELECT, INSERT, UPDATE")

    op.execute("""
        CREATE TABLE session_tag (
            gym_id uuid NOT NULL REFERENCES gym (id),
            session_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            PRIMARY KEY (session_id, tag_id),
            FOREIGN KEY (gym_id, session_id) REFERENCES session (gym_id, id) ON DELETE CASCADE,
            FOREIGN KEY (gym_id, tag_id) REFERENCES class_tag (gym_id, id)
        )
    """)
    op.execute("CREATE INDEX session_tag_tag_idx ON session_tag (tag_id)")
    _isolate("session_tag", "SELECT, INSERT, DELETE")

    op.execute("""
        CREATE TABLE schedule_slot_tag (
            gym_id uuid NOT NULL REFERENCES gym (id),
            slot_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            PRIMARY KEY (slot_id, tag_id),
            FOREIGN KEY (gym_id, slot_id) REFERENCES schedule_slot (gym_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (gym_id, tag_id) REFERENCES class_tag (gym_id, id)
        )
    """)
    _isolate("schedule_slot_tag", "SELECT, INSERT, DELETE")

    op.execute(FUNCTION)


def downgrade() -> None:
    op.execute(PREVIOUS_FUNCTION)
    op.execute("DROP TABLE schedule_slot_tag")
    op.execute("DROP TABLE session_tag")
    op.execute("DROP TABLE class_tag")
