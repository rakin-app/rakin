"""Deshacer importación: undo the history an import wrote, owner only, with a reason (#300).

The last of the historical-data tickets (docs/design/historical-data.md, sections 6 and
8). An import's `history_imported` row (0053) is the `import_id` every history row it
wrote carries, so the undo finds them all by it:

- `import_set(import)`: each field the import set on someone, from its `history_set`
  rows, with the value it found (`before`), the one it wrote (`after`) and the one there
  now (`now`). A field still holding `after` is put back; one changed since is kept.
- `import_undo_counts(import)`: what an undo would remove, for the confirmation: the
  history payments and grades with that `import_id`, the people whose fields go back,
  and the fields kept. Null for an import that is not this gym's.
- `undo_import(import, reason)`, `SECURITY DEFINER` as `forget_gym_person` is, because
  grades are append-only to `rakin_app`: in one transaction it deletes the payments and
  grades with that `import_id` and nothing else, puts the fields back, writes a
  `history_set` row for each person it changed (`undo_of` names the import, so they are
  the person's, and go with them), and one `import_undone` row with the reason and the
  counts. The owner alone, checked here as the API does. It answers `not_found` or
  `undone`, writing nothing, else null.
- `import_undone` names nobody, as `history_imported` does, and an import is undone once:
  a unique index on its `import_id` holds that against two undos at the same moment.

People and memberships the import created stay: they are today's import, which has no
undo.

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-16

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

UNDONE = "import_undone"
IMPORTED = "history_imported"

# The fields an import writes on a person (`app.api.member_import.Writer._history`).
FIELDS = ("member_since", "prior_classes", "left_on", "left_reason")

SET = "import_set(uuid)"
COUNTS = "import_undo_counts(uuid)"
UNDO = "undo_import(uuid, text)"

IMPORT_SET = f"""
    CREATE FUNCTION {SET}
    RETURNS TABLE (person_id uuid, field text, before jsonb, after jsonb, now jsonb)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public
    AS $$
        SELECT a.person_id, f.key, f.value -> 'before', f.value -> 'after', to_jsonb(gp) -> f.key
        FROM audit_event a
        CROSS JOIN LATERAL jsonb_each(a.detail) f
        JOIN gym_person gp ON gp.gym_id = a.gym_id AND gp.person_id = a.person_id
        WHERE a.gym_id = {CURRENT_GYM} AND a.action = 'history_set'
          AND a.detail ->> 'import_id' = $1::text
          AND f.key IN ({", ".join(f"'{f}'" for f in FIELDS)})
    $$
"""

IMPORT_UNDO_COUNTS = f"""
    CREATE FUNCTION {COUNTS} RETURNS jsonb
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public
    AS $$
        SELECT jsonb_build_object(
            'payments', (SELECT count(*) FROM history_payment WHERE import_id = $1),
            'grades', (SELECT count(*) FROM grade_event WHERE import_id = $1),
            'people', (SELECT count(DISTINCT s.person_id) FROM import_set($1) s
                       WHERE s.now = s.after),
            'kept', (SELECT count(*) FROM import_set($1) s WHERE s.now <> s.after)
        )
        WHERE EXISTS (
            SELECT FROM audit_event
            WHERE id = $1 AND gym_id = {CURRENT_GYM} AND action = '{IMPORTED}'
        )
    $$
