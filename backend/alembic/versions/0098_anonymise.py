"""Anonimizar: someone who paid leaves the gym's books as an anonymous record (#372).

`forget_gym_person` (0044) refuses anyone the gym kept money from, so a member who ever
paid could not be deleted. `anonymise_gym_person(person, reason)` is the way for them
(docs/compliance-audit.md; docs/legal-research.md, questions 7 and 10):

- `anonymise_refusal(person)` says why not: `not_found`, `anonymised` (already),
  `staff`, `guardian` (they answer for a dependent), `running` (not dado de baja, or a
  membership not ended: while the contract runs, refusing is lawful), `pending` (a
  proof waiting) or `owes` (a charge owed and not voided). Money kept, or moved to a
  sibling, is no reason: those rows stay.
- What stays is the books: memberships, billing periods, ledger entries, cobro lines,
  freezes, plan changes, attendance, history payments and the log's money corrections.
  They move onto a new person with nothing about them, whose record here is
  `ANONYMOUS_NAME` with `gym_person.anonymised_at` set, its RUT, email, phone, birth
  date and reason for leaving empty (`gym_person_anonymised`). Every column naming the
  person in a row of this gym moves with them, so no row of it leads to who they were,
  and a RUT another gym still has leads nowhere here: they may join again as anyone.
  Ledger notes the gym wrote on them (not a correction's reason, which the books keep)
  and history payments' notes are cleared, and each proof key becomes
  `anonimizado/<entry id>`, since a key names the uploader.
- What goes is the rest: custom fields, guardian links, unsubscribe, sign-in sessions,
  sibling groups, consent records, requirements, appointments, grades, freeze
  requests, the gym's messages to them (`message_log`), their idempotency keys, their
  sign-in links to the email this gym had, and the log's rows of their history.
- `person_anonymisation` lets the append-only guards (`ledger_entry`, `audit_event`) and
  `membership_cancelled_is_final` pass a row moving to the anonymous record, through
  `anonymising(old, new, scrubbed)`: only during an anonymisation, which writes a row
  there and deletes it again before it returns, and for a change that only moves the
  person or clears a `scrubbed` column. Nobody is granted it but its owner, so no
  other role can open the guards; and nothing keeps who became whom.
- The log keeps a `person_anonymised` row, with no person, and counts.
- `forget_gym_person` deletes the same leftovers (#366): the messages, idempotency keys
  and sign-in links it used to leave behind.
- Both then retire the global `person` when no other gym knows them, as `delete_gym`
  does (0094): deleted with their sign-in links, else, when a row still names them,
  emptied but for the id.

The proof files go after the answer, from the API (`delete_proofs` in `app.api.member_roll`).

A downgrade drops all of it; anonymous records stay, as people of their gym.

Revision ID: 0098
Revises: 0097
Create Date: 2026-11-23

"""

import re
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
ANONYMOUS_NAME = "Exalumno anonimizado"
CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# The log's rows of someone's history and team, which go; the rest are the books'.
HISTORY_ACTIONS = (
    "history_set",
    "history_removed",
    "health_reason_cleared",
    "attendance_backfilled",
    "appointment_started",
    "appointment_ended",
    "appointment_corrected",
)

GUARDED = {
    "ledger_entry_append_only()": "ARRAY['note', 'proof_object_key']",
    "audit_event_append_only()": "ARRAY[]::text[]",
    "membership_cancelled_is_final()": "ARRAY[]::text[]",
}


