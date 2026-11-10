"""`deploy/restore.sh`'s role discovery: the roles a scratch database needs first.

The rest of the script (fetch, decrypt, restore, the row counts) runs against a real
backup in `deploy/test-hosted.sh`.
"""

import subprocess
from pathlib import Path

RESTORE = Path(__file__).resolve().parents[2] / "deploy" / "restore.sh"


def schema_roles(sql: str) -> list[str]:
    done = subprocess.run(
        ["bash", str(RESTORE), "--schema-roles"],
        input=sql,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.split()


def test_owners_and_grantees_are_found() -> None:
    sql = """
ALTER TABLE public.gym OWNER TO rakin_owner;
ALTER FUNCTION public.join_gym_by_phone(text) OWNER TO rakin_auth;
GRANT SELECT,INSERT ON TABLE public.gym TO rakin_app;
GRANT USAGE ON SCHEMA public TO rakin_api WITH GRANT OPTION;
REVOKE ALL ON FUNCTION public.f() FROM rakin_old;
"""
    assert schema_roles(sql) == ["rakin_api", "rakin_app", "rakin_auth", "rakin_old", "rakin_owner"]


def test_every_role_of_a_list_is_found() -> None:
    sql = """
GRANT SELECT ON TABLE public.gym TO rakin_app, rakin_auth;
"""
    # pg_dump writes each statement's head on one line, however long.
    sql += (
        "CREATE POLICY by_role ON public.ledger_entry FOR SELECT TO rakin_app, rakin_reader"
        " USING ((gym_id = current_gym()));\n"
        "CREATE POLICY strict ON public.gym AS RESTRICTIVE FOR INSERT TO rakin_writer,rakin_x"
        " WITH CHECK (true);\n"
    )
    assert schema_roles(sql) == [
        "rakin_app",
        "rakin_auth",
        "rakin_reader",
        "rakin_writer",
        "rakin_x",
    ]


def test_public_and_policy_bodies_are_not_roles() -> None:
    sql = """
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT SELECT ON TABLE public.v TO PUBLIC;
CREATE POLICY isolation ON public.gym_person USING ((EXISTS ( SELECT 1 FROM public.staff s)));
CREATE POLICY own ON public.ledger_entry FOR SELECT TO rakin_app USING ((person_id IN (
   SELECT g.person_id FROM public.guardian_link g)));
COMMENT ON TABLE public.gym IS 'grants nothing TO nobody';
"""
    assert schema_roles(sql) == ["rakin_app"]
