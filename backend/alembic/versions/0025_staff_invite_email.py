"""Whether a staff invite may give someone its email: `staff_invite_email_ok`.

Sign-in finds a person by any gym's own record of their email (`auth_people_by_email`,
0005). So the email one gym writes on a person another gym also has is a way into that
person's account: an owner who invites someone else's phone with their own address
could sign in as them, and, once a person in several gyms picks one (#16), act in the
other gym. An invite (`POST /api/staff`) therefore writes its email only for someone no
other gym has, or when the email is one another gym already has for them.

The answer needs every gym's records, which RLS keeps from the API and FORCEd RLS from
this migration's owner, so the function belongs to `rakin_auth` (`app.db_bootstrap`),
like 0005's lookups. It answers yes or no and nothing else, and only for a person the
current gym has a record of. The full fix, for every path that writes an email, is #146.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

SIGNATURE = "staff_invite_email_ok(uuid, text)"

FUNCTION = f"""
CREATE FUNCTION staff_invite_email_ok(person uuid, address text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT EXISTS (SELECT FROM public.gym_person g
                   WHERE g.person_id = person AND g.gym_id = {CURRENT_GYM})
       AND (NOT EXISTS (SELECT FROM public.gym_person g
                        WHERE g.person_id = person AND g.gym_id <> {CURRENT_GYM})
            OR EXISTS (SELECT FROM public.gym_person g
                       WHERE g.person_id = person AND g.gym_id <> {CURRENT_GYM}
                         AND lower(g.email) = lower(btrim(address))))
$$
"""


def upgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
