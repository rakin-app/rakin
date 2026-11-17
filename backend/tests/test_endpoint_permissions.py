"""Every endpoint asks for the permission it needs, and the team is managed by the
strictly-fewer rule (#310, docs/design/expenses-and-officers.md, sections 1, 4 and 5).

Each gym-scoped endpoint names one gate (`app.permissions.GATES`): one permission,
being on the team, or the titular; a test lists any that names none. Titles holding a
single permission then use what it opens and nothing else: `money_read` reads Pagos and
records nothing, `members_manage` adds and edits people and sees no amounts. And the
staff API holds each case of section 4: an Administrador and another, an Administrador
and a Coach, a Presidente and each seat of the Club federado board, a role with fewer
permissions than yours that holds one you lack, and the titular, whom nobody touches.
`tests/test_permissions_equivalence.py` holds that owner, admin and coach answer as
before.
"""

import uuid
from collections.abc import Iterable, Iterator
from typing import Any

import asyncpg
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from app.permissions import (
    ADMINISTRADOR,
    CLUB_FEDERADO,
    COACH,
    DELEGADO,
    DIRECTOR,
    GATES,
    NOBODY,
    PRESIDENTE,
    SECRETARIO,
    TESORERO,
    Permission,
    PresetTitle,
    StaffSession,
    Standing,
    manages,
    may_change_role,
    preset_title_id,
)
from app.tenancy import TenantSession
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_coach_money import money_keys
from tests.test_tenancy import PUBLIC_PATHS

pg = pytest.mark.postgres

# --- every endpoint names its gate ---------------------------------------------------


