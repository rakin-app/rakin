"""Open access: a class type people come to when they want, and its session of the day (#348).

A climbing gym is open from 7:00 to 23:00 with no classes. Its visits are attendance
like any other, at a session of a class type of the third kind, `open_access`
(`class_type.kind`, which 0028 held to `class` and `open_mat`). Such a type has no
timer blocks and, by the API's default, counts as a class.

Nothing schedules its sessions: the first check-in of a day makes that day's, and
`session.open_day` is the gym-local date it is for, null on every other session. One
per open-access type per day is the unique index below, so two first check-ins at once
make one session between them: the second insert does nothing and reads the first's.

A downgrade makes every open-access type a class and drops `open_day`; its sessions
and their attendance stay, as classes.

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE class_type DROP CONSTRAINT class_type_kind_check")
    op.execute(
        "ALTER TABLE class_type ADD CONSTRAINT class_type_kind_check"
        " CHECK (kind IN ('class', 'open_mat', 'open_access'))"
    )
    op.execute("ALTER TABLE session ADD COLUMN open_day date")
    op.execute(
        "CREATE UNIQUE INDEX session_open_day_key ON session (class_type_id, open_day)"
        " WHERE open_day IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE session DROP COLUMN open_day")
    # Every gym's, so past RLS for this statement alone.
    op.execute("ALTER TABLE class_type NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE class_type SET kind = 'class' WHERE kind = 'open_access'")
    op.execute("ALTER TABLE class_type FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE class_type DROP CONSTRAINT class_type_kind_check")
    op.execute(
        "ALTER TABLE class_type ADD CONSTRAINT class_type_kind_check"
        " CHECK (kind IN ('class', 'open_mat'))"
    )
