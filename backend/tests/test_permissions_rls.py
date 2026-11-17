"""Each permission holds at the database (#309, #310, docs/design/expenses-and-officers.md,
section 7).

Every policy that asks `app_can` has a case here: what `rakin_app` does under it, and
the permission it needs. For each, run as `rakin_app` in a transaction that is rolled
back, a person holding only that permission (with what it implies) succeeds, a person
holding every permission but that one gets nothing, and so does a person whose
appointment to it ended yesterday. The titular, holding the account, succeeds at all of
it. The staff rows carry the role that would have decided before (`coach` for the one
who succeeds, `admin` for the ones who do not), so these pass only when the database
reads permissions and not `staff.role`.

A drift test holds the list to the database: no policy names a role, and every policy
that asks `app_can` is a case here, so a new money table cannot ship without one.
"""

import json
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import asyncpg
import pytest

from app.permissions import IMPLIES, Permission
from tests.conftest import require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)

pytestmark = pytest.mark.postgres

ALL = frozenset(Permission)


@dataclass(frozen=True)
class Gym:
    """The rows each case reads, writes or deletes, seeded in one gym."""

    id: uuid.UUID
    owner: uuid.UUID
    pending_entry: uuid.UUID
    charge: uuid.UUID
    line: uuid.UUID
    group: uuid.UUID
    empty_group: uuid.UUID
    session: uuid.UUID
    history_payment: uuid.UUID
    newcomer: uuid.UUID  # in the gym, on no line and in no group


Args = Callable[[Gym, uuid.UUID], tuple[object, ...]]
Holder = Callable[[frozenset[Permission], bool, str], uuid.UUID]


@dataclass(frozen=True)
class Case:
    """What `rakin_app` does under `policy`, which needs `permission`. `sql` takes the
    arguments `args` builds from the gym and the person acting; it succeeds when it
    returns or touches a row."""

    policy: str
    permission: Permission
    sql: str
    args: Args = lambda gym, actor: (gym.id,)

    @property
    def id(self) -> str:
        return f"{self.policy}:{self.sql.split()[0].lower()}"


EXPENSE_ACTION = "expense_changed"
# The team's actions (0071), read with `team_manage` alone.
TEAM_ACTIONS = (
    "('title_created', 'title_changed', 'appointment_started', 'appointment_ended',"
    " 'appointment_corrected')"
)

