"""A grade belongs to the person, not a membership (#296).

The fourth of the historical-data tickets (docs/design/historical-data.md, section 2,
"Grades by person"). A belt earned before Rakin, or by a former student with no plan
here, is a real grade, but 0018 hung every grade off a membership, so someone with none
could hold none.

- `grade_event.person_id`, backfilled from the grade's membership, then `NOT NULL`. A
  person's ranks are read by it from now on, not through `membership`.
- `membership_id` becomes nullable: a grade recorded with no plan has none. When it has
  one, the membership is the person's, by a foreign key on `(gym_id, membership_id,
  person_id)` against a new unique key on `membership`.
- `source` says how the grade came in: `app`, awarded in Rakin (every row so far, and the
  default); `manual`, typed in as history ("Agregar historial", "Grado anterior");
  `import`, from a spreadsheet. `import_id` names the import, on an `import` row only;
  #297 owns its table and the foreign key to it.
  A history grade writes no `promoted` plan event (`app.api.grades`).
- `forget_gym_person` deletes the person's grades by `person_id`, so those with no
  membership go too.

A downgrade refuses while any grade has no membership, which 0052 has no place for.

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

SOURCES = ("app", "manual", "import")

# 0051's `forget_gym_person`, whose grades this one deletes by person.
GRADES_BEFORE = (
    "DELETE FROM grade_event WHERE membership_id IN"
    " (SELECT id FROM membership WHERE gym_id = gym AND person_id = $1);"
)
GRADES_AFTER = "DELETE FROM grade_event WHERE gym_id = gym AND person_id = $1;"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(by_person: bool) -> str:
    """0051's function, replacing itself; with `by_person`, it deletes the person's grades
    by `person_id`."""
    sql: str = _migration("0051_person_history.py").forget_gym_person(history=True)
    if by_person:
        assert sql.count(GRADES_BEFORE) == 1, GRADES_BEFORE
        sql = sql.replace(GRADES_BEFORE, GRADES_AFTER)
    return sql


def upgrade() -> None:
    listed = ", ".join(f"'{s}'" for s in SOURCES)
    op.execute(
        "ALTER TABLE grade_event ADD COLUMN person_id uuid REFERENCES person (id),"
        " ADD COLUMN source text NOT NULL DEFAULT 'app'"
        f" CONSTRAINT grade_event_source CHECK (source IN ({listed})),"
        " ADD COLUMN import_id uuid,"
        " ADD CONSTRAINT grade_event_import CHECK (import_id IS NULL OR source = 'import')"
    )
    # Every gym's grades, past the policy that holds even the owner to one gym (0018).
    op.execute("ALTER TABLE grade_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        UPDATE grade_event ge SET person_id = m.person_id
        FROM membership m WHERE m.id = ge.membership_id
    """)
    op.execute("ALTER TABLE membership FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE grade_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE grade_event ALTER COLUMN person_id SET NOT NULL")

    op.execute(
        "ALTER TABLE membership ADD CONSTRAINT membership_gym_id_id_person_id_key"
        " UNIQUE (gym_id, id, person_id)"
    )
    op.execute("ALTER TABLE grade_event ALTER COLUMN membership_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE grade_event ADD CONSTRAINT grade_event_persons_membership
            FOREIGN KEY (gym_id, membership_id, person_id)
            REFERENCES membership (gym_id, id, person_id)
    """)
    op.execute(
        "CREATE INDEX grade_event_person_idx"
        " ON grade_event (person_id, awarded_on DESC, created_at DESC)"
    )
    op.execute(forget_gym_person(by_person=True))


def downgrade() -> None:
    op.execute("ALTER TABLE grade_event NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM grade_event WHERE membership_id IS NULL) THEN
                RAISE EXCEPTION 'grades with no membership, which 0052 has no place for'
                    USING HINT = 'grades cannot be deleted: stay on 0053';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE grade_event FORCE ROW LEVEL SECURITY")
    op.execute(forget_gym_person(by_person=False))
    op.execute("DROP INDEX grade_event_person_idx")
    op.execute("ALTER TABLE grade_event DROP CONSTRAINT grade_event_persons_membership")
    op.execute("ALTER TABLE grade_event ALTER COLUMN membership_id SET NOT NULL")
    op.execute("ALTER TABLE membership DROP CONSTRAINT membership_gym_id_id_person_id_key")
    op.execute(
        "ALTER TABLE grade_event DROP COLUMN import_id, DROP COLUMN source, DROP COLUMN person_id"
    )
