"""A weekly schedule: recurring classes that generate their sessions, a class's
duration, and the days a gym is closed (#167).

A `schedule_slot` is one class of the gym's weekly timetable: a class type on one or
more weekdays (ISO, 1 is Monday), at a local start time, lasting `duration_minutes`,
taught by a default coach, with an optional default topic, from `valid_from` and, if
set, until `valid_to`. Its sessions are made ahead of time, one per slot and date,
by `schedule_sessions()`: the nightly `schedule` job, and the API when a slot is
saved or a closed day reopened.

A session made from a slot carries `slot_id` and `slot_date`, the date in the gym's
timezone it was made for, kept when that one class is moved. `UNIQUE (slot_id,
slot_date)` makes a second run on a date make nothing. A one-off session has
neither. Every session may carry `duration_minutes`: a slot's is copied onto its
sessions, and a one-off one sets its own or none, as every session before this did.

`generated_until` is the last date a slot's sessions were made through. The nightly
run starts after it, so a generated class someone deleted does not come back; the
API passes `refill` to make a range again, ON CONFLICT keeping what is there. A
refill moves `generated_until` only when its range starts no later than the day after
it, so reopening a day past a gap the nightly run has not reached does not skip it.

No class is made whose start has passed: a slot saved at 21:00 makes today's 19:00
class no more than a run late at night does.

A `closed_day` is a date, in the gym's timezone, with no classes: no session is made
on it. Both tables are per gym under RLS, as every tenant table is; that only an
owner or admin changes them is the API's check.

`schedule_sessions()` runs as its caller, so RLS holds it to the gym in `app.gym_id`
for the API and the job alike. A slot whose class type was deactivated makes no
sessions. Local wall times become instants with `AT TIME ZONE`: a start time Chile's
spring-forward skips takes the offset in force before the change, as
`app.domain.dates.start_of_local_day` does.

Revision ID: 0035
Revises: 0033
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

SIGNATURE = "schedule_sessions(date, date, uuid, boolean)"

FUNCTION = """
CREATE FUNCTION schedule_sessions(
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


def _tenant_table(name: str, grants: str) -> None:
    op.execute(f"GRANT {grants} ON {name} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {name}_isolation ON {name}"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE schedule_slot (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            class_type_id uuid NOT NULL,
            weekdays smallint[] NOT NULL
                CHECK (cardinality(weekdays) > 0 AND weekdays <@ '{1,2,3,4,5,6,7}'),
            start_time time NOT NULL,
            duration_minutes integer NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
            coach_id uuid NOT NULL,
            topic text CHECK (btrim(topic) <> ''),
            valid_from date NOT NULL,
            valid_to date CHECK (valid_to >= valid_from),
            generated_until date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id),
            FOREIGN KEY (gym_id, class_type_id) REFERENCES class_type (gym_id, id),
            FOREIGN KEY (gym_id, coach_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    _tenant_table("schedule_slot", "SELECT, INSERT, UPDATE, DELETE")

    op.execute("""
        CREATE TABLE closed_day (
            gym_id uuid NOT NULL REFERENCES gym (id),
            day date NOT NULL,
            label text CHECK (btrim(label) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gym_id, day)
        )
    """)
    _tenant_table("closed_day", "SELECT, INSERT, UPDATE, DELETE")

    op.execute("""
        ALTER TABLE session
            ADD COLUMN duration_minutes integer CHECK (duration_minutes BETWEEN 1 AND 1440),
            ADD COLUMN slot_id uuid,
            ADD COLUMN slot_date date,
            ADD CHECK ((slot_id IS NULL) = (slot_date IS NULL)),
            ADD UNIQUE (slot_id, slot_date),
            ADD FOREIGN KEY (gym_id, slot_id) REFERENCES schedule_slot (gym_id, id)
    """)

    op.execute(FUNCTION)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(
        "ALTER TABLE session DROP COLUMN slot_date, DROP COLUMN slot_id,"
        " DROP COLUMN duration_minutes"
    )
    op.execute("DROP TABLE closed_day")
    op.execute("DROP TABLE schedule_slot")