CASES = (
    Case(
        "ledger_entry_read", Permission.MONEY_READ, "SELECT id FROM ledger_entry WHERE gym_id = $1"
    ),
    Case(
        "ledger_entry_insert",
        Permission.MONEY_WRITE,
        "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, method)"
        " SELECT gym_id, id, 1000, 'payment', 'cash' FROM membership WHERE gym_id = $1",
    ),
    Case(
        "ledger_entry_update",
        Permission.MONEY_WRITE,
        "UPDATE ledger_entry SET note = 'revisado' WHERE id = $1",
        lambda gym, actor: (gym.pending_entry,),
    ),
    Case(
        "extra_charge_read", Permission.MONEY_READ, "SELECT id FROM extra_charge WHERE gym_id = $1"
    ),
    Case(
        "extra_charge_insert",
        Permission.MONEY_WRITE,
        "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode, amount_clp,"
        " target_kind) VALUES ($1, 'Rifa', 'rifa', '2026-12-01', 'fixed', 1000, 'people')",
    ),
    Case(
        "extra_charge_update",
        Permission.MONEY_WRITE,
        "UPDATE extra_charge SET description = 'Para el viaje' WHERE id = $1",
        lambda gym, actor: (gym.charge,),
    ),
    Case("extra_line_read", Permission.MONEY_READ, "SELECT id FROM extra_line WHERE gym_id = $1"),
    Case(
        "extra_line_insert",
        Permission.MONEY_WRITE,
        "INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp)"
        " VALUES ($1, $2, $3, 1000)",
        lambda gym, actor: (gym.id, gym.charge, gym.newcomer),
    ),
    Case(
        "extra_line_update",
        Permission.MONEY_WRITE,
        "UPDATE extra_line SET amount_due_clp = 2000 WHERE id = $1",
        lambda gym, actor: (gym.line,),
    ),
    Case(
        "charge_group_insert",
        Permission.MEMBERS_MANAGE,
        "INSERT INTO charge_group (gym_id, name) VALUES ($1, 'Nuevo')",
    ),
    Case(
        "charge_group_update",
        Permission.MEMBERS_MANAGE,
        "UPDATE charge_group SET name = 'Renombrado' WHERE id = $1",
        lambda gym, actor: (gym.group,),
    ),
    Case(
        "charge_group_delete",
        Permission.MEMBERS_MANAGE,
        "DELETE FROM charge_group WHERE id = $1",
        lambda gym, actor: (gym.empty_group,),
    ),
    Case(
        "charge_group_member_insert",
        Permission.MEMBERS_MANAGE,
        "INSERT INTO charge_group_member (gym_id, group_id, person_id) VALUES ($1, $2, $3)",
        lambda gym, actor: (gym.id, gym.group, gym.newcomer),
    ),
    Case(
        "charge_group_member_delete",
        Permission.MEMBERS_MANAGE,
        "DELETE FROM charge_group_member WHERE group_id = $1",
        lambda gym, actor: (gym.group,),
    ),
    Case(
        "session_delete",
        Permission.GYM_SETUP,
        "DELETE FROM session WHERE id = $1",
        lambda gym, actor: (gym.session,),
    ),
    Case(
        "audit_event_read",
        Permission.MONEY_READ,
        "SELECT id FROM audit_event WHERE gym_id = $1 AND NOT starts_with(action, 'expense_')"
        f" AND action NOT IN {TEAM_ACTIONS}",
    ),
    Case(
        "audit_event_read",
        Permission.TEAM_MANAGE,
        f"SELECT id FROM audit_event WHERE gym_id = $1 AND action IN {TEAM_ACTIONS}",
    ),
    Case(
        "audit_event_read",
        Permission.EXPENSES_READ,
        "SELECT id FROM audit_event WHERE gym_id = $1 AND starts_with(action, 'expense_')",
    ),
    Case(
        "audit_event_correct",
        Permission.MONEY_WRITE,
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $3, 'ledger_corrected', '{}')",
        lambda gym, actor: (gym.id, actor, gym.owner),
    ),
    Case(
        "audit_event_correct",
        Permission.MEMBERS_MANAGE,
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $3, 'history_set', '{}')",
        lambda gym, actor: (gym.id, actor, gym.owner),
    ),
    Case(
        "audit_event_discount",
        Permission.MONEY_WRITE,
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $3, 'discount_changed', '{}')",
        lambda gym, actor: (gym.id, actor, gym.owner),
    ),
    Case(
        "audit_event_team",
        Permission.TEAM_MANAGE,
        "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
        " VALUES ($1, $2, 'title_created', '{}')",
        lambda gym, actor: (gym.id, actor),
    ),
    Case(
        "audit_event_team",
        Permission.TEAM_MANAGE,
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $3, 'appointment_started', '{}')",
        lambda gym, actor: (gym.id, actor, gym.owner),
    ),
    Case(
        "audit_event_backfill",
        Permission.ATTENDANCE,
        "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
        " VALUES ($1, $2, 'class_backfilled', '{}')",
        lambda gym, actor: (gym.id, actor),
    ),
    Case(
        "audit_event_backfill",
        Permission.ATTENDANCE,
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $3, 'attendance_backfilled', '{}')",
        lambda gym, actor: (gym.id, actor, gym.owner),
    ),
    Case(
        "audit_event_import",
        Permission.GYM_SETUP,
        "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
        " VALUES ($1, $2, 'history_imported', '{}')",
        lambda gym, actor: (gym.id, actor),
    ),
    Case(
        "history_payment_read",
        Permission.MONEY_READ,
        "SELECT id FROM history_payment WHERE gym_id = $1",
    ),
    Case(
        "history_payment_write",
        Permission.MONEY_WRITE,
        "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
        " created_by) VALUES ($1, $2, '2020-03-01', 30000, 'manual', $3)",
        lambda gym, actor: (gym.id, gym.owner, actor),
    ),
    Case(
        "history_payment_remove",
        Permission.MONEY_WRITE,
        "DELETE FROM history_payment WHERE id = $1",
        lambda gym, actor: (gym.history_payment,),
    ),
)


def with_implied(permission: Permission) -> frozenset[Permission]:
    """`permission` and what holding it brings with it, as a role stores them."""
    implied = IMPLIES.get(permission)
    return frozenset({permission} if implied is None else {permission, implied})


def all_but(permission: Permission) -> frozenset[Permission]:
    """Every permission except `permission` and those that bring it with them."""
    return frozenset(p for p in ALL if permission not in with_implied(p))


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def superuser(db: Database, sql: str, *args: object) -> Any:
    """As the superuser, whom RLS does not hold."""
    return run(db.admin_url, lambda c: c.fetchval(sql, *args))


