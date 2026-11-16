"""Registro de consentimiento: who accepted which notice when, past approval (#370).

The join form's consent used to live on `join_request.consented_at`, which approving
deletes with the request, and no notice version was ever stored. The owner's decision
(docs/legal-research.md, row 1): an adult's data rests on the membership contract, and
every member under 18 needs their guardian's consent, as an act of its own that the
guardian may refuse or withdraw without losing the membership.

- `consent_event`, one row per act, never changed or deleted but with the person:
  - `notice_accepted`: the join form's box, ticked by the person or, for a minor, by
    their guardian. Evidence the notice was shown; not consent.
  - `consent_given` and `consent_withdrawn`: a guardian's consent to the processing of
    a minor's data, from the join form or the guardian's own page. The latest by `at`
    stands.
  - `by_person_id` is who acted: the person themselves, or their guardian in this gym,
    which the insert policy holds (`guardian_link`). It references `person`, not
    `gym_person`, so a guardian who leaves this gym later does not hold the row up.
  - The notice's version is the two dates its "last updated" is the later of: the
    template's (`template_on`, `TEMPLATE_UPDATED_ON`) and the gym's details'
    (`details_on`, `settings.privacy.updated_on`). A withdrawal names none, and a
    `notice_accepted` carried from a request sent before this migration has none.
  - `source`: `join`, the form, at the time it was sent; `page`, the guardian's page.
- `join_request` keeps what the form sent: the version, and the guardian's own box,
  `guardian_consent`, apart from the notice's.
- `forget_gym_person` deletes the person's rows with the rest.

`rakin_app` may read and add rows, never change or delete them.

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-16

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"

# Who may act for the person: themselves, for the notice, or their guardian here.
BY_WHOM = """(
    (action = 'notice_accepted' AND by_person_id = person_id)
    OR EXISTS (
        SELECT FROM guardian_link gl
        WHERE gl.gym_id = consent_event.gym_id
          AND gl.dependent_person_id = consent_event.person_id
          AND gl.guardian_person_id = consent_event.by_person_id
    )
)"""

DELETE_BEFORE = "        DELETE FROM gym_person WHERE gym_id = gym AND person_id = $1;"
DELETE_AFTER = (
    "        DELETE FROM consent_event WHERE gym_id = gym AND person_id = $1;\n" + DELETE_BEFORE
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forget_gym_person(consent: bool) -> str:
    """0055's function, replacing itself; with `consent`, it deletes the person's
    consent rows."""
    sql: str = _migration("0055_history_payment.py").forget_gym_person(payments=True)
    if consent:
        assert sql.count(DELETE_BEFORE) == 1, DELETE_BEFORE
        sql = sql.replace(DELETE_BEFORE, DELETE_AFTER)
    return sql


def upgrade() -> None:
    op.execute(
        "ALTER TABLE join_request ADD COLUMN notice_template_on date,"
        " ADD COLUMN notice_details_on date,"
        " ADD COLUMN guardian_consent boolean NOT NULL DEFAULT false"
    )
    op.execute("""
        CREATE TABLE consent_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            gym_id uuid NOT NULL,
            person_id uuid NOT NULL,
            action text NOT NULL
                CHECK (action IN ('notice_accepted', 'consent_given', 'consent_withdrawn')),
            by_person_id uuid NOT NULL REFERENCES person (id),
            source text NOT NULL CHECK (source IN ('join', 'page')),
            template_on date,
            details_on date,
            at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT consent_event_version CHECK ((template_on IS NULL) = (details_on IS NULL)),
            CONSTRAINT consent_event_given_names_version CHECK (
                action <> 'consent_given' OR template_on IS NOT NULL),
            CONSTRAINT consent_event_withdrawn_names_none CHECK (
                action <> 'consent_withdrawn' OR template_on IS NULL),
            FOREIGN KEY (gym_id, person_id) REFERENCES gym_person (gym_id, person_id)
        )
    """)
    op.execute("CREATE INDEX consent_event_person ON consent_event (gym_id, person_id, at)")
    op.execute(f"GRANT SELECT, INSERT ON consent_event TO {APP_ROLE}")
    op.execute("ALTER TABLE consent_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE consent_event FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY consent_event_isolation ON consent_event"
        f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM} AND {BY_WHOM})"
    )
    op.execute(forget_gym_person(consent=True))


def downgrade() -> None:
    op.execute(forget_gym_person(consent=False))
    op.execute("DROP TABLE consent_event")
    op.execute(
        "ALTER TABLE join_request DROP COLUMN notice_template_on,"
        " DROP COLUMN notice_details_on, DROP COLUMN guardian_consent"
    )