def routes(app: FastAPI) -> Iterator[APIRoute]:
    """Every operation of `app`, through the routers it includes."""
    pending: list[Any] = list(app.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            yield route
        elif (router := getattr(route, "original_router", None)) is not None:
            pending.extend(router.routes)


def gates_of(dependant: Dependant) -> list[frozenset[Permission] | str]:
    """The gates `dependant` passes through, its own and its dependencies'."""
    found, pending = [], [dependant]
    while pending:
        current = pending.pop()
        if current.call in GATES:
            found.append(GATES[current.call])
        pending.extend(current.dependencies)
    return found


def own_or_public(path: str) -> bool:
    """A path anyone may call (`PUBLIC_PATHS`), or the member's own (`/api/me`)."""
    return path.replace(":path}", "}") in PUBLIC_PATHS or path.startswith("/api/me/")


def ungated(app: FastAPI) -> list[str]:
    """The gym's operations that name no gate, or more than one."""
    return sorted(
        f"{','.join(sorted(route.methods or ()))} {route.path}"
        for route in routes(app)
        if not own_or_public(route.path) and len(gates_of(route.dependant)) != 1
    )


def test_every_endpoint_names_one_permission_or_the_team() -> None:
    app = create_app(make_settings())
    assert ungated(app) == []
    # And the walk reaches them all: most of the app is gated.
    assert sum(1 for r in routes(app) if gates_of(r.dependant)) > 150


def test_the_listing_finds_an_endpoint_that_names_none() -> None:
    router = APIRouter()

    @router.get("/api/bare")
    async def bare(session: TenantSession) -> None: ...

    @router.get("/api/gated")
    async def gated(session: StaffSession) -> None: ...

    app = FastAPI()
    app.include_router(router)
    assert ungated(app) == ["GET /api/bare"]


# --- the rule, no database -----------------------------------------------------------


def standing(*permissions: Permission, titular: bool = False) -> Standing:
    return Standing(account_holder=titular, permissions=frozenset(permissions))


def held(title: PresetTitle) -> Standing:
    return Standing(account_holder=False, permissions=title.permissions)


TITULAR = Standing(account_holder=True, permissions=frozenset(Permission))


def test_strictly_fewer_is_a_proper_subset_never_a_count() -> None:
    admin = held(ADMINISTRADOR)
    assert manages(admin, COACH.permissions)
    assert not manages(admin, ADMINISTRADOR.permissions)  # equal
    assert not manages(admin, TESORERO.permissions)  # fewer, but expenses they lack
    assert not manages(admin, frozenset({Permission.EXPENSES_READ}))  # one, which they lack
    assert manages(admin, NOBODY.permissions)
    assert not manages(NOBODY, NOBODY.permissions)  # nothing is fewer than nothing


def test_the_titular_manages_everyone() -> None:
    for title in (ADMINISTRADOR, TESORERO, PRESIDENTE):
        assert manages(TITULAR, title.permissions)
    assert manages(TITULAR, frozenset(Permission))


def test_a_presidente_manages_only_a_director() -> None:
    presidente = held(PRESIDENTE)
    assert manages(presidente, DIRECTOR.permissions)
    for title in (SECRETARIO, DELEGADO, TESORERO, COACH, PRESIDENTE):
        assert not manages(presidente, title.permissions), title.name


def test_editing_a_role_needs_the_rule_before_and_after() -> None:
    admin = held(ADMINISTRADOR)
    coach = COACH.permissions
    assert may_change_role(admin, coach, coach | {Permission.MONEY_READ})
    # Widened into something they do not hold all of, or out of it.
    assert not may_change_role(admin, coach, coach | {Permission.EXPENSES_READ})
    assert not may_change_role(admin, TESORERO.permissions, coach)
    assert not may_change_role(admin, coach, ADMINISTRADOR.permissions)


# --- the database --------------------------------------------------------------------


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
    """A gym with the Academia roles, and the Club federado ones beside them."""
    gym_id = seed_gym(db, f"club-{uuid.uuid4().hex[:6]}")

    async def query(conn: asyncpg.Connection) -> None:
        for sort, title in enumerate((PRESIDENTE, TESORERO, SECRETARIO, DIRECTOR, DELEGADO)):
            await conn.execute(
                "INSERT INTO gym_title (id, gym_id, name, permissions, public, preset, sort)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7)",
                title_id(gym_id, title),
                gym_id,
                title.name,
                sorted(title.permissions),
                title.public,
                CLUB_FEDERADO,
                10 + sort,
            )

    run(db.admin_url, query)
    return gym_id


def title_id(gym: uuid.UUID, title: PresetTitle) -> uuid.UUID:
    preset = "academia" if title in (ADMINISTRADOR, COACH) else CLUB_FEDERADO
    return preset_title_id(gym, preset, title.key)


def staff(db: Database, gym: uuid.UUID, *titles: PresetTitle) -> uuid.UUID:
    """Someone on the staff list of `gym`, appointed from today to each of `titles`."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym,
                person,
            )
            # The row's role is read by nothing (#309); `coach` writes no appointment.
            await make_staff(conn, gym, person, "coach")
            await conn.execute("DELETE FROM staff_title WHERE person_id = $1", person)
            for title in titles:
                await conn.execute(
                    "INSERT INTO staff_title (gym_id, person_id, title_id, title_name,"
                    " starts_on) VALUES ($1, $2, $3, $4, $5)",
                    gym,
                    person,
                    title_id(gym, title),
                    title.name,
                    seeded_today(),
                )

    run(db.admin_url, query)
    return person


def titles_of(db: Database, person: uuid.UUID) -> set[str]:
    """The roles `person` holds today or from a later day."""
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT title_name FROM staff_title WHERE person_id = $1"
            " AND (ends_on IS NULL OR ends_on > $2)",
            person,
            seeded_today(),
        ),
    )
    return {r["title_name"] for r in rows}


def statuses(
    client: TestClient, headers: dict[str, str], calls: Iterable[tuple[str, str]]
) -> dict[str, int]:
    return {f"{m} {u}": client.request(m, u, headers=headers).status_code for m, u in calls}


# --- one permission, one area --------------------------------------------------------

# A title with `money_read` alone: Pagos and the money of any ficha.
MONEY_READ_ONLY = PresetTitle("lectura", "Revisora", frozenset({Permission.MONEY_READ}), False)
MEMBERS_ONLY = PresetTitle(
    "alumnos",
    "Encargada de alumnos",
    frozenset({Permission.MEMBERS_MANAGE, Permission.MEMBERS_ADD}),
    False,
)


def with_title(db: Database, gym: uuid.UUID, title: PresetTitle) -> uuid.UUID:
    """Someone appointed to a role of `gym` holding `title`'s permissions."""
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO gym_title (id, gym_id, name, permissions) VALUES ($1, $2, $3, $4)",
            preset_title_id(gym, "test", title.key),
            gym,
            title.name,
            sorted(title.permissions),
        ),
    )
    person = staff(db, gym)
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
            " VALUES ($1, $2, $3, $4, $5)",
            gym,
            person,
            preset_title_id(gym, "test", title.key),
            title.name,
            seeded_today(),
        ),
    )
    return person


@pg
def test_money_read_alone_reads_pagos_and_records_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    headers = as_gym(gym, with_title(db, gym, MONEY_READ_ONLY))
    reads = [
        ("GET", "/api/ledger/pending"),
        ("GET", "/api/ledger/overdue"),
        ("GET", "/api/extra-charges"),
        ("GET", "/api/ledger/proofs"),
        ("GET", "/api/freeze-requests"),
        ("GET", "/api/inactive"),
    ]
    assert set(statuses(client, headers, reads).values()) == {200}
    # A payment, a void, a cobro, a plan started or frozen, a reminder: each a 403
    # before its body is read.
    writes = [
        ("POST", "/api/ledger/payments"),
        ("POST", "/api/ledger/voids"),
        ("POST", "/api/extra-charges"),
        ("POST", "/api/memberships"),
        ("POST", f"/api/memberships/{uuid.uuid4()}/freeze"),
        ("POST", f"/api/reminders/{uuid.uuid4()}"),
        ("POST", f"/api/ledger/proofs/{uuid.uuid4()}/validate"),
    ]
    assert set(statuses(client, headers, writes).values()) == {403}
    # Nor anything of the members' or the gym's.
    others = [("POST", "/api/people"), ("POST", "/api/groups"), ("PATCH", "/api/gym/settings")]
    assert set(statuses(client, headers, others).values()) == {403}


