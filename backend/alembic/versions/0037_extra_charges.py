"""Cobros extra: one-off charges beside the membership's billing periods (#195).

Besides its monthly plans a gym charges one-off amounts: a rifa, a seminar, gear, or a
cost the team splits. Each is an `extra_charge`, with one `extra_line` per person it
charges: what they owe and by when. A line is to a cobro what a billing period is to a
membership, and its money goes through the same ledger: a proof claims a pending
payment on it, an admin validates it, records a payment, adjusts it or refunds one, all
as `ledger_entry` rows that name the line in `extra_line_id` instead of a membership's
period. So Validar comprobante, Cobrado (`v_monthly_income`) and the ledger book see
both kinds.

- An entry names a membership or a line, never both (`ledger_entry_owner`), and one on
  a line has no billing period and is never a `charge`: the line's `amount_due_clp` is
  what it owes, as a period's is. `membership_id` is nullable for it.
- A refund's `refund_of` is held to an entry on the same line, as 0021 holds it to one
  on the same membership, and `ledger_entry_refund_target` to a validated payment on
  the same line.
- A line's amount may change after it is written (an admin's override, a re-split) and
  the line may be cancelled (`cancelled_at`); neither is a ledger entry, since neither
  moves money. The ledger stays append-only (0002).
- Every entry on a line takes the cobro's lock, shared, and is refused on a cancelled
  line (`ledger_entry_line_open`). The API takes it exclusively before it cancels a
  line or divides the total again, so a student's claim, which may not lock either row
  itself, either lands first and is seen or comes after and is refused.
- `v_monthly_income` (0022) gains `extra_income_clp`: what of the month's income the
  lines brought in, net of their refunds, by the same expression.
- Nothing about a line touches a membership: the lapse job and `v_overdue` read billing
  periods only, and `v_balance` now leaves line entries out, since it is per membership.

A `charge_group` is a named, reusable list of people (`charge_group_member`) a cobro can
target: a snapshot the admin edits, not a live filter.

RLS, as for the ledger (0006, 0010): for `rakin_app`, cobros and their lines are an
owner's or admin's, and anyone may read their own lines and their dependents', and the
cobros those lines are of, for the student page. A coach reads none. Anyone in the gym
may read the groups, a coach their names for rosters; only an owner or admin writes
them. The owner role, which the seed, the jobs and
`forget_gym_person` run as, is scoped by the gym alone.

`forget_refusal` keeps anyone with a cobro line as it keeps anyone with ledger entries,
and `forget_gym_person` takes them out of every group.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# 0006's LEDGER_ACCESS: an owner or admin of the current gym.
LEDGER_ACCESS = (
    f"(gym_id = {CURRENT_GYM} AND EXISTS ("
    f"SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    " AND s.role IN ('owner', 'admin')))"
)


def me_and_mine(person: str) -> str:
    """`person` is the person acting or one of their dependents, as 0010 reads them."""
    return f"""({person} = {CURRENT_PERSON}
       OR {person} IN (SELECT g.dependent_person_id FROM guardian_link g
                       WHERE g.gym_id = {CURRENT_GYM}
                         AND g.guardian_person_id = {CURRENT_PERSON}))"""


OWN_LINE = f"(gym_id = {CURRENT_GYM} AND {me_and_mine('person_id')})"

# 0010's OWN_LEDGER: the person's own memberships and their dependents'.
OWN_MEMBERSHIP_LEDGER = f"""(gym_id = {CURRENT_GYM} AND membership_id IN (
    SELECT m.id FROM membership m
    WHERE m.gym_id = {CURRENT_GYM}
      AND (m.person_id = {CURRENT_PERSON}
           OR m.person_id IN (SELECT g.dependent_person_id FROM guardian_link g
                              WHERE g.gym_id = {CURRENT_GYM}
                                AND g.guardian_person_id = {CURRENT_PERSON}))
))"""


def own_lines(open_only: bool) -> str:
    """Entries on the person's own lines and their dependents'; to claim, open ones."""
    still_open = " AND l.cancelled_at IS NULL" if open_only else ""
    return f"""(gym_id = {CURRENT_GYM} AND extra_line_id IN (
    SELECT l.id FROM extra_line l
    WHERE l.gym_id = {CURRENT_GYM}{still_open} AND {me_and_mine("l.person_id")}
))"""


# 0012's claim, past the ownership test.
OWN_PROOF = (
    "starts_with(proof_object_key,"
    f" 'proofs/' || {CURRENT_GYM}::text || '/' || {CURRENT_PERSON}::text || '/')"
)
CLAIM_TERMS = f"""kind = 'payment' AND status = 'pending' AND method = 'transfer'
    AND claimed_by = {CURRENT_PERSON} AND claimed_at IS NOT NULL
    AND validated_by IS NULL AND validated_at IS NULL
    AND {OWN_PROOF}"""

OWN_BEFORE = OWN_MEMBERSHIP_LEDGER
OWN_AFTER = f"({OWN_MEMBERSHIP_LEDGER} OR {own_lines(open_only=False)})"
CLAIM_BEFORE = f"({OWN_MEMBERSHIP_LEDGER} AND {CLAIM_TERMS})"
CLAIM_AFTER = f"(({OWN_MEMBERSHIP_LEDGER} OR {own_lines(open_only=True)}) AND {CLAIM_TERMS})"

V_BALANCE = """
SELECT e.gym_id, e.membership_id,
       sum(CASE
               WHEN e.kind IN ('charge', 'refund') THEN e.amount_clp
               WHEN e.kind = 'payment' THEN -e.amount_clp
               WHEN e.kind = 'adjustment' AND e.billing_period_id IS NOT NULL
                   THEN -e.amount_clp
               ELSE 0
           END)::bigint AS balance_clp
