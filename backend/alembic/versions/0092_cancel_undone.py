"""Deshacer baja: a cancel made by mistake is undone, through the database (#285).

docs/design/billing-corrections.md, section 2 (C11). A cancelled membership is final
(0009) except for its void (0044) and now for this: `POST /api/memberships/{id}/uncancel`
returns it to `active`, or to `lapsed` when a period past due plus grace is unpaid.

- 0009's trigger lets the undo through only for a membership not voided, changing
  `status` (to `active` or `lapsed`), `cancel_reason` and `cancelled_at` (both to null)
  and nothing else, and only when the API has first written the matching audit row in
  the same transaction: `action = 'cancel_undone'`, `detail->>'membership_id'` the
  membership's id, `detail->'status'->>'after'` the new status, `actor_id` the person
  acting (`app.person_id`) and `at = now()`. `now()` is the transaction's start, so a
  row of another transaction cannot match, and no other action opens it, a due-date
  change included. The function reads the log as its owner (`SECURITY DEFINER`), held
  to the current gym by the log's own policy (0044), so whether the gate opens never
  depends on what the acting role may read.
- `membership.cancel_undone_at`: when a cancel was last undone. Its periods since the
  cancel are billed then, already past due, so the nightly `lapse` job gives it its
  grace from that day, as from a reactivation's (`reactivated_at`, 0050). A column of
  its own, so the month's "Planes vencidos que volvieron a activarse" does not count
  it. It is set by a second `UPDATE`, once the row is no longer cancelled.

Revision ID: 0092
Revises: 0091
Create Date: 2026-11-22

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0092"
down_revision: str | Sequence[str] | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"
VOID_COLUMNS = ("voided_at", "voided_by", "void_reason")
UNDO_COLUMNS = ("status", "cancel_reason", "cancelled_at")
CANCEL_UNDONE = "cancel_undone"


def _migration_0044() -> ModuleType:
    """0044, whose trigger function a downgrade puts back."""
    path = Path(__file__).with_name("0044_void_and_forget.py")
    spec = importlib.util.spec_from_file_location("migration_0044", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(columns: Sequence[str]) -> str:
    return ", ".join(f"'{c}'" for c in columns)


CANCELLED_IS_FINAL = f"""
    CREATE OR REPLACE FUNCTION membership_cancelled_is_final() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    BEGIN
        -- A void (0044): its three columns and nothing else.
        IF OLD.voided_at IS NULL AND NEW.voided_at IS NOT NULL
           AND to_jsonb(NEW) - ARRAY[{_columns(VOID_COLUMNS)}]
               IS NOT DISTINCT FROM to_jsonb(OLD) - ARRAY[{_columns(VOID_COLUMNS)}]
        THEN
            RETURN NEW;
        END IF;
        -- An undo (#285), with its audit row of this transaction.
        IF OLD.voided_at IS NULL
           AND NEW.status IN ('active', 'lapsed')
           AND NEW.cancel_reason IS NULL AND NEW.cancelled_at IS NULL
           AND to_jsonb(NEW) - ARRAY[{_columns(UNDO_COLUMNS)}]
               IS NOT DISTINCT FROM to_jsonb(OLD) - ARRAY[{_columns(UNDO_COLUMNS)}]
           AND EXISTS (
               SELECT FROM audit_event a
               WHERE a.gym_id = OLD.gym_id
                 AND a.action = '{CANCEL_UNDONE}'
                 AND a.detail->>'membership_id' = OLD.id::text
                 AND a.detail->'status'->>'after' = NEW.status
                 AND a.actor_id = {CURRENT_PERSON}
                 AND a.at = now()
           )
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'a cancelled membership cannot change'
            USING ERRCODE = 'restrict_violation';
    END
    $$
"""


def upgrade() -> None:
    op.execute("ALTER TABLE membership ADD COLUMN cancel_undone_at timestamptz")
    op.execute(CANCELLED_IS_FINAL)


def downgrade() -> None:
    # CREATE OR REPLACE assigns every property it does not name its default: 0044's
    # function comes back SECURITY INVOKER, with no search_path of its own.
    op.execute(_migration_0044().cancelled_is_final(voidable=True))
    op.execute("ALTER TABLE membership DROP COLUMN cancel_undone_at")
