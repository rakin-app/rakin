"""Términos de encargo: which version of the processor terms each gym signed, and when (#367).

Hosting makes the company each gym's processor, and art. 15 bis asks for a written
contract: `docs/legal/terminos-de-encargo.md`. The gym signs it before its data goes
in, and again whenever the terms change, as a new subprocessor in Anexo A does.

- `processor_terms`, one row per signature, never changed: `version` is the terms'
  "Versión" line (`app.gyms.PROCESSOR_TERMS_VERSION`), `signed_on` the date on the
  signed copy, `recorded_at` when `app.gyms` wrote it. The latest by `signed_on` is the
  one in force. The signed copy itself is kept with the company's records, not here.
- `rakin_app` gets nothing: only `app.gyms`, as the table owner, writes or reads it.

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-18

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075"
down_revision: str | Sequence[str] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE processor_terms (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            version text NOT NULL CHECK (version ~ '^\\d{4}-\\d{2}-\\d{2}$'),
            signed_on date NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gym_id, version)
        )
    """)
    op.execute("ALTER TABLE processor_terms ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE processor_terms FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY processor_terms_isolation ON processor_terms"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE processor_terms")