FROM ledger_entry e
WHERE e.status = 'validated'{only_memberships}
GROUP BY e.gym_id, e.membership_id
"""


def refund_target(same: str) -> str:
    """0021's trigger function, holding a refund to a validated payment on `same`."""
    return f"""
    CREATE OR REPLACE FUNCTION ledger_entry_refund_target() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT FROM ledger_entry p
            WHERE p.id = NEW.refund_of AND p.kind = 'payment' AND p.status = 'validated'
              {same}
        ) THEN
            RAISE EXCEPTION 'refund %: refund_of % is not a validated payment on its period',
                NEW.id, NEW.refund_of
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END
    $$
"""


REFUND_TARGET_BEFORE = refund_target(
    "AND p.billing_period_id IS NOT DISTINCT FROM NEW.billing_period_id"
)
REFUND_TARGET_AFTER = refund_target(
    "AND p.billing_period_id IS NOT DISTINCT FROM NEW.billing_period_id"
    " AND p.extra_line_id IS NOT DISTINCT FROM NEW.extra_line_id"
)

# Every entry on a line waits for the cobro's lock, shared, and is refused once the line
# is cancelled. SECURITY DEFINER: a student's claim may not lock the cobro (FOR SHARE
# needs its UPDATE policy), so the owner role, held to the gym in `app.gym_id`, takes
# it. The line is read after the lock, by a statement of its own, so a cancel that
# held the lock is seen once it commits.
LINE_OPEN = f"""
    CREATE FUNCTION ledger_entry_line_open() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    BEGIN
        PERFORM FROM extra_charge x
        WHERE x.id = (SELECT l.extra_charge_id FROM extra_line l WHERE l.id = NEW.extra_line_id)
          AND x.gym_id = {CURRENT_GYM}
        FOR SHARE;
        IF EXISTS (
            SELECT FROM extra_line l
            WHERE l.id = NEW.extra_line_id AND l.cancelled_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'entry %: line % is cancelled', NEW.id, NEW.extra_line_id
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ledger_entry_line_open';
        END IF;
        RETURN NEW;
    END
    $$
"""

# 0022's `v_monthly_income`, and the same with what the cobro lines brought in.
INCOME_OPTIONS = "WITH (security_invoker = true)"
NET = "CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END"
INCOME_COLUMNS = f"""SELECT e.gym_id,
       date_trunc('month', e.validated_at AT TIME ZONE g.timezone)::date AS month,
       sum({NET})::bigint AS income_clp,
       count(*) FILTER (WHERE e.kind = 'payment') AS payments,
       coalesce(sum(e.amount_clp) FILTER (WHERE e.kind = 'refund'), 0)::bigint
           AS refunds_clp,
       count(*) FILTER (WHERE e.kind = 'refund') AS refunds"""
INCOME_FROM = """
FROM ledger_entry e
JOIN gym g ON g.id = e.gym_id
WHERE e.kind IN ('payment', 'refund') AND e.status = 'validated'
GROUP BY e.gym_id, month
"""
INCOME_BEFORE = INCOME_COLUMNS + INCOME_FROM
INCOME_AFTER = (
    INCOME_COLUMNS
    + f""",
       coalesce(sum({NET}) FILTER (WHERE e.extra_line_id IS NOT NULL), 0)::bigint
           AS extra_income_clp"""
    + INCOME_FROM
)
INCOME_COMMENT_BEFORE = (
    "Validated payments less validated refunds per gym and gym-local month, each by the"
    " month it was validated in. The gym's income only for an owner or admin: RLS gives"
    " anyone else the sum of the entries they may read."
)
INCOME_COMMENT_AFTER = (
    INCOME_COMMENT_BEFORE + " extra_income_clp is the part of it on cobro extra lines."
)


