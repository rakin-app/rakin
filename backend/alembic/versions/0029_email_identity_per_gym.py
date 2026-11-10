"""An email signs in to a gym only where that gym's own record holds it (#146).

Identity is global by phone, so two gyms can know one person, and each gym writes its
own record of their email (`gym_person`, 0004). Until now sign-in resolved the person
by any gym's record and then let the session reach every gym they belong to
(`auth_gyms_of`, 0005). So an owner of gym B who typed their own address on a person
gym A also has could sign in as that person, and once a person in several gyms picks
one (#16), act in gym A. 0025 kept a staff invite from writing such an email; every
other path that writes one (adding or editing a person, the import) still could.

The rule is now per `(gym, email)`, not per person, and it is held where sign-in reads
rather than where gyms write, so no write path can get around it:

- A link records the address it was sent to (`auth_link.email`), and so does the
  session it turns into (`auth_session.email`).
- `auth_gyms_of(person, address)` is the gyms a sign-in with `address` reaches: those
  the person belongs to whose own record of them holds that address, case and outer
  spaces ignored. A session starts in the one gym when there is one; the picker (#16)
  offers these and no others. The one-argument version, every gym of the person, is
  dropped so nothing can scope by person alone.
- `auth_live_session` finds a session with a gym only while that gym's own record
  still holds the session's email, as well as while the person still belongs there.
  However a session comes to name a gym, it works there only on that gym's email; and
  a gym that changes someone's email ends the sessions signed in with the old one.

So an email gym B writes reaches gym B alone, which is already that gym's to act in,
and `staff_invite_email_ok` (0025) has nothing left to guard: it is dropped, and an
invite writes its email like any other path.

Links and sessions from before this migration have no email and could have come
from an email another gym wrote, so they end here: everyone signs in once more.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"


def _belongs(person: str, gym: str) -> str:
    """0010's test for "`person` is in `gym`": a membership, a staff row or a guardian
    link there."""
    return (
        f"(EXISTS (SELECT FROM public.membership m WHERE m.person_id = {person}"
        f" AND m.gym_id = {gym})"
        f" OR EXISTS (SELECT FROM public.staff st WHERE st.person_id = {person}"
        f" AND st.gym_id = {gym})"
        f" OR EXISTS (SELECT FROM public.guardian_link gl WHERE gl.guardian_person_id = {person}"
        f" AND gl.gym_id = {gym}))"
    )


def _holds(person: str, gym: str, address: str) -> str:
    """`gym`'s own record of `person` holds `address`, case and outer spaces ignored."""
    return (
        f"EXISTS (SELECT FROM public.gym_person gp WHERE gp.person_id = {person}"
        f" AND gp.gym_id = {gym} AND lower(gp.email) = lower(btrim({address})))"
    )


GYMS_OF = "auth_gyms_of(uuid, text)"
OLD_GYMS_OF = "auth_gyms_of(uuid)"
LIVE_SESSION = "auth_live_session(bytea, timestamptz)"
STAFF_INVITE_EMAIL_OK = "staff_invite_email_ok(uuid, text)"

NEW_GYMS_OF = f"""
CREATE FUNCTION auth_gyms_of(person uuid, address text)
RETURNS SETOF uuid
LANGUAGE sql STABLE {DEFINER} AS $$
    -- Each gym's own record of the person, where it holds the address and the person
    -- belongs to that gym. One row per gym: `(gym_id, person_id)` is its key.
    SELECT g.gym_id FROM public.gym_person g
    WHERE g.person_id = person AND lower(g.email) = lower(btrim(address))
      AND {_belongs("person", "g.gym_id")}
$$
"""


