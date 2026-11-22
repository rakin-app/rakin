"""Mover pago: a payment moved to another period is neither income nor a refund (#280).

docs/design/billing-corrections.md, section 2 (`move`). A payment recorded on the wrong
month, plan, or sibling is moved with a pair of entries written in one transaction, both
`purpose = 'move'` and both naming the payment in `corrects`: a refund-shaped entry on
the old period (`refund_of` the payment, so what is left of it to refund or move goes
down as a refund takes it), and a validated payment on the new one. 0049 already holds
the purpose to those two kinds.

- `v_monthly_income` leaves both out: the money was counted when it was first paid, and
  never left. `income_clp` was unchanged by the pair already (they net to zero), but
  `payments`, `refunds_clp` and `refunds` counted them. `v_balance` needs nothing: it
  sums per membership, so the amount moves from one membership to the other.
- `ledger_entry_move` holds a move to a period, never a cobro line, and the refund half
  to its own payment (`corrects = refund_of`, as 0087 holds a mistake).
- `ledger_entry_move_pair`, a constraint trigger checked at commit, holds every move
  to its pair: for each payment moved, what moved in equals what moved out.
- `forget_refusal` counts a moved-out payment as given back from its membership, as it
  nets every refund (0044). A payment moved to *another* person (a sibling) is still
  named by that person's entry, which the ledger cannot change or delete, so the person
  it came from is refused: `moved`.

A downgrade refuses while a move is in the ledger, and puts 0087's view and 0044's
`forget_refusal` back.

Revision ID: 0089
Revises: 0088
Create Date: 2026-11-22

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0089"
down_revision: str | Sequence[str] | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPTIONS = "WITH (security_invoker = true)"
MOVE = "e.purpose = 'move'"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MISTAKE = _migration("0087_payment_mistake.py")
FORGET = _migration("0044_void_and_forget.py")

WHERE_BEFORE = "WHERE e.kind IN ('payment', 'refund') AND e.status = 'validated'\n"
WHERE_AFTER = (
    f"WHERE e.kind IN ('payment', 'refund') AND e.status = 'validated' AND {MOVE} IS NOT TRUE\n"
)


def income(moves: bool) -> str:
    """0087's view; with `moves`, without the entries of a payment moved."""
    sql: str = MISTAKE.income(corrections=True)
    if moves:
        assert sql.count(WHERE_BEFORE) == 1, WHERE_BEFORE
        sql = sql.replace(WHERE_BEFORE, WHERE_AFTER)
    return sql


COMMENT_AFTER = (
    MISTAKE.COMMENT_AFTER + " A payment moved to another period (purpose move) is in none"
    " of it: its money was counted when first paid."
)

MOVE_CHECK = """
    CHECK (purpose IS DISTINCT FROM 'move' OR (
        extra_line_id IS NULL AND billing_period_id IS NOT NULL
        AND CASE kind
            WHEN 'payment' THEN refund_of IS NULL
            WHEN 'refund' THEN corrects = refund_of
        END
    ))
"""

# At commit, so the pair's two inserts are both in: what moved in of the payment equals
# what moved out of it. Checked per payment, so two moves of one payment add up too.
MOVE_PAIR = """
    CREATE FUNCTION ledger_entry_move_pair() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF (
            SELECT coalesce(sum(CASE WHEN m.kind = 'payment' THEN m.amount_clp
                                     ELSE -m.amount_clp END), 0)
            FROM ledger_entry m WHERE m.corrects = NEW.corrects AND m.purpose = 'move'
        ) <> 0 THEN
            RAISE EXCEPTION 'move of %: what moved in is not what moved out', NEW.corrects
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ledger_entry_move_pair';
        END IF;
        RETURN NULL;
    END
    $$
"""

STAFF_CHECK = "        IF EXISTS (SELECT FROM staff WHERE gym_id = gym AND person_id = $1)\n"
MOVED_CHECK = f"""        -- A payment of theirs moved to someone else (a sibling, #280): that entry
        -- names theirs, and neither can change or go.
        IF EXISTS (
            SELECT FROM ledger_entry o
            WHERE o.purpose = 'move' AND o.corrects IN (SELECT e.id FROM ({FORGET.THEIR_ENTRIES}) e)
              AND o.id NOT IN (SELECT e.id FROM ({FORGET.THEIR_ENTRIES}) e)
        ) THEN
            RETURN 'moved';
        END IF;
"""


def forget_refusal(moves: bool) -> str:
    """0044's function; with `moves`, refusing someone a payment of whom moved to
    another person."""
    sql: str = FORGET.FORGET_REFUSAL
    if moves:
        assert sql.count(STAFF_CHECK) == 1, STAFF_CHECK
        sql = sql.replace(STAFF_CHECK, MOVED_CHECK + STAFF_CHECK)
    return sql


def upgrade() -> None:
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {income(moves=True)}")
    op.execute(MISTAKE.comment(COMMENT_AFTER))
    op.execute(f"ALTER TABLE ledger_entry ADD CONSTRAINT ledger_entry_move {MOVE_CHECK}")
    op.execute(MOVE_PAIR)
    op.execute(
        "CREATE CONSTRAINT TRIGGER ledger_entry_move_pair AFTER INSERT ON ledger_entry"
        " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.purpose = 'move')"
        " EXECUTE FUNCTION ledger_entry_move_pair()"
    )
    op.execute(forget_refusal(moves=True))


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_entry NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM ledger_entry WHERE purpose = 'move') THEN
                RAISE EXCEPTION 'the ledger holds payments moved, which 0088 reports as refunds'
                    USING HINT = 'entries cannot be deleted: stay on 0089';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY")
    op.execute(forget_refusal(moves=False))
    op.execute("DROP TRIGGER ledger_entry_move_pair ON ledger_entry")
    op.execute("DROP FUNCTION ledger_entry_move_pair()")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ledger_entry_move")
    op.execute(f"CREATE OR REPLACE VIEW v_monthly_income {OPTIONS} AS {income(moves=False)}")
    op.execute(MISTAKE.comment(MISTAKE.COMMENT_AFTER))