@pg
def test_members_manage_alone_adds_and_edits_people_and_sees_no_amounts(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    headers = as_gym(gym, with_title(db, gym, MEMBERS_ONLY))
    added = client.post(
        "/api/people", json={"name": "Ana Pérez", "email": "ana@example.com"}, headers=headers
    )
    assert added.status_code == 201, added.text
    person = added.json()["id"]
    edited = client.patch(f"/api/people/{person}", json={"name": "Ana Rojas"}, headers=headers)
    assert (edited.status_code, edited.json()["name"]) == (200, "Ana Rojas")

    group = client.post(
        "/api/groups", json={"name": "Competidores", "person_ids": [person]}, headers=headers
    )
    assert group.status_code == 201, group.text
    # Dar de baja writes its `history_set` row, which the database lets them (0069).
    left = client.post(f"/api/people/{person}/leave", json={}, headers=headers)
    assert left.status_code == 200, left.text

    for url in ("/api/people", "/api/plans", f"/api/people/{person}"):
        answer = client.get(url, headers=headers)
        assert answer.status_code == 200, url
        assert money_keys(answer.json()) == [], url
    money = [("GET", "/api/ledger/pending"), ("POST", "/api/ledger/payments")]
    assert set(statuses(client, headers, money).values()) == {403}
    # A plan is money: enrolling someone on one is a 403, with none it is theirs.
    plan = run(db.admin_url, lambda c: c.fetchval("SELECT id FROM plan WHERE gym_id = $1", gym))
    enrol = {"name": "Beto", "email": "beto@example.com", "no_whatsapp": True}
    on_plan = {**enrol, "membership": {"plan_id": str(plan)}}
    assert client.post("/api/people/enrol", json=on_plan, headers=headers).status_code == 403
    assert client.post("/api/people/enrol", json=enrol, headers=headers).status_code == 201


@pg
def test_attendance_alone_runs_a_class_and_adds_nobody(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    headers = as_gym(gym, staff(db, gym, DELEGADO))
    class_type = run(
        db.admin_url,
        lambda c: c.fetchval(
            "WITH p AS (INSERT INTO program (gym_id, name) VALUES ($1, 'Kids') RETURNING id)"
            " INSERT INTO class_type (gym_id, program_id, name)"
            " SELECT $1, id, 'Kids' FROM p RETURNING id",
            gym,
        ),
    )
    started = client.post("/api/sessions", json={"class_type_id": str(class_type)}, headers=headers)
    assert started.status_code == 201, started.text
    roster = client.get(f"/api/sessions/{started.json()['id']}/roster", headers=headers)
    assert roster.status_code == 200, roster.text
    assert client.post("/api/people", json={}, headers=headers).status_code == 403
    assert client.get("/api/join-requests", headers=headers).status_code == 403


@pg
def test_no_permissions_is_on_the_team_and_does_nothing_more(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    headers = as_gym(gym, staff(db, gym, DIRECTOR))
    reads = [("GET", "/api/people"), ("GET", "/api/plans"), ("GET", "/api/sessions")]
    assert set(statuses(client, headers, reads).values()) == {200}
    writes = [("POST", "/api/people"), ("POST", "/api/sessions"), ("GET", "/api/staff")]
    assert set(statuses(client, headers, writes).values()) == {403}


# --- section 4: the team, by the strictly-fewer rule ---------------------------------


def appoint(
    client: TestClient, gym: uuid.UUID, by: uuid.UUID | None, person: uuid.UUID, title: PresetTitle
) -> Any:
    return client.post(
        f"/api/staff/{person}/appointments",
        json={"title_id": str(title_id(gym, title))},
        headers=as_gym(gym, by),
    )


def end(
    client: TestClient, gym: uuid.UUID, by: uuid.UUID | None, person: uuid.UUID, title: PresetTitle
) -> Any:
    return client.delete(
        f"/api/staff/{person}/appointments/{title_id(gym, title)}", headers=as_gym(gym, by)
    )


def refused(response: Any, reason: str) -> bool:
    return response.status_code == 403 and reason in response.json()["detail"]


PERSON_RULE = "people whose permissions are strictly fewer"
ROLE_RULE = "a role whose permissions are strictly fewer"


@pg
def test_an_administrador_does_not_touch_another(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    admin, other = staff(db, gym, ADMINISTRADOR), staff(db, gym, ADMINISTRADOR)
    headers = as_gym(gym, admin)
    assert refused(client.delete(f"/api/staff/{other}", headers=headers), PERSON_RULE)
    change = client.patch(f"/api/staff/{other}", json={"role": "coach"}, headers=headers)
    assert refused(change, PERSON_RULE)
    assert refused(end(client, gym, admin, other, ADMINISTRADOR), PERSON_RULE)
    invite = {"name": "Otra", "email": "otra@example.com", "role": "admin"}
    assert refused(client.post("/api/staff", json=invite, headers=headers), ROLE_RULE)
    assert titles_of(db, other) == {"Administrador"}


@pg
def test_an_administrador_appoints_and_ends_coaches(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    admin, coach = staff(db, gym, ADMINISTRADOR), staff(db, gym, COACH)
    headers = as_gym(gym, admin)
    invite = {"name": "Nuevo", "email": "nuevo@example.com", "role": "coach"}
    assert client.post("/api/staff", json=invite, headers=headers).status_code == 201
    # Not to a role as wide as their own.
    to_admin = client.patch(f"/api/staff/{coach}", json={"role": "admin"}, headers=headers)
    assert refused(to_admin, ROLE_RULE)
    assert end(client, gym, admin, coach, COACH).status_code == 204
    assert titles_of(db, coach) == set()
    assert appoint(client, gym, admin, coach, COACH).status_code == 201
    assert appoint(client, gym, admin, coach, COACH).status_code == 409
    assert titles_of(db, coach) == {"Coach"}
    assert client.delete(f"/api/staff/{coach}", headers=headers).status_code == 204


@pg
def test_a_presidente_appoints_only_a_director(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    presidente, someone = staff(db, gym, PRESIDENTE), staff(db, gym)
    assert appoint(client, gym, presidente, someone, DIRECTOR).status_code == 201
    for title in (SECRETARIO, DELEGADO, TESORERO, COACH, PRESIDENTE):
        assert refused(appoint(client, gym, presidente, someone, title), ROLE_RULE), title.name
    assert titles_of(db, someone) == {"Director"}
    # A Director holds nothing, so they are fewer; the board's other seats are not.
    assert end(client, gym, presidente, someone, DIRECTOR).status_code == 204
    for title in (SECRETARIO, DELEGADO, TESORERO):
        seated = staff(db, gym, title)
        assert refused(end(client, gym, presidente, seated, title), PERSON_RULE), title.name
        assert titles_of(db, seated) == {title.name}


@pg
def test_a_role_with_fewer_permissions_but_one_you_lack_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Tesorero holds four permissions to the Administrador's seven, two of them expenses.
    admin, someone = staff(db, gym, ADMINISTRADOR), staff(db, gym)
    assert refused(appoint(client, gym, admin, someone, TESORERO), ROLE_RULE)
    treasurer = staff(db, gym, TESORERO)
    assert refused(
        client.delete(f"/api/staff/{treasurer}", headers=as_gym(gym, admin)), PERSON_RULE
    )
    # And a Tesorero, without `team_manage`, manages nobody.
    assert appoint(client, gym, treasurer, someone, DIRECTOR).status_code == 403


@pg
def test_nobody_touches_the_titular_and_the_titular_touches_everyone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owner = seeded_owner(gym)
    admin, presidente = staff(db, gym, ADMINISTRADOR), staff(db, gym, PRESIDENTE)
    titular_fixed = "the account holder is not changed here"
    for by in (admin, presidente, None):
        assert refused(appoint(client, gym, by, owner, DIRECTOR), titular_fixed)
        assert refused(client.delete(f"/api/staff/{owner}", headers=as_gym(gym, by)), titular_fixed)
    # The titular, acting by default in these headers, appoints to any role and ends any.
    for title in (TESORERO, SECRETARIO, ADMINISTRADOR):
        assert appoint(client, gym, None, presidente, title).status_code == 201, title.name
    assert end(client, gym, None, admin, ADMINISTRADOR).status_code == 204
    assert titles_of(db, presidente) == {"Presidente", "Tesorero", "Secretario", "Administrador"}


@pg
def test_an_unknown_or_archived_role_is_not_found(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    someone = staff(db, gym)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_title SET archived_at = now() WHERE id = $1", title_id(gym, DIRECTOR)
        ),
    )
    assert appoint(client, gym, None, someone, DIRECTOR).status_code == 404
    unknown = client.post(
        f"/api/staff/{someone}/appointments",
        json={"title_id": str(uuid.uuid4())},
        headers=as_gym(gym),
    )
    assert unknown.status_code == 404
    assert end(client, gym, None, someone, COACH).status_code == 404
