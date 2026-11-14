"""`freeze_request`: a student, or their guardian, asks for a freeze (#270).

A member asks from their own page for a freeze of an Active membership, with its
dates and why; the owner or an admin approves or rejects it. Approving writes the
freeze the admin would have written (`membership_freeze`, 0017) through the same code,
so this table only records the asking and the answer.

- `requested_by` is who asked: the member, or a guardian for a dependent. `from_date`
  is the first day asked for and `to_date` the day the membership is Active again, as
  a freeze's; the admin may approve other dates, which the freeze holds.
- `reason` is one of a short list (`lesion`, `viaje`, `salud`, `otro`), `note` what
  they wrote besides; `otro` needs one.
- `status` is `pending` until someone decides: `approved` or `rejected` by staff
  (`decided_by`, with an optional `decision_note` on a rejection), or `withdrawn` by
  whoever asked. `decided_at` is set with any of the three. A membership has one
  pending request at most.

A request goes with its membership: when a person is forgotten (0044) the delete of
their memberships cascades to their requests. Isolated by `gym_id` like every tenant
table. `rakin_app` reads, adds and decides requests, and never deletes one.

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-13

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE freeze_request (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL REFERENCES gym (id),
            membership_id uuid NOT NULL,
            requested_by uuid NOT NULL REFERENCES person (id),
            from_date date NOT NULL,
            to_date date NOT NULL,
            reason text NOT NULL CHECK (reason IN ('lesion', 'viaje', 'salud', 'otro')),
            note text CHECK (length(note) BETWEEN 1 AND 500),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
            decided_by uuid REFERENCES person (id),
            decided_at timestamptz,
            decision_note text CHECK (length(decision_note) BETWEEN 1 AND 500),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (to_date > from_date),
            CHECK (reason <> 'otro' OR note IS NOT NULL),
            CHECK ((status = 'pending') = (decided_at IS NULL)),
            CHECK (decided_by IS NULL OR status IN ('approved', 'rejected')),
            CHECK (decision_note IS NULL OR status = 'rejected'),
            FOREIGN KEY (gym_id, membership_id) REFERENCES membership (gym_id, id)
                ON DELETE CASCADE
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX freeze_request_one_pending ON freeze_request (membership_id)"
        " WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX freeze_request_membership_idx"
        " ON freeze_request (membership_id, decided_at DESC)"
    )
    op.execute(
        "CREATE INDEX freeze_request_pending_idx ON freeze_request (gym_id, created_at)"
        " WHERE status = 'pending'"
    )

    op.execute(f"GRANT SELECT, INSERT ON freeze_request TO {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE (status, decided_by, decided_at, decision_note) ON freeze_request"
        f" TO {APP_ROLE}"
    )
    op.execute("ALTER TABLE freeze_request ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE freeze_request FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY freeze_request_isolation ON freeze_request"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE freeze_request")
