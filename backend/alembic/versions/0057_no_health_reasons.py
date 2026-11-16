"""No health data among the reasons Rakin offers, nor in those it stored (#384).

Art. 16 bis of Ley 19.628 (as Ley 21.719 rewrites it) forbids processing health data
collected in a sports setting, consent or not, unless a law expressly allows it
(docs/legal-research.md, "Found along the way: health data in a gym"). Rakin offered it
itself: `lesion` and `salud` among a freeze request's reasons, and a "Lesión" chip for
why someone left, whose label an approved request also copied into its freeze. Each
becomes "Motivo personal", `personal` for a request:

- `freeze_request.reason`: the check allows `viaje`, `personal` and `otro`; a request
  stored as `lesion` or `salud` becomes `personal`.
- `membership_freeze.reason` that an approval wrote from those labels: "Lesión" or
  "Salud", alone or before ": <note>", becomes "Motivo personal", the note kept.
- `gym_person.left_reason` that is the chip, "Lesión" (any case, with or without the
  accent, trimmed), becomes "Motivo personal".
- `message_log.payload` of a `freeze_requested` email, which kept the label it sent
  staff as `reason`: "Lesión" or "Salud" becomes "Motivo personal", its `note` kept.
- `audit_event.detail` of a `history_set` row (0051), which kept `left_reason` as its
  `before` and `after`: either that is the chip becomes "Motivo personal".

That last is the one exception to the log being append-only (0048), decided for #384:
the log must not keep the health data it cleared everywhere else. The trigger that
refuses an update, `audit_event_append_only`, is disabled for that statement alone and
enabled again in the same transaction; nothing else in the log changes, and the app
still cannot update a row.

What a person wrote stays as written: a request's `note`, the note in a freeze's
reason, a reason typed by hand. Health words there are the gym's to remove; the PR for
#384 lists where such text lives.

Each changed row writes one `health_reason_cleared` row in the gym's log
(`audit_event`), for the person it is about (an email's member, or its recipient once
the member is forgotten), by nobody (`actor_id` null): which table,
row and column, and the value it holds now. Never the value it held, which is the
health data being cleared. The ficha's "Correcciones" leaves them out: they are no
correction of billing.

A downgrade restores the old check, making a `personal` request `otro`, which needs a
note: one without gets "Motivo personal". It deletes the log rows and their action. It
brings back no `lesion`, `salud` or "Lesión": they were never kept.

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

CLEARED = "health_reason_cleared"
NEUTRAL = "Motivo personal"
LOG_REASON = "Dato de salud reemplazado por un motivo neutro (art. 16 bis, #384)"

# Each table changed, its rows, the person each is about, and the new value, with
# `{changed}` the rows to change. One statement each: the update, and its log rows.
REQUESTS = """
    WITH changed AS (
        UPDATE freeze_request SET reason = 'personal'
        WHERE reason IN ('lesion', 'salud')
        RETURNING id, gym_id, membership_id
    )
    INSERT INTO audit_event (gym_id, person_id, action, reason, detail)
    SELECT c.gym_id, m.person_id, '{action}', '{why}',
           jsonb_build_object('table', 'freeze_request', 'id', c.id, 'column', 'reason',
                              'now', 'personal')
    FROM changed c JOIN membership m ON m.id = c.membership_id
"""

# "Lesión" or "Salud", alone or as the label before an approved request's note.
LABEL = "^(Lesión|Salud)(: |$)"
FREEZES = f"""
    WITH changed AS (
        UPDATE membership_freeze
        SET reason = left(regexp_replace(reason, '{LABEL}', '{NEUTRAL}\\2'), 500)
        WHERE reason ~ '{LABEL}'
        RETURNING id, gym_id, membership_id
    )
    INSERT INTO audit_event (gym_id, person_id, action, reason, detail)
    SELECT c.gym_id, m.person_id, '{{action}}', '{{why}}',
           jsonb_build_object('table', 'membership_freeze', 'id', c.id, 'column', 'reason',
                              'now', '{NEUTRAL}')
    FROM changed c JOIN membership m ON m.id = c.membership_id
"""

LEFT = f"""
    WITH changed AS (
        UPDATE gym_person SET left_reason = '{NEUTRAL}'
        WHERE lower(btrim(left_reason)) IN ('lesión', 'lesion')
        RETURNING gym_id, person_id
    )
    INSERT INTO audit_event (gym_id, person_id, action, reason, detail)
    SELECT gym_id, person_id, '{{action}}', '{{why}}',
           jsonb_build_object('table', 'gym_person', 'id', person_id, 'column', 'left_reason',
                              'now', '{NEUTRAL}')
    FROM changed
