"""A freeze ended early, edited, or booked ahead (#115); who ended it.

`membership_freeze` (0017) was history from the start. Now a freeze can change while it
runs or before it starts, so `rakin_app` may update a freeze's `to_date` and `reason`
(its `from_date` never moves), and the `freezes` job its `started`:

- Ended early, its `to_date` is the day it ended. Ended on its first day, or called
  off before it started, `to_date` is its `from_date`: no day frozen. Such a freeze
  lists no lines, and leaves its first day free for another, so the unique key on
  `(membership_id, from_date)` holds only for freezes of a day or more.
- `started` is false on a freeze booked to start on a later day, until the `freezes`
  job starts it on its `from_date` and moves the due date then. Every freeze before
  this one started the day it was written.

`plan_event.created_by` is the staff member whose request wrote the event, as when an
admin ends a freeze early; null when a job wrote it.

`shift_billing_periods` moves a membership's billing periods starting on or after a
day by a number of days, either way, one at a time in the order that keeps their
`(membership_id, period_start)` key unique on the way. A freeze moves them as it
starts, and again by the difference when its end moves; the API and the `freezes` job
both call it. It runs with the caller's privileges and row-level security.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE membership_freeze"
        " DROP CONSTRAINT membership_freeze_check,"
        " DROP CONSTRAINT membership_freeze_membership_id_from_date_key,"
        " ADD COLUMN started boolean NOT NULL DEFAULT true,"
        " ADD CONSTRAINT membership_freeze_dates CHECK (to_date >= from_date)"
    )
    op.execute(
        "CREATE UNIQUE INDEX membership_freeze_from_key ON membership_freeze"
        " (membership_id, from_date) WHERE to_date > from_date"
    )
    op.execute(f"GRANT UPDATE (to_date, reason, started) ON membership_freeze TO {APP_ROLE}")

    op.execute("ALTER TABLE plan_event ADD COLUMN created_by uuid REFERENCES person (id)")

    op.execute("""
        CREATE FUNCTION shift_billing_periods(p_membership uuid, p_from date, p_days integer)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            period_id uuid;
        BEGIN
            -- Latest first moving later, earliest first moving earlier: each period
            -- moves out of the way of the next before that one moves.
            FOR period_id IN
                SELECT id FROM billing_period
                WHERE membership_id = p_membership AND period_start >= p_from
                ORDER BY CASE WHEN p_days > 0 THEN period_start END DESC,
                         CASE WHEN p_days < 0 THEN period_start END
                FOR UPDATE
            LOOP
                UPDATE billing_period SET period_start = period_start + p_days,
                    period_end = period_end + p_days, due_date = due_date + p_days
                WHERE id = period_id;
            END LOOP;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION shift_billing_periods(uuid, date, integer)")
    op.execute("ALTER TABLE plan_event DROP COLUMN created_by")
    op.execute(f"REVOKE UPDATE (to_date, reason, started) ON membership_freeze FROM {APP_ROLE}")
    op.execute("DROP INDEX membership_freeze_from_key")
    # A freeze of no days, or one booked ahead, has no place in 0017's table.
    op.execute("DELETE FROM membership_freeze WHERE to_date = from_date OR NOT started")
    op.execute(
        "ALTER TABLE membership_freeze"
        " DROP CONSTRAINT membership_freeze_dates,"
        " DROP COLUMN started,"
        " ADD CONSTRAINT membership_freeze_check CHECK (to_date > from_date),"
        " ADD CONSTRAINT membership_freeze_membership_id_from_date_key"
        " UNIQUE (membership_id, from_date)"
    )
