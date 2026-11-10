"""The class timer's data: block kinds, open mats, and the blocks a session ran.

A class is run as a sequence of blocks (#136): warm-up, technique, games, sparring
rounds. A block kind is one of the gym's names for a block (`block_kind`), ordered by
`position`, and `is_sparring` says its time is sparring, which drives a student's
sparring total. A kind's name is unique in its gym, case ignored. One in use by a
session's blocks is archived rather than deleted (the API's 409, `block_kind_in_use`),
so `rakin_app` may delete one only while nothing points at it.

Every gym starts with six kinds, Calentamiento to Otro (`DEFAULT_BLOCK_KINDS`): a gym
created later gets them from a trigger on `gym`, and the gyms already here get them
below. Their ids are derived from the gym's (`block_kind_default_id`), so the demo seed
can point its blocks at them without looking them up; `app.seed.build` derives the same.

A class type is a class or an open mat (`class_type.kind`), and `counts_as_class` says
whether attending one counts towards a student's classes, by default true for a class
and false for an open mat (the API's default; existing class types are classes).

A session block (`session_block`) is one block of a session's plan, at `position` from
0: its kind and planned seconds, and once run its `actual_seconds` (null until then, and
less than planned when the coach stopped early). A block of a sparring kind also has
its rounds: planned, completed, and the seconds of each round and of the rest between
them. Its seconds are the rounds' alone, rest not included, since that is the time
spent sparring. A student's time is the blocks of every session they attended
(docs/technical.md#domain-model).

The plan is replaced whole, so `rakin_app` may delete blocks as well as add and change
them. Both tables reference the gym's rows with `gym_id` in the key, as attendance does.

Revision ID: 0028
Revises: 0025
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# (key, name, is_sparring), in their order. The key only derives the id.
DEFAULT_BLOCK_KINDS = (
    ("warmup", "Calentamiento", False),
    ("technique", "Técnica", False),
    ("drilling", "Drilling", False),
    ("games", "Juegos", False),
    ("sparring", "Sparring", True),
    ("other", "Otro", False),
)

DEFAULTS = ", ".join(
    f"('{key}', '{name}', {str(sparring).lower()}, {position})"
    for position, (key, name, sparring) in enumerate(DEFAULT_BLOCK_KINDS)
)


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
        CREATE TABLE block_kind (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            is_sparring boolean NOT NULL DEFAULT false,
            position integer NOT NULL DEFAULT 0,
            archived boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX block_kind_name_key ON block_kind (gym_id, lower(name))")
    _isolate("block_kind", "SELECT, INSERT, UPDATE, DELETE")

    # md5 of the gym and the key, as a uuid: `app.seed.build.default_block_kind_id`.
    op.execute("""
        CREATE FUNCTION block_kind_default_id(gym uuid, key text) RETURNS uuid
        LANGUAGE sql IMMUTABLE AS $$ SELECT md5(gym::text || '/block_kind/' || key)::uuid $$
    """)
    # As whoever inserts the gym, with `app.gym_id` set to it for the inserts and put
    # back after, so RLS holds them to that gym.
    op.execute(f"""
        CREATE FUNCTION add_default_block_kinds(gym uuid) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            previous text := current_setting('app.gym_id', true);
        BEGIN
            PERFORM set_config('app.gym_id', gym::text, true);
            INSERT INTO block_kind (id, gym_id, name, is_sparring, position)
            SELECT block_kind_default_id(gym, d.key), gym, d.name, d.sparring, d.position
            FROM (VALUES {DEFAULTS}) AS d (key, name, sparring, position)
            ON CONFLICT DO NOTHING;
            PERFORM set_config('app.gym_id', coalesce(previous, ''), true);
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION gym_default_block_kinds() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM add_default_block_kinds(NEW.id);
            RETURN NULL;
        END
        $$
    """)
    op.execute(
        "CREATE TRIGGER gym_default_block_kinds AFTER INSERT ON gym"
        " FOR EACH ROW EXECUTE FUNCTION gym_default_block_kinds()"
    )
    # FORCEd RLS hides every gym from the owner running this; `jobs_gym_ids()` (0011)
    # lists them.
    op.execute("SELECT add_default_block_kinds(g) FROM jobs_gym_ids() AS g")

    op.execute(
        "ALTER TABLE class_type ADD COLUMN kind text NOT NULL DEFAULT 'class'"
        " CHECK (kind IN ('class', 'open_mat'))"
    )
    op.execute("ALTER TABLE class_type ADD COLUMN counts_as_class boolean NOT NULL DEFAULT true")

    op.execute("""
        CREATE TABLE session_block (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            session_id uuid NOT NULL,
            position integer NOT NULL CHECK (position >= 0),
            block_kind_id uuid NOT NULL,
            planned_seconds integer NOT NULL CHECK (planned_seconds > 0),
            actual_seconds integer CHECK (actual_seconds >= 0),
            rounds_planned integer CHECK (rounds_planned > 0),
            rounds_completed integer CHECK (rounds_completed >= 0),
            round_seconds integer CHECK (round_seconds > 0),
            rest_seconds integer CHECK (rest_seconds >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (session_id, position),
            FOREIGN KEY (gym_id, session_id) REFERENCES session (gym_id, id),
            FOREIGN KEY (gym_id, block_kind_id) REFERENCES block_kind (gym_id, id),
            -- A block has rounds whole or not at all, and completes no more than planned.
            CHECK (
                (rounds_planned IS NULL) = (round_seconds IS NULL)
                AND (rounds_planned IS NULL) = (rest_seconds IS NULL)
                AND (rounds_completed IS NULL
                     OR (rounds_planned IS NOT NULL AND rounds_completed <= rounds_planned))
            )
        )
    """)
    op.execute("CREATE INDEX session_block_kind_idx ON session_block (block_kind_id)")
    _isolate("session_block", "SELECT, INSERT, UPDATE, DELETE")


def downgrade() -> None:
    op.execute("DROP TABLE session_block")
    op.execute("ALTER TABLE class_type DROP COLUMN counts_as_class")
    op.execute("ALTER TABLE class_type DROP COLUMN kind")
    op.execute("DROP TRIGGER gym_default_block_kinds ON gym")
    op.execute("DROP FUNCTION gym_default_block_kinds()")
    op.execute("DROP FUNCTION add_default_block_kinds(uuid)")
    op.execute("DROP FUNCTION block_kind_default_id(uuid, text)")
    op.execute("DROP TABLE block_kind")
