"""The titular accepts the Términos de servicio and de encargo in the app (#499).

A gym is created pending its terms, and its titular accepts both texts on a page of
the admin before any of its data goes in (`app.api.terms`). The acceptance is a simple
electronic signature (Ley 19.799, art. 2 f): what makes it hold up is the record, so
each one is kept whole, as #500 lists it (docs/legal-research.md, "Requirements for
#499").

- `terms_acceptance`, one row per acceptance, never changed or deleted. `in_app`: the
  person who accepted; both versions; the exact HTML shown, blanks filled, and its
  SHA-256, taken here over what is stored; what each checkbox said, and the
  subencargados it named; the values the titular filled in; the address the session
  signed in with and when it did; the address the gym was created with, and by which
  operator; the request's IP and user agent, on this row only; and when the copy was
  emailed. `outside`: an acceptance signed on paper, as `app.gyms sign-terms` and the
  panel record it, with the date on the copy. No link, code, fingerprint or the
  person's RUT is kept. Rows are kept for the contract's life and five years after;
  #377, which deletes a gym, is to drop them then.
- A trigger refuses UPDATE, DELETE and TRUNCATE on it, whoever runs them, the owner
  too. The one exception is the copy's email, set once (`app_terms_copy_sent`).
- `gym_terms`, one row per gym created from here on: whether the gym is exempt (an
  instance the company does not host, `--no-processor-terms`), and the address it was
  created with and the operator who did. A table of its own, not columns of `gym`,
  which `rakin_app` may update.
- The terms state, `pending` (no acceptance and no signature ever), `outdated` (some
  before, not both current versions) or `current` (both, or exempt), is one SQL
  expression (`terms_state`), in `app_terms_state` for the API and inline in the
  panel's functions. A signature in `processor_terms` (0075) counts as an acceptance
  before, so Meta is `outdated`, not `pending`.
- `rakin_app` reads and writes the table only through `app_terms_state`,
  `app_accept_terms` (the titular alone; the hashes taken here),
  `app_terms_acceptances` (the titular alone, with the signatures in
  `processor_terms` from before) and `app_terms_copy` (the titular alone) and
  `app_terms_copy_sent`. Each is `SECURITY DEFINER`, owned by the table owner, and
  held to the gym `app.gym_id` names by its forced RLS.
- `gym_create` (0078) writes the gym's `gym_terms` row; `platform_create_gym` (0077)
  names its operator there. A gym created with no terms is now pending, not unhosted.
- `platform_record_terms` (0078) also writes an `outside` acceptance of both texts.
- `platform_owner_link` (0077) logs `terms_invite_sent` or `terms_invite_failed`
  for an invitation to accept; `platform_gyms` counts a failed one as a failed link.
- `platform_titular` (0077) also says the titular's person and name, the gym's
  name and its terms state, for the invitation.
- `platform_gyms` (0079) says `terms_state` and when the latest acceptance was, and
  `platform_gym` (0079) lists every acceptance and the state.

0077's, 0078's and 0079's functions are rebuilt from their own text, patched by string
replacement, as 0079 does. Each patch asserts it matches once, so those must not be
reformatted or edited.

Revision ID: 0081
Revises: 0080
Create Date: 2026-11-20

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
PLATFORM_ROLE = "rakin_platform"

CURRENT_GYM = "NULLIF(current_setting('app.gym_id', true), '')::uuid"
CURRENT_PERSON = "NULLIF(current_setting('app.person_id', true), '')::uuid"

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
)
NEW_ACTIONS = ("terms_invite_sent", "terms_invite_failed")

VERSION_CHECK = "~ '^\\d{4}-\\d{2}-\\d{2}$'"

TABLES = (
    """
CREATE TABLE gym_terms (
    gym_id uuid PRIMARY KEY REFERENCES gym (id) ON DELETE CASCADE,
    exempt boolean NOT NULL DEFAULT false,
    invited_email text,
    invited_by uuid REFERENCES platform_operator (id)
)
""",
    "ALTER TABLE gym_terms ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE gym_terms FORCE ROW LEVEL SECURITY",
    "CREATE POLICY gym_terms_isolation ON gym_terms"
    f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})",
    f"""
