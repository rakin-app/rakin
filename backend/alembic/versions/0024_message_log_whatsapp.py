"""`message_log` records WhatsApp messages too.

A `wa.me` link (`app.integrations.messenger`) is sent by the admin from their own phone,
so Rakin never learns whether it went: the row is written when the admin opens the
link from one of their lists, and `sent` means just that. `to_address` is the phone it
was addressed to, E.164 as on `person.phone`. The first is the inactive nudge (#50).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _channels(channels: str) -> None:
    op.execute("ALTER TABLE message_log DROP CONSTRAINT message_log_channel_check")
    op.execute(
        "ALTER TABLE message_log ADD CONSTRAINT message_log_channel_check"
        f" CHECK (channel IN ({channels}))"
    )


def upgrade() -> None:
    _channels("'email', 'whatsapp'")


def downgrade() -> None:
    # The rows of a channel that would no longer exist go with it.
    op.execute("DELETE FROM message_log WHERE channel = 'whatsapp'")
    _channels("'email'")
