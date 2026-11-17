"""Permissions behind the roles (#308): what the person acting may do, read from the
gym's roles and the dates of their appointments, and the titular who holds it all.

docs/design/expenses-and-officers.md, sections 1 to 3 and 7. `tests/test_permissions
_equivalence.py` holds that nobody's access changed; `tests/test_migration_0065.py`
that today's roles moved onto the Academia preset.
"""

import ast
import re
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.permissions import (
    ACADEMIA,
    ADMINISTRADOR,
    COACH,
    IMPLIES,
    PRESETS,
    Permission,
    preset_title_id,
)
from app.roles import TITLE_OF, Role
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)

APP = Path(__file__).resolve().parents[1] / "app"

pg = pytest.mark.postgres


# --- the literals, no database --------------------------------------------------------


def test_each_permission_is_its_own_literal() -> None:
    # An enum member whose value repeats another's is an alias of it: none is.
    assert len(Permission.__members__) == len(Permission) == 9
    for permission in Permission:
        assert permission.value == permission.name.lower()


def test_the_presets_store_what_each_permission_implies() -> None:
    for titles in PRESETS.values():
        for title in titles:
            for held, implied in IMPLIES.items():
                assert held not in title.permissions or implied in title.permissions, title


def test_the_academia_roles_carry_what_an_admin_and_a_coach_do_today() -> None:
    assert ADMINISTRADOR.permissions == {
        Permission.MONEY_READ,
        Permission.MONEY_WRITE,
        Permission.MEMBERS_MANAGE,
        Permission.MEMBERS_ADD,
        Permission.ATTENDANCE,
        Permission.GYM_SETUP,
        Permission.TEAM_MANAGE,
    }
    assert COACH.permissions == {Permission.ATTENDANCE, Permission.MEMBERS_ADD}
    assert TITLE_OF == {Role.ADMIN: ADMINISTRADOR, Role.COACH: COACH}


def _sources() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(APP.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def _permission_sets(tree: ast.Module) -> set[str]:
    """Module-level names bound to an expression that names a `Permission` member."""
    names = set()
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign) and node.value is not None
            else []
        )
        value = getattr(node, "value", None)
        mentions = value is not None and any(
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "Permission"
            for n in ast.walk(value)
        )
        if mentions:
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def test_no_permission_set_is_defined_as_another() -> None:
    # `LEDGER = ADMIN`, say, would narrow one the day the other is narrowed.
    sets: set[str] = set()
    trees = list(_sources())
    for _, tree in trees:
        sets |= _permission_sets(tree)
    aliased = []
    for path, tree in trees:
        for node in tree.body:
            value = getattr(node, "value", None)
            if isinstance(node, ast.Assign | ast.AnnAssign) and value is not None:
                named = value.attr if isinstance(value, ast.Attribute) else getattr(value, "id", "")
                if named in sets:
                    aliased.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert aliased == []


# A role's name in a condition: `t.name = …`, `gym_title.name IN …`, `title_name <> …`.
NAME_IN_SQL = re.compile(
    r"\b(?:\w+\.)?(?:title_name|name)\s*(?:=|<>|!=|\bIN\b|\bLIKE\b|\bILIKE\b)", re.IGNORECASE
)
GYM_TITLE_ALIASES = re.compile(r"\bgym_title\s+(?:AS\s+)?(\w+)", re.IGNORECASE)


def test_no_condition_compares_a_roles_name() -> None:
    # The name is only ever shown: a gym renames its roles and gives two people one.
    names = {title.name for titles in PRESETS.values() for title in titles}
    found = []
    for path, tree in _sources():
        where = path.relative_to(APP)
        for node in ast.walk(tree):
            # In Python: a comparison with a preset role's name.
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(isinstance(o, ast.Constant) and o.value in names for o in operands):
                    found.append(f"{where}:{node.lineno}")
            # In SQL: a condition on the name of a `gym_title` or an appointment.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = node.value
                aliases = {"gym_title", *GYM_TITLE_ALIASES.findall(sql)}
                for match in NAME_IN_SQL.finditer(sql):
                    column = match.group(0).split(".")[0] if "." in match.group(0) else ""
                    names_a_role = "title_name" in match.group(0).lower() or column in aliases
                    if names_a_role and ("staff_title" in sql or "gym_title" in sql):
                        found.append(f"{where}:{node.lineno}: {match.group(0)}")
    assert found == []


