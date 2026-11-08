"""Person rows are visible only to gyms they belong to.

`person` stays global (one row per human, shared across gyms), but a read sees only
the people with a `membership` or `staff` row in the gym in `app.gym_id`. With
`app.gym_id` unset, no person is visible. RLS is FORCEd, as in 0001, so the owner is
held to it as well.

Inserts are open: a new person belongs to no gym until its membership or staff row
is written in the same transaction. Postgres applies the SELECT policy to an
`INSERT ... RETURNING`, so generate the id client-side rather than reading it back.
Finding an existing person by phone across gyms (global identity) needs a
`SECURITY DEFINER` function written for it; a plain query cannot see them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# `membership` and `staff` are themselves isolated to the current gym; the explicit
# `gym_id` test keeps this policy correct on its own and lets it use the indexes.
IN_CURRENT_GYM = f"""(
    EXISTS (SELECT FROM membership m WHERE m.person_id = person.id AND m.gym_id = {CURRENT_GYM})
    OR EXISTS (SELECT FROM staff s WHERE s.person_id = person.id AND s.gym_id = {CURRENT_GYM})
)"""


def upgrade() -> None:
    # `staff`'s primary key (gym_id, person_id) already serves its half of the policy.
    op.execute("CREATE INDEX membership_gym_person_idx ON membership (gym_id, person_id)")
    op.execute("ALTER TABLE person ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE person FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY person_read ON person FOR SELECT USING {IN_CURRENT_GYM}")
    op.execute(
        f"CREATE POLICY person_update ON person FOR UPDATE"
        f" USING {IN_CURRENT_GYM} WITH CHECK {IN_CURRENT_GYM}"
    )
    op.execute("CREATE POLICY person_insert ON person FOR INSERT WITH CHECK (true)")


def downgrade() -> None:
    for policy in ("person_insert", "person_update", "person_read"):
        op.execute(f"DROP POLICY {policy} ON person")
    op.execute("ALTER TABLE person NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE person DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX membership_gym_person_idx")
