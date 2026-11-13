"""Fixing a mistake on a member: void a charge or a plan, then delete them (#256).

The history stays, but it must not stand in the way of correcting things.

- A void (`ledger_entry.voids`) is a validated adjustment in the member's favour of
  what a billing period still owes, with the reason in `note`: the period's charge
  reads as voided and nothing is owed on it any more. It is a new entry, as every
  correction is (0002), and settles the period as any adjustment does
  (`app.domain.billing`), so `v_overdue`, `v_balance` and every query that settles a
  period need no change. One per period.
- A membership started by mistake is voided (`membership.voided_at`, `voided_by`,
  `void_reason`): it is cancelled as of its start and its unpaid periods are voided.
  A cancelled membership is final (0009) except for this: one cancelled before may
  still be voided, setting those three columns and nothing else.
- A cobro extra line is voided as it was already cancelled ("Anular", 0037), now with
  a reason (`extra_line.cancel_reason`). Lines cancelled before have none.
- `forget_refusal` no longer refuses someone for having ledger entries, but for what
  they still hold: `payment`, money the gym kept from them (validated payments less
  refunds); `pending`, a proof waiting for review; `owes`, a period or a line not
  cancelled that is not settled, due or not. Then `staff` and `guardian` as before.
- `forget_gym_person(person, reason)` deletes their ledger entries and cobro lines
  with the rest, since none of them holds money any more. The append-only trigger
  (0002) lets a `DELETE` through only for the person `app.forget_person` names, which
  the function sets for its own transaction; `TRUNCATE` and every other delete are
  refused as before. It leaves an `audit_event` row behind: who deleted, when, the
  reason they gave, and counts and sums, with nothing about the person.
- `audit_event` is the gym's log. An owner or admin reads it; only the owner role,
  which `forget_gym_person` runs as, writes it, and nothing changes or deletes a row.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-13

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"
FORGET_PERSON = "NULLIF(current_setting('app.forget_person', true), '')::uuid"

LEDGER_ACCESS = (
    f"(gym_id = {CURRENT_GYM} AND EXISTS ("
    f"SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    " AND s.role IN ('owner', 'admin')))"
)

HINT = "ledger entries are append-only; record a correction as a new entry"
SETTLEMENT_COLUMNS = ("status", "validated_by", "validated_at", "note")
VOID_COLUMNS = ("voided_at", "voided_by", "void_reason")

REFUSAL = "forget_refusal(uuid)"
OLD_SIGNATURE = "forget_gym_person(uuid)"
SIGNATURE = "forget_gym_person(uuid, text)"

THEIRS = "SELECT id FROM membership WHERE gym_id = gym AND person_id = $1"
THEIR_LINES = "SELECT id FROM extra_line WHERE gym_id = gym AND person_id = $1"
# Their ledger entries, on their memberships and their cobro lines.
THEIR_ENTRIES = (
    f"SELECT e.* FROM ledger_entry e WHERE e.membership_id IN ({THEIRS})"
    f" OR e.extra_line_id IN ({THEIR_LINES})"
)
# What a validated entry counts towards its period or line (`settled_amount`).
SETTLED = "CASE WHEN s.kind = 'refund' THEN -s.amount_clp ELSE s.amount_clp END"
SETTLING = "s.status = 'validated' AND s.kind IN ('payment', 'adjustment', 'refund')"


def append_only(forget: bool) -> str:
    """0002's trigger function; with `forget`, a `DELETE` of an entry of the person
    `app.forget_person` names goes through."""
    settlement = ", ".join(f"'{c}'" for c in SETTLEMENT_COLUMNS)
    forgotten = (
        f"""
            IF TG_OP = 'DELETE' AND {FORGET_PERSON} IS NOT NULL AND (
                EXISTS (SELECT FROM membership m
                        WHERE m.id = OLD.membership_id AND m.person_id = {FORGET_PERSON})
                OR EXISTS (SELECT FROM extra_line l
                           WHERE l.id = OLD.extra_line_id AND l.person_id = {FORGET_PERSON})
            ) THEN
                RETURN OLD;
            END IF;"""
        if forget
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION ledger_entry_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN{forgotten}
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'ledger_entry rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', HINT = '{HINT}';
            END IF;
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'ledger entry % is %, and only pending entries can change',
                    OLD.id, OLD.status
                    USING ERRCODE = 'restrict_violation', HINT = '{HINT}';
            END IF;
            IF to_jsonb(NEW) - ARRAY[{settlement}]
                    IS DISTINCT FROM to_jsonb(OLD) - ARRAY[{settlement}] THEN
                RAISE EXCEPTION 'ledger entry %: only {", ".join(SETTLEMENT_COLUMNS)} can change',
                    OLD.id
                    USING ERRCODE = 'restrict_violation', HINT = '{HINT}';
            END IF;
            RETURN NEW;
        END
        $$
    """