"""

UNDO_IMPORT = f"""
    CREATE FUNCTION {UNDO} RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        gym uuid := {CURRENT_GYM};
        actor uuid := {CURRENT_PERSON};
        counts jsonb;
        person record;
    BEGIN
        IF gym IS NULL THEN
            RAISE EXCEPTION 'app.gym_id is not set' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NOT EXISTS (
            SELECT FROM staff WHERE gym_id = gym AND person_id = actor AND role = 'owner'
        ) THEN
            RAISE EXCEPTION 'only the owner undoes an import'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF $2 IS NULL OR length(btrim($2)) NOT BETWEEN 1 AND 500 THEN
            RAISE EXCEPTION 'an undo needs a reason' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT FROM audit_event WHERE id = $1 AND gym_id = gym AND action = '{IMPORTED}'
        ) THEN
            RETURN 'not_found';
        END IF;
        IF EXISTS (
            SELECT FROM audit_event
            WHERE gym_id = gym AND action = '{UNDONE}' AND detail ->> 'import_id' = $1::text
        ) THEN
            RETURN 'undone';
        END IF;
        -- Locked before they are read: an edit on the ficha meanwhile waits, rather than
        -- being put back by an undo that read the value before it.
        PERFORM FROM gym_person gp
        WHERE gp.gym_id = gym AND gp.person_id IN (SELECT s.person_id FROM import_set($1) s)
        ORDER BY gp.person_id
        FOR UPDATE;
        counts := import_undo_counts($1);

        FOR person IN
            SELECT s.person_id,
                   jsonb_object_agg(s.field, s.before) AS restored,
                   jsonb_object_agg(s.field, jsonb_build_object(
                       'before', s.after, 'after', s.before)) AS changed
            FROM import_set($1) s
            WHERE s.now = s.after
            GROUP BY s.person_id
        LOOP
            UPDATE gym_person SET
                member_since = CASE WHEN person.restored ? 'member_since'
                    THEN (person.restored ->> 'member_since')::date ELSE member_since END,
                prior_classes = CASE WHEN person.restored ? 'prior_classes'
                    THEN (person.restored ->> 'prior_classes')::integer ELSE prior_classes END,
                left_on = CASE WHEN person.restored ? 'left_on'
                    THEN (person.restored ->> 'left_on')::date ELSE left_on END,
                left_reason = CASE WHEN person.restored ? 'left_reason'
                    THEN person.restored ->> 'left_reason' ELSE left_reason END,
                updated_at = now()
            WHERE gym_id = gym AND person_id = person.person_id;
            INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)
            VALUES (gym, actor, person.person_id, 'history_set',
                    jsonb_build_object('undo_of', $1::text) || person.changed);
        END LOOP;

        DELETE FROM history_payment WHERE gym_id = gym AND import_id = $1;
        DELETE FROM grade_event WHERE gym_id = gym AND import_id = $1;

        INSERT INTO audit_event (gym_id, actor_id, action, reason, detail)
        VALUES (gym, actor, '{UNDONE}', btrim($2),
                jsonb_build_object('import_id', $1::text) || counts);
        RETURN NULL;
    END
    $$
"""


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraints(undone: bool) -> None:
    """0055's actions and 0053's actions that name nobody, with `import_undone` or
    without."""
    m0048 = _migration("0048_correction_audit.py")
    m0055 = _migration("0055_history_payment.py")
    actions: tuple[str, ...] = (
        *_migration("0051_person_history.py")._actions(history=True)[0],
        IMPORTED,
        m0055.REMOVED,
    )
    nobody: tuple[str, ...] = ("person_deleted", IMPORTED)
    if undone:
        actions, nobody = (*actions, UNDONE), (*nobody, UNDONE)
    op.execute(
        "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check,"
        f" ADD CONSTRAINT audit_event_action_check CHECK (action IN {m0048._in(actions)}),"
        " DROP CONSTRAINT audit_event_person,"
        " ADD CONSTRAINT audit_event_person CHECK ("
        f"(action IN {m0048._in(nobody)}) = (person_id IS NULL))"
    )


def upgrade() -> None:
    _constraints(undone=True)
    op.execute(
        "CREATE UNIQUE INDEX audit_event_import_undone ON audit_event ((detail ->> 'import_id'))"
        f" WHERE action = '{UNDONE}'"
    )
    op.execute(
        "CREATE INDEX grade_event_import_idx ON grade_event (import_id) WHERE import_id IS NOT NULL"
    )
    op.execute(IMPORT_SET)
    op.execute(IMPORT_UNDO_COUNTS)
    op.execute(UNDO_IMPORT)
    for function in (SET, COUNTS, UNDO):
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {UNDO}")
    op.execute(f"DROP FUNCTION {COUNTS}")
    op.execute(f"DROP FUNCTION {SET}")
    op.execute("DROP INDEX grade_event_import_idx")
    op.execute("DROP INDEX audit_event_import_undone")
    # The undo rows go with their action, past the policy that holds even the owner to
    # one gym (0044) and the trigger that keeps the log append-only (0048). What they
    # undid stays undone.
    op.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
    op.execute("ALTER TABLE audit_event NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM audit_event WHERE action = '{UNDONE}'")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    _constraints(undone=False)
