"""A six-digit code with a sign-in link, for the app installed on an iPhone (#276).

A link from email or WhatsApp opens in Safari, never in the app on the home screen,
and the two keep separate cookies; so the email carries a code to type instead.

- `auth_link.code_hash` is the code's HMAC with the address and site it was sent for
  (`app.magiclink.tokens.CodeHasher`), `NULL` for a link with no code or whose code no
  longer works: a later code for the same person at the same address replaces it, and
  `CODE_TRIES` wrong codes at the address spend it. Spending the link (`used_at`)
  spends its code, and the other way round.
- `auth_link.code_misses` is how many wrong codes were typed at the address while the
  code worked.

`rakin_app` already reads and updates `auth_link`, columns included.

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


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth_link ADD COLUMN code_hash bytea CHECK (octet_length(code_hash) = 32)"
    )
    op.execute("ALTER TABLE auth_link ADD COLUMN code_misses integer NOT NULL DEFAULT 0")
    op.execute(
        "CREATE INDEX auth_link_code_idx ON auth_link (code_hash) WHERE code_hash IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX auth_link_code_email_idx ON auth_link (lower(email))"
        " WHERE code_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE auth_link DROP COLUMN code_misses")
    op.execute("ALTER TABLE auth_link DROP COLUMN code_hash")
