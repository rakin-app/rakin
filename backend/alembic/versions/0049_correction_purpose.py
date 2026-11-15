"""Restaurar cargo: what a correcting entry is for, and what it corrects (#278).

docs/design/billing-corrections.md, section 2. The ledger stays append-only, and every
correction of money is a new entry linked to what it corrects. Two columns say what a
correction is, for this ticket's restore and every later one:

- `ledger_entry.purpose`: why an adjustment or a refund was written, when it is a
  correction. `void`, `restore`, `revert`, `write_off`, `move` or `mistake`, each held
  to its kind and sign by `ledger_entry_purpose`; every one is validated, on a period
  where it settles one, with its reason in `note`.
- `ledger_entry.corrects`: the entry it undoes or moves, for the purposes that have
  one (`restore`, `revert`, `move`, `mistake`).

0044's `voids` boolean becomes `purpose = 'void'` and goes, with its check and its
one-void-per-period index. A void a restore stands against no longer counts as one, so
the rule is now one void *without a restore* per period, which a partial index cannot
say: `ledger_entry_correction`, a constraint trigger, locks the period and counts them,
and holds a restore to the void it names (an unrestored void of its own period, of the
same amount the other way). `ledger_entry_one_restore` lets a void be restored once.

`forget_gym_person`'s `voided_clp` (0044, 0048) sums the voids still standing.

A downgrade puts `voids` back from `purpose = 'void'`, and refuses while any other
purpose is in the ledger: a restore has nowhere to go in 0048's schema, and an entry
cannot be deleted.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-15

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = ("void", "restore", "revert", "write_off", "move", "mistake")
# The purposes whose entry names the one it corrects.
CORRECTING = ("restore", "revert", "move", "mistake")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# Each purpose's kind and sign (the design's table). A void and a write-off take what a
# period owes off it; a restore puts a void's amount back on; a revert undoes an
# adjustment either way; a move takes a payment out of one period (a refund) and into
# another (a payment); a mistake takes back what is left of a payment.
PURPOSE_CHECK = f"""
    CHECK (purpose IS NULL OR (
        purpose IN {_in(PURPOSES)}
        AND status = 'validated' AND note IS NOT NULL
        AND (corrects IS NOT NULL) = (purpose IN {_in(CORRECTING)})
        AND CASE purpose
            WHEN 'void' THEN kind = 'adjustment' AND amount_clp > 0
                AND billing_period_id IS NOT NULL
            WHEN 'restore' THEN kind = 'adjustment' AND amount_clp < 0
                AND billing_period_id IS NOT NULL
            WHEN 'revert' THEN kind = 'adjustment'
            WHEN 'write_off' THEN kind = 'adjustment' AND amount_clp > 0
                AND billing_period_id IS NOT NULL
            WHEN 'move' THEN kind IN ('payment', 'refund')
            WHEN 'mistake' THEN kind = 'refund'
        END
    ))
"""

# A void no restore stands against, for `v`, a `ledger_entry`.
STANDING_VOID = (
    "v.purpose = 'void' AND NOT EXISTS ("
    "SELECT FROM ledger_entry r WHERE r.corrects = v.id AND r.purpose = 'restore')"
)

# After the row is in, under the period's lock, so two voids inserted at once count one
# after the other: in a plpgsql function each statement reads what committed before it.
CORRECTION_TRIGGER = f"""
    CREATE FUNCTION ledger_entry_correction() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM FROM billing_period WHERE id = NEW.billing_period_id FOR UPDATE;
        IF NEW.purpose = 'restore' AND NOT EXISTS (
            SELECT FROM ledger_entry v
            WHERE v.id = NEW.corrects AND v.purpose = 'void'
              AND v.billing_period_id = NEW.billing_period_id
              AND v.amount_clp = -NEW.amount_clp
        ) THEN
            RAISE EXCEPTION 'restore %: % is not a void of % on its period',
                NEW.id, NEW.corrects, -NEW.amount_clp
                USING ERRCODE = 'check_violation';
        END IF;
        IF (
            SELECT count(*) FROM ledger_entry v
            WHERE v.billing_period_id = NEW.billing_period_id AND {STANDING_VOID}
        ) > 1 THEN
            RAISE EXCEPTION 'billing period % has a void already', NEW.billing_period_id
                USING ERRCODE = 'unique_violation';
        END IF;
        RETURN NULL;
    END
    $$
