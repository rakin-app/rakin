"""Programs and class types: what a gym teaches, to whom, and what a class costs.

A program is one of a gym's groups of students: adults, kids, competition, whatever
the gym calls them (docs/technical.md#domain-model). Each gym keeps its own list, so
`program` is a tenant table rather than a fixed set of values. A program's name is
unique in its gym, case ignored.

A class type is a kind of class the gym holds (Fundamentos, Avanzado, Open mat): it
belongs to one program and costs `credit_cost` credits from a credits membership per
attendance, 0 for a free one. Its name is unique within its program, case ignored, so
the adults and the kids may each have their "Fundamentos". Sessions (#43) will point
at it.

A plan may name the program it is for (`plan.program_id`). That is how a member is in
a program: through the plan of their membership. A plan with none, such as a drop-in
class, puts its members in no program. Attendance does not exist yet (#44), and a
member's program has to be known before they attend, for announcements (#56) and the
member list's filter.

Both reference their program with `gym_id` in the key, so a row cannot name another
gym's program even past RLS. Neither is ever deleted: they are deactivated
(`active = false`), as plans are, since plans, sessions and attendance point at them.
`rakin_app` may read, add and change them, never delete.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def _isolate(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table}"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE program (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX program_name_key ON program (gym_id, lower(name))")
    _isolate("program")

    op.execute("""
        CREATE TABLE class_type (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            program_id uuid NOT NULL,
            name text NOT NULL CHECK (btrim(name) <> ''),
            credit_cost integer NOT NULL DEFAULT 1 CHECK (credit_cost >= 0),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id),
            FOREIGN KEY (gym_id, program_id) REFERENCES program (gym_id, id)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX class_type_name_key ON class_type (gym_id, program_id, lower(name))"
    )
    _isolate("class_type")

    op.execute("ALTER TABLE plan ADD COLUMN program_id uuid")
    op.execute(
        "ALTER TABLE plan ADD CONSTRAINT plan_program_fkey"
        " FOREIGN KEY (gym_id, program_id) REFERENCES program (gym_id, id)"
    )
    op.execute("CREATE INDEX plan_program_idx ON plan (gym_id, program_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE plan DROP COLUMN program_id")
    op.execute("DROP TABLE class_type")
    op.execute("DROP TABLE program")
