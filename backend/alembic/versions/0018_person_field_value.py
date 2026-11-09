"""`person_field_value`: a gym's custom-field values, one row per person and field.

The definitions live in `gym.settings.custom_fields` (#20); a row here holds what one
gym recorded for one person under one field's `field_key`. It references the gym's
record of the person, `gym_person`, and is isolated by `gym_id` like every tenant table.

A plain value is `value`, as JSON. A field flagged `sensitive` keeps its value in
`secret` instead, encrypted by the API (`app.domain.custom_fields`), so the database
and its backups never hold it in the clear. Exactly one of the two is set.

Who may see a field (`visible_to`) is decided by the API from the definition; RLS here
keeps rows to the current gym.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE person_field_value (
            gym_id uuid NOT NULL,
            person_id uuid NOT NULL,
            field_key text NOT NULL CHECK (btrim(field_key) <> ''),
            value jsonb,
            secret bytea,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gym_id, person_id, field_key),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id),
            CHECK ((value IS NULL) <> (secret IS NULL))
        )
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON person_field_value TO {APP_ROLE}")
    op.execute("ALTER TABLE person_field_value ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE person_field_value FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY person_field_value_isolation ON person_field_value"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE person_field_value")
