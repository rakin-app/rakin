"""Baja de un gimnasio: a removal the panel schedules, and the deletion that ends it (#377).

The end of service of the Términos de encargo, clause 14 ("Al terminar"), whose numbers
live in `app.platform.removal`:

- `gym.removal_started_at`: when an operator started the gym's removal, only while it
  is suspended; `gym.early_deletion_on`: the date the gym asked in writing for its
  deletion before its export window ends, only with a removal.
- `platform_start_removal`, `platform_cancel_removal` and
  `platform_record_early_deletion`, with a session proved within 10 minutes, as
  suspending asks (0079). Each logs `gym_removal_started`, `gym_removal_cancelled` or
  `gym_early_deletion`, naming the gym by its slug; a call that changes nothing logs
  nothing. Starting one takes the gym's slug, typed again, and refuses an active gym.
- `platform_resume_gym` (0079) refuses a gym with a removal: it is cancelled first.
- `platform_gym` (0081) says when the removal started and the early date.
- `delete_gym(gym, by, files)`: every row with the gym's id, in `TABLES`' order (each before
  any it references), then the gym, then each of its people no other gym knows, and
  their sign-in links. Only the owner runs it (`python -m app.gyms delete`), and only
  for a gym whose removal started; which day it may is `app.platform.removal`'s rule,
  which the command applies. It logs `gym_deleted` in `platform_event`, the
  platform's own log, which keeps the gym's id and slug and nothing about its people:
  who ran it, how many rows of each table went, how many of its people, and `files`,
  the count of its files the command deleted first. It returns that detail.
- The append-only tables (`ledger_entry`, `audit_event`, `plan`, `terms_acceptance`)
  let a row go only when `app.forget_gym` names its gym and that gym's removal has
  started: the same opening `app.forget_person` is for one person (0032). The API's
  role has no DELETE on any of them, so it cannot use it.
- `gym_people_elsewhere(gym)`, owned by `rakin_auth`, which reads across gyms: the
  gym's people another gym also has. `person_forget` lets the owner delete a person
  while `app.person_forget` is on, as `person_claim` (0036) lets it update one.

A downgrade refuses while a gym has a removal started, and drops all of it.

Revision ID: 0094
Revises: 0093
Create Date: 2026-11-22

"""

import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from alembic import op

revision: str = "0094"
down_revision: str | Sequence[str] | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"
PLATFORM_ROLE = "rakin_platform"

# How recent a proof starting, cancelling and dating a removal ask for, as suspending.
FRESH = "10 minutes"

OLD_ACTIONS = (
    "operator_granted",
    "operator_revoked",
    "operator_signed_in",
    "operator_signed_out",
    "gym_created",
    "owner_link_sent",
    "owner_link_failed",
    "gym_edited",
    "terms_recorded",
    "gym_renamed",
    "gym_suspended",
    "gym_resumed",
    "terms_invite_sent",
    "terms_invite_failed",
)
NEW_ACTIONS = ("gym_removal_started", "gym_removal_cancelled", "gym_early_deletion", "gym_deleted")

# Every table with a `gym_id` but `platform_event`, each before any it references, so
# a plain DELETE of each in turn breaks no foreign key. `tests/test_gym_removal.py`
# fails when a table with a `gym_id` is missing here: a migration that adds one makes
# `delete_gym` again with it.
TABLES = (
    "attendance",
    "auth_session",
    "charge_group_member",
    "closed_day",
    "consent_event",
    "expense",
    "expense_skip",
    "freeze_request",
    "grade_event",
    "guardian_link",
    "gym_month_figure",
    "gym_slug_alias",
    "gym_terms",
    "history_payment",
    "idempotency_key",
    "join_link",
    "join_request",
    "ledger_entry",
    "mail_unsubscribe",
    "membership_freeze",
    "message_log",
    "person_field_value",
    "person_requirement",
    "plan_event",
    "processor_terms",
    "schedule_slot_tag",
    "session_block",
    "session_tag",
    "staff",
    "staff_title",
    "study_material_plan",
    "study_material_slot",
    "terms_acceptance",
    "audit_event",
    "billing_period",
    "block_kind",
    "charge_group",
    "class_tag",
    "expense_recurring",
    "extra_line",
    "gym_title",
    "requirement",
    "study_material",
    "expense_category",
    "extra_charge",
    "session",
    "membership",
    "schedule_slot",
    "class_type",
    "gym_person",
    "plan",
    "gym_activity",
    "program",
)

COLUMNS = (
    "ALTER TABLE gym ADD COLUMN removal_started_at timestamptz",
    "ALTER TABLE gym ADD COLUMN early_deletion_on date",
    # A removal only of a suspended gym, and an early date only with a removal.
    "ALTER TABLE gym ADD CONSTRAINT gym_removal_suspended"
    " CHECK (removal_started_at IS NULL OR suspended_at IS NOT NULL)",
    "ALTER TABLE gym ADD CONSTRAINT gym_early_deletion_removal"
    " CHECK (early_deletion_on IS NULL OR removal_started_at IS NOT NULL)",
)