@pytest.fixture(scope="module")
def gym(db: Database) -> Gym:
    gym_id = seed_gym(db, "academia-sur")
    owner = seeded_owner(gym_id)

    def one(sql: str, *args: object) -> Any:
        """`sql` in this gym, `$1` its id."""
        return superuser(db, sql, gym_id, *args)

    pending_entry = one(
        "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, method)"
        " SELECT gym_id, id, 45000, 'payment', 'transfer' FROM membership WHERE gym_id = $1"
        " RETURNING id"
    )
    charge = one(
        "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode, amount_clp,"
        " target_kind) VALUES ($1, 'Seminario', 'seminario', '2026-12-01', 'fixed', 20000,"
        " 'people') RETURNING id"
    )
    line = one(
        "INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp)"
        " VALUES ($1, $2, $3, 20000) RETURNING id",
        charge,
        owner,
    )
    group = one("INSERT INTO charge_group (gym_id, name) VALUES ($1, 'Kids') RETURNING id")
    one(
        "INSERT INTO charge_group_member (gym_id, group_id, person_id) VALUES ($1, $2, $3)",
        group,
        owner,
    )
    empty_group = one("INSERT INTO charge_group (gym_id, name) VALUES ($1, 'Vacío') RETURNING id")
    session = one(
        "WITH p AS (INSERT INTO program (gym_id, name) VALUES ($1, 'Adultos') RETURNING id),"
        " t AS (INSERT INTO class_type (gym_id, program_id, name)"
        "       SELECT $1, id, 'Clase' FROM p RETURNING id)"
        " INSERT INTO session (gym_id, class_type_id, starts_at, coach_id)"
        " SELECT $1, id, now(), $2 FROM t RETURNING id",
        owner,
    )
    history_payment = one(
        "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
        " created_by) VALUES ($1, $2, '2019-05-01', 30000, 'manual', $2) RETURNING id",
        owner,
    )
    one(
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        " VALUES ($1, $2, $2, 'ledger_corrected', '{}')",
        owner,
    )
    # A team's row (0071), which only `team_manage` reads.
    one(
        "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
        " VALUES ($1, $2, 'title_created', '{}')",
        owner,
    )
    # An expense's row, which #314 adds the action for: this database lets it in early.
    superuser(db, "ALTER TABLE audit_event DROP CONSTRAINT audit_event_action_check")
    one(
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
        f" VALUES ($1, $2, $2, '{EXPENSE_ACTION}', '{{}}')",
        owner,
    )
    newcomer = uuid.uuid4()
    superuser(db, "INSERT INTO person (id, name) VALUES ($1, 'x')", newcomer)
    one("INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", newcomer)
    return Gym(
        gym_id,
        owner,
        pending_entry,
        charge,
        line,
        group,
        empty_group,
        session,
        history_payment,
        newcomer,
    )


@pytest.fixture(scope="module")
def holder(db: Database, gym: Gym) -> Holder:
    """Someone on the team holding a role with exactly `permissions`: from a month ago
    and still, or until today, so their last day with it was yesterday. `role` is their
    `staff.role`, which the database no longer reads."""
    made: dict[tuple[frozenset[Permission], bool, str], uuid.UUID] = {}
    today = seeded_today()

    def make(permissions: frozenset[Permission], ended: bool, role: str) -> uuid.UUID:
        if (permissions, ended, role) in made:
            return made[permissions, ended, role]
        person = uuid.uuid4()

        async def query(conn: asyncpg.Connection) -> None:
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym.id,
                person,
            )
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)",
                gym.id,
                person,
                role,
            )
            title = await conn.fetchval(
                "INSERT INTO gym_title (gym_id, name, permissions) VALUES ($1, $2, $3)"
                " RETURNING id",
                gym.id,
                f"Cargo {person}",
                sorted(permissions),
            )
            await conn.execute(
                "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on,"
                " ends_on) VALUES ($1, $2, $3, 'Cargo', $4, $5)",
                gym.id,
                person,
                title,
                today - timedelta(days=30),
                today if ended else None,
            )

        run(db.admin_url, query)
        made[permissions, ended, role] = person
        return person

    return make


class _RolledBack(Exception):
    def __init__(self, touched: int) -> None:
        self.touched = touched


