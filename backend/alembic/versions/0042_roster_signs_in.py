"""Anyone on a gym's roster signs in to it, with a plan or without (#246).

Until now a person was in a gym, for sign-in, only with a membership, a staff row or
a guardian link there (0005, 0010). A student added with no plan had none of them, so
asking for a link at `/ingresar` sent nothing, and said nothing, as it must not.

The roster's own test is now one more way in: this gym has a record of them
(`gym_person`) and they have not left it (`left_on`, 0032). It is added to the three
others rather than put in their place, so nobody who signs in today stops: a member
dado de baja still has their memberships and still signs in, to see and pay what they
owe. Someone the gym forgot (`forget_gym_person`, 0032) has no record and nothing
else here, so they get no link; nor does someone who left with no plan, staff role or
dependent.

The rule is the same in all three lookups that hold it: `auth_people_by_email` (who
gets a link), `auth_gyms_of` (which gyms it reaches) and `auth_live_session` (whether a
session in a gym is still good). Same signatures, so `CREATE OR REPLACE` keeps their
owner, `rakin_auth`, and their grants; `rakin_auth` already reads `gym_person`.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-12

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"


def _belongs(person: str, gym: str, *, roster: bool) -> str:
    """ "`person` is in `gym`": 0010's membership, staff row or guardian link, and with
    `roster` a record there they have not left."""
    tests = [
        f"EXISTS (SELECT FROM public.membership m WHERE m.person_id = {person}"
        f" AND m.gym_id = {gym})",
        f"EXISTS (SELECT FROM public.staff st WHERE st.person_id = {person} AND st.gym_id = {gym})",
        f"EXISTS (SELECT FROM public.guardian_link gl WHERE gl.guardian_person_id = {person}"
        f" AND gl.gym_id = {gym})",
    ]
    if roster:
        tests.append(
            f"EXISTS (SELECT FROM public.gym_person r WHERE r.person_id = {person}"
            f" AND r.gym_id = {gym} AND r.left_on IS NULL)"
        )
    return "(" + " OR ".join(tests) + ")"


def _holds(person: str, gym: str, address: str) -> str:
    """0029's: `gym`'s own record of `person` holds `address`, case and outer spaces
    ignored."""
    return (
        f"EXISTS (SELECT FROM public.gym_person gp WHERE gp.person_id = {person}"
        f" AND gp.gym_id = {gym} AND lower(gp.email) = lower(btrim({address})))"
    )


def _functions(*, roster: bool) -> list[str]:
    """The three lookups as 0010 (`auth_people_by_email`) and 0029 (the other two) left
    them, with `roster` widened to the roster."""
    return [
        f"""
CREATE OR REPLACE FUNCTION auth_people_by_email(address text)
RETURNS TABLE (person_id uuid, name text, email text)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT DISTINCT ON (g.person_id) g.person_id, g.name, g.email
    FROM public.gym_person g
    WHERE lower(g.email) = lower(btrim(address))
      AND {_belongs("g.person_id", "g.gym_id", roster=roster)}
    ORDER BY g.person_id, g.created_at
    LIMIT 10
$$
""",
        f"""
CREATE OR REPLACE FUNCTION auth_gyms_of(person uuid, address text)
RETURNS SETOF uuid
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT g.gym_id FROM public.gym_person g
    WHERE g.person_id = person AND lower(g.email) = lower(btrim(address))
      AND {_belongs("person", "g.gym_id", roster=roster)}
$$
""",
        f"""
CREATE OR REPLACE FUNCTION auth_live_session(hash bytea, at timestamptz)
RETURNS TABLE (person_id uuid, email text, gym_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT s.person_id, s.email, s.gym_id, s.expires_at
    FROM public.auth_session s
    WHERE s.token_hash = hash AND s.ended_at IS NULL AND s.expires_at > at
      AND s.email IS NOT NULL
      AND (s.gym_id IS NULL
           OR ({_belongs("s.person_id", "s.gym_id", roster=roster)}
               AND {_holds("s.person_id", "s.gym_id", "s.email")}))
$$
""",
    ]


def upgrade() -> None:
    for statement in _functions(roster=True):
        op.execute(statement)


def downgrade() -> None:
    for statement in _functions(roster=False):
        op.execute(statement)
