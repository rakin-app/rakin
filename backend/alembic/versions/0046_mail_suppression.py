"""`mail_suppression`: addresses no mail goes to, from Resend's bounces and complaints (#104).

Resend tells us by webhook (`app.api.webhooks`) when a message hard-bounced or its
recipient marked it as spam. Mailing that address again only hurts `rakin.app`'s
sender reputation, and with it every gym's sign-in links, so it goes here and
`app.notices` sends it nothing more, essential or not: each attempt is recorded as
`suppressed` in `message_log`.

One row per address, lower case with no outer spaces, as sign-in compares them (0029).
`reason` is `bounce` (a permanent one; a transient bounce is not recorded) or
`complaint`, and `detail` what Resend said about it, for the ficha. The first event
for an address is the one kept: a later one is ignored.

An address is not a gym's: one bounce stops every gym's mail to it. So the table has
no `gym_id` and no RLS. The webhook adds rows with no gym set; a gym reads them only
for the addresses on its own records, which it already knows. `rakin_app` may read and
add rows, never change or delete them.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-13

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mail_suppression (
            address text PRIMARY KEY
                CHECK (address = lower(btrim(address)) AND position('@' IN address) > 1),
            reason text NOT NULL CHECK (reason IN ('bounce', 'complaint')),
            detail text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"GRANT SELECT, INSERT ON mail_suppression TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE mail_suppression")
