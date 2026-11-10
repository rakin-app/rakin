"""Attendance: who was at each class, and `v_inactive`.

An attendance is one membership present at one session (migration 0020), at most once:
`(session_id, membership_id)` is the key (docs/technical.md#domain-model). It records
who marked it and when, and `credits_consumed`, what it took from a credits pack or a
trial's free classes (`app.domain.attendance`), so unmarking it gives back exactly
that. The session and the membership are referenced with `gym_id` in the key, so a row
cannot join one gym's member to another gym's class even past RLS.

Unlike the ledger, attendance is not append-only: a coach taps a name to mark it and
taps it again to unmark it, so `rakin_app` may read, add and delete rows, never change
one.

`v_inactive` (waiting on this table since 0014) is one row per person with a trial or
Active membership: the gym-local day they last attended, and how many days ago that
was, null for someone who never has. "More than N days" is the reader's `WHERE`.

A coach must see that a member is overdue, the roster's orange dot, but never the
ledger that says so (0006). `overdue_memberships()` answers only that: the ids of the
current gym's memberships with a period in `v_overdue`. It is `SECURITY DEFINER`, so it
reads the ledger as this migration's owner, whose policy is the gym alone (0006), and
it filters on `app.gym_id` itself too, so it never answers for another gym, even run by
a role that skips RLS.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

V_INACTIVE = """
SELECT gp.gym_id, gp.person_id, a.last_attended_on,
       (now() AT TIME ZONE g.timezone)::date - a.last_attended_on AS days_absent
FROM gym_person gp
JOIN gym g ON g.id = gp.gym_id
LEFT JOIN LATERAL (
    SELECT max((s.starts_at AT TIME ZONE g.timezone)::date) AS last_attended_on
    FROM attendance at
    JOIN session s ON s.id = at.session_id
    JOIN membership am ON am.id = at.membership_id
    WHERE am.person_id = gp.person_id AND am.gym_id = gp.gym_id
) a ON true
WHERE EXISTS (
    SELECT FROM membership m
    WHERE m.gym_id = gp.gym_id AND m.person_id = gp.person_id
      AND m.status IN ('trial', 'active')
)
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE attendance (
            gym_id uuid NOT NULL REFERENCES gym (id),
            session_id uuid NOT NULL,
            membership_id uuid NOT NULL,
            marked_by uuid REFERENCES person (id),
            marked_at timestamptz NOT NULL DEFAULT now(),
            credits_consumed integer NOT NULL DEFAULT 0 CHECK (credits_consumed >= 0),
            PRIMARY KEY (session_id, membership_id),
            FOREIGN KEY (gym_id, session_id) REFERENCES session (gym_id, id),
            FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
        )
    """)
    op.execute("CREATE INDEX attendance_membership_idx ON attendance (membership_id)")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON attendance TO {APP_ROLE}")
    op.execute("ALTER TABLE attendance ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE attendance FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY attendance_isolation ON attendance"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )

    op.execute(f"CREATE VIEW v_inactive WITH (security_invoker = true) AS {V_INACTIVE}")
    op.execute(f"GRANT SELECT ON v_inactive TO {APP_ROLE}")

    op.execute(f"""
        CREATE FUNCTION overdue_memberships() RETURNS SETOF uuid
        LANGUAGE sql STABLE {DEFINER} AS $$
            SELECT DISTINCT o.membership_id FROM public.v_overdue o
            WHERE o.gym_id = {CURRENT_GYM}
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION overdue_memberships() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION overdue_memberships() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION overdue_memberships()")
    op.execute("DROP VIEW v_inactive")
    op.execute("DROP TABLE attendance")