def cancelled_is_final(voidable: bool) -> str:
    """0009's trigger function; with `voidable`, a cancelled row not yet voided may be,
    changing its void columns and nothing else."""
    void = ", ".join(f"'{c}'" for c in VOID_COLUMNS)
    allowed = (
        f"""
            IF OLD.voided_at IS NULL AND NEW.voided_at IS NOT NULL
               AND to_jsonb(NEW) - ARRAY[{void}] IS NOT DISTINCT FROM to_jsonb(OLD) - ARRAY[{void}]
            THEN
                RETURN NEW;
            END IF;"""
        if voidable
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION membership_cancelled_is_final() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN{allowed}
            RAISE EXCEPTION 'a cancelled membership cannot change'
                USING ERRCODE = 'restrict_violation';
        END
        $$
    """


FORGET_REFUSAL = f"""
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
        -- Money the gym kept: validated payments less what was given back of them.
        IF (
            SELECT coalesce(sum(CASE WHEN e.kind = 'payment' THEN e.amount_clp
                                     ELSE -e.amount_clp END), 0)
            FROM ({THEIR_ENTRIES}) e
            WHERE e.status = 'validated' AND e.kind IN ('payment', 'refund')
        ) > 0 THEN
            RETURN 'payment';
        END IF;
        IF EXISTS (
            SELECT FROM ({THEIR_ENTRIES}) e WHERE e.kind = 'payment' AND e.status = 'pending'
        ) THEN
            RETURN 'pending';
        END IF;
        IF EXISTS (
            SELECT FROM billing_period bp
            WHERE bp.membership_id IN ({THEIRS}) AND bp.amount_due_clp > (
                SELECT coalesce(sum({SETTLED}), 0) FROM ledger_entry s
                WHERE s.billing_period_id = bp.id AND {SETTLING}
            )
        ) OR EXISTS (
            SELECT FROM extra_line l
            WHERE l.gym_id = gym AND l.person_id = $1 AND l.cancelled_at IS NULL
              AND l.amount_due_clp > (
                  SELECT coalesce(sum({SETTLED}), 0) FROM ledger_entry s
                  WHERE s.extra_line_id = l.id AND {SETTLING}
              )
        ) THEN
            RETURN 'owes';
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

FORGET = f"""
    CREATE FUNCTION {SIGNATURE} RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        gym uuid := {CURRENT_GYM};
        refusal text;
        detail jsonb;
    BEGIN
        IF $2 IS NULL OR length(btrim($2)) NOT BETWEEN 1 AND 500 THEN
            RAISE EXCEPTION 'a deletion needs a reason' USING ERRCODE = 'check_violation';
        END IF;
        -- Locked before the check: a payment or a membership started meanwhile
        -- waits, rather than slipping in between the check and the deletes.
        PERFORM FROM gym_person WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
        PERFORM FROM membership WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
        PERFORM FROM extra_line WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
        refusal := forget_refusal($1);
        IF refusal IS NOT NULL THEN
            RETURN refusal;
        END IF;

        -- What the log keeps: how much there was, and nothing about whose it was.
        SELECT jsonb_build_object(
            'memberships', (SELECT count(*) FROM membership WHERE gym_id = gym AND person_id = $1),
            'voided_memberships', (
                SELECT count(*) FROM membership
                WHERE gym_id = gym AND person_id = $1 AND voided_at IS NOT NULL
            ),
            'extra_lines', (SELECT count(*) FROM extra_line WHERE gym_id = gym AND person_id = $1),
            'ledger_entries', (SELECT count(*) FROM ({THEIR_ENTRIES}) e),
            'voided_clp', (
                SELECT coalesce(sum(e.amount_clp), 0) FROM ({THEIR_ENTRIES}) e WHERE e.voids
            ),
            'refunded_clp', (
                SELECT coalesce(sum(e.amount_clp), 0) FROM ({THEIR_ENTRIES}) e
                WHERE e.kind = 'refund'
            )
        ) INTO detail;

        PERFORM set_config('app.forget_person', $1::text, true);
        DELETE FROM ledger_entry
        WHERE membership_id IN ({THEIRS}) OR extra_line_id IN ({THEIR_LINES});
        PERFORM set_config('app.forget_person', '', true);
        DELETE FROM extra_line WHERE gym_id = gym AND person_id = $1;

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
        DELETE FROM charge_group_member WHERE gym_id = gym AND person_id = $1;
        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;

        INSERT INTO audit_event (gym_id, actor_id, action, reason, detail)
        VALUES (gym, {CURRENT_PERSON}, 'person_deleted', btrim($2), detail);
        RETURN NULL;
    END
    $$
"""


def _migration_0037() -> ModuleType:
    """0037, whose `forget_refusal` and `forget_gym_person` a downgrade puts back."""
    path = Path(__file__).with_name("0037_extra_charges.py")
    spec = importlib.util.spec_from_file_location("migration_0037", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    op.execute("ALTER TABLE ledger_entry ADD COLUMN voids boolean NOT NULL DEFAULT false")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_void CHECK (NOT voids OR ("
        "kind = 'adjustment' AND status = 'validated' AND amount_clp > 0"
        " AND billing_period_id IS NOT NULL AND note IS NOT NULL))"
    )
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_one_void ON ledger_entry (billing_period_id) WHERE voids"
    )

    op.execute(
        "ALTER TABLE membership"
        " ADD COLUMN voided_at timestamptz,"
        " ADD COLUMN voided_by uuid REFERENCES person (id),"
        " ADD COLUMN void_reason text CHECK (length(void_reason) BETWEEN 1 AND 500),"
        " ADD CONSTRAINT membership_void CHECK ("
        "(voided_at IS NULL) = (void_reason IS NULL)"
        " AND (voided_at IS NULL OR status = 'cancelled'))"
    )
    op.execute(cancelled_is_final(voidable=True))

    op.execute(
        "ALTER TABLE extra_line ADD COLUMN cancel_reason text"
        " CHECK (length(cancel_reason) BETWEEN 1 AND 500)"
    )

    op.execute("""
        CREATE TABLE audit_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            at timestamptz NOT NULL DEFAULT now(),
            actor_id uuid REFERENCES person (id),
            action text NOT NULL CHECK (action IN ('person_deleted')),
            reason text CHECK (length(reason) BETWEEN 1 AND 500),
            detail jsonb NOT NULL DEFAULT '{}'
        )
    """)
    op.execute("CREATE INDEX audit_event_gym_at_idx ON audit_event (gym_id, at DESC)")
    op.execute(f"GRANT SELECT ON audit_event TO {APP_ROLE}")
    op.execute("ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_event_isolation ON audit_event TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY audit_event_read ON audit_event FOR SELECT TO {APP_ROLE}"
        f" USING {LEDGER_ACCESS}"
    )

    op.execute(append_only(forget=True))
    op.execute(FORGET_REFUSAL)
    op.execute(f"DROP FUNCTION {OLD_SIGNATURE}")
    op.execute(FORGET)
    op.execute(f"REVOKE EXECUTE ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")


def downgrade() -> None:
    before = _migration_0037()
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(before.forget_refusal(extra_lines=True))
    op.execute(before.forget_gym_person(groups=True))
    op.execute(f"REVOKE EXECUTE ON FUNCTION {OLD_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {OLD_SIGNATURE} TO {APP_ROLE}")
    op.execute(append_only(forget=False))

    op.execute("DROP TABLE audit_event")
    op.execute("ALTER TABLE extra_line DROP COLUMN cancel_reason")
    op.execute(cancelled_is_final(voidable=False))
    op.execute(
        "ALTER TABLE membership DROP CONSTRAINT membership_void,"
        " DROP COLUMN void_reason, DROP COLUMN voided_by, DROP COLUMN voided_at"
    )
    op.execute("DROP INDEX ledger_entry_one_void")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_void")
    op.execute("ALTER TABLE ledger_entry DROP COLUMN voids")