CREATE TABLE terms_acceptance (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gym_id uuid NOT NULL REFERENCES gym (id),
    person_id uuid REFERENCES person (id),
    accepted_at timestamptz NOT NULL DEFAULT now(),
    channel text NOT NULL CHECK (channel IN ('in_app', 'outside')),
    service_version text CHECK (service_version {VERSION_CHECK}),
    processor_version text NOT NULL CHECK (processor_version {VERSION_CHECK}),
    service_html text,
    processor_html text,
    service_sha256 bytea CHECK (octet_length(service_sha256) = 32),
    processor_sha256 bytea CHECK (octet_length(processor_sha256) = 32),
    service_declaration text,
    processor_declaration text,
    subprocessors text[],
    filled jsonb NOT NULL DEFAULT '{{}}',
    session_email text,
    signed_in_at timestamptz,
    invited_email text,
    invited_by uuid REFERENCES platform_operator (id),
    ip text,
    user_agent text,
    signed_on date,
    copy_sent_at timestamptz,
    copy_message_id text,
    CONSTRAINT terms_acceptance_in_app CHECK (channel <> 'in_app' OR (
        person_id IS NOT NULL AND service_version IS NOT NULL
        AND service_html IS NOT NULL AND processor_html IS NOT NULL
        AND service_sha256 IS NOT NULL AND processor_sha256 IS NOT NULL
        AND service_declaration IS NOT NULL AND processor_declaration IS NOT NULL
        AND subprocessors IS NOT NULL AND session_email IS NOT NULL
        AND signed_in_at IS NOT NULL AND signed_on IS NULL
    )),
    CONSTRAINT terms_acceptance_outside CHECK (channel <> 'outside' OR (
        signed_on IS NOT NULL AND service_html IS NULL AND processor_html IS NULL
        AND service_sha256 IS NULL AND processor_sha256 IS NULL
        AND ip IS NULL AND user_agent IS NULL
    ))
)
""",
    "CREATE INDEX terms_acceptance_gym_idx ON terms_acceptance (gym_id, accepted_at DESC)",
    "ALTER TABLE terms_acceptance ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE terms_acceptance FORCE ROW LEVEL SECURITY",
    "CREATE POLICY terms_acceptance_isolation ON terms_acceptance"
    f" USING (gym_id = {CURRENT_GYM}) WITH CHECK (gym_id = {CURRENT_GYM})",
    """
CREATE FUNCTION terms_acceptance_immutable()
RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    -- The copy's email is the one thing written after the acceptance, once.
    IF TG_OP = 'UPDATE' AND OLD.copy_sent_at IS NULL AND NEW.copy_sent_at IS NOT NULL
       AND to_jsonb(NEW) - 'copy_sent_at' - 'copy_message_id'
           = to_jsonb(OLD) - 'copy_sent_at' - 'copy_message_id' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a terms acceptance is never changed or deleted'
        USING ERRCODE = 'restrict_violation';