def _opening(scrubbed: str) -> str:
    return f"""
    -- An anonymisation (#372) moves the row onto the anonymous record it leaves.
    IF TG_OP = 'UPDATE' THEN
        IF public.anonymising(to_jsonb(OLD), to_jsonb(NEW), {scrubbed}) THEN
            RETURN NEW;
        END IF;
    END IF;
"""


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# Their memberships' and cobro lines' entries.
ENTRIES = (
    "(SELECT e.* FROM ledger_entry e"
    " WHERE e.membership_id IN (SELECT id FROM membership WHERE gym_id = gym AND person_id = $1)"
    " OR e.extra_line_id IN (SELECT id FROM extra_line WHERE gym_id = gym AND person_id = $1))"
)
SETTLED = (
    "SELECT coalesce(sum(CASE WHEN s.kind = 'refund' THEN -s.amount_clp ELSE s.amount_clp END),"
    " 0) FROM ledger_entry s WHERE s.status = 'validated'"
    " AND s.kind IN ('payment', 'adjustment', 'refund')"
)

ANONYMISING = """
CREATE FUNCTION anonymising(old jsonb, new jsonb, scrubbed text[])
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    -- Every column the same, but those naming the person, now the anonymous record,
    -- and those `scrubbed`.
    SELECT EXISTS (
        SELECT FROM person_anonymisation a
        WHERE a.at = now() AND a.of_gym = (old->>'gym_id')::uuid
          AND NOT EXISTS (
              SELECT FROM jsonb_each(old) o JOIN jsonb_each(new) n USING (key)
              WHERE o.value IS DISTINCT FROM n.value
                AND NOT (o.value = to_jsonb(a.person_id::text)
                         AND n.value = to_jsonb(a.anonymised_as::text))
                AND NOT o.key = ANY (scrubbed)
          )
    )
$$
"""

# Who someone is to the platform, once this gym is done with them: deleted with their
# sign-in links when no other gym knows them, else emptied; with another gym, the links
# to the email this gym had go and the rest is that gym's.
RETIRE = """
CREATE FUNCTION retire_person(who uuid, elsewhere boolean, gym_email text)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF elsewhere THEN
        DELETE FROM auth_link WHERE person_id = who AND lower(email) = lower(gym_email);
        RETURN;
    END IF;
    DELETE FROM auth_link WHERE person_id = who;
    PERFORM set_config('app.person_lookup', 'on', true);
    PERFORM set_config('app.person_forget', 'on', true);
    BEGIN
        DELETE FROM person WHERE id = who;
    EXCEPTION WHEN foreign_key_violation THEN
        PERFORM set_config('app.person_claim', 'on', true);
        UPDATE person SET name = '', email = NULL, rut = NULL, dob = NULL WHERE id = who;
        PERFORM set_config('app.person_claim', '', true);
    END;
    PERFORM set_config('app.person_forget', '', true);
    PERFORM set_config('app.person_lookup', '', true);
END
$$
"""

REFUSAL = f"""
CREATE FUNCTION anonymise_refusal(uuid)
RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    gym uuid := {CURRENT_GYM};
    kept gym_person;
BEGIN
    IF gym IS NULL THEN
        RAISE EXCEPTION 'app.gym_id is not set' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO kept FROM gym_person WHERE gym_id = gym AND person_id = $1;
    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;
    IF kept.anonymised_at IS NOT NULL THEN
        RETURN 'anonymised';
    END IF;
    IF EXISTS (SELECT FROM staff WHERE gym_id = gym AND person_id = $1)
       OR EXISTS (SELECT FROM session WHERE gym_id = gym AND coach_id = $1) THEN
        RETURN 'staff';
    END IF;
    IF EXISTS (SELECT FROM guardian_link WHERE gym_id = gym AND guardian_person_id = $1) THEN
        RETURN 'guardian';
    END IF;
    IF kept.left_on IS NULL OR EXISTS (
        SELECT FROM membership
        WHERE gym_id = gym AND person_id = $1 AND status <> 'cancelled' AND voided_at IS NULL
    ) THEN
        RETURN 'running';
    END IF;
    IF EXISTS (
        SELECT FROM {ENTRIES} e WHERE e.kind = 'payment' AND e.status = 'pending'
    ) THEN
        RETURN 'pending';
    END IF;
    IF EXISTS (
        SELECT FROM billing_period bp
        WHERE bp.membership_id IN (SELECT id FROM membership WHERE gym_id = gym AND person_id = $1)
          AND bp.amount_due_clp > ({SETTLED} AND s.billing_period_id = bp.id)
    ) OR EXISTS (
        SELECT FROM extra_line l
        WHERE l.gym_id = gym AND l.person_id = $1 AND l.cancelled_at IS NULL
          AND l.amount_due_clp > ({SETTLED} AND s.extra_line_id = l.id)
    ) THEN
        RETURN 'owes';
    END IF;
    RETURN NULL;
END
$$
"""

