"""Each gym's own record of a person, and joining a gym by phone without an oracle.

`person` is the global identity: one row per phone. What a gym knows about someone
(name, email, RUT, date of birth) lives in `gym_person`, one row per gym and person,
isolated by `gym_id` like every other tenant table. Two gyms that share a member each
keep their own record of them, and an edit in one never shows in the other.

That is what lets a gym add a member by a phone that is already known elsewhere
without learning so. `join_gym_by_phone` is the only way the API adds someone: it
finds or creates the person with that phone and writes this gym's record of them,
and it answers the same way whether the phone was new or not. It reports only whether
the person was already in this gym, which the gym can see anyway.

A gym holds a membership or a staff row only for someone it has a record of: both
reference `gym_person (gym_id, person_id)`, added after the backfill. So every person
a gym sees through `person_read` is one `GET /api/people/{id}` can answer for.

To make that hold at the database too, `rakin_app` can read only `person.id` and
`person.phone` (the phone the gym itself entered) and can no longer update `person`.
The other columns are what the first gym entered, or later the person's own record;
a gym reading them could learn another gym's data, and `created_at` alone would say
the phone was already known.

The function runs as the owner, which FORCEd RLS holds to the current gym like
everyone else. `person_lookup` lets the owner read every person while
`app.person_lookup` is `on`, which the function sets only around its own lookup. The
policy names the owner, so the API's role setting it achieves nothing; an owner
session setting it by hand is a deliberate act, as with `DISABLE TRIGGER` in 0002.

The downgrade is lossy. It drops `gym_person`, so every gym's own record goes, and
`person` keeps only what the first gym entered. Someone added through the API who has
no membership or staff row yet stops being visible in any gym. Downgrades are for
development, not production.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def in_current_gym(*tables: str) -> str:
    """The person policy's test: a row in one of `tables` for this person and gym."""
    return (
        "("
        + " OR ".join(
            f"EXISTS (SELECT FROM {t} x WHERE x.person_id = person.id AND x.gym_id = {CURRENT_GYM})"
            for t in tables
        )
        + ")"
    )


IN_CURRENT_GYM_0003 = in_current_gym("membership", "staff")
IN_CURRENT_GYM = in_current_gym("gym_person", "membership", "staff")

# The tables whose rows need the gym's record of their person.
GYM_PERSON_TABLES = ("membership", "staff")

# The columns `rakin_app` may read on `person`.
VISIBLE_PERSON_COLUMNS = "id, phone"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE gym_person (
            gym_id uuid NOT NULL REFERENCES gym (id),
            person_id uuid NOT NULL REFERENCES person (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            email text,
            rut text,
            dob date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gym_id, person_id)
        )
    """)

    # Everyone a gym already has: its members and staff, with what `person` holds.
    # The owner is held to FORCEd RLS, so it lifts the force for the copy; the
    # migration's transaction puts it back before anyone else can see the tables.
    for table in ("person", "membership", "staff"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        INSERT INTO gym_person (gym_id, person_id, name, email, rut, dob, created_at, updated_at)
        SELECT j.gym_id, p.id, p.name, p.email, p.rut, p.dob, j.joined, j.joined
        FROM (
            SELECT gym_id, person_id, min(created_at) AS joined
            FROM (
                SELECT gym_id, person_id, created_at FROM membership
                UNION ALL
                SELECT gym_id, person_id, created_at FROM staff
            ) links
            GROUP BY gym_id, person_id
        ) j
        JOIN person p ON p.id = j.person_id
    """)
    for table in ("person", "membership", "staff"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for table in GYM_PERSON_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_gym_person_fkey"
            " FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)"
        )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON gym_person TO {APP_ROLE}")
    op.execute("ALTER TABLE gym_person ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gym_person FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY gym_person_isolation ON gym_person"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )

    op.execute("DROP POLICY person_read ON person")
    op.execute("DROP POLICY person_update ON person")
    op.execute(f"CREATE POLICY person_read ON person FOR SELECT USING {IN_CURRENT_GYM}")
    op.execute(
        "CREATE POLICY person_lookup ON person FOR SELECT TO CURRENT_USER"
        " USING (current_setting('app.person_lookup', true) = 'on')"
    )
    op.execute(f"REVOKE SELECT, UPDATE ON person FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT ({VISIBLE_PERSON_COLUMNS}) ON person TO {APP_ROLE}")

    # Arguments arrive already normalised by the API (app.domain.phone, app.domain.rut).
    op.execute(f"""
        CREATE FUNCTION join_gym_by_phone(
            p_phone text, p_name text, p_email text, p_rut text, p_dob date
        ) RETURNS TABLE (person_id uuid, joined boolean)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            gym uuid := {CURRENT_GYM};
            found_id uuid;
        BEGIN
            IF gym IS NULL THEN
                RAISE EXCEPTION 'app.gym_id is not set' USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF p_phone IS NULL THEN
                RAISE EXCEPTION 'a phone is required' USING ERRCODE = 'not_null_violation';
            END IF;

            -- Not a `SET` clause on the function: only a superuser may attach one for a
            -- custom setting. Off again below, before the caller sees the transaction.
            PERFORM set_config('app.person_lookup', 'on', true);

            -- A new person starts with what this gym entered; a known one is left as is.
            INSERT INTO person (phone, name, email, rut, dob)
            VALUES (p_phone, p_name, p_email, p_rut, p_dob)
            ON CONFLICT (phone) DO NOTHING;
            SELECT id INTO STRICT found_id FROM person WHERE phone = p_phone;
            PERFORM set_config('app.person_lookup', 'off', true);

            INSERT INTO gym_person (gym_id, person_id, name, email, rut, dob)
            VALUES (gym, found_id, p_name, p_email, p_rut, p_dob)
            ON CONFLICT ON CONSTRAINT gym_person_pkey DO NOTHING;

            person_id := found_id;
            joined := FOUND;
            RETURN NEXT;
        END
        $$
    """)
    op.execute(
        "REVOKE EXECUTE ON FUNCTION join_gym_by_phone(text, text, text, text, date) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION join_gym_by_phone(text, text, text, text, date) TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION join_gym_by_phone(text, text, text, text, date)")
    op.execute(f"REVOKE SELECT ON person FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON person TO {APP_ROLE}")
    op.execute("DROP POLICY person_lookup ON person")
    op.execute("DROP POLICY person_read ON person")
    op.execute(f"CREATE POLICY person_read ON person FOR SELECT USING {IN_CURRENT_GYM_0003}")
    op.execute(
        f"CREATE POLICY person_update ON person FOR UPDATE"
        f" USING {IN_CURRENT_GYM_0003} WITH CHECK {IN_CURRENT_GYM_0003}"
    )
    for table in GYM_PERSON_TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_gym_person_fkey")
    op.execute("DROP TABLE gym_person")