END
$$
""",
    "CREATE TRIGGER terms_acceptance_immutable BEFORE UPDATE OR DELETE ON terms_acceptance"
    " FOR EACH ROW EXECUTE FUNCTION terms_acceptance_immutable()",
    "CREATE TRIGGER terms_acceptance_no_truncate BEFORE TRUNCATE ON terms_acceptance"
    " FOR EACH STATEMENT EXECUTE FUNCTION terms_acceptance_immutable()",
)

# What the panel's functions read and write of them; `rakin_platform` bypasses RLS.
PLATFORM_GRANTS = (
    "GRANT SELECT (gym_id, exempt, invited_by) ON gym_terms TO {role}",
    "GRANT UPDATE (invited_by) ON gym_terms TO {role}",
    "GRANT SELECT (gym_id, person_id, accepted_at, channel, service_version,"
    " processor_version, signed_on) ON terms_acceptance TO {role}",
    "GRANT INSERT (gym_id, channel, service_version, processor_version, signed_on)"
    " ON terms_acceptance TO {role}",
)


def terms_state(gym: str, service: str, processor: str) -> str:
    """The terms state of `gym`, against the current `service` and `processor`
    versions: `current`, `outdated` or `pending`. Qualified names, for any path."""
    accepted = f"SELECT FROM public.terms_acceptance a WHERE a.gym_id = {gym}"
    return f"""CASE
        WHEN coalesce((SELECT t.exempt FROM public.gym_terms t WHERE t.gym_id = {gym}), false)
            THEN 'current'
        WHEN EXISTS ({accepted} AND a.service_version = {service})
         AND EXISTS ({accepted} AND a.processor_version = {processor})
            THEN 'current'
        WHEN EXISTS ({accepted})
          OR EXISTS (SELECT FROM public.processor_terms p WHERE p.gym_id = {gym})
            THEN 'outdated'
        ELSE 'pending'
    END"""


TITULAR = (
    "EXISTS (SELECT FROM public.staff s"
    f" WHERE s.gym_id = {CURRENT_GYM} AND s.person_id = {CURRENT_PERSON}"
    " AND s.account_holder)"
)
NOT_TITULAR = f"""    IF NOT {TITULAR} THEN
        RAISE EXCEPTION 'only the titular may do this' USING ERRCODE = 'insufficient_privilege';
    END IF;
"""

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

STATE = "app_terms_state(text, text)"
ACCEPT = (
    "app_accept_terms(text, text, text, text, text, text, text[], jsonb, text,"
    " timestamptz, text, text)"
)
ACCEPTANCES = "app_terms_acceptances()"
COPY = "app_terms_copy(uuid)"
COPY_SENT = "app_terms_copy_sent(uuid, text)"

APP_FUNCTIONS = {
    STATE: f"""
CREATE FUNCTION app_terms_state(service text, processor text)
RETURNS text
LANGUAGE sql STABLE {DEFINER} AS $$
    SELECT {terms_state(CURRENT_GYM, "service", "processor")}
$$
""",
    ACCEPT: f"""
CREATE FUNCTION app_accept_terms(
    p_service_version text, p_processor_version text,
    p_service_html text, p_processor_html text,
    p_service_declaration text, p_processor_declaration text, p_subprocessors text[],
    p_filled jsonb, p_session_email text, p_signed_in_at timestamptz,
    p_ip text, p_user_agent text
)
RETURNS TABLE (id uuid, accepted_at timestamptz)
LANGUAGE plpgsql VOLATILE {DEFINER} AS $$
#variable_conflict use_column
DECLARE
    found_gym uuid := {CURRENT_GYM};
    invite record;
    made_id uuid;
    made_at timestamptz;
BEGIN
{NOT_TITULAR}    SELECT t.invited_email, t.invited_by INTO invite
    FROM public.gym_terms t WHERE t.gym_id = found_gym;
    -- The hashes are taken here, over exactly what is stored.
    INSERT INTO public.terms_acceptance AS a (
        gym_id, person_id, channel, service_version, processor_version,
        service_html, processor_html, service_sha256, processor_sha256,
        service_declaration, processor_declaration, subprocessors, filled,
        session_email, signed_in_at, invited_email, invited_by, ip, user_agent
    )
    VALUES (
        found_gym, {CURRENT_PERSON}, 'in_app', p_service_version, p_processor_version,
        p_service_html, p_processor_html,
        sha256(convert_to(p_service_html, 'UTF8')), sha256(convert_to(p_processor_html, 'UTF8')),
        p_service_declaration, p_processor_declaration, p_subprocessors, p_filled,
        p_session_email, p_signed_in_at, invite.invited_email, invite.invited_by,
        p_ip, p_user_agent
    )
    RETURNING a.id, a.accepted_at INTO made_id, made_at;
    id := made_id;
    accepted_at := made_at;
    RETURN NEXT;
END
$$
""",
    ACCEPTANCES: f"""
