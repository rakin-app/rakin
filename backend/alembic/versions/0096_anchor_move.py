"""Día de cobro: a plan's anchor changed reaches the members already on it (#547).

A monthly plan's `anchor` (0007) was copied into `membership.anchor_day` as a membership
started, and a later change of the plan's reached only the members who joined after.
Now the owner may move the members on the plan to the new day as they save it:

- `membership.next_anchor_day`: the anchor day it moves to from its first period not
  billed, null with no move pending. That period runs to the day before the new day,
  prorated (`app.domain.billing.transition_period`), and billing then moves
  `anchor_day` to it and clears this. A plan change reaching that period replaces it.
- `audit_event` takes `anchor_changed`, one row per membership moved, with the anchor
  day before and after and the first day billed on the new one, which the ficha's
  "Correcciones" lists. Someone holding `money_write` writes it, as themselves, now,
  about one of the gym's people, under a policy of its own as the discount's (0066).

A downgrade drops the column and the rows of the action.

Revision ID: 0096
Revises: 0095
Create Date: 2026-11-22

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0096"
down_revision: str | Sequence[str] | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

CHANGED = "anchor_changed"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0067 = _migration("0067_rls_by_permission.py")
M0088 = _migration("0088_study_material.py")

# As 0066's discount row: someone holding `money_write`, as themselves, now, about one of
# the gym's people.
ANCHOR_INSERT = (
    f"(gym_id = {CURRENT_GYM} AND actor_id = {CURRENT_PERSON} AND at = now()"
    f" AND action = '{CHANGED}' AND {M0067.can('money_write')}"
    f" AND EXISTS (SELECT FROM gym_person gp WHERE gp.gym_id = {CURRENT_GYM}"
    " AND gp.person_id = audit_event.person_id))"
)


def _constraint(changed: bool) -> None:
    """0088's actions, with `anchor_changed` or without; it names a person."""
    if not changed:
        M0088._constraints(material=True)
        return
    actions = (
        *M0088.M0071._actions(team=True),
        *M0088.M0083.EXPENSE_ACTIONS,
        *M0088.MATERIAL_ACTIONS,
        CHANGED,
    )
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {M0088._in(actions)})"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE membership ADD COLUMN next_anchor_day smallint"
        " CHECK (next_anchor_day BETWEEN 1 AND 31)"
    )
    _constraint(changed=True)
    op.execute(
        f"CREATE POLICY audit_event_anchor ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {ANCHOR_INSERT}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_anchor ON audit_event")
    # The rows go with their action, past the trigger that keeps the log append-only
    # (0048), and the policy that holds even the owner to one gym (0044).
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action = '{CHANGED}'")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    _constraint(changed=False)
    op.execute("ALTER TABLE membership DROP COLUMN next_anchor_day")
