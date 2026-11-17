"""Drop-in visits: a coach charges a single class, and gives it back the same day (#130).

A drop-in visit ("Clase suelta") is a one-day membership on a `dropin` plan, ended as
it starts, with its attendance at the class (docs/adr/0002-drop-in-visits.md). The
ledger is a membership's billing periods, so the visit's price is the one period of
that day, with its charge, as the nightly job would bill a drop-in; payments,
proofs, receipts, refunds and the book take it as any other period.

A coach adds the visitor and marks them present, but may not write the ledger (0006)
or a correction's record (0048). Two `SECURITY DEFINER` functions do exactly what a
visit needs there, as the owner role, held to the gym in `app.gym_id`, and refuse
anyone who is not staff of it:

- `dropin_charge(visit)` bills the visit's one period, at its plan's price less the
  membership's discount, with a validated charge, once. A visit that is not a
  drop-in, or is billed already, is an error.
- `dropin_void(visit, reason)` gives it back: what the period still owes is voided
  (an adjustment, `purpose = 'void'`, never a delete), the correction is recorded in
  `audit_event` under the person acting, and the membership is marked voided, as
  "Anular plan" does (0044). It answers `paid` or `pending`, and writes nothing, while
  the period has a payment the gym kept or a proof waiting: refunding or rejecting it
  is the ledger's, an owner's or admin's. A visit voided already answers nothing and
  writes nothing.

Their `search_path` takes in `public`, as every plpgsql writer here does: the ledger's
own triggers name its tables unqualified, and run under it.

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

WRITER = "LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public"

# The person acting is staff of the current gym, any role: a coach adds visitors.
REQUIRE_STAFF = f"""
        IF NOT EXISTS (
            SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}
        ) THEN
            RAISE EXCEPTION 'only staff of the gym add or remove a drop-in visit'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
"""

# One period, the visit's day in the gym's timezone, as `app.domain.billing` bills a
# drop-in; its charge validated as it is written, as the billing job writes one.
CHARGE = f"""
    CREATE FUNCTION dropin_charge(visit uuid) RETURNS uuid
    {WRITER}
    AS $$
    DECLARE
        held record;
        period uuid;
    BEGIN
        {REQUIRE_STAFF}
        SELECT (m.started_at AT TIME ZONE g.timezone)::date AS day,
               (pl.price_clp * (100 - m.discount_pct) / 100)::bigint AS amount
        INTO held
        FROM membership m
        JOIN plan pl ON pl.id = m.plan_id
        JOIN gym g ON g.id = m.gym_id
        WHERE m.id = visit AND m.gym_id = {CURRENT_GYM} AND pl.kind = 'dropin'
          AND NOT EXISTS (SELECT FROM billing_period b WHERE b.membership_id = m.id)
        FOR UPDATE OF m;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'membership % is no drop-in visit waiting for its charge', visit
                USING ERRCODE = 'check_violation';
        END IF;
        INSERT INTO billing_period
            (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)
        VALUES ({CURRENT_GYM}, visit, held.day, held.day, held.amount, held.day)
        RETURNING id INTO period;
        IF held.amount > 0 THEN
            INSERT INTO ledger_entry
                (gym_id, membership_id, billing_period_id, amount_clp, kind, status,
                 validated_at)
            VALUES ({CURRENT_GYM}, visit, period, held.amount, 'charge', 'validated', now());
        END IF;
        RETURN period;
    END
    $$
"""

# What a period's entries settle, as `app.domain.billing.settled_amount` reads them.
SETTLED = "CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END"

# `app.api.ledger.void_period` for the visit's one period, then the plan's void
# (`app.api.memberships.VOID_CANCELLED`). The figures recorded are those
# `app.api.corrections.record_correction` records: what the period owes and the
# membership's balance, before and after.
VOID = f"""
    CREATE FUNCTION dropin_void(visit uuid, reason text) RETURNS text
    {WRITER}
    AS $$
    DECLARE
        actor uuid := {CURRENT_PERSON};
        held record;
        period record;
        money record;
        owed bigint;
        before_balance bigint;
        entry uuid;
    BEGIN
        {REQUIRE_STAFF}
        SELECT m.person_id, m.voided_at INTO held
        FROM membership m JOIN plan pl ON pl.id = m.plan_id
        WHERE m.id = visit AND m.gym_id = {CURRENT_GYM} AND pl.kind = 'dropin'
        FOR UPDATE OF m;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'membership % is no drop-in visit', visit
                USING ERRCODE = 'check_violation';
        END IF;
        IF held.voided_at IS NOT NULL THEN
            RETURN NULL;
        END IF;

        SELECT b.id, b.amount_due_clp INTO period
        FROM billing_period b WHERE b.membership_id = visit FOR UPDATE;
        IF FOUND THEN
            SELECT coalesce(sum(CASE WHEN e.kind = 'payment' AND e.status = 'validated'
                                     THEN e.amount_clp
                                     WHEN e.kind = 'refund' THEN -e.amount_clp
                                     ELSE 0 END), 0) AS kept_clp,
                   coalesce(bool_or(e.kind = 'payment' AND e.status = 'pending'), false)
                       AS pending,
                   coalesce(sum({SETTLED}) FILTER (
                       WHERE e.status = 'validated'
                         AND e.kind IN ('payment', 'adjustment', 'refund')
                   ), 0) AS settled_clp
            INTO money
            FROM ledger_entry e WHERE e.billing_period_id = period.id;
            IF money.kept_clp > 0 THEN
                RETURN 'paid';
            END IF;
            IF money.pending THEN
                RETURN 'pending';
            END IF;
            owed := period.amount_due_clp - money.settled_clp;
            IF owed > 0 THEN
                SELECT coalesce(sum(balance_clp), 0) INTO before_balance
                FROM v_balance WHERE membership_id = visit;
                INSERT INTO ledger_entry
                    (gym_id, membership_id, billing_period_id, amount_clp, kind, status,
                     claimed_by, claimed_at, validated_by, validated_at, note, purpose)
                VALUES ({CURRENT_GYM}, visit, period.id, owed, 'adjustment', 'validated',
                        actor, now(), actor, now(), reason, 'void')
                RETURNING id INTO entry;
                INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, reason, detail)
                VALUES ({CURRENT_GYM}, now(), actor, held.person_id, 'ledger_corrected', reason,
                        jsonb_build_object(
                            'membership_id', visit,
                            'purpose', 'void',
                            'billing_period_id', period.id,
                            'entry_ids', jsonb_build_array(entry),
                            'before', jsonb_build_object(
                                'outstanding_clp', owed, 'balance_clp', before_balance),
                            'after', jsonb_build_object(
                                'outstanding_clp', 0, 'balance_clp', before_balance - owed),
                            'plan_void', true,
                            'dropin', true));
            END IF;
        END IF;

        UPDATE membership SET voided_at = now(), voided_by = actor, void_reason = reason
        WHERE id = visit;
        RETURN NULL;
    END
    $$
"""


def upgrade() -> None:
    for sql, signature in ((CHARGE, "dropin_charge(uuid)"), (VOID, "dropin_void(uuid, text)")):
        op.execute(sql)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION dropin_void(uuid, text)")
    op.execute("DROP FUNCTION dropin_charge(uuid)")
