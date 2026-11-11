"""Idempotency keys: a double tap records one payment, not two (#201, #203, #204, #208).

The web app sends an `Idempotency-Key` header, fresh for each submission, on every
mutating request. `app.idempotency` claims the key here before the request runs and
stores the answer once it succeeds, so a repeat of the same submission (a double tap,
a retry after a dropped connection) waits for the first and gets its answer back
instead of running again.

A key is scoped to the gym and the person acting: `gym_id` and `person_id` are the
request's tenant, or both NULL for an anonymous request (the join form). `fingerprint`
is the method and path it was claimed for, so a key sent again for another request is
refused. `status_code` is NULL while the first request runs. Only a 2xx answer is
kept: a refused request had no effect, and its key is released so a retry runs.

Rows are kept 24 hours. The middleware deletes its own scope's older rows when it
claims a key, so nothing else needs to sweep them.

RLS: the middleware runs outside the endpoint's transaction, as `rakin_app` with
`app.gym_id` and `app.person_id` set to the request's tenant, or unset for an
anonymous one. Each scope sees only its own keys; `IS NOT DISTINCT FROM` lets the
anonymous scope, NULL and NULL, see the anonymous keys and no others. The owner role
is held to the gym alone, as everywhere.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

OWN_SCOPE = (
    f"(gym_id IS NOT DISTINCT FROM {CURRENT_GYM}"
    f" AND person_id IS NOT DISTINCT FROM {CURRENT_PERSON})"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE idempotency_key (
            gym_id uuid,
            person_id uuid,
            key text NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
            fingerprint text NOT NULL,
            status_code integer,
            content_type text,
            body bytea,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX idempotency_key_scope ON idempotency_key"
        " (gym_id, person_id, key) NULLS NOT DISTINCT"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_key TO {APP_ROLE}")
    op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_key FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY idempotency_key_isolation ON idempotency_key TO CURRENT_USER"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )
    op.execute(
        f"CREATE POLICY idempotency_key_own ON idempotency_key TO {APP_ROLE}"
        f" USING {OWN_SCOPE} WITH CHECK {OWN_SCOPE}"
    )


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_key")