def income_comment(comment: str) -> str:
    quoted = comment.replace("'", "''")
    return f"COMMENT ON VIEW v_monthly_income IS '{quoted}'"


REFUSAL = "forget_refusal(uuid)"
SIGNATURE = "forget_gym_person(uuid)"
THEIRS = "SELECT id FROM membership WHERE gym_id = gym AND person_id = $1"


def forget_refusal(extra_lines: bool) -> str:
    lines = (
        "OR EXISTS (SELECT FROM extra_line WHERE gym_id = gym AND person_id = $1)"
        if extra_lines
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION {REFUSAL} RETURNS text
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
            ) {lines} THEN
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
    """


def forget_gym_person(groups: bool) -> str:
    leave_groups = (
        "DELETE FROM charge_group_member WHERE gym_id = gym AND person_id = $1;" if groups else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION {SIGNATURE} RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            gym uuid := {CURRENT_GYM};
            refusal text;
        BEGIN
            -- Locked before the check: a payment or a membership started meanwhile
            -- waits, rather than slipping in between the check and the deletes.
            PERFORM FROM gym_person WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
            PERFORM FROM membership WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
            refusal := forget_refusal($1);
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
            {leave_groups}
            DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;
            RETURN NULL;
        END
        $$
    """


def _admin_written(table: str, grants: str) -> None:
    """A tenant table anyone in the gym reads and only an owner or admin writes: the
    gym alone for the owner role, as `_money`."""
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE}"
        f" USING (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY {table}_by_role ON {table} TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS} WITH CHECK {LEDGER_ACCESS}"
    )