CREATE FUNCTION app_terms_acceptances()
RETURNS TABLE (
    id uuid,
    accepted_at timestamptz,
    channel text,
    service_version text,
    processor_version text,
    accepted_by_name text,
    signed_on date,
    service_sha256 bytea,
    processor_sha256 bytea,
    filled jsonb,
    copy_sent_at timestamptz
)
LANGUAGE plpgsql STABLE {DEFINER} AS $$
#variable_conflict use_column
BEGIN
{NOT_TITULAR}    RETURN QUERY
    SELECT t.* FROM (
        SELECT a.id, a.accepted_at, a.channel, a.service_version, a.processor_version,
               gp.name, a.signed_on, a.service_sha256, a.processor_sha256, a.filled,
               a.copy_sent_at
        FROM public.terms_acceptance a
        LEFT JOIN public.gym_person gp ON gp.gym_id = a.gym_id AND gp.person_id = a.person_id
        WHERE a.gym_id = {CURRENT_GYM}
        UNION ALL
        -- Signatures recorded before 0081, which no acceptance repeats.
        SELECT p.id, p.recorded_at, 'outside', NULL, p.version, NULL, p.signed_on,
               NULL, NULL, '{{}}'::jsonb, NULL
        FROM public.processor_terms p
        WHERE p.gym_id = {CURRENT_GYM} AND NOT EXISTS (
            SELECT FROM public.terms_acceptance x
            WHERE x.gym_id = p.gym_id AND x.channel = 'outside' AND x.processor_version = p.version
        )
    ) t
    ORDER BY t.accepted_at DESC;
END
$$
""",
    COPY: f"""
CREATE FUNCTION app_terms_copy(acceptance uuid)
RETURNS TABLE (
    id uuid,
    accepted_at timestamptz,
    channel text,
    accepted_by_name text,
    session_email text,
    service_version text,
    processor_version text,
    service_html text,
    processor_html text,
    service_sha256 bytea,
    processor_sha256 bytea,
    service_declaration text,
    processor_declaration text,
    filled jsonb
)
LANGUAGE plpgsql STABLE {DEFINER} AS $$
#variable_conflict use_column
BEGIN
{NOT_TITULAR}    RETURN QUERY
    SELECT a.id, a.accepted_at, a.channel, gp.name, a.session_email,
           a.service_version, a.processor_version, a.service_html, a.processor_html,
           a.service_sha256, a.processor_sha256, a.service_declaration,
           a.processor_declaration, a.filled
    FROM public.terms_acceptance a
    LEFT JOIN public.gym_person gp ON gp.gym_id = a.gym_id AND gp.person_id = a.person_id
    WHERE a.gym_id = {CURRENT_GYM} AND a.id = acceptance;
END
$$
""",
    COPY_SENT: f"""
CREATE FUNCTION app_terms_copy_sent(acceptance uuid, message_id text)
RETURNS boolean
LANGUAGE sql VOLATILE {DEFINER} AS $$
    WITH sent AS (
        UPDATE public.terms_acceptance a
        SET copy_sent_at = now(), copy_message_id = message_id
        WHERE a.gym_id = {CURRENT_GYM} AND a.id = acceptance AND a.copy_sent_at IS NULL
        RETURNING 1
    )
    SELECT EXISTS (SELECT FROM sent)
$$
""",
}


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


def _replacing(sql: str) -> str:
    return sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def gym_create(*, terms: bool) -> str:
    """0078's `gym_create`, as `CREATE OR REPLACE`; with `terms`, writing `gym_terms`."""
    sql: str = _migration("0078_gym_slug_alias.py").gym_create(aliases=True)
    if not terms:
        return sql
    return _patched(
        sql,
        [
            (
                "    VALUES (p_id, p_name, p_slug, p_timezone, p_settings);\n",
                "    VALUES (p_id, p_name, p_slug, p_timezone, p_settings);\n"
                "    -- Pending its terms (0081): the address its titular accepts from.\n"
                "    INSERT INTO gym_terms (gym_id, invited_email) VALUES (p_id, p_owner_email);\n",
            )
        ],
    )