def touched(db: Database, gym: Gym, person: uuid.UUID, case: Case) -> int:
    """How many rows `case` reads or writes as `person` through `rakin_app`, in a
    transaction rolled back after; 0 when a policy refuses the write."""

    async def query(conn: asyncpg.Connection) -> int:
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym.id))
                await conn.execute("SELECT set_config('app.person_id', $1, true)", str(person))
                args = case.args(gym, person)
                if case.sql.startswith("SELECT"):
                    count = len(await conn.fetch(case.sql, *args))
                else:
                    count = int((await conn.execute(case.sql, *args)).split()[-1])
                raise _RolledBack(count)
        except _RolledBack as done:
            return done.touched
        except asyncpg.InsufficientPrivilegeError as refused:
            assert "row-level security" in str(refused)
            return 0

    result: int = run(db.api_url, query)
    return result


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_only_that_permission_succeeds(db: Database, gym: Gym, holder: Holder, case: Case) -> None:
    # A coach's row, whom the roles kept out of everything here.
    person = holder(with_implied(case.permission), False, "coach")
    assert touched(db, gym, person, case) > 0


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_every_other_permission_gets_nothing(
    db: Database, gym: Gym, holder: Holder, case: Case
) -> None:
    # An admin's row, whom the roles let into everything here.
    person = holder(all_but(case.permission), False, "admin")
    assert touched(db, gym, person, case) == 0


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_an_ended_appointment_gets_nothing(
    db: Database, gym: Gym, holder: Holder, case: Case
) -> None:
    person = holder(ALL, True, "admin")
    assert touched(db, gym, person, case) == 0


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_titular_does_it_all(db: Database, gym: Gym, case: Case) -> None:
    assert touched(db, gym, gym.owner, case) > 0


def test_money_read_alone_reads_the_ledger_and_cannot_add_to_it(
    db: Database, gym: Gym, holder: Holder
) -> None:
    person = holder(frozenset({Permission.MONEY_READ}), False, "admin")
    [read] = [c for c in CASES if c.policy == "ledger_entry_read"]
    [insert] = [c for c in CASES if c.policy == "ledger_entry_insert"]
    assert touched(db, gym, person, read) > 0
    assert touched(db, gym, person, insert) == 0


def test_app_can_is_evaluated_once_per_query(db: Database, gym: Gym) -> None:
    """On `ledger_entry`, the largest table, `app_can` is an initplan: the scan's filter
    reads its result, and never calls it per row."""
    [[plan]] = run(
        db.api_url,
        in_gym(
            gym.id, "EXPLAIN (VERBOSE, FORMAT JSON) SELECT id FROM ledger_entry", person=gym.owner
        ),
    )
    scan = json.loads(plan)[0]["Plan"]
    assert scan["Relation Name"] == "ledger_entry"
    assert "app_can" not in scan["Filter"]
    initplans = {
        p["Subplan Name"]: " ".join(p.get("Output", []))
        for p in scan["Plans"]
        if p["Parent Relationship"] == "InitPlan"
    }
    [money_read] = [name for name, output in initplans.items() if "'money_read'" in output]
    assert f"({money_read})" in scan["Filter"]


POLICIES = (
    "SELECT tablename, policyname, coalesce(qual, '') || ' ' || coalesce(with_check, '') AS expr"
    " FROM pg_policies"
)
NAMES_A_ROLE = re.compile(r"\brole\b")
ASKS = re.compile(r"app_can\('(\w+)'")


def drift(policies: list[asyncpg.Record]) -> list[str]:
    """What is wrong with the database's policies: one that names a role, one that asks
    `app_can` with no case here, or for no permission there is."""
    covered = {c.policy for c in CASES}
    problems = []
    for p in policies:
        if NAMES_A_ROLE.search(p["expr"]):
            problems.append(f"{p['tablename']}.{p['policyname']} names a role")
        asked = ASKS.findall(p["expr"])
        if asked and p["policyname"] not in covered:
            problems.append(f"{p['tablename']}.{p['policyname']} has no case")
        problems += [f"{p['policyname']} asks for {a}" for a in asked if a not in set(Permission)]
    return problems


def test_no_policy_names_a_role_and_every_permission_policy_has_a_case(db: Database) -> None:
    policies = run(db.admin_url, lambda c: c.fetch(POLICIES))
    assert drift(policies) == []
    assert {p["policyname"] for p in policies if ASKS.search(p["expr"])} == {
        c.policy for c in CASES
    }


@pytest.mark.parametrize(
    ("policy", "problem"),
    [
        (
            "CREATE POLICY plan_by_role ON plan FOR DELETE TO rakin_app USING (EXISTS ("
            "SELECT FROM staff s WHERE s.person_id = NULLIF(current_setting('app.person_id',"
            " true), '')::uuid AND s.role = 'admin'))",
            "plan.plan_by_role names a role",
        ),
        (
            "CREATE POLICY plan_by_permission ON plan FOR DELETE TO rakin_app"
            " USING ((SELECT app_can('gym_setup')))",
            "plan.plan_by_permission has no case",
        ),
    ],
    ids=["names-a-role", "no-case"],
)
def test_the_drift_test_fails_on_a_policy_it_should_refuse(
    db: Database, policy: str, problem: str
) -> None:
    async def query(conn: asyncpg.Connection) -> list[asyncpg.Record]:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(policy)
            return list(await conn.fetch(POLICIES))
        finally:
            await tx.rollback()

    assert problem in drift(run(db.admin_url, query))