# This gym's rows of someone that are about them and not the books.
FORGET_ROWS = """
        DELETE FROM guardian_link WHERE gym_id = gym AND dependent_person_id = $1;
        DELETE FROM person_field_value WHERE gym_id = gym AND person_id = $1;
        DELETE FROM mail_unsubscribe WHERE gym_id = gym AND person_id = $1;
        DELETE FROM auth_session WHERE gym_id = gym AND person_id = $1;
        DELETE FROM charge_group_member WHERE gym_id = gym AND person_id = $1;
        DELETE FROM consent_event WHERE gym_id = gym AND person_id = $1;
        DELETE FROM person_requirement WHERE gym_id = gym AND person_id = $1;
        DELETE FROM staff_title WHERE gym_id = gym AND person_id = $1;
        DELETE FROM grade_event WHERE gym_id = gym AND person_id = $1;
        DELETE FROM freeze_request WHERE gym_id = gym AND membership_id IN (
            SELECT id FROM membership WHERE gym_id = gym AND person_id = $1
        );
"""

# What `forget_gym_person` (0044) left behind (#366).
LEFTOVERS = """
        DELETE FROM message_log WHERE gym_id = gym AND person_id = $1;
        DELETE FROM idempotency_key WHERE gym_id = gym AND person_id = $1;
"""

