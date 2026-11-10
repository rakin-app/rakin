"""A person is their RUT, or an email in one gym, not their phone (#165).

Until now `person` was one row per phone (0004), and every way in went through
`join_gym_by_phone`. People don't want to hand over a phone just to exist in the app,
and phones change, are shared within a family and are recycled. So:

- `person.rut` is the global identity, unique when present, in the form
  `app.domain.rut` stores (`76123456-0`).
- Someone with no RUT (a foreigner, a coach who won't give one) is keyed by an email in
  the gym that adds them: a gym that adds that email again, with no RUT, finds the
  same person. An email never links two gyms' people; a second gym that adds the same
  address gets a person of its own. #146's per-(gym, email) sign-in is unchanged.
- A child with neither is a person of their own under their guardian, as before.
- The phone is a contact, per gym, on `gym_person.phone` beside the email: what the
  WhatsApp links go to. It is never used to find anyone, so `person.phone` goes.
- `gym_person.no_whatsapp` is the gym's "No tiene WhatsApp": a member it may save
  with no phone, whom no WhatsApp link goes to. `join_request.no_whatsapp` is the same
  box ticked on the join form. Whether a phone is required is the API's rule (a
  member's, or a minor's guardian's; staff need none), so a member left with neither
  shows "Falta teléfono" until one is filled in or the box ticked.

`join_gym(rut, email, name, phone, dob)` replaces `join_gym_by_phone` under the same
contract: it is the only way the API adds someone, it writes this gym's record with
what this gym entered, and it answers the same whether the RUT was new or known. Its
answer says only whether the person was already in this gym, which the gym can see
anyway. With a RUT it finds or creates the person that RUT is; with none, the person
this gym already has under the email, if any; otherwise someone new. `rakin_app` can
no longer insert into `person` at all, so nothing outside the function can learn a
RUT is taken from a unique violation, and it reads only `person.id`.

`claim_rut(person, rut)` makes a RUT given later (their ficha, a join request, a sheet)
who someone with none is, when nobody has it; when someone does, it changes nothing and
answers the same, since linking two people is a merge, left for later. The owner updates
`person` only inside it, through the `person_claim` policy it turns on.

The backfill keeps everyone working:

- Each gym's record takes the phone `person` held, so every phone a gym had stays
  where it showed.
- `person.rut` keeps what the first gym entered, and a person with none takes the RUT
  their gyms' records agree on, if they agree. A RUT not in the stored form is cleared
  from `person` only. Where two people hold one RUT (one human added under two phones,
  or a typo), the oldest keeps it and the others are left with none, keyed as people
  with no RUT are. Every gym's own record keeps the RUT it entered either way.
- `join_request.rut` becomes optional, and a request's guardian is found by their
  email, so the phone is optional for them too. An adult's request still needs an
  email, which is how they are told they are in and how they sign in.

The downgrade puts `person.phone` back from the gyms' records and refuses, changing
nothing, where it cannot do so without losing one: a person whose gyms hold different
phones for them, a phone held by two people, or a join request with no RUT or no
guardian phone. Someone added with no phone after this migration is left with none,
which 0004's schema allows but its API would not have added. It refuses, too, while
anyone is marked "No tiene WhatsApp", which 0004 has no place for. The RUTs this
migration cleared from `person` are not put back.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

E164 = "'^\\+[1-9][0-9]{1,14}$'"
# `app.domain.rut.normalize_rut`'s output.
STORED_RUT = "'^[1-9][0-9]{0,8}-[0-9K]$'"

JOIN_GYM = "join_gym(text, text, text, text, date)"
CLAIM_RUT = "claim_rut(uuid, text)"
JOIN_GYM_BY_PHONE = "join_gym_by_phone(text, text, text, text, date)"

# The tables the backfill reads across gyms.
BACKFILLED = ("person", "gym_person", "join_request")

REQUEST_CHECK = "join_request_check"


def _force(force: bool) -> None:
    """Lift or restore FORCEd RLS on the owner, for a backfill across gyms. The
    migration's transaction puts it back before anyone else can see the tables."""
    for table in BACKFILLED:
        op.execute(f"ALTER TABLE {table} {'' if force else 'NO '}FORCE ROW LEVEL SECURITY")


def _grant_join(signature: str) -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")


