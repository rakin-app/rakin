"""Resumen del mes keeps each closed month's figures, as numbers only (#506).

#505's page counts a month from `message_log`, `ledger_entry` and `attendance`. #378
will purge `message_log.payload`, and with it the `billing_period_id` and `about` keys
those counts read, and `v_overdue` only knows today. So once a month has closed, the
nightly job (`app.jobs.month_summary`) writes what it counted, and the page reads it
from here (docs/design/value-summary.md, sections 1 and 3).

- `gym_month_figure`, one row per gym, month and figure: `month` is its first day,
  `figure` a key of `app.domain.value_summary.Figure`, `value` a count or a sum in
  pesos, `rules_version` the rules it was counted under, `computed_at` when. No
  `person_id` and nothing about anyone: totals of the gym's own data.
- RLS by gym. `rakin_app` reads it under `money_read`, as it reads the ledger (0067),
  and may add rows to its gym's months under the same; nothing changes a row. A month
  is written once: the primary key keeps a figure from being written twice, and a
  trigger refuses an UPDATE from anyone, the owner too. A DELETE is left to the owner,
  for #377's deletion of a gym.

Revision ID: 0082
Revises: 0081
Create Date: 2026-11-21

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# 0067's `access`: a row of the current gym, for someone holding `money_read`.
MONEY_READ = f"(gym_id = {CURRENT_GYM} AND (SELECT app_can('money_read')))"

STATEMENTS = (
    """
CREATE TABLE gym_month_figure (
    gym_id uuid NOT NULL REFERENCES gym (id),
    month date NOT NULL CHECK (extract(day FROM month) = 1),
    figure text NOT NULL CHECK (figure ~ '^[a-z][a-z0-9_]*$'),
    value bigint NOT NULL,
    rules_version smallint NOT NULL CHECK (rules_version > 0),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gym_id, month, figure)
)
""",
    "ALTER TABLE gym_month_figure ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE gym_month_figure FORCE ROW LEVEL SECURITY",
    # The owner, which the nightly job runs as and which runs this, is held to the gym
    # it sets, as for `history_payment` (0055).
    "CREATE POLICY gym_month_figure_isolation ON gym_month_figure TO CURRENT_USER"
    f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})",
    f"CREATE POLICY gym_month_figure_read ON gym_month_figure FOR SELECT TO {APP_ROLE}"
    f" USING {MONEY_READ}",
    f"CREATE POLICY gym_month_figure_insert ON gym_month_figure FOR INSERT TO {APP_ROLE}"
    f" WITH CHECK {MONEY_READ}",
    """
CREATE FUNCTION gym_month_figure_kept()
RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'a month''s figures are written once and never changed'
        USING ERRCODE = 'restrict_violation';
END
$$
""",
    "CREATE TRIGGER gym_month_figure_kept BEFORE UPDATE ON gym_month_figure"
    " FOR EACH ROW EXECUTE FUNCTION gym_month_figure_kept()",
    f"GRANT SELECT, INSERT ON gym_month_figure TO {APP_ROLE}",
)


def upgrade() -> None:
    # asyncpg runs one statement per call.
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE gym_month_figure")
    op.execute("DROP FUNCTION gym_month_figure_kept()")