PLATFORM_CREATE = (
    "platform_create_gym(bytea, text, uuid, text, text, text, jsonb, text[], text, text,"
    " text, text, text, text, text, text, date)"
)


def platform_create_gym(*, terms: bool) -> str:
    """0077's `platform_create_gym`, as `CREATE OR REPLACE`; with `terms`, naming the
    operator who created the gym in its `gym_terms`."""
    sql = _replacing(_migration("0077_gym_create.py").FUNCTIONS[PLATFORM_CREATE])
    if not terms:
        return sql
    return _patched(
        sql,
        [
            (
                "    IF made.created THEN\n",
                "    IF made.created THEN\n"
                "        UPDATE public.gym_terms t SET invited_by = found_operator\n"
                "        WHERE t.gym_id = made.id;\n",
            )
        ],
    )


OLD_LINK = "platform_owner_link(bytea, uuid, boolean)"
LINK = "platform_owner_link(bytea, uuid, boolean, boolean)"


def owner_link() -> str:
    """0077's `platform_owner_link`, which logs an invitation to accept the terms too."""
    return _patched(
        _migration("0077_gym_create.py").FUNCTIONS[OLD_LINK],
        [
            (
                "CREATE FUNCTION platform_owner_link(session bytea, gym uuid, sent boolean)\n",
                "CREATE FUNCTION platform_owner_link(\n"
                "    session bytea, gym uuid, sent boolean, invite boolean DEFAULT false\n)\n",
            ),
            (
                "        CASE WHEN sent THEN 'owner_link_sent' ELSE 'owner_link_failed' END,\n",
                "        CASE\n"
                "            WHEN invite AND sent THEN 'terms_invite_sent'\n"
                "            WHEN invite THEN 'terms_invite_failed'\n"
                "            WHEN sent THEN 'owner_link_sent'\n"
                "            ELSE 'owner_link_failed'\n"
                "        END,\n",
            ),
        ],
    )


OLD_TITULAR = "platform_titular(bytea, uuid)"
TITULAR_OF = "platform_titular(bytea, uuid, text, text)"


def titular() -> str:
    """0077's `platform_titular`, with the titular's person and name and the state."""
    return _patched(
        _migration("0077_gym_create.py").FUNCTIONS[OLD_TITULAR],
        [
            (
                "CREATE FUNCTION platform_titular(session bytea, gym uuid)\n"
                "RETURNS TABLE (slug text, email text)\n",
                "CREATE FUNCTION platform_titular(\n"
                "    session bytea, gym uuid, service_terms text, current_terms text\n)\n"
                "RETURNS TABLE (\n    slug text, email text, person_id uuid, name text,"
                " gym_name text, terms_state text\n)\n",
            ),
            (
                "    SELECT g.slug, holder.email\n",
                "    SELECT g.slug, holder.email, holder.person_id, holder.name, g.name,\n"
                f"           {terms_state('g.id', 'service_terms', 'current_terms')}\n",
            ),
            ("        SELECT gp.email\n", "        SELECT gp.email, gp.person_id, gp.name\n"),
        ],
    )


OLD_GYMS = "platform_gyms(bytea, text)"
GYMS = "platform_gyms(bytea, text, text)"

# The terms in force, the latest accepted: in the app, outside it, or signed before.
LATEST_TERMS = """    LEFT JOIN LATERAL (
        SELECT t.version, t.accepted_at
        FROM (
            SELECT a.processor_version AS version, a.accepted_at
            FROM public.terms_acceptance a WHERE a.gym_id = g.id
            UNION ALL
            SELECT p.version, p.recorded_at FROM public.processor_terms p WHERE p.gym_id = g.id
        ) t
        ORDER BY t.accepted_at DESC, t.version DESC
        LIMIT 1
    ) terms ON true
"""


