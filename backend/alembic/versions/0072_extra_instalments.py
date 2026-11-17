"""Cuotas: a Cobro extra paid in instalments (#356).

A rowing club charges a regatta's travel in two or three instalments. A cobro may now
be split into N of them (2 to 12), monthly from its first due date: each person's line
becomes N lines, one per instalment, each with its own due date, paid, proved,
reminded and corrected on its own as any line is.

- `extra_charge.instalments`: how many, 1 for a cobro paid at once, as every cobro
  here so far. `due_date` stays the first instalment's.
- `extra_line.instalment`: which of them the line is, from 1; and
  `extra_line.due_date`, its own, which every line here takes from its cobro.
- A person has one line per instalment, so the cobro's `(extra_charge_id, person_id)`
  uniqueness takes the instalment too.

A downgrade refuses while any cobro is in instalments: its lines would collide.

Revision ID: 0072
Revises: 0071
Create Date: 2026-11-17

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_INSTALMENTS = 12

TABLES = ("extra_charge", "extra_line")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE extra_charge ADD COLUMN instalments smallint NOT NULL DEFAULT 1"
        f" CHECK (instalments BETWEEN 1 AND {MAX_INSTALMENTS})"
    )
    op.execute("ALTER TABLE extra_line ADD COLUMN instalment smallint NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE extra_line ADD COLUMN due_date date")
    # Every gym's lines, past the policies that hold even the owner to one (0037).
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE extra_line l SET due_date = x.due_date FROM extra_charge x"
        " WHERE x.id = l.extra_charge_id"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extra_line ALTER COLUMN due_date SET NOT NULL")
    op.execute(
        "ALTER TABLE extra_line ADD CONSTRAINT extra_line_instalment"
        f" CHECK (instalment BETWEEN 1 AND {MAX_INSTALMENTS})"
    )
    op.execute("ALTER TABLE extra_line DROP CONSTRAINT extra_line_extra_charge_id_person_id_key")
    op.execute(
        "ALTER TABLE extra_line ADD CONSTRAINT extra_line_person_instalment"
        " UNIQUE (extra_charge_id, person_id, instalment)"
    )


def downgrade() -> None:
    # Any gym's cobro, as the upgrade's backfill reads every gym's.
    op.execute("ALTER TABLE extra_charge NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM extra_charge WHERE instalments > 1) THEN
                RAISE EXCEPTION 'a cobro is in instalments: its lines would collide';
            END IF;
        END $$
    """)
    op.execute("ALTER TABLE extra_charge FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extra_line DROP CONSTRAINT extra_line_person_instalment")
    op.execute(
        "ALTER TABLE extra_line ADD CONSTRAINT extra_line_extra_charge_id_person_id_key"
        " UNIQUE (extra_charge_id, person_id)"
    )
    op.execute("ALTER TABLE extra_line DROP CONSTRAINT extra_line_instalment")
    op.execute("ALTER TABLE extra_line DROP COLUMN due_date")
    op.execute("ALTER TABLE extra_line DROP COLUMN instalment")
    op.execute("ALTER TABLE extra_charge DROP COLUMN instalments")
