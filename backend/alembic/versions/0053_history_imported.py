"""An import's record: `history_imported` in the gym's log (#297).

The fifth of the historical-data tickets (docs/design/historical-data.md, sections 3
and 6). Every import that writes anything records one `audit_event` row: the file's
name and SHA-256, and the counts it wrote. It is about the import, not one person, so
its `person_id` is null, as a deletion's is. Its id is the `import_id` that each
`history_set` row the import writes carries in its `detail`, so a later undo (#300)
finds what the import set.

`rakin_app` inserts it under a policy of its own, beside the corrections' one: the
actor is the person acting, an owner or admin of the current gym, at the transaction's
time, with no person. Nothing changes or deletes it; `forget_gym_person` deletes a
person's rows only, and this one names nobody.

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-15

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

IMPORTED = "history_imported"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraints(imported: bool) -> None:
    m0048 = _migration("0048_correction_audit.py")
    actions: tuple[str, ...] = _migration("0051_person_history.py")._actions(history=True)[0]
    nobody: tuple[str, ...] = ("person_deleted",)
    if imported:
        actions, nobody = (*actions, IMPORTED), (*nobody, IMPORTED)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {m0048._in(actions)}),"
        " DROP CONSTRAINT audit_event_person,"
        " ADD CONSTRAINT audit_event_person CHECK ("
        f"(action IN {m0048._in(nobody)}) = (person_id IS NULL))"
    )


def import_check() -> str:
    """`audit_event_import`'s check."""
    m0048 = _migration("0048_correction_audit.py")
    return (
        f"(gym_id = {m0048.CURRENT_GYM} AND actor_id = {m0048.CURRENT_PERSON}"
        f" AND at = now() AND action = '{IMPORTED}' AND person_id IS NULL"
        f" AND EXISTS (SELECT FROM staff s WHERE s.gym_id = {m0048.CURRENT_GYM}"
        f" AND s.person_id = {m0048.CURRENT_PERSON} AND s.role IN ('owner', 'admin')))"
    )


def upgrade() -> None:
    _constraints(imported=True)
    op.execute(
        f"CREATE POLICY audit_event_import ON audit_event FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {import_check()}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_event_import ON audit_event")
    # The import rows go with their action, past the policy that holds even the owner
    # to one gym (0044) and the trigger that keeps the log append-only (0048).
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM audit_event WHERE action = '{IMPORTED}'")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _constraints(imported=False)