ANONYMISE = f"""
CREATE FUNCTION anonymise_gym_person(uuid, text)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    gym uuid := {CURRENT_GYM};
    refusal text;
    kept gym_person;
    anonymous uuid := gen_random_uuid();
    elsewhere boolean;
    detail jsonb;
    ref record;
BEGIN
    IF $2 IS NULL OR length(btrim($2)) NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'an anonymisation needs a reason' USING ERRCODE = 'check_violation';
    END IF;
    -- Locked before the check, as a deletion is.
    SELECT * INTO kept FROM gym_person WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
    PERFORM FROM membership WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
    PERFORM FROM extra_line WHERE gym_id = gym AND person_id = $1 FOR UPDATE;
    refusal := anonymise_refusal($1);
    IF refusal IS NOT NULL THEN
        RETURN refusal;
    END IF;
    -- Read before their rows here go.
    elsewhere := $1 IN (SELECT gym_people_elsewhere(gym));

    -- What the log keeps: how much stayed, and nothing about whose it was.
    SELECT jsonb_build_object(
        'memberships', (SELECT count(*) FROM membership WHERE gym_id = gym AND person_id = $1),
        'extra_lines', (SELECT count(*) FROM extra_line WHERE gym_id = gym AND person_id = $1),
        'ledger_entries', (SELECT count(*) FROM {ENTRIES} e),
        'history_payments', (
            SELECT count(*) FROM history_payment WHERE gym_id = gym AND person_id = $1
        )
    ) INTO detail;

    {FORGET_ROWS}
    {LEFTOVERS}
    PERFORM set_config('app.forget_person', $1::text, true);
    DELETE FROM audit_event
    WHERE gym_id = gym AND person_id = $1 AND action IN {_in(HISTORY_ACTIONS)};
    PERFORM set_config('app.forget_person', '', true);

    -- The anonymous record, then every row of this gym naming them, moved onto it.
    INSERT INTO person (id, name) VALUES (anonymous, '');
    INSERT INTO gym_person (
        gym_id, person_id, name, created_at, updated_at, left_on, left_at, no_whatsapp,
        member_since, prior_classes, anonymised_at
    ) VALUES (
        gym, anonymous, '{ANONYMOUS_NAME}', kept.created_at, now(), kept.left_on,
        kept.left_at, true, kept.member_since, kept.prior_classes, now()
    );
    INSERT INTO person_anonymisation (of_gym, person_id, anonymised_as, at)
    VALUES (gym, $1, anonymous, now());
    FOR ref IN
        SELECT c.relname AS tab, a.attname AS col
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
        WHERE k.contype = 'f' AND k.confrelid = 'public.person'::regclass
          AND cardinality(k.conkey) = 1 AND c.relname <> 'gym_person'
          AND EXISTS (
              SELECT FROM pg_attribute g
              WHERE g.attrelid = k.conrelid AND g.attname = 'gym_id' AND NOT g.attisdropped
          )
        ORDER BY 1, 2
    LOOP
        EXECUTE format('UPDATE %I SET %I = $1 WHERE gym_id = $2 AND %I = $3',
                       ref.tab, ref.col, ref.col)
        USING anonymous, gym, $1;
    END LOOP;
    -- What the gym wrote about them, and the proof keys, which name the uploader.
    UPDATE ledger_entry e
    SET note = CASE WHEN e.purpose IS NULL THEN NULL ELSE e.note END,
        proof_object_key = CASE WHEN e.proof_object_key IS NULL THEN NULL
                                ELSE 'anonimizado/' || e.id END
    WHERE e.id IN (
        SELECT x.id FROM ledger_entry x
        WHERE x.membership_id IN (
                  SELECT id FROM membership WHERE gym_id = gym AND person_id = anonymous)
           OR x.extra_line_id IN (
                  SELECT id FROM extra_line WHERE gym_id = gym AND person_id = anonymous)
    ) AND ((e.purpose IS NULL AND e.note IS NOT NULL) OR e.proof_object_key IS NOT NULL);
    UPDATE history_payment SET note = NULL WHERE gym_id = gym AND person_id = anonymous;
    DELETE FROM person_anonymisation p WHERE p.of_gym = gym AND p.anonymised_as = anonymous;
    DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;

    PERFORM retire_person($1, elsewhere, kept.email);
    INSERT INTO audit_event (gym_id, actor_id, action, reason, detail)
    VALUES (gym, NULLIF(current_setting('app.person_id', true), '')::uuid,
            'person_anonymised', btrim($2), detail);
    RETURN NULL;
END
$$
"""

FORGET = "forget_gym_person(uuid, text)"
# 0071's `forget_gym_person`, as it stands: what it deletes last, and its new tail.
FORGET_LAST = "        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;\n"
FORGET_TAIL = LEFTOVERS + "        PERFORM retire_person($1, elsewhere, gym_email);\n"
FORGET_DECLARE = "        detail jsonb;\n"
FORGET_DECLARED = "        detail jsonb;\n        elsewhere boolean;\n        gym_email text;\n"
FORGET_REFUSED = "            RETURN refusal;\n        END IF;\n"
FORGET_READ = (
    FORGET_REFUSED
    + "        -- Read before their rows here go.\n"
    + "        elsewhere := $1 IN (SELECT gym_people_elsewhere(gym));\n"
    + "        SELECT email INTO gym_email FROM gym_person WHERE gym_id = gym AND person_id = $1;\n"
)

TABLE = """
CREATE TABLE person_anonymisation (
    of_gym uuid NOT NULL,
    person_id uuid NOT NULL,
    anonymised_as uuid NOT NULL,
    at timestamptz NOT NULL
)
"""