def _money(table: str, own: str) -> None:
    """A table of money: the gym alone for the owner role, an owner or admin for
    `rakin_app`, and `own` for anyone reading their own."""
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY {table}_by_role ON {table} TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS} WITH CHECK {LEDGER_ACCESS}"
    )
    op.execute(f"CREATE POLICY {table}_own ON {table} FOR SELECT TO {APP_ROLE} USING {own}")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE charge_group (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX charge_group_name ON charge_group (gym_id, lower(name))")
    _admin_written("charge_group", "SELECT, INSERT, UPDATE, DELETE")

    op.execute("""
        CREATE TABLE charge_group_member (
            gym_id uuid NOT NULL,
            group_id uuid NOT NULL,
            person_id uuid NOT NULL,
            PRIMARY KEY (group_id, person_id),
            FOREIGN KEY (gym_id, group_id) REFERENCES charge_group (gym_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    _admin_written("charge_group_member", "SELECT, INSERT, DELETE")

    op.execute("""
        CREATE TABLE extra_charge (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            title text NOT NULL CHECK (btrim(title) <> ''),
            description text,
            message text,
            category text NOT NULL CHECK (category IN
                ('rifa', 'seminario', 'equipamiento', 'gasto_compartido', 'otro')),
            due_date date NOT NULL,
            -- `fixed`: `amount_clp` from each person; `split`: `amount_clp` in all,
            -- divided among the lines.
            amount_mode text NOT NULL CHECK (amount_mode IN ('fixed', 'split')),
            amount_clp bigint NOT NULL CHECK (amount_clp > 0),
            -- Whom it was for, as the admin chose them; the lines are who it charges.
            target_kind text NOT NULL CHECK (target_kind IN
                ('active', 'program', 'group', 'people')),
            target_label text,
            created_by uuid REFERENCES person (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE extra_line (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL,
            extra_charge_id uuid NOT NULL,
            person_id uuid NOT NULL,
            amount_due_clp bigint NOT NULL CHECK (amount_due_clp >= 0),
            -- Set by hand, so a re-split leaves it as it is.
            overridden boolean NOT NULL DEFAULT false,
            cancelled_at timestamptz,
            cancelled_by uuid REFERENCES person (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id),
            UNIQUE (extra_charge_id, person_id),
            FOREIGN KEY (gym_id, extra_charge_id) REFERENCES extra_charge (gym_id, id),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute("CREATE INDEX extra_line_person ON extra_line (gym_id, person_id)")
    _money("extra_line", OWN_LINE)
    _money(
        "extra_charge",
        f"(gym_id = {CURRENT_GYM} AND id IN (SELECT l.extra_charge_id FROM extra_line l"
        f" WHERE l.gym_id = {CURRENT_GYM} AND {me_and_mine('l.person_id')}))",
    )

    op.execute("ALTER TABLE ledger_entry ALTER COLUMN membership_id DROP NOT NULL")
    op.execute("ALTER TABLE ledger_entry ADD COLUMN extra_line_id uuid")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_extra_line_fkey"
        " FOREIGN KEY (gym_id, extra_line_id) REFERENCES extra_line (gym_id, id)"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_owner CHECK ("
        " (membership_id IS NULL) <> (extra_line_id IS NULL)"
        " AND (extra_line_id IS NULL OR (billing_period_id IS NULL AND kind <> 'charge')))"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_extra_line_entry"
        " UNIQUE (extra_line_id, id)"
    )
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_refund_of_line_fkey"
        " FOREIGN KEY (extra_line_id, refund_of) REFERENCES ledger_entry (extra_line_id, id)"
    )
    op.execute(
        "CREATE INDEX ledger_entry_extra_line ON ledger_entry (extra_line_id)"
        " WHERE extra_line_id IS NOT NULL"
    )
    op.execute(REFUND_TARGET_AFTER)
    op.execute(LINE_OPEN)
    op.execute(
        "CREATE TRIGGER ledger_entry_line_open BEFORE INSERT ON ledger_entry"
        " FOR EACH ROW WHEN (NEW.extra_line_id IS NOT NULL)"
        " EXECUTE FUNCTION ledger_entry_line_open()"
    )

    op.execute("DROP POLICY ledger_entry_own ON ledger_entry")
    op.execute(
        f"CREATE POLICY ledger_entry_own ON ledger_entry FOR SELECT TO {APP_ROLE} USING {OWN_AFTER}"
    )
    op.execute("DROP POLICY ledger_entry_claim ON ledger_entry")
    op.execute(
        f"CREATE POLICY ledger_entry_claim ON ledger_entry FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CLAIM_AFTER}"
    )

    op.execute(
        "CREATE OR REPLACE VIEW v_balance WITH (security_invoker = true) AS"
        + V_BALANCE.format(only_memberships=" AND e.membership_id IS NOT NULL")
    )
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {INCOME_OPTIONS} AS {INCOME_AFTER}")
    op.execute(income_comment(INCOME_COMMENT_AFTER))
    op.execute(forget_refusal(extra_lines=True))
    op.execute(forget_gym_person(groups=True))


def downgrade() -> None:
    op.execute(forget_gym_person(groups=False))
    op.execute(forget_refusal(extra_lines=False))
    # `CREATE OR REPLACE VIEW` cannot drop a column: 0022's view, recreated.
    op.execute("DROP VIEW v_monthly_income")
    op.execute(f"CREATE VIEW v_monthly_income {INCOME_OPTIONS} AS {INCOME_BEFORE}")
    op.execute(f"GRANT SELECT ON v_monthly_income TO {APP_ROLE}")
    op.execute(income_comment(INCOME_COMMENT_BEFORE))
    op.execute(
        "CREATE OR REPLACE VIEW v_balance WITH (security_invoker = true) AS"
        + V_BALANCE.format(only_memberships="")
    )
    op.execute("DROP POLICY ledger_entry_claim ON ledger_entry")
    op.execute(
        f"CREATE POLICY ledger_entry_claim ON ledger_entry FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CLAIM_BEFORE}"
    )
    op.execute("DROP POLICY ledger_entry_own ON ledger_entry")
    op.execute(
        f"CREATE POLICY ledger_entry_own ON ledger_entry FOR SELECT TO {APP_ROLE}"
        f" USING {OWN_BEFORE}"
    )
    op.execute("DROP TRIGGER ledger_entry_line_open ON ledger_entry")
    op.execute("DROP FUNCTION ledger_entry_line_open()")
    op.execute(REFUND_TARGET_BEFORE)
    op.execute("DROP INDEX ledger_entry_extra_line")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_refund_of_line_fkey")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_extra_line_entry")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_owner")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_extra_line_fkey")
    op.execute("ALTER TABLE ledger_entry DROP COLUMN extra_line_id")
    # Fails while an entry has no membership: the cobros' money has to go first, and
    # the ledger keeps every entry (0002), so this is for development only.
    op.execute("ALTER TABLE ledger_entry ALTER COLUMN membership_id SET NOT NULL")
    op.execute("DROP TABLE extra_charge, extra_line")
    op.execute("DROP TABLE charge_group_member")
    op.execute("DROP TABLE charge_group")