"""

# 0048's `forget_gym_person`, whose `voided_clp` this one turns into the standing voids'.
VOIDED_BEFORE = "FROM ({THEIR_ENTRIES}) e WHERE e.voids"
VOIDED_AFTER = "FROM ({THEIR_ENTRIES}) e WHERE {STANDING}"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(standing: bool) -> str:
    """0048's function, replacing itself; with `standing`, its `voided_clp` sums the
    voids no restore stands against, read from `purpose`."""
    sql: str = _migration("0048_correction_audit.py").forget_gym_person(corrections=True)
    if standing:
        entries = _migration("0044_void_and_forget.py").THEIR_ENTRIES
        before = VOIDED_BEFORE.format(THEIR_ENTRIES=entries)
        after = VOIDED_AFTER.format(
            THEIR_ENTRIES=entries, STANDING=STANDING_VOID.replace("v.", "e.")
        )
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def _set_every_row(sql: str) -> None:
    """Run `sql`, an `UPDATE` of every gym's entries, past the append-only trigger (0002)
    and the policy that holds even the owner to one gym (0006). Only the column this
    migration moves changes."""
    op.execute("ALTER TABLE ledger_entry DISABLE TRIGGER ledger_entry_append_only")
    op.execute("ALTER TABLE ledger_entry NO FORCE ROW LEVEL SECURITY")
    op.execute(sql)
    op.execute("ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ledger_entry ENABLE TRIGGER ledger_entry_append_only")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ledger_entry ADD COLUMN purpose text,"
        " ADD COLUMN corrects uuid REFERENCES ledger_entry (id)"
    )
    _set_every_row("UPDATE ledger_entry SET purpose = 'void' WHERE voids")
    op.execute("DROP INDEX ledger_entry_one_void")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_void")
    op.execute("ALTER TABLE ledger_entry DROP COLUMN voids")

    op.execute(f"ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_purpose {PURPOSE_CHECK}")
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_one_restore ON ledger_entry (corrects)"
        " WHERE purpose = 'restore'"
    )
    op.execute("CREATE INDEX ledger_entry_corrects_idx ON ledger_entry (corrects)")
    op.execute(CORRECTION_TRIGGER)
    op.execute(
        "CREATE CONSTRAINT TRIGGER ledger_entry_correction AFTER INSERT ON ledger_entry"
        " FOR EACH ROW WHEN (NEW.purpose IN ('void', 'restore'))"
        " EXECUTE FUNCTION ledger_entry_correction()"
    )
    op.execute(forget_gym_person(standing=True))


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_entry NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM ledger_entry WHERE purpose <> 'void') THEN
                RAISE EXCEPTION 'the ledger holds corrections 0048 has no place for'
                    USING HINT = 'entries cannot be deleted: stay on 0049';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY")
    op.execute(forget_gym_person(standing=False))
    op.execute("DROP TRIGGER ledger_entry_correction ON ledger_entry")
    op.execute("DROP FUNCTION ledger_entry_correction()")
    op.execute("DROP INDEX ledger_entry_corrects_idx")
    op.execute("DROP INDEX ledger_entry_one_restore")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_purpose")

    op.execute("ALTER TABLE ledger_entry ADD COLUMN voids boolean NOT NULL DEFAULT false")
    _set_every_row("UPDATE ledger_entry SET voids = true WHERE purpose = 'void'")
    op.execute(
        "ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_void CHECK (NOT voids OR ("
        "kind = 'adjustment' AND status = 'validated' AND amount_clp > 0"
        " AND billing_period_id IS NOT NULL AND note IS NOT NULL))"
    )
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_one_void ON ledger_entry (billing_period_id) WHERE voids"
    )
    op.execute("ALTER TABLE ledger_entry DROP COLUMN corrects, DROP COLUMN purpose")
