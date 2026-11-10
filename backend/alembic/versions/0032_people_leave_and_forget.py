"""A person leaves a gym (dado de baja), and a gym forgets one added by mistake.

`gym_person.left_on` is the day someone left this gym, null while they are here. The
API sets it as it ends every membership they hold (#157), so billing, the roster and
the inactive list, which read memberships, already leave them out; the member list
leaves them out by it. Reactivating clears it. History stays: payments, attendance,
belts and time on the mat are all still there.

`forget_gym_person(person)` deletes this gym's records of someone, for a person added
by mistake or a data-deletion request. It refuses, writing nothing, and answers why,
as `forget_refusal(person)` does without deleting anything, for the screen to say so
before it is asked:

- `ledger`: they have ledger entries here, which accounting has to keep (0002);
- `staff`: they are on the gym's staff, or coached a session here;
- `guardian`: they answer for a dependent here, who would be left with nobody.

Otherwise it deletes their memberships and everything on them (attendance, belts,
freezes, plan events, billing periods), their family link, custom-field values,
unsubscribe, sign-in sessions here and last the gym's record itself, and answers null.
The global `person` row stays: other gyms may know them, and erasing it is #69's.
`message_log` stays too, append-only as it is.

It runs as the owner, which FORCEd RLS holds to the current gym as it holds everyone
(0004), so it reaches no other gym's rows, and `rakin_app` gets no `DELETE` on any of
those tables.

Revision ID: 0032
Revises: 0029
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

SIGNATURE = "forget_gym_person(uuid)"
REFUSAL = "forget_refusal(uuid)"

# Their memberships in this gym, inside the function.
THEIRS = "SELECT id FROM membership WHERE gym_id = gym AND person_id = $1"


def upgrade() -> None:
    op.execute("ALTER TABLE gym_person ADD COLUMN left_on date")

    op.execute(f"""
        CREATE FUNCTION {REFUSAL} RETURNS text
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            gym uuid := {CURRENT_GYM};
        BEGIN
            IF gym IS NULL THEN
                RAISE EXCEPTION 'app.gym_id is not set' USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NOT EXISTS (SELECT FROM gym_person WHERE gym_id = gym AND person_id = $1) THEN
                RETURN 'not_found';
            END IF;
            IF EXISTS (
                SELECT FROM ledger_entry e JOIN membership m ON m.id = e.membership_id
                WHERE m.gym_id = gym AND m.person_id = $1
            ) THEN
                RETURN 'ledger';
            END IF;
            IF EXISTS (SELECT FROM staff WHERE gym_id = gym AND person_id = $1)
               OR EXISTS (SELECT FROM session WHERE gym_id = gym AND coach_id = $1) THEN
                RETURN 'staff';
            END IF;
            IF EXISTS (
                SELECT FROM guardian_link WHERE gym_id = gym AND guardian_person_id = $1
            ) THEN
                RETURN 'guardian';
            END IF;
            RETURN NULL;
        END
        $$
    """)

    op.execute(f"""
        CREATE FUNCTION {SIGNATURE} RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            gym uuid := {CURRENT_GYM};
            refusal text := forget_refusal($1);
        BEGIN
            IF refusal IS NOT NULL THEN
                RETURN refusal;
            END IF;

            DELETE FROM attendance WHERE membership_id IN ({THEIRS});
            DELETE FROM grade_event WHERE membership_id IN ({THEIRS});
            DELETE FROM plan_event WHERE membership_id IN ({THEIRS});
            DELETE FROM membership_freeze WHERE membership_id IN ({THEIRS});
            DELETE FROM billing_period WHERE membership_id IN ({THEIRS});
            DELETE FROM membership WHERE id IN ({THEIRS});

            DELETE FROM guardian_link WHERE gym_id = gym AND dependent_person_id = $1;
            DELETE FROM person_field_value WHERE gym_id = gym AND person_id = $1;
            DELETE FROM mail_unsubscribe WHERE gym_id = gym AND person_id = $1;
            DELETE FROM auth_session WHERE gym_id = gym AND person_id = $1;
            DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;
            RETURN NULL;
        END
        $$
    """)
    for function in (REFUSAL, SIGNATURE):
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(f"DROP FUNCTION {REFUSAL}")
    op.execute("ALTER TABLE gym_person DROP COLUMN left_on")
