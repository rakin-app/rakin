"""A membership's discount with why, and each period billed with the discount it had (#25).

`membership.discount_pct` (0001) was billed but never set by anyone and said nothing
of why. Now an admin sets it on the ficha with a reason ("Hermanos", "Beca", or
anything else the gym gives one for), and the ledger shows it on each charge:

- `membership.discount_reason`, why it has the discount. There is none without a
  discount: clearing the discount clears it. A discount from before this migration has
  no reason; the API asks for one from now on.
- `billing_period.discount_pct` and `discount_reason`, the discount the period was
  billed at, as it was when it was written. A discount changed later bills the periods
  after it and leaves these as they were, so the ledger keeps saying what each charge
  was billed at. A trigger copies them from the membership as the period is written,
  so the billing job, a start, a drop-in visit (0061) and the seed all record it.

Existing periods take their membership's discount: nothing could change it before, so
it is the one they were billed at.

Each set, change or removal of a discount, a plan started with one included, is a
correction of the member's billing (0048): a `discount_changed` row in `audit_event`,
whose `detail` has the percentage and reason before and after and the first day billed
at the new one, and which the ficha's "Correcciones" lists. An owner or admin writes it,
under a policy of its own that holds it as `audit_event_correct` holds the others.

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-17

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("membership", "billing_period")

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

CHANGED = "discount_changed"

# As 0048's `audit_event_correct`, for this action: an owner or admin of the current
# gym, as themselves, now, about one of the gym's people.
DISCOUNT_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action = '{CHANGED}'"
    f" AND EXISTS (SELECT FROM staff s WHERE s.gym_id = {CURRENT_GYM}"
    f" AND s.person_id = {CURRENT_PERSON} AND s.role IN ('owner', 'admin'))"
    f" AND EXISTS (SELECT FROM gym_person gp WHERE gp.gym_id = {CURRENT_GYM}"
    " AND gp.person_id = audit_event.person_id))"
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint(changed: bool) -> None:
    """0057's actions, with `discount_changed` or without."""
    m0057 = _migration("0057_no_health_reasons.py")
    m0055 = _migration("0055_history_payment.py")
    m0056 = _migration("0056_import_undone.py")
    actions: tuple[str, ...] = (
        *_migration("0051_person_history.py")._actions(history=True)[0],
        m0056.IMPORTED,
        m0055.REMOVED,
        m0056.UNDONE,
        m0057.CLEARED,
    )
    if changed:
        actions = (*actions, CHANGED)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        " ADD CONSTRAINT audit_event_action_check"
        f" CHECK (action IN {_migration('0048_correction_audit.py')._in(actions)})"
    )


# Run as the period's writer, which may read its membership: RLS holds both to the gym.
STAMP = """
    CREATE FUNCTION billing_period_discount() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        SELECT m.discount_pct, m.discount_reason INTO NEW.discount_pct, NEW.discount_reason
        FROM membership m WHERE m.id = NEW.membership_id;
        RETURN NEW;
    END
    $$
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE membership ADD COLUMN discount_reason text,"
        " ADD CONSTRAINT membership_discount_reason"
        " CHECK (discount_reason IS NULL OR discount_pct > 0)"
    )
    op.execute(
        "ALTER TABLE billing_period"
        " ADD COLUMN discount_pct smallint NOT NULL DEFAULT 0"
        " CHECK (discount_pct BETWEEN 0 AND 100),"
        " ADD COLUMN discount_reason text"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE billing_period b SET discount_pct = m.discount_pct"
        " FROM membership m WHERE m.id = b.membership_id AND m.discount_pct > 0"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(STAMP)
    op.execute(
        "CREATE TRIGGER billing_period_discount BEFORE INSERT ON billing_period"
        " FOR EACH ROW EXECUTE FUNCTION billing_period_discount()"
    )
    _constraint(changed=True)
    op.execute(
        f"CREATE POLICY audit_event_discount ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {DISCOUNT_INSERT}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_discount ON audit_event")
    # The rows go with their action, past the trigger that keeps the log append-only
    # (0048), and the policy that holds even the owner to one gym (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action = '{CHANGED}'")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraint(changed=False)
    op.execute("DROP TRIGGER billing_period_discount ON billing_period")
    op.execute("DROP FUNCTION billing_period_discount()")
    op.execute("ALTER TABLE billing_period DROP COLUMN discount_reason, DROP COLUMN discount_pct")
    op.execute(
        "ALTER TABLE membership DROP CONSTRAINT membership_discount_reason,"
        " DROP COLUMN discount_reason"
    )