PLATFORM_GRANTS = (
    "GRANT SELECT (removal_started_at, early_deletion_on) ON gym TO {role}",
    "GRANT UPDATE (removal_started_at, early_deletion_on) ON gym TO {role}",
)

# The append-only tables' guards, opened for the gym being deleted.
GUARDED = (
    "ledger_entry_append_only()",
    "audit_event_append_only()",
    "plan_never_deleted()",
    "terms_acceptance_immutable()",
)
OPENING = """
    -- The removal of the row's gym (#377, `delete_gym`) deletes every row it has.
    IF TG_OP = 'DELETE' THEN
        IF OLD.gym_id = NULLIF(current_setting('app.forget_gym', true), '')::uuid
           AND EXISTS (
               SELECT FROM public.gym x
               WHERE x.id = OLD.gym_id AND x.removal_started_at IS NOT NULL
           ) THEN
            RETURN OLD;
        END IF;
    END IF;
"""

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

START = "platform_start_removal(bytea, uuid, text)"
CANCEL = "platform_cancel_removal(bytea, uuid)"
EARLY = "platform_record_early_deletion(bytea, uuid, date)"

FUNCTIONS = {
    START: f"""
CREATE FUNCTION platform_start_removal(session bytea, gym uuid, typed_slug text)
RETURNS TABLE (
    slug text, suspended boolean, confirmed boolean, changed boolean, started_at timestamptz
)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    since timestamptz;
    started timestamptz;
BEGIN
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug, g.suspended_at, g.removal_started_at INTO found_slug, since, started
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    slug := found_slug;
    suspended := since IS NOT NULL;
    confirmed := typed_slug = found_slug;
    changed := suspended AND confirmed AND started IS NULL;
    IF changed THEN
        started := now();
        UPDATE public.gym g SET removal_started_at = started WHERE g.id = gym;
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_removal_started', gym, jsonb_build_object(
            'slug', found_slug
        ));
    END IF;
    started_at := started;
    RETURN NEXT;
END
$$
""",
    CANCEL: f"""
CREATE FUNCTION platform_cancel_removal(session bytea, gym uuid)
RETURNS TABLE (slug text, changed boolean)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    started timestamptz;
BEGIN
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug, g.removal_started_at INTO found_slug, started
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    slug := found_slug;
    changed := started IS NOT NULL;
    IF changed THEN
        -- Back to suspended, as it was before.
        UPDATE public.gym g SET removal_started_at = NULL, early_deletion_on = NULL
        WHERE g.id = gym;
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_removal_cancelled', gym, jsonb_build_object(
            'slug', found_slug
        ));
    END IF;
    RETURN NEXT;
END
$$
""",
    EARLY: f"""
CREATE FUNCTION platform_record_early_deletion(session bytea, gym uuid, asked_on date)
RETURNS TABLE (slug text, removing boolean, changed boolean)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_operator uuid;
    found_slug text;
    started timestamptz;
    before date;
BEGIN
    found_operator := public.platform_operator_of(session, interval '{FRESH}');
    SELECT g.slug, g.removal_started_at, g.early_deletion_on INTO found_slug, started, before
    FROM public.gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RETURN;
    END IF;
    slug := found_slug;
    removing := started IS NOT NULL;
    changed := removing AND before IS DISTINCT FROM asked_on;
    IF changed THEN
        UPDATE public.gym g SET early_deletion_on = asked_on WHERE g.id = gym;
        INSERT INTO public.platform_event (operator_id, action, gym_id, detail)
        VALUES (found_operator, 'gym_early_deletion', gym, jsonb_build_object(
            'slug', found_slug, 'asked_on', asked_on
        ));
    END IF;
    RETURN NEXT;
END
$$
""",
}

RESUME = "platform_resume_gym(bytea, uuid)"
GYM = "platform_gym(bytea, uuid, text, text)"

ELSEWHERE = "gym_people_elsewhere(uuid)"
ELSEWHERE_FUNCTION = """
CREATE FUNCTION gym_people_elsewhere(gym uuid)
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT DISTINCT mine.person_id
    FROM (
        SELECT person_id FROM public.gym_person WHERE gym_id = gym
        UNION SELECT person_id FROM public.membership WHERE gym_id = gym
        UNION SELECT person_id FROM public.staff WHERE gym_id = gym
    ) mine
    WHERE EXISTS (
        SELECT FROM public.gym_person x WHERE x.person_id = mine.person_id AND x.gym_id <> gym
    ) OR EXISTS (
        SELECT FROM public.membership x WHERE x.person_id = mine.person_id AND x.gym_id <> gym
    ) OR EXISTS (
        SELECT FROM public.staff x WHERE x.person_id = mine.person_id AND x.gym_id <> gym
    )
$$
"""