def upgrade() -> None:
    op.execute(f"ALTER TABLE gym_person ADD COLUMN phone text CHECK (phone ~ {E164})")
    op.execute("ALTER TABLE gym_person ADD COLUMN no_whatsapp boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE join_request ADD COLUMN no_whatsapp boolean NOT NULL DEFAULT false")

    _force(False)
    op.execute("""
        UPDATE gym_person gp SET phone = p.phone
        FROM person p WHERE p.id = gp.person_id AND p.phone IS NOT NULL
    """)
    op.execute(f"UPDATE person SET rut = NULL WHERE rut !~ {STORED_RUT}")
    op.execute(f"""
        UPDATE person p SET rut = agreed.rut
        FROM (
            SELECT person_id, min(rut) AS rut FROM gym_person
            WHERE rut ~ {STORED_RUT}
            GROUP BY person_id HAVING count(DISTINCT rut) = 1
        ) agreed
        WHERE p.id = agreed.person_id AND p.rut IS NULL
    """)
    op.execute("""
        UPDATE person p SET rut = NULL
        FROM (
            SELECT id, row_number() OVER (PARTITION BY rut ORDER BY created_at, id) AS nth
            FROM person WHERE rut IS NOT NULL
        ) ranked
        WHERE p.id = ranked.id AND ranked.nth > 1
    """)
    _force(True)

    op.execute("ALTER TABLE person ADD CONSTRAINT person_rut_key UNIQUE (rut)")
    op.execute(f"ALTER TABLE person ADD CONSTRAINT person_rut_check CHECK (rut ~ {STORED_RUT})")

    op.execute(f"DROP FUNCTION {JOIN_GYM_BY_PHONE}")
    # Dropping the column takes `rakin_app`'s grant on it along.
    op.execute("ALTER TABLE person DROP COLUMN phone")
    op.execute(f"REVOKE INSERT ON person FROM {APP_ROLE}")

    # Arguments arrive already normalised by the API (app.domain.rut, app.domain.phone).
    op.execute(f"""
        CREATE FUNCTION join_gym(
            p_rut text, p_email text, p_name text, p_phone text, p_dob date
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

            IF p_rut IS NOT NULL THEN
                -- Not a `SET` clause on the function: only a superuser may attach one for
                -- a custom setting. Off again below, before the caller sees the transaction.
                PERFORM set_config('app.person_lookup', 'on', true);
                -- A new person starts with what this gym entered; a known one is left as is.
                INSERT INTO person (rut, name, email, dob)
                VALUES (p_rut, p_name, p_email, p_dob)
                ON CONFLICT (rut) DO NOTHING;
                SELECT id INTO STRICT found_id FROM person WHERE rut = p_rut;
                PERFORM set_config('app.person_lookup', 'off', true);
            ELSIF p_email IS NOT NULL THEN
                -- This gym's own records only: FORCEd RLS holds the owner to the gym.
                SELECT gp.person_id INTO found_id FROM gym_person gp
                WHERE lower(gp.email) = lower(btrim(p_email))
                ORDER BY gp.created_at, gp.person_id
                LIMIT 1;
            END IF;

            IF found_id IS NULL THEN
                found_id := gen_random_uuid();
                INSERT INTO person (id, name, email, dob) VALUES (found_id, p_name, p_email, p_dob);
            END IF;

            INSERT INTO gym_person (gym_id, person_id, name, email, rut, phone, dob)
            VALUES (gym, found_id, p_name, p_email, p_rut, p_phone, p_dob)
            ON CONFLICT ON CONSTRAINT gym_person_pkey DO NOTHING;

            person_id := found_id;
            joined := FOUND;
            RETURN NEXT;
        END
        $$
    """)
    _grant_join(JOIN_GYM)

    # The owner updates a person only inside `claim_rut`, which turns this on around it.
    op.execute(
        "CREATE POLICY person_claim ON person FOR UPDATE TO CURRENT_USER"
        " USING (current_setting('app.person_claim', true) = 'on')"
    )
    # A person with no RUT, given one later (their ficha, a join request, a sheet): it
    # becomes who they are when nobody has it. When someone does, nothing changes here,
    # and the answer is the same: linking two people is a merge, not this (#165).
    op.execute(f"""
        CREATE FUNCTION claim_rut(p_person uuid, p_rut text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            gym uuid := {CURRENT_GYM};
        BEGIN
            IF gym IS NULL THEN
                RAISE EXCEPTION 'app.gym_id is not set' USING ERRCODE = 'insufficient_privilege';
            END IF;
            -- Only someone this gym has: FORCEd RLS holds the owner to the gym.
            IF p_rut IS NULL OR NOT EXISTS (
                SELECT FROM gym_person WHERE person_id = p_person
            ) THEN
                RETURN;
            END IF;
            PERFORM set_config('app.person_lookup', 'on', true);
            PERFORM set_config('app.person_claim', 'on', true);
            BEGIN
                UPDATE person SET rut = p_rut
                WHERE id = p_person AND rut IS NULL
                  AND NOT EXISTS (SELECT FROM person WHERE rut = p_rut);
            EXCEPTION WHEN unique_violation THEN
                -- Taken at the same moment by someone else: as if it had been already.
                NULL;
            END;
            PERFORM set_config('app.person_claim', 'off', true);
            PERFORM set_config('app.person_lookup', 'off', true);
        END
        $$
    """)
    _grant_join(CLAIM_RUT)

    # A request is found by its RUT, or its email when it has none; a guardian by
    # their email.
    op.execute("ALTER TABLE join_request ALTER COLUMN rut DROP NOT NULL")
    op.execute(f"ALTER TABLE join_request DROP CONSTRAINT {REQUEST_CHECK}")
    op.execute(f"""
        ALTER TABLE join_request ADD CONSTRAINT {REQUEST_CHECK} CHECK (
            (guardian_name IS NULL) = (guardian_email IS NULL)
            AND (guardian_name IS NOT NULL OR guardian_phone IS NULL)
            AND (guardian_name IS NOT NULL OR email IS NOT NULL)
        )
    """)
    # The queue looks up each request's email in the gym.
    op.execute("CREATE INDEX gym_person_email_idx ON gym_person (gym_id, lower(email))")