"""

EMAILS = f"""
    WITH changed AS (
        UPDATE message_log SET payload = payload || '{{{{"reason": "{NEUTRAL}"}}}}'::jsonb
        WHERE template = 'freeze_requested' AND payload ->> 'reason' IN ('Lesión', 'Salud')
        RETURNING id, gym_id, person_id, payload ->> 'member_id' AS member_id
    )
    INSERT INTO audit_event (gym_id, person_id, action, reason, detail)
    SELECT c.gym_id, COALESCE(p.id, c.person_id), '{{action}}', '{{why}}',
           jsonb_build_object('table', 'message_log', 'id', c.id, 'column', 'payload.reason',
                              'now', '{NEUTRAL}')
    FROM changed c LEFT JOIN person p ON p.id = c.member_id::uuid
"""

# The chip, as the left reason above matches it, for a JSON string in a log row; its
# path's braces doubled for the `format` each statement goes through.
CHIP = "lower(btrim({value})) IN ('lesión', 'lesion')"
BEFORE = CHIP.format(value="detail #>> '{{left_reason,before}}'")
AFTER = CHIP.format(value="detail #>> '{{left_reason,after}}'")
HISTORY = f"""
    WITH changed AS (
        UPDATE audit_event
        SET detail = detail || jsonb_build_object('left_reason', (detail -> 'left_reason')
            || CASE WHEN {BEFORE} THEN '{{{{"before": "{NEUTRAL}"}}}}'::jsonb ELSE '{{{{}}}}' END
            || CASE WHEN {AFTER} THEN '{{{{"after": "{NEUTRAL}"}}}}'::jsonb ELSE '{{{{}}}}' END)
        WHERE action = 'history_set' AND ({BEFORE} OR {AFTER})
        RETURNING id, gym_id, person_id
    )
    INSERT INTO audit_event (gym_id, person_id, action, reason, detail)
    SELECT gym_id, person_id, '{{action}}', '{{why}}',
           jsonb_build_object('table', 'audit_event', 'id', id, 'column', 'detail.left_reason',
                              'now', '{NEUTRAL}')
    FROM changed
"""

TABLES = (
    "freeze_request",
    "membership_freeze",
    "gym_person",
    "message_log",
    "person",
    "membership",
    "audit_event",
)


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraints(cleared: bool) -> None:
    """0056's actions, with `health_reason_cleared` or without. It names a person, so
    the actions that name nobody are 0056's."""
    m0048 = _migration("0048_correction_audit.py")
    m0055 = _migration("0055_history_payment.py")
    m0056 = _migration("0056_import_undone.py")
    actions: tuple[str, ...] = (
        *_migration("0051_person_history.py")._actions(history=True)[0],
        m0056.IMPORTED,
        m0055.REMOVED,
        m0056.UNDONE,
    )
    if cleared:
        actions = (*actions, CLEARED)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {m0048._in(actions)})"
    )


def _every_gym(force: bool) -> None:
    """Past the policies that hold even the owner to one gym, or back under them."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} {'' if force else 'NO '}FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _constraints(cleared=True)
    op.execute("ALTER TABLE freeze_request DROP CONSTRAINT freeze_request_reason_check")
    _every_gym(force=False)
    for statement in (REQUESTS, FREEZES, LEFT, EMAILS):
        op.execute(statement.format(action=CLEARED, why=LOG_REASON))
    # The exception to append-only, above: this statement alone.
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(HISTORY.format(action=CLEARED, why=LOG_REASON))
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _every_gym(force=True)
    op.execute(
        "ALTER TABLE freeze_request ADD CONSTRAINT freeze_request_reason_check"
        " CHECK (reason IN ('viaje', 'personal', 'otro'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE freeze_request DROP CONSTRAINT freeze_request_reason_check")
    _every_gym(force=False)
    op.execute(
        f"UPDATE freeze_request SET reason = 'otro', note = COALESCE(note, '{NEUTRAL}')"
        " WHERE reason = 'personal'"
    )
    # The log rows go with their action, past the trigger that keeps the log
    # append-only (0048). What they cleared stays cleared.
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute(f"DELETE FROM audit_event WHERE action = '{CLEARED}'")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _every_gym(force=True)
    op.execute(
        "ALTER TABLE freeze_request ADD CONSTRAINT freeze_request_reason_check"
        " CHECK (reason IN ('lesion', 'viaje', 'salud', 'otro'))"
    )
    _constraints(cleared=False)