DELETE = "delete_gym(uuid, text, integer)"


def delete_function() -> str:
    tables = ", ".join(f"'{table}'" for table in TABLES)
    return f"""
CREATE FUNCTION delete_gym(gym uuid, by_user text, files integer)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    found_slug text;
    started timestamptz;
    people uuid[];
    elsewhere uuid[];
    counts jsonb := '{{}}'::jsonb;
    total bigint := 0;
    n bigint;
    t text;
    who uuid;
    deleted int := 0;
    kept int := 0;
    detail jsonb;
BEGIN
    PERFORM set_config('app.gym_id', gym::text, true);
    SELECT g.slug, g.removal_started_at INTO found_slug, started
    FROM gym g WHERE g.id = gym FOR UPDATE;
    IF found_slug IS NULL THEN
        RAISE EXCEPTION 'no gym %', gym USING ERRCODE = 'no_data_found';
    END IF;
    IF started IS NULL THEN
        RAISE EXCEPTION 'gym % has no removal started', found_slug
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    -- Its people, read before their rows go, and which of them another gym has.
    people := ARRAY(
        SELECT person_id FROM gym_person WHERE gym_id = gym
        UNION SELECT person_id FROM membership WHERE gym_id = gym
        UNION SELECT person_id FROM staff WHERE gym_id = gym
    );
    elsewhere := ARRAY(SELECT gym_people_elsewhere(gym));

    PERFORM set_config('app.forget_gym', gym::text, true);
    FOREACH t IN ARRAY ARRAY[{tables}] LOOP
        EXECUTE format('DELETE FROM %I WHERE gym_id = $1', t) USING gym;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n > 0 THEN
            counts := counts || jsonb_build_object(t, n);
            total := total + n;
        END IF;
    END LOOP;
    DELETE FROM gym g WHERE g.id = gym;
    PERFORM set_config('app.forget_gym', '', true);
    PERFORM set_config('app.gym_id', '', true);

    -- A person another gym knows stays, with that gym's record of them; so does one
    -- that a row of another gym still names.
    PERFORM set_config('app.person_lookup', 'on', true);
    PERFORM set_config('app.person_forget', 'on', true);
    FOREACH who IN ARRAY people LOOP
        IF who = ANY (elsewhere) THEN
            kept := kept + 1;
            CONTINUE;
        END IF;
        BEGIN
            DELETE FROM auth_link WHERE person_id = who;
            DELETE FROM person WHERE id = who;
            deleted := deleted + 1;
        EXCEPTION WHEN foreign_key_violation THEN
            kept := kept + 1;
        END;
    END LOOP;
    PERFORM set_config('app.person_forget', '', true);
    PERFORM set_config('app.person_lookup', '', true);

    detail := jsonb_build_object(
        'slug', found_slug, 'by', 'cli', 'host_user', by_user,
        'removal_started_at', started, 'rows', total, 'tables', counts, 'files', files,
        'people_deleted', deleted, 'people_kept', kept
    );
    INSERT INTO platform_event (operator_id, action, gym_id, detail)
    VALUES (NULL, 'gym_deleted', gym, detail);
    RETURN detail;
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


def _patched(sql: str, patches: Sequence[tuple[str, str]]) -> str:
    for before, after in patches:
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def resume(*, removal: bool) -> str:
    """0079's `platform_resume_gym`; with `removal`, refusing a gym being removed."""
    sql: str = _migration("0079_gym_suspension.py").FUNCTIONS[RESUME]
    if not removal:
        return sql
    return _patched(
        sql,
        [
            ("    since timestamptz;\n", "    since timestamptz;\n    removing timestamptz;\n"),
            (
                "    SELECT g.slug, g.suspended_at INTO found_slug, since\n",
                "    SELECT g.slug, g.suspended_at, g.removal_started_at\n"
                "    INTO found_slug, since, removing\n",
            ),
            (
                "    slug := found_slug;\n",
                "    IF removing IS NOT NULL THEN\n"
                "        RAISE EXCEPTION 'gym % has a removal started: cancel it first',"
                " found_slug\n"
                "            USING ERRCODE = 'object_not_in_prerequisite_state';\n"
                "    END IF;\n"
                "    slug := found_slug;\n",
            ),
        ],
    )