def _live_session(*, by_email: bool) -> str:
    """0010's lookup, which this migration has return the session's email and hold to
    it, and its downgrade puts back."""
    if not by_email:
        return f"""
CREATE FUNCTION auth_live_session(hash bytea, at timestamptz)
RETURNS TABLE (person_id uuid, gym_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT s.person_id, s.gym_id, s.expires_at
    FROM public.auth_session s
    WHERE s.token_hash = hash AND s.ended_at IS NULL AND s.expires_at > at
      AND (s.gym_id IS NULL OR {_belongs("s.person_id", "s.gym_id")})
$$
"""
    return f"""
CREATE FUNCTION auth_live_session(hash bytea, at timestamptz)
RETURNS TABLE (person_id uuid, email text, gym_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT s.person_id, s.email, s.gym_id, s.expires_at
    FROM public.auth_session s
    WHERE s.token_hash = hash AND s.ended_at IS NULL AND s.expires_at > at
      AND s.email IS NOT NULL
      AND (s.gym_id IS NULL
           OR ({_belongs("s.person_id", "s.gym_id")}
               AND {_holds("s.person_id", "s.gym_id", "s.email")}))
$$
"""


# 0010's, as the downgrade puts it back.
OLD_GYMS_OF_BODY = """
CREATE FUNCTION auth_gyms_of(person uuid)
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT gym_id FROM public.membership WHERE person_id = person
    UNION
    SELECT gym_id FROM public.staff WHERE person_id = person
    UNION
    SELECT gym_id FROM public.guardian_link WHERE guardian_person_id = person
$$
"""

# 0025's, as the downgrade puts it back.
STAFF_INVITE_EMAIL_OK_BODY = f"""
CREATE FUNCTION staff_invite_email_ok(person uuid, address text)
RETURNS boolean
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT EXISTS (SELECT FROM public.gym_person g
                   WHERE g.person_id = person AND g.gym_id = {CURRENT_GYM})
       AND (NOT EXISTS (SELECT FROM public.gym_person g
                        WHERE g.person_id = person AND g.gym_id <> {CURRENT_GYM})
            OR EXISTS (SELECT FROM public.gym_person g
                       WHERE g.person_id = person AND g.gym_id <> {CURRENT_GYM}
                         AND lower(g.email) = lower(btrim(address))))
$$
"""


def _hand_to_rakin_auth(signature: str) -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {AUTH_ROLE}")


def upgrade() -> None:
    op.execute("ALTER TABLE auth_link ADD COLUMN email text")
    op.execute("ALTER TABLE auth_session ADD COLUMN email text")

    # End what came before. `auth_link` has no RLS; `auth_session`'s is FORCEd on the
    # owner, lifted for this statement's transaction only.
    op.execute("UPDATE auth_link SET used_at = now() WHERE used_at IS NULL AND email IS NULL")
    op.execute("ALTER TABLE auth_session NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE auth_session SET ended_at = now() WHERE ended_at IS NULL AND email IS NULL")
    op.execute("ALTER TABLE auth_session FORCE ROW LEVEL SECURITY")

    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"DROP FUNCTION {OLD_GYMS_OF}")
    op.execute(NEW_GYMS_OF)
    _hand_to_rakin_auth(GYMS_OF)
    # It returns one more column, which `CREATE OR REPLACE` cannot do.
    op.execute(f"DROP FUNCTION {LIVE_SESSION}")
    op.execute(_live_session(by_email=True))
    _hand_to_rakin_auth(LIVE_SESSION)
    op.execute(f"DROP FUNCTION {STAFF_INVITE_EMAIL_OK}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(STAFF_INVITE_EMAIL_OK_BODY)
    _hand_to_rakin_auth(STAFF_INVITE_EMAIL_OK)
    op.execute(f"DROP FUNCTION {LIVE_SESSION}")
    op.execute(_live_session(by_email=False))
    _hand_to_rakin_auth(LIVE_SESSION)
    op.execute(f"DROP FUNCTION {GYMS_OF}")
    op.execute(OLD_GYMS_OF_BODY)
    _hand_to_rakin_auth(OLD_GYMS_OF)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    op.execute("ALTER TABLE auth_session DROP COLUMN email")
    op.execute("ALTER TABLE auth_link DROP COLUMN email")
