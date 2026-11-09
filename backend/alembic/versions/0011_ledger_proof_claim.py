"""A student claims a payment by uploading a transfer proof (#35).

The student, or a guardian for a dependent, PUTs the proof straight to object storage
and then asks the API for a pending payment entry pointing at it. Until now every
write to `ledger_entry` was an owner's or admin's (0006); `ledger_entry_claim` lets
anyone add exactly that entry, and nothing else:

- for a membership whose entries they may read (`ledger_entry_own`, 0010): their own
  or a dependent's;
- a `payment`, `pending`, by `transfer`, claimed by the person acting and validated by
  nobody;
- with a proof under their own prefix, `proofs/<gym_id>/<person_id>/`, which is where
  the API presigns their uploads, so nobody can claim a file someone else uploaded.

Validating or rejecting it stays an owner's or admin's (0006, #36).

One proof backs one entry: `proof_object_key` is unique, so the same upload cannot be
claimed twice, by a double tap or a replayed request.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

# 0010's OWN_LEDGER: the person's own memberships and their dependents'.
OWN_LEDGER = f"""(gym_id = {CURRENT_GYM} AND membership_id IN (
    SELECT m.id FROM membership m
    WHERE m.gym_id = {CURRENT_GYM}
      AND (m.person_id = {CURRENT_PERSON}
           OR m.person_id IN (SELECT g.dependent_person_id FROM guardian_link g
                              WHERE g.gym_id = {CURRENT_GYM}
                                AND g.guardian_person_id = {CURRENT_PERSON}))
))"""

# app.api.proofs.proof_prefix. `starts_with`, not LIKE: a key holds `_`, which LIKE reads
# as a wildcard.
OWN_PROOF = (
    "starts_with(proof_object_key,"
    f" 'proofs/' || {CURRENT_GYM}::text || '/' || {CURRENT_PERSON}::text || '/')"
)

CLAIM = f"""({OWN_LEDGER}
    AND kind = 'payment' AND status = 'pending' AND method = 'transfer'
    AND claimed_by = {CURRENT_PERSON} AND claimed_at IS NOT NULL
    AND validated_by IS NULL AND validated_at IS NULL
    AND {OWN_PROOF})"""


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ledger_entry_proof_object_key ON ledger_entry (proof_object_key)"
        " WHERE proof_object_key IS NOT NULL"
    )
    op.execute(
        f"CREATE POLICY ledger_entry_claim ON ledger_entry FOR INSERT TO {APP_ROLE}"
        f" WITH CHECK {CLAIM}"
    )


def downgrade() -> None:
    op.execute("DROP POLICY ledger_entry_claim ON ledger_entry")
    op.execute("DROP INDEX ledger_entry_proof_object_key")
