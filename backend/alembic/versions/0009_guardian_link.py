"""Guardians and their dependents: one payer, N dependents, per gym.

A guardian is a parent who pays for one or more kids, and kids have no phone
(docs/product.md#users). `guardian_link` records who answers for whom in one gym,
isolated by `gym_id` like every tenant table: a family a gym records is that gym's
knowledge, and another gym that shares the parent or the kid never sees it. Both
ends reference the gym's own record of the person (`gym_person`, 0004).

Rules held by the table:

- A dependent has one guardian in a gym: `(gym_id, dependent_person_id)` is the key.
  A guardian has any number of dependents.
- One level only. A guardian is nobody's dependent and a dependent is nobody's
  guardian, so contact always resolves in one step (`app.contacts`). A trigger
  refuses the link with `check_violation` (SQLSTATE 23514). It first takes a
  transaction-level advisory lock on the gym, so link writes in one gym run one at a
  time: without it, A→B and B→C inserted concurrently would each find no conflicting
  row (neither sees the other's uncommitted insert) and both commit, leaving B on both
  sides. The second waits for the first to commit and then sees its row, since each
  statement in READ COMMITTED takes a fresh snapshot after the lock is granted. Link
  writes are rare, so serialising them per gym costs nothing that matters.
- Nobody is their own guardian.

`rakin_app` may add and remove links: a link is not history, unlike the ledger.

Two more things change with it:

- A guardian who does not train is still in the gym. The sign-in lookups (0005)
  count a guardian link the way they count a membership or a staff row, so a parent
  who only pays for their kids gets a magic link, a session in that gym, and keeps
  it only while the link stands.
- A person may read the ledger entries of their own memberships and of their
  dependents' (`ledger_entry_own`), as the guardian page shows each kid's balance.
  That is read-only and adds to 0006, which still holds every other entry, and every
  write, to an owner or admin. A coach who trains reads their own payments and no one
  else's.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# The memberships whose entries the person acting may read: their own and their
# dependents'. `membership` and `guardian_link` are isolated to the current gym too;
# the explicit tests keep this correct on its own.
OWN_LEDGER = f"""(gym_id = {CURRENT_GYM} AND membership_id IN (
    SELECT m.id FROM membership m
    WHERE m.gym_id = {CURRENT_GYM}
      AND (m.person_id = {CURRENT_PERSON}
           OR m.person_id IN (SELECT g.dependent_person_id FROM guardian_link g
                              WHERE g.gym_id = {CURRENT_GYM}
                                AND g.guardian_person_id = {CURRENT_PERSON}))
))"""

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"


def _belongs(person: str, gym: str, *, guardians: bool) -> str:
    """0005's test for "`person` is in `gym`": a membership or a staff row, and with
    `guardians` a guardian link too."""
    tests = [
        f"EXISTS (SELECT FROM public.membership m WHERE m.person_id = {person}"
        f" AND m.gym_id = {gym})",
        f"EXISTS (SELECT FROM public.staff st WHERE st.person_id = {person} AND st.gym_id = {gym})",
    ]
    if guardians:
        tests.append(
            f"EXISTS (SELECT FROM public.guardian_link gl WHERE gl.guardian_person_id = {person}"
            f" AND gl.gym_id = {gym})"
        )
    return "(" + " OR ".join(tests) + ")"


def _auth_functions(*, guardians: bool) -> list[str]:
    """0005's lookups, which this migration widens to guardians and its downgrade
    narrows back. Same signatures, so `CREATE OR REPLACE` keeps owner and grants."""
    gyms_of = """
    SELECT gym_id FROM public.membership WHERE person_id = person
    UNION
    SELECT gym_id FROM public.staff WHERE person_id = person"""
    if guardians:
        gyms_of += """
    UNION
    SELECT gym_id FROM public.guardian_link WHERE guardian_person_id = person"""
    return [
        f"""
CREATE OR REPLACE FUNCTION auth_people_by_email(address text)
RETURNS TABLE (person_id uuid, name text, email text)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT DISTINCT ON (g.person_id) g.person_id, g.name, g.email
    FROM public.gym_person g
    WHERE lower(g.email) = lower(btrim(address))
      AND {_belongs("g.person_id", "g.gym_id", guardians=guardians)}
    ORDER BY g.person_id, g.created_at
    LIMIT 10
$$
""",
        f"""
CREATE OR REPLACE FUNCTION auth_gyms_of(person uuid)
RETURNS SETOF uuid
LANGUAGE sql STABLE {DEFINER} AS $${gyms_of}
$$
""",
        f"""
CREATE OR REPLACE FUNCTION auth_live_session(hash bytea, at timestamptz)
RETURNS TABLE (person_id uuid, gym_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT s.person_id, s.gym_id, s.expires_at
    FROM public.auth_session s
    WHERE s.token_hash = hash AND s.ended_at IS NULL AND s.expires_at > at
      AND (s.gym_id IS NULL OR {_belongs("s.person_id", "s.gym_id", guardians=guardians)})
$$
""",
    ]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE guardian_link (
            gym_id uuid NOT NULL REFERENCES gym (id),
            guardian_person_id uuid NOT NULL,
            dependent_person_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gym_id, dependent_person_id),
            CHECK (guardian_person_id <> dependent_person_id),
            FOREIGN KEY (gym_id, guardian_person_id) REFERENCES gym_person (gym_id, person_id),
            FOREIGN KEY (gym_id, dependent_person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute(
        "CREATE INDEX guardian_link_guardian_idx ON guardian_link (gym_id, guardian_person_id)"
    )

    op.execute("""
        CREATE FUNCTION guardian_link_one_level() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- Serialise link writes per gym, so the checks below see every committed
            -- link; see the docstring.
            PERFORM pg_advisory_xact_lock(hashtext('guardian_link:' || NEW.gym_id::text));
            IF EXISTS (SELECT FROM guardian_link
                       WHERE gym_id = NEW.gym_id AND dependent_person_id = NEW.guardian_person_id)
            THEN
                RAISE EXCEPTION 'the guardian is a dependent'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'guardian_link_one_level';
            END IF;
            IF EXISTS (SELECT FROM guardian_link
                       WHERE gym_id = NEW.gym_id AND guardian_person_id = NEW.dependent_person_id)
            THEN
                RAISE EXCEPTION 'the dependent is a guardian'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'guardian_link_one_level';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute(
        "CREATE TRIGGER guardian_link_one_level BEFORE INSERT OR UPDATE ON guardian_link"
        " FOR EACH ROW EXECUTE FUNCTION guardian_link_one_level()"
    )

    op.execute(f"GRANT SELECT, INSERT, DELETE ON guardian_link TO {APP_ROLE}")
    op.execute("ALTER TABLE guardian_link ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guardian_link FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY guardian_link_isolation ON guardian_link"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )

    op.execute(
        f"CREATE POLICY ledger_entry_own ON ledger_entry FOR SELECT TO {APP_ROLE}"
        f" USING {OWN_LEDGER}"
    )

    op.execute(f"GRANT SELECT ON guardian_link TO {AUTH_ROLE}")
    for statement in _auth_functions(guardians=True):
        op.execute(statement)


def downgrade() -> None:
    for statement in _auth_functions(guardians=False):
        op.execute(statement)
    op.execute(f"REVOKE SELECT ON guardian_link FROM {AUTH_ROLE}")
    op.execute("DROP POLICY ledger_entry_own ON ledger_entry")
    op.execute("DROP TABLE guardian_link")
    op.execute("DROP FUNCTION guardian_link_one_level()")
