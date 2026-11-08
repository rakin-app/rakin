"""Ledger entries are append-only: no DELETE, and UPDATE only to settle a pending one.

Grants already keep `DELETE` from `rakin_app`; these triggers hold every role to it,
the owner and superusers included, so a backfill or a console session cannot erase
or rewrite money history either. A correction is a new entry.

An `UPDATE` may change only `status`, `validated_by`, `validated_at` and `note`, and
only while the row is still `pending`. Every other column, including any added
later, is compared and must stay as it was. `TRUNCATE` skips row triggers, so it has
a statement trigger of its own.

Violations raise `restrict_violation` (SQLSTATE 23001). The table owner can still
`DISABLE TRIGGER`; that is a deliberate, visible act, not an accident.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The columns that settling a pending entry may change; see app.domain.ledger.
SETTLEMENT_COLUMNS = ("status", "validated_by", "validated_at", "note")

HINT = "ledger entries are append-only; record a correction as a new entry"


def upgrade() -> None:
    settlement = ", ".join(f"'{c}'" for c in SETTLEMENT_COLUMNS)
    op.execute(f"""
        CREATE FUNCTION ledger_entry_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
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
    """)
    op.execute(
        "CREATE TRIGGER ledger_entry_append_only BEFORE UPDATE OR DELETE ON ledger_entry"
        " FOR EACH ROW EXECUTE FUNCTION ledger_entry_append_only()"
    )
    op.execute(
        "CREATE TRIGGER ledger_entry_no_truncate BEFORE TRUNCATE ON ledger_entry"
        " FOR EACH STATEMENT EXECUTE FUNCTION ledger_entry_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER ledger_entry_no_truncate ON ledger_entry")
    op.execute("DROP TRIGGER ledger_entry_append_only ON ledger_entry")
    op.execute("DROP FUNCTION ledger_entry_append_only()")