def platform_gym(*, removal: bool) -> str:
    """0081's `platform_gym`; with `removal`, when it started and the early date."""
    sql: str = _migration("0081_terms_acceptance.py").platform_gym(terms=True)
    if not removal:
        return sql
    return _patched(
        sql,
        [
            (
                "    terms_state text\n)",
                "    terms_state text,\n    removal_started_at timestamptz,\n"
                "    early_deletion_on date\n)",
            ),
            (
                "        ELSE 'pending'\n    END\n    FROM public.gym g\n",
                "        ELSE 'pending'\n    END,\n"
                "    g.removal_started_at, g.early_deletion_on\n    FROM public.gym g\n",
            ),
        ],
    )


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _actions(actions: Sequence[str], *, valid: bool = True) -> None:
    op.execute("ALTER TABLE platform_event DROP CONSTRAINT platform_event_action_check")
    op.execute(
        "ALTER TABLE platform_event ADD CONSTRAINT platform_event_action_check"
        f" CHECK (action IN {_in(actions)}){'' if valid else ' NOT VALID'}"
    )


def _revoke(grant: str, role: str) -> str:
    return grant.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM ").format(role=role)


def _platform(signature: str, statement: str) -> None:
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {PLATFORM_ROLE}")


def _guards(*, open_for_removal: bool) -> None:
    """Each guarded function as it stands, with `OPENING` after its first BEGIN, or
    without it."""
    conn = op.get_bind()
    for signature in GUARDED:
        sql = conn.execute(
            text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": signature}
        ).scalar_one()
        if open_for_removal:
            assert OPENING not in sql, signature
            sql, count = re.subn(r"\bBEGIN\n", "BEGIN\n" + OPENING, sql, count=1)
            assert count == 1, signature
        else:
            assert sql.count(OPENING) == 1, signature
            sql = sql.replace(OPENING, "")
        op.execute(sql)


# FORCEd RLS hides every gym from the owner running this; `jobs_gym_ids()` leaves out
# a suspended one, so each gym is looked at by id through the platform's view of them.
REFUSE_DOWNGRADE = """
    DO $$
    DECLARE
        g uuid;
    BEGIN
        FOR g IN SELECT x.gym_id FROM platform_event x WHERE x.action = 'gym_removal_started'
        LOOP
            PERFORM set_config('app.gym_id', g::text, true);
            IF EXISTS (SELECT FROM gym WHERE id = g AND removal_started_at IS NOT NULL) THEN
                RAISE EXCEPTION 'gym % has a removal started: cancel it before downgrading', g;
            END IF;
        END LOOP;
        PERFORM set_config('app.gym_id', '', true);
    END
    $$
"""


def upgrade() -> None:
    _actions((*OLD_ACTIONS, *NEW_ACTIONS))
    for statement in COLUMNS:
        op.execute(statement)
    for grant in PLATFORM_GRANTS:
        op.execute(grant.format(role=PLATFORM_ROLE))

    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in FUNCTIONS.items():
        _platform(signature, statement)
    for signature, statement in (
        (RESUME, resume(removal=True)),
        (GYM, platform_gym(removal=True)),
    ):
        op.execute(f"DROP FUNCTION {signature}")
        _platform(signature, statement)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")

    # A new owner needs CREATE on the schema at the moment it takes a function over.
    op.execute(ELSEWHERE_FUNCTION)
    op.execute(f"REVOKE ALL ON FUNCTION {ELSEWHERE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ELSEWHERE} TO CURRENT_USER")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"ALTER FUNCTION {ELSEWHERE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")

    op.execute(
        "CREATE POLICY person_forget ON person FOR DELETE TO CURRENT_USER"
        " USING (current_setting('app.person_forget', true) = 'on')"
    )
    _guards(open_for_removal=True)
    # The owner's alone: the API's role never deletes a gym.
    op.execute(delete_function())
    op.execute(f"REVOKE ALL ON FUNCTION {DELETE} FROM PUBLIC")


def downgrade() -> None:
    op.execute(REFUSE_DOWNGRADE)
    op.execute(f"DROP FUNCTION {DELETE}")
    _guards(open_for_removal=False)
    op.execute("DROP POLICY person_forget ON person")
    op.execute(f"DROP FUNCTION {ELSEWHERE}")

    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for signature, statement in (
        (RESUME, resume(removal=False)),
        (GYM, platform_gym(removal=False)),
    ):
        op.execute(f"DROP FUNCTION {signature}")
        _platform(signature, statement)
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")

    for grant in PLATFORM_GRANTS:
        op.execute(_revoke(grant, PLATFORM_ROLE))
    op.execute("ALTER TABLE gym DROP CONSTRAINT gym_early_deletion_removal")
    op.execute("ALTER TABLE gym DROP CONSTRAINT gym_removal_suspended")
    op.execute("ALTER TABLE gym DROP COLUMN early_deletion_on")
    op.execute("ALTER TABLE gym DROP COLUMN removal_started_at")
    # The log keeps what was removed: the check stops taking new ones.
    _actions(OLD_ACTIONS, valid=False)
