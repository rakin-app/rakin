"""`message_log` and `mail_unsubscribe`: what was sent to whom, and who asked not to be.

`message_log` records every message the system sends (#52), one row per attempt with
its outcome: `sent` (handed to the mailer), `failed` (refused or not accepted, with the
error), or `suppressed` (a non-essential notice to someone who unsubscribed). `payload`
is what the template was rendered from, less anything secret, such as a magic link's
URL. Rows are history: `rakin_app` may read and add them, never change or delete them.

A gym's notices carry its `gym_id` and are isolated by it like every tenant table. A
sign-in link belongs to no gym (a person may be in several), so its row has none:
`rakin_app` may add one only while no gym is set, and no gym ever reads it.

`mail_unsubscribe` is one row per gym and person who used a notice's one-click
unsubscribe link. It stops that gym's non-essential notices to them; receipts, sign-in
links and the like are essential and still go out.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE message_log (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid REFERENCES gym (id),
            person_id uuid NOT NULL REFERENCES person (id),
            channel text NOT NULL CHECK (channel IN ('email')),
            template text NOT NULL CHECK (btrim(template) <> ''),
            to_address text NOT NULL,
            status text NOT NULL CHECK (status IN ('sent', 'failed', 'suppressed')),
            error text,
            sent_at timestamptz NOT NULL DEFAULT now(),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CHECK ((status = 'failed') = (error IS NOT NULL))
        )
    """)
    op.execute(
        "CREATE INDEX message_log_gym_person_idx ON message_log (gym_id, person_id, sent_at)"
    )

    op.execute(f"GRANT SELECT, INSERT ON message_log TO {APP_ROLE}")
    op.execute("ALTER TABLE message_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE message_log FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY message_log_read ON message_log FOR SELECT USING (gym_id = {CURRENT_GYM})"
    )
    # With no gym set both sides are NULL: a sign-in link's row, and only that.
    op.execute(
        f"CREATE POLICY message_log_add ON message_log FOR INSERT"
        f" WITH CHECK (gym_id IS NOT DISTINCT FROM {CURRENT_GYM})"
    )

    op.execute("""
        CREATE TABLE mail_unsubscribe (
            gym_id uuid NOT NULL,
            person_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gym_id, person_id),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute(f"GRANT SELECT, INSERT ON mail_unsubscribe TO {APP_ROLE}")
    op.execute("ALTER TABLE mail_unsubscribe ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mail_unsubscribe FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY mail_unsubscribe_isolation ON mail_unsubscribe"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE mail_unsubscribe")
    op.execute("DROP TABLE message_log")
