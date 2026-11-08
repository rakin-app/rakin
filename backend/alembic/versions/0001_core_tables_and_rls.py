"""Core tables and RLS policies.

Roles are not created here: `python -m app.db_bootstrap` creates the owner that runs
this migration and the `rakin_app` role it grants to, so the owner needs no
superuser or CREATEROLE.

RLS is FORCEd, so it applies to the table owner too, not only to `rakin_app`. A
backfill, seed or one-off script run with the owner's credentials therefore sees and
writes only the gym in `app.gym_id`, the same as the API: a missed `SET` returns
nothing there as well. Cross-gym work (the nightly jobs, a gym switcher) sets
`app.gym_id` per gym, or goes through a `SECURITY DEFINER` function written for it.
Only a superuser skips RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The role the API's login user is a member of. It owns nothing and never bypasses
# RLS; the role running this migration owns the tables.
APP_ROLE = "rakin_app"

# Tables isolated by `gym_id` (and `gym`, isolated by its own id).
TENANT_TABLES = ("staff", "plan", "membership", "billing_period", "ledger_entry")

# Every table here, listed so grants never reach `alembic_version`.
APP_TABLES = ("person", "gym", *TENANT_TABLES, "job_run")

# An unset or empty `app.gym_id` matches no row instead of raising.
CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

TABLES = (
    """
CREATE TABLE person (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Nullable: dependents may have no phone, and deletion anonymises the row.
    phone text UNIQUE CHECK (phone ~ '^\\+[1-9][0-9]{1,14}$'),
    email text,
    name text NOT NULL,
    rut text,
    dob date,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE gym (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    timezone text NOT NULL DEFAULT 'America/Santiago',
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE staff (
    gym_id uuid NOT NULL REFERENCES gym (id),
    person_id uuid NOT NULL REFERENCES person (id),
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'coach')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gym_id, person_id)
)
""",
    """
CREATE TABLE plan (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('monthly', 'prepaid', 'credits', 'dropin', 'trial')),
    price_clp bigint NOT NULL CHECK (price_clp >= 0),
    period_months integer CHECK (period_months > 0),
    credits integer CHECK (credits > 0),
    credit_expiry_days integer CHECK (credit_expiry_days > 0),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (gym_id, id),
    CHECK (kind <> 'prepaid' OR period_months IS NOT NULL),
    CHECK (kind <> 'credits' OR credits IS NOT NULL)
)
""",
    """
CREATE TABLE membership (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    person_id uuid NOT NULL REFERENCES person (id),
    plan_id uuid NOT NULL,
    status text NOT NULL
        CHECK (status IN ('trial', 'active', 'frozen', 'lapsed', 'cancelled')),
    anchor_day smallint CHECK (anchor_day BETWEEN 1 AND 31),
    started_at timestamptz NOT NULL DEFAULT now(),
    current_period_end date,
    credits_remaining integer CHECK (credits_remaining >= 0),
    discount_pct smallint NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (gym_id, id),
    FOREIGN KEY (gym_id, plan_id) REFERENCES plan (gym_id, id)
)
""",
    """
CREATE TABLE billing_period (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    membership_id uuid NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    amount_due_clp bigint NOT NULL CHECK (amount_due_clp >= 0),
    due_date date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (membership_id, id),
    UNIQUE (membership_id, period_start),
    CHECK (period_end >= period_start),
    FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
)
""",
    """
CREATE TABLE ledger_entry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    membership_id uuid NOT NULL,
    billing_period_id uuid,
    amount_clp bigint NOT NULL,
    kind text NOT NULL CHECK (kind IN ('charge', 'payment', 'adjustment', 'refund')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'validated', 'rejected')),
    method text,
    claimed_by uuid REFERENCES person (id),
    claimed_at timestamptz,
    validated_by uuid REFERENCES person (id),
    validated_at timestamptz,
    proof_object_key text,
    bank_tx_ref text,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id),
    FOREIGN KEY (membership_id, billing_period_id) REFERENCES billing_period (membership_id, id)
)
""",
    """
CREATE TABLE job_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name text NOT NULL,
    run_date date NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (job_name, run_date)
)
""",
)


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'role {APP_ROLE} does not exist; run python -m app.db_bootstrap';
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}'
                       AND (rolsuper OR rolbypassrls)) THEN
                RAISE EXCEPTION 'role {APP_ROLE} must not be a superuser or bypass RLS';
            END IF;
        END
        $$
    """)

    # asyncpg runs one statement per call.
    for statement in TABLES:
        op.execute(statement)

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    tables = ", ".join(APP_TABLES)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {tables} TO {APP_ROLE}")
    op.execute(f"GRANT DELETE ON staff TO {APP_ROLE}")

    for table in ("gym", *TENANT_TABLES):
        column = "id" if table == "gym" else "gym_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_isolation ON {table}"
            f" USING ({column} = {CURRENT_GYM}) WITH CHECK ({column} = {CURRENT_GYM})"
        )


def downgrade() -> None:
    # Roles belong to db_bootstrap, not to this migration: they stay.
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(
        "DROP TABLE job_run, ledger_entry, billing_period, membership, plan, staff, gym, person"
    )