def platform_gyms(*, terms: bool) -> str:
    """0079's `platform_gyms`; with `terms`, each gym's terms state and when the latest
    acceptance was, and a failed invitation counted as a failed link."""
    sql: str = _migration("0079_gym_suspension.py").platform_gyms(suspension=True)
    if not terms:
        return sql
    return _patched(
        sql,
        [
            (
                "CREATE FUNCTION platform_gyms(session bytea, current_terms text)\n",
                "CREATE FUNCTION platform_gyms(session bytea, service_terms text,"
                " current_terms text)\n",
            ),
            (
                "    terms_signed_on date,\n    terms_current boolean,\n",
                "    terms_accepted_at timestamptz,\n    terms_state text,\n",
            ),
            (
                "           terms.version, terms.signed_on,"
                " coalesce(terms.version = current_terms, false),\n",
                "           terms.version, terms.accepted_at,\n"
                f"           {terms_state('g.id', 'service_terms', 'current_terms')},\n",
            ),
            (
                """    -- The terms in force: the latest signed (0075).
    LEFT JOIN LATERAL (
        SELECT p.version, p.signed_on
        FROM public.processor_terms p
        WHERE p.gym_id = g.id
        ORDER BY p.signed_on DESC, p.recorded_at DESC
        LIMIT 1
    ) terms ON true
""",
                LATEST_TERMS,
            ),
            (
                "        SELECT e.action = 'owner_link_failed' AS failed\n",
                "        SELECT e.action IN ('owner_link_failed', 'terms_invite_failed')"
                " AS failed\n",
            ),
            (
                "        WHERE e.gym_id = g.id"
                " AND e.action IN ('owner_link_sent', 'owner_link_failed')\n",
                "        WHERE e.gym_id = g.id AND e.action IN (\n"
                "            'owner_link_sent', 'owner_link_failed',"
                " 'terms_invite_sent', 'terms_invite_failed'\n"
                "        )\n",
            ),
        ],
    )


OLD_GYM = "platform_gym(bytea, uuid)"
GYM = "platform_gym(bytea, uuid, text, text)"

ACCEPTANCE_LIST = """           coalesce((
               SELECT jsonb_agg(jsonb_build_object(
                   'accepted_at', t.accepted_at, 'channel', t.channel,
                   'service_version', t.service_version,
                   'processor_version', t.processor_version,
                   'accepted_by_name', t.accepted_by_name, 'signed_on', t.signed_on
               ) ORDER BY t.accepted_at DESC)
               FROM (
                   SELECT a.accepted_at, a.channel, a.service_version, a.processor_version,
                          who.name AS accepted_by_name, a.signed_on
                   FROM public.terms_acceptance a
                   LEFT JOIN public.gym_person who
                       ON who.gym_id = a.gym_id AND who.person_id = a.person_id
                   WHERE a.gym_id = g.id
                   UNION ALL
                   -- Signatures recorded before 0081, which no acceptance repeats.
                   SELECT p.recorded_at, 'outside', NULL, p.version, NULL, p.signed_on
                   FROM public.processor_terms p
                   WHERE p.gym_id = g.id AND NOT EXISTS (
                       SELECT FROM public.terms_acceptance x
                       WHERE x.gym_id = p.gym_id AND x.channel = 'outside'
                         AND x.processor_version = p.version
                   )
               ) t
           ), '[]'::jsonb),
"""


def platform_gym(*, terms: bool) -> str:
    """0079's `platform_gym`; with `terms`, every acceptance and the terms state."""
    sql: str = _migration("0079_gym_suspension.py").platform_gym(suspension=True)
    if not terms:
        return sql
    return _patched(
        sql,
        [
            (
                "CREATE FUNCTION platform_gym(session bytea, gym uuid)\n",
                "CREATE FUNCTION platform_gym(\n"
                "    session bytea, gym uuid, service_terms text, current_terms text\n)\n",
            ),
            ("    suspended_reason text\n)", "    suspended_reason text,\n    terms_state text\n)"),
            (
                """           coalesce((
               SELECT jsonb_agg(jsonb_build_object('version', p.version, 'signed_on', p.signed_on)
                                ORDER BY p.signed_on DESC, p.recorded_at DESC)
               FROM public.processor_terms p WHERE p.gym_id = g.id
           ), '[]'::jsonb),
""",
                ACCEPTANCE_LIST,
            ),
            (
                "           g.suspended_at, g.suspended_reason\n    FROM public.gym g\n",
                "           g.suspended_at, g.suspended_reason,\n"
                f"           {terms_state('g.id', 'service_terms', 'current_terms')}\n"
                "    FROM public.gym g\n",
            ),
        ],
    )