ANONYMISED = (
    "ALTER TABLE gym_person ADD CONSTRAINT gym_person_anonymised CHECK ("
    f" anonymised_at IS NULL OR (name = '{ANONYMOUS_NAME}' AND rut IS NULL AND email IS NULL"
    " AND phone IS NULL AND dob IS NULL AND left_reason IS NULL AND left_on IS NOT NULL))"
)

ACTION_CHECKS = ("audit_event_action_check", "audit_event_person")


def _definition(signature: str) -> str:
    sql: str = (
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": signature})
        .scalar_one()
    )
    return sql


def _guards(*, open_: bool) -> None:
    """Each guard as it stands, with its opening after its first BEGIN, or without."""
    for signature, scrubbed in GUARDED.items():
        sql = _definition(signature)
        opening = _opening(scrubbed)
        if open_:
            assert opening not in sql, signature
            sql, count = re.subn(r"\bBEGIN\n", "BEGIN\n" + opening, sql, count=1)
            assert count == 1, signature
        else:
            assert sql.count(opening) == 1, signature
            sql = sql.replace(opening, "")
        op.execute(sql)


def _forget(*, leftovers: bool) -> None:
    sql = _definition(FORGET)
    patches = [
        (FORGET_DECLARE, FORGET_DECLARED),
        (FORGET_REFUSED, FORGET_READ),
        (FORGET_LAST, FORGET_LAST + FORGET_TAIL),
    ]
    for before, after in patches if leftovers else [(a, b) for b, a in reversed(patches)]:
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    op.execute(sql)


def _actions(*, anonymised: bool) -> None:
    conn = op.get_bind()
    for name in ACTION_CHECKS:
        definition: str = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = :n AND conrelid = 'audit_event'::regclass"
            ),
            {"n": name},
        ).scalar_one()
        old, new = "'person_deleted'::text", "'person_deleted'::text, 'person_anonymised'::text"
        if anonymised:
            assert definition.count(old) == 1, name
            definition = definition.replace(old, new)
        else:
            assert definition.count(new) == 1, name
            definition = definition.replace(new, old) + " NOT VALID"
        op.execute(f"ALTER TABLE audit_event DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE audit_event ADD CONSTRAINT {name} {definition}")


def upgrade() -> None:
    op.execute("ALTER TABLE gym_person ADD COLUMN anonymised_at timestamptz")
    op.execute(ANONYMISED)
    _actions(anonymised=True)
    # Nobody's but the owner's: who became whom, while one runs. Its gym is `of_gym`, not a
    # `gym_id`: empty outside a call, it is no gym's data to isolate or to delete.
    op.execute(TABLE)
    op.execute("REVOKE ALL ON person_anonymisation FROM PUBLIC")
    # The owner reads and deletes the gym's messages only through these functions.
    op.execute(
        "CREATE POLICY message_log_forget ON message_log FOR DELETE TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM})"
    )
    op.execute(ANONYMISING)
    _guards(open_=True)
    op.execute(RETIRE)
    op.execute("REVOKE ALL ON FUNCTION retire_person(uuid, boolean, text) FROM PUBLIC")
    _forget(leftovers=True)
    op.execute(REFUSAL)
    op.execute(ANONYMISE)
    for signature in ("anonymise_refusal(uuid)", "anonymise_gym_person(uuid, text)"):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION anonymise_gym_person(uuid, text)")
    op.execute("DROP FUNCTION anonymise_refusal(uuid)")
    _forget(leftovers=False)
    op.execute("DROP FUNCTION retire_person(uuid, boolean, text)")
    _guards(open_=False)
    op.execute("DROP FUNCTION anonymising(jsonb, jsonb, text[])")
    op.execute("DROP POLICY message_log_forget ON message_log")
    op.execute("DROP TABLE person_anonymisation")
    _actions(anonymised=False)
    op.execute("ALTER TABLE gym_person DROP CONSTRAINT gym_person_anonymised")
    op.execute("ALTER TABLE gym_person DROP COLUMN anonymised_at")