def test_a_preset_roles_id_is_derived_from_the_gym() -> None:
    gym = uuid.uuid4()
    assert preset_title_id(gym, ACADEMIA, "coach") == preset_title_id(gym, ACADEMIA, "coach")
    assert preset_title_id(gym, ACADEMIA, "coach") != preset_title_id(gym, ACADEMIA, "x")
    assert preset_title_id(gym, ACADEMIA, "coach") != preset_title_id(
        uuid.uuid4(), ACADEMIA, "coach"
    )


# --- the database ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def person_in(db: Database, gym: uuid.UUID, role: str | None = None, **term: Any) -> uuid.UUID:
    """Someone with a record in `gym`; staff in `role`, appointed for `term`, if given."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym,
                person,
            )
            if role is not None:
                await make_staff(conn, gym, person, role, **term)

    run(db.admin_url, query)
    return person


def admin(db: Database, sql: str, *args: object) -> list[Any]:
    return list(run(db.admin_url, lambda c: c.fetch(sql, *args)))


def me(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None) -> dict[str, Any]:
    response = client.get("/api/me/role", headers=as_gym(gym, person))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


@pg
def test_a_new_gym_has_the_academia_roles(db: Database, gym: uuid.UUID) -> None:
    rows = admin(
        db,
        "SELECT id, name, permissions, public, preset, system FROM gym_title"
        " WHERE gym_id = $1 ORDER BY sort",
        gym,
    )
    assert [
        (r["id"], r["name"], set(r["permissions"]), r["public"], r["preset"], r["system"])
        for r in rows
    ] == [
        (
            preset_title_id(gym, ACADEMIA, t.key),
            t.name,
            set(t.permissions),
            t.public,
            ACADEMIA,
            None,
        )
        for t in PRESETS[ACADEMIA]
    ]


@pg
@pytest.mark.parametrize(
    ("role", "permissions", "holder"),
    [
        ("owner", sorted(Permission), True),
        ("admin", sorted(ADMINISTRADOR.permissions), False),
        ("coach", sorted(COACH.permissions), False),
        (None, None, False),
    ],
)
def test_my_role_answers_my_permissions(
    client: TestClient,
    db: Database,
    gym: uuid.UUID,
    role: str | None,
    permissions: list[str] | None,
    holder: bool,
) -> None:
    person = seeded_owner(gym) if role == "owner" else person_in(db, gym, role)
    answer = me(client, gym, person)
    assert (answer["role"], answer["permissions"], answer["account_holder"]) == (
        role,
        permissions,
        holder,
    )


@pg
def test_the_dates_of_an_appointment_are_read_at_each_request(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    month_ago, tomorrow = today - timedelta(days=30), today + timedelta(days=1)
    ended_today = person_in(db, gym, "coach", starts_on=month_ago, ends_on=today)
    starts_tomorrow = person_in(db, gym, "coach", starts_on=tomorrow)
    ends_tomorrow = person_in(db, gym, "coach", starts_on=month_ago, ends_on=tomorrow)
    open_since = person_in(db, gym, "coach", starts_on=month_ago)

    for person, on_the_team in (
        (ended_today, False),
        (starts_tomorrow, False),
        (ends_tomorrow, True),
        (open_since, True),
    ):
        answer = me(client, gym, person)
        assert answer["permissions"] == (sorted(COACH.permissions) if on_the_team else None)
        # A staff endpoint (`StaffSession`) lets them in only while the term runs.
        status = client.get("/api/plans", headers=as_gym(gym, person)).status_code
        assert status == (200 if on_the_team else 403)


@pg
def test_a_staff_row_with_no_current_appointment_is_not_on_the_team(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person = person_in(db, gym, "coach")
    admin(db, "DELETE FROM staff_title WHERE person_id = $1", person)
    assert me(client, gym, person)["permissions"] is None
    assert client.get("/api/plans", headers=as_gym(gym, person)).status_code == 403


@pg
def test_permissions_are_the_union_of_the_roles_held(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person = person_in(db, gym, "coach")
    treasurer = uuid.uuid4()
    admin(
        db,
        "INSERT INTO gym_title (id, gym_id, name, permissions)"
        " VALUES ($1, $2, 'Tesorera', ARRAY['money_read', 'money_write'])",
        treasurer,
        gym,
    )
    admin(
        db,
        "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
        " VALUES ($1, $2, $3, 'Tesorera', $4)",
        gym,
        person,
        treasurer,
        seeded_today(),
    )
    assert me(client, gym, person)["permissions"] == sorted(
        {*COACH.permissions, Permission.MONEY_READ, Permission.MONEY_WRITE}
    )
    # `LedgerSession` reads `money_write`, which a coach alone never holds.
    assert client.get("/api/ledger/pending", headers=as_gym(gym, person)).status_code == 200


# --- the roles' rules ------------------------------------------------------------------


@pg
@pytest.mark.parametrize(
    "permissions",
    [["money_write"], ["expenses_write"], ["members_manage"], ["nonsense"]],
)
def test_a_role_lists_only_known_permissions_with_what_they_imply(
    db: Database, gym: uuid.UUID, permissions: list[str]
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        admin(
            db,
            "INSERT INTO gym_title (gym_id, name, permissions) VALUES ($1, 'X', $2)",
            gym,
            permissions,
        )


@pg
def test_a_roles_name_is_unique_among_the_gyms_unarchived_ones(
    db: Database, gym: uuid.UUID
) -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        admin(db, "INSERT INTO gym_title (gym_id, name) VALUES ($1, 'COACH')", gym)
    admin(db, "UPDATE gym_title SET archived_at = now() WHERE gym_id = $1 AND name = 'Coach'", gym)
    admin(db, "INSERT INTO gym_title (gym_id, name) VALUES ($1, 'Coach')", gym)


@pg
def test_a_term_never_ends_before_it_starts(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    with pytest.raises(asyncpg.CheckViolationError):
        person_in(db, gym, "coach", starts_on=today, ends_on=today - timedelta(days=1))
    # One that ends on the day it starts was ended then, and granted nothing (0070).
    person = person_in(db, gym, "coach", starts_on=today, ends_on=today)
    assert me(client, gym, person)["permissions"] is None


@pg
def test_the_roles_and_appointments_are_the_gyms_own(db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    person_in(db, gym, "coach")
    for table in ("gym_title", "staff_title"):
        rows = run(db.api_url, in_gym(other, f"SELECT gym_id FROM {table}"))
        assert {r["gym_id"] for r in rows} <= {other}
        assert run(db.api_url, in_gym(None, f"SELECT 1 FROM {table}")) == []


# --- the titular ---------------------------------------------------------------------


@pg
def test_a_gym_never_has_two_titulars(db: Database, gym: uuid.UUID) -> None:
    person = person_in(db, gym, "admin")
    with pytest.raises(asyncpg.UniqueViolationError):
        admin(db, "UPDATE staff SET account_holder = true WHERE person_id = $1", person)


@pg
def test_a_gym_never_has_none_at_commit(db: Database, gym: uuid.UUID) -> None:
    owner = seeded_owner(gym)
    with pytest.raises(asyncpg.CheckViolationError, match="no account holder"):
        admin(db, "UPDATE staff SET account_holder = false WHERE person_id = $1", owner)
    # With the rest of the staff still there.
    person_in(db, gym, "coach")
    with pytest.raises(asyncpg.CheckViolationError, match="no account holder"):
        admin(db, "DELETE FROM staff WHERE person_id = $1", owner)
    assert admin(db, "SELECT account_holder FROM staff WHERE person_id = $1", owner) == [(True,)]


@pg
def test_the_titular_changes_hands_in_one_transaction(db: Database, gym: uuid.UUID) -> None:
    owner, heir = seeded_owner(gym), person_in(db, gym, "admin")

    async def swap(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            # The old flag cleared first, then the new one set: never two, at no point.
            await conn.execute(
                "UPDATE staff SET account_holder = false WHERE person_id = $1", owner
            )
            await conn.execute("UPDATE staff SET account_holder = true WHERE person_id = $1", heir)

    run(db.admin_url, swap)
    rows = admin(db, "SELECT person_id FROM staff WHERE gym_id = $1 AND account_holder", gym)
    assert rows == [(heir,)]


@pg
def test_a_gym_with_no_staff_has_no_titular_to_keep(db: Database, gym: uuid.UUID) -> None:
    # A gym taken down whole: its last staff row goes too.
    admin(db, "DELETE FROM staff WHERE gym_id = $1", gym)
    assert admin(db, "SELECT 1 FROM staff WHERE gym_id = $1", gym) == []


# --- the staff API writes the appointments ----------------------------------------------


def invite(client: TestClient, gym: uuid.UUID, role: str, name: str) -> uuid.UUID:
    key = "administrador" if role == "admin" else "coach"
    title = str(preset_title_id(gym, ACADEMIA, key))
    body = {"name": name, "email": f"{name.lower()}@example.cl", "title_ids": [title]}
    response = client.post("/api/staff", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["person_id"])


def terms(db: Database, person: uuid.UUID) -> list[tuple[Any, ...]]:
    rows = admin(
        db,
        "SELECT title_id, title_name, starts_on, ends_on, created_by FROM staff_title"
        " WHERE person_id = $1 ORDER BY starts_on, created_at",
        person,
    )
    return [tuple(r) for r in rows]


@pg
def test_an_invite_appoints_from_today(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    owner, today = seeded_owner(gym), seeded_today()
    pedro, carla = invite(client, gym, "coach", "Pedro"), invite(client, gym, "admin", "Carla")
    coach = preset_title_id(gym, ACADEMIA, "coach")
    administrador = preset_title_id(gym, ACADEMIA, "administrador")
    assert terms(db, pedro) == [(coach, "Coach", today, None, owner)]
    assert terms(db, carla) == [(administrador, "Administrador", today, None, owner)]
    # The row's role, which no policy reads since #309, is still written until #313.
    assert admin(db, "SELECT role FROM staff WHERE person_id = $1", pedro) == [("coach",)]
    assert me(client, gym, carla)["permissions"] == sorted(ADMINISTRADOR.permissions)


@pg
def test_a_new_role_is_appointed_beside_the_one_ended(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owner, today = seeded_owner(gym), seeded_today()
    since = today - timedelta(days=90)
    beto = person_in(db, gym, "coach", starts_on=since)
    coach = preset_title_id(gym, ACADEMIA, "coach")
    administrador = preset_title_id(gym, ACADEMIA, "administrador")
    [(appointment,)] = admin(db, "SELECT id FROM staff_title WHERE person_id = $1", beto)

    made = client.post(
        f"/api/staff/{beto}/appointments",
        json={"title_id": str(administrador)},
        headers=as_gym(gym),
    )
    assert made.status_code == 201, made.text
    ended = client.post(f"/api/staff/{beto}/appointments/{appointment}/end", headers=as_gym(gym))
    assert ended.status_code == 204, ended.text

    assert terms(db, beto) == [
        (coach, "Coach", since, today, None),
        (administrador, "Administrador", today, None, owner),
    ]
    ended_by = "SELECT ended_by FROM staff_title WHERE person_id = $1 AND ends_on IS NOT NULL"
    assert admin(db, ended_by, beto) == [(owner,)]
    assert me(client, gym, beto)["permissions"] == sorted(ADMINISTRADOR.permissions)


@pg
def test_a_revoke_ends_the_appointment_and_the_row(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    since = today - timedelta(days=90)
    beto = person_in(db, gym, "coach", starts_on=since)

    assert client.delete(f"/api/staff/{beto}", headers=as_gym(gym)).status_code == 204

    assert admin(db, "SELECT 1 FROM staff WHERE person_id = $1", beto) == []
    # The term stays on record, ended today.
    [(_, name, starts, ends, _)] = terms(db, beto)
    assert (name, starts, ends) == ("Coach", since, today)


@pg
def test_revoked_on_the_day_of_the_invite_and_invited_again(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    pedro = invite(client, gym, "coach", "Pedro")
    assert client.delete(f"/api/staff/{pedro}", headers=as_gym(gym)).status_code == 204
    # Today's term never ran a day: it ends on the day it started, and stays on record.
    today = seeded_today()
    [(_, name, starts, ends, _)] = terms(db, pedro)
    assert (name, starts, ends) == ("Coach", today, today)
    assert invite(client, gym, "coach", "Pedro") == pedro
    assert [(name, starts, ends) for _, name, starts, ends, _ in terms(db, pedro)] == [
        ("Coach", today, today),
        ("Coach", today, None),
    ]


@pg
def test_forgetting_a_former_coach_deletes_their_terms(db: Database, gym: uuid.UUID) -> None:
    since = seeded_today() - timedelta(days=90)
    beto = person_in(db, gym, "coach", starts_on=since, ends_on=seeded_today())
    admin(db, "DELETE FROM staff WHERE person_id = $1", beto)

    refusal = run(
        db.api_url,
        in_gym(gym, "SELECT forget_gym_person($1, 'pidió borrar')", beto, person=seeded_owner(gym)),
    )
    assert refusal == [(None,)]
    assert terms(db, beto) == []