OLD_RECORD = "platform_record_terms(bytea, uuid, text, date)"
RECORD = "platform_record_terms(bytea, uuid, text, date, text)"


def record_terms() -> str:
    """0078's `platform_record_terms`, writing an `outside` acceptance of both texts."""
    return _patched(
        _migration("0078_gym_slug_alias.py").FUNCTIONS[OLD_RECORD],
        [
            (
                "    session bytea, gym uuid, p_version text, p_signed_on date\n)",
                "    session bytea, gym uuid, p_version text, p_signed_on date,"
                " p_service_version text\n)",
            ),
            (
                """    ON CONFLICT (gym_id, version) DO NOTHING
    RETURNING true INTO recorded;
""",
                """    ON CONFLICT (gym_id, version) DO NOTHING;
    -- Both texts, signed outside the app (0081): once for each pair of versions.
    IF NOT EXISTS (
        SELECT FROM public.terms_acceptance a
        WHERE a.gym_id = gym AND a.channel = 'outside' AND a.processor_version = p_version
          AND a.service_version IS NOT DISTINCT FROM p_service_version
    ) THEN
        INSERT INTO public.terms_acceptance
            (gym_id, channel, service_version, processor_version, signed_on)
        VALUES (gym, 'outside', p_service_version, p_version, p_signed_on);
        recorded := true;
    END IF;
""",
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


def _panel() -> list[tuple[str, str, str, str]]:
    """Each panel function this changes, whose signature changes too: its signature
    and text before, and after."""
    before = _migration("0077_gym_create.py").FUNCTIONS
    signed = _migration("0078_gym_slug_alias.py").FUNCTIONS
    return [
        (OLD_LINK, before[OLD_LINK], LINK, owner_link()),
        (OLD_TITULAR, before[OLD_TITULAR], TITULAR_OF, titular()),
        (OLD_GYMS, platform_gyms(terms=False), GYMS, platform_gyms(terms=True)),
        (OLD_GYM, platform_gym(terms=False), GYM, platform_gym(terms=True)),
        (OLD_RECORD, signed[OLD_RECORD], RECORD, record_terms()),
    ]


def upgrade() -> None:
    _actions((*OLD_ACTIONS, *NEW_ACTIONS))
    # asyncpg runs one statement per call.
    for statement in TABLES:
        op.execute(statement)
    for grant in PLATFORM_GRANTS:
        op.execute(grant.format(role=PLATFORM_ROLE))

    # Owned by whoever runs the migrations, the table owner, held to the gym by RLS.
    for signature, statement in APP_FUNCTIONS.items():
        op.execute(statement)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")

    # Same signature: a replace keeps its owner and its grants.
    op.execute(gym_create(terms=True))

    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(platform_create_gym(terms=True))
    for old, _, new, statement in _panel():
        op.execute(f"DROP FUNCTION {old}")
        _platform(new, statement)
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    for old, statement, new, _ in _panel():
        op.execute(f"DROP FUNCTION {new}")
        _platform(old, statement)
    op.execute(platform_create_gym(terms=False))
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")

    op.execute(gym_create(terms=False))
    for signature in APP_FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    for grant in PLATFORM_GRANTS:
        op.execute(_revoke(grant, PLATFORM_ROLE))
    op.execute("DROP TABLE terms_acceptance")
    op.execute("DROP FUNCTION terms_acceptance_immutable()")
    op.execute("DROP TABLE gym_terms")
    # The log keeps its rows, these included: the old CHECK holds new rows only.
    _actions(OLD_ACTIONS, valid=False)
