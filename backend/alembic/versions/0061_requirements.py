"""Requisitos para entrenar: what the gym asks before someone trains, and when each was done (#349).

A climbing gym lets nobody climb before the safety induction and a signed waiver; a
rowing club needs a current medical certificate (docs/design/sport-fit.md, sections 1
and 5). Two tables:

- `requirement`, the gym's list: a name, `valid_months` (null for a requirement done
  once, else how long one lasts), `sensitive` and `visible_to` as a custom field has
  them (`app.domain.custom_fields`), `active` (a requirement is deactivated, never
  deleted, since people's records point at it) and `position`, the order the ficha
  shows them in.
- `person_requirement`, one row per time it was recorded for a person: the day it was
  done (`done_on`), a note, who recorded it and when. A record is never changed or
  deleted: a new one takes the place of the previous as the person's current one (the
  latest `recorded_at`), which stays. A sensitive requirement's note is stored sealed in
  `note_secret` and never in `note`, as a sensitive field's value is; `rakin_app` may
  change those two columns alone, to seal or open the notes when the owner marks the
  requirement sensitive or not.

Both are gym-keyed, as attendance is: a record's requirement and person are the gym's
by their foreign keys. RLS as every tenant table, and a record is inserted as the one
who records it (`recorded_by`). `forget_gym_person` deletes the person's records with
the rest.

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-16

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

DELETE_BEFORE = "        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;"
DELETE_AFTER = (
    "        DELETE FROM person_requirement WHERE gym_id = gym AND person_id = $1;\n"
    + DELETE_BEFORE
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(requirements: bool) -> str:
    """0058's function, replacing itself; with `requirements`, it deletes the person's
    requirement records."""
    sql: str = _migration("0058_consent_register.py").forget_gym_person(consent=True)
    if requirements:
        assert sql.count(DELETE_BEFORE) == 1, DELETE_BEFORE
        sql = sql.replace(DELETE_BEFORE, DELETE_AFTER)
    return sql


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table}"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE requirement (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
            valid_months integer CHECK (valid_months BETWEEN 1 AND 120),
            sensitive boolean NOT NULL DEFAULT false,
            visible_to text NOT NULL DEFAULT 'staff'
                CHECK (visible_to IN ('owner', 'admin', 'staff')),
            active boolean NOT NULL DEFAULT true,
            position integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, id)
        )
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON requirement TO {APP_ROLE}")
    _isolate("requirement")

    op.execute("""
        CREATE TABLE person_requirement (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL,
            person_id uuid NOT NULL,
            requirement_id uuid NOT NULL,
            done_on date NOT NULL,
            note text CHECK (char_length(note) BETWEEN 1 AND 500),
            note_secret bytea,
            recorded_by uuid NOT NULL REFERENCES person (id),
            recorded_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT person_requirement_one_note CHECK (note IS NULL OR note_secret IS NULL),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id),
            FOREIGN KEY (gym_id, requirement_id) REFERENCES requirement (gym_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX person_requirement_current"
        " ON person_requirement (gym_id, person_id, requirement_id, recorded_at)"
    )
    op.execute(f"GRANT SELECT, INSERT ON person_requirement TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (note, note_secret) ON person_requirement TO {APP_ROLE}")
    _isolate("person_requirement")
    op.execute(
        "CREATE POLICY person_requirement_recorded_by ON person_requirement AS RESTRICTIVE"
        f" FOR INSERT TO {APP_ROLE} WITH CHECK (recorded_by = {CURRENT_PERSON})"
    )
    op.execute(forget_gym_person(requirements=True))


def downgrade() -> None:
    op.execute(forget_gym_person(requirements=False))
    op.execute("DROP TABLE person_requirement")
    op.execute("DROP TABLE requirement")