# 0004's, as the downgrade puts it back.
JOIN_GYM_BY_PHONE_BODY = f"""
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

        PERFORM set_config('app.person_lookup', 'on', true);

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
"""

# What would not survive the downgrade, each with the reason it gives.
LOSSY = (
    (
        "someone has different phones in different gyms",
        "SELECT FROM gym_person WHERE phone IS NOT NULL"
        " GROUP BY person_id HAVING count(DISTINCT phone) > 1",
    ),
    (
        "two people hold one phone",
        "SELECT FROM gym_person WHERE phone IS NOT NULL"
        " GROUP BY phone HAVING count(DISTINCT person_id) > 1",
    ),
    (
        "a join request has no RUT, or a guardian with no phone",
        "SELECT FROM join_request"
        " WHERE rut IS NULL OR (guardian_name IS NOT NULL AND guardian_phone IS NULL)"
        " OR (guardian_name IS NULL AND phone IS NULL)",
    ),
    (
        "someone is marked No tiene WhatsApp",
        "SELECT FROM gym_person WHERE no_whatsapp UNION ALL"
        " SELECT FROM join_request WHERE no_whatsapp",
    ),
)


def downgrade() -> None:
    _force(False)
    for reason, query in LOSSY:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS ({query}) THEN
                    RAISE EXCEPTION 'downgrade from 0036 refused: %', '{reason}'
                        USING HINT = 'it would lose data; nothing was changed';
                END IF;
            END $$
        """)

    op.execute("DROP INDEX gym_person_email_idx")
    op.execute(f"ALTER TABLE join_request DROP CONSTRAINT {REQUEST_CHECK}")
    op.execute(f"""
        ALTER TABLE join_request ADD CONSTRAINT {REQUEST_CHECK} CHECK (
            (guardian_name IS NULL) = (guardian_phone IS NULL)
            AND (guardian_name IS NULL) = (guardian_email IS NULL)
            AND (guardian_name IS NOT NULL OR (phone IS NOT NULL AND email IS NOT NULL))
        )
    """)
    op.execute("ALTER TABLE join_request ALTER COLUMN rut SET NOT NULL")

    op.execute(f"DROP FUNCTION {CLAIM_RUT}")
    op.execute("DROP POLICY person_claim ON person")
    op.execute(f"DROP FUNCTION {JOIN_GYM}")
    op.execute(f"ALTER TABLE person ADD COLUMN phone text UNIQUE CHECK (phone ~ {E164})")
    op.execute("""
        UPDATE person p SET phone = held.phone
        FROM (SELECT DISTINCT person_id, phone FROM gym_person WHERE phone IS NOT NULL) held
        WHERE p.id = held.person_id
    """)
    _force(True)
    op.execute("ALTER TABLE person DROP CONSTRAINT person_rut_check")
    op.execute("ALTER TABLE person DROP CONSTRAINT person_rut_key")
    op.execute("ALTER TABLE gym_person DROP COLUMN phone")
    op.execute("ALTER TABLE gym_person DROP COLUMN no_whatsapp")
    op.execute("ALTER TABLE join_request DROP COLUMN no_whatsapp")

    op.execute(f"GRANT INSERT ON person TO {APP_ROLE}")
    op.execute(f"GRANT SELECT (phone) ON person TO {APP_ROLE}")
    op.execute(JOIN_GYM_BY_PHONE_BODY)
    _grant_join(JOIN_GYM_BY_PHONE)
