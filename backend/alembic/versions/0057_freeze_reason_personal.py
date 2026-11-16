"""A freeze request's reason says nothing about health (#384).

Art. 16 bis of Ley 19.628 (as Ley 21.719 rewrites it) forbids processing health data
collected in a sports setting, consent or not, unless a law expressly allows it
(docs/legal-research.md, "Found along the way: health data in a gym"). The short list a
member picked from offered `lesion` and `salud`: a structured record that they are
injured or ill. Both go, for `personal` ("Motivo personal").

- The check on `freeze_request.reason` allows `viaje`, `personal` and `otro`.
- Requests already stored with `lesion` or `salud` become `personal`. Their `note` is
  what the member wrote, and stays.

The freezes an approval wrote keep their text: it is a free-text reason the admin may
have edited since, as any freeze's.

A downgrade restores the old check and makes a `personal` request `otro`, which needs a
note: one without keeps "Motivo personal" as its note. It does not bring back `lesion`
or `salud`, which were never recorded apart.

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE freeze_request DROP CONSTRAINT freeze_request_reason_check")
    # Every gym's requests, past the policy that holds even the owner to one gym (0045).
    op.execute("ALTER TABLE freeze_request NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE freeze_request SET reason = 'personal' WHERE reason IN ('lesion', 'salud')")
    op.execute("ALTER TABLE freeze_request FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE freeze_request ADD CONSTRAINT freeze_request_reason_check"
        " CHECK (reason IN ('viaje', 'personal', 'otro'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE freeze_request DROP CONSTRAINT freeze_request_reason_check")
    op.execute("ALTER TABLE freeze_request NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE freeze_request SET reason = 'otro', note = COALESCE(note, 'Motivo personal')"
        " WHERE reason = 'personal'"
    )
    op.execute("ALTER TABLE freeze_request FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE freeze_request ADD CONSTRAINT freeze_request_reason_check"
        " CHECK (reason IN ('lesion', 'viaje', 'salud', 'otro'))"
    )
