"""The demo gym: the roster the UI design shows, consistent with the domain rules.

Most of this checks `build` alone. The Postgres tests load it twice into a migrated
database, as the owner, and read it back as the API user under RLS.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import asyncpg
import pytest

from app.domain.dates import add_months
from app.domain.membership import Membership, MembershipStatus, PlanKind, is_due_to_lapse
from app.domain.phone import normalize_phone
from app.domain.rut import is_valid_rut
from app.seed import Loaded, load
from app.seed.build import GYM_ID, Row, Seed, build, local, seed_id
from app.seed.data import (
    GENERATE_AHEAD_DAYS,
    GRACE_DAYS,
    GRADING,
    KIDS_LADDER,
    MEMBERS,
    RANKS,
    STRIPES,
)
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, throwaway_database

DESIGN_DAY = date(2026, 11, 8)  # "Hoy, sáb 8 nov" in docs/design/ui-design.html
# The design's day, a month-end, and the spring-forward Sunday in Santiago.
DAYS = [DESIGN_DAY, date(2027, 1, 31), date(2026, 9, 6)]

S = MembershipStatus


@pytest.fixture(scope="module", params=DAYS, ids=str)
def seed(request: pytest.FixtureRequest) -> Seed:
    day: date = request.param
    return build(day)


def by_id(rows: list[Row]) -> dict[object, Row]:
    return {row["id"]: row for row in rows}


def names(seed: Seed) -> dict[object, object]:
    return {p["id"]: p["name"] for p in seed.people}


def plan_kinds(seed: Seed) -> dict[object, PlanKind]:
    return {p["id"]: PlanKind(p["kind"]) for p in seed.plans}


def validated_payments(seed: Seed) -> dict[object, list[Row]]:
    paid = defaultdict(list)
    for e in seed.ledger_entries:
        if e["kind"] == "payment" and e["status"] == "validated":
            paid[e["billing_period_id"]].append(e)
    return paid


def overdue(seed: Seed) -> dict[object, tuple[int, int]]:
    """Active members with a period past due and no validated payment: (days, amount)."""
    memberships = by_id(seed.memberships)
    paid = validated_payments(seed)
    found = {}
    for p in seed.billing_periods:
        due = p["due_date"]
        assert isinstance(due, date)
        membership = memberships[p["membership_id"]]
        if due < seed.as_of and p["id"] not in paid and membership["status"] == "active":
            found[names(seed)[membership["person_id"]]] = (
                (seed.as_of - due).days,
                p["amount_due_clp"],
            )
    return found


def test_build_is_deterministic() -> None:
    assert build(DESIGN_DAY) == build(DESIGN_DAY)


def test_roster(seed: Seed) -> None:
    statuses = Counter(m["status"] for m in seed.memberships)
    # "64 membresías activas · 2 congeladas"
    assert statuses == {"active": 64, "frozen": 2, "trial": 2, "lapsed": 2, "cancelled": 1}
    assert {m["person_id"] for m in seed.memberships} <= {p["id"] for p in seed.people}
    assert len({m["person_id"] for m in seed.memberships}) == len(seed.memberships)
    assert Counter(s["role"] for s in seed.staff) == {"owner": 1, "admin": 1, "coach": 1}


def test_every_plan_kind(seed: Seed) -> None:
    kinds = plan_kinds(seed)
    assert set(kinds.values()) == set(PlanKind)
    # A drop-in is a single attendance, not a membership (app.domain.membership.create).
    held = Counter(kinds[m["plan_id"]] for m in seed.memberships)
    assert set(held) == set(PlanKind) - {PlanKind.DROPIN}


def test_guardians_pay_for_dependents(seed: Seed) -> None:
    people = by_id(seed.people)
    members = {m.key: m for m in MEMBERS}
    kids = [m for m in MEMBERS if m.is_kid]
    assert len(kids) >= 10
    families = Counter(m.guardian for m in kids)
    assert max(families.values()) >= 2
    for kid in kids:
        assert kid.guardian is not None
        assert not members[kid.guardian].is_kid
        person = people[seed_id("person", kid.key)]
        # Kids have no phone or email: everything goes to the guardian.
        assert (person["phone"], person["email"]) == (None, None)
        transfers = [
            e
            for e in seed.ledger_entries
            if e["membership_id"] == seed_id("membership", kid.key) and e["method"] == "transfer"
        ]
        assert transfers
        assert {e["claimed_by"] for e in transfers} == {seed_id("person", kid.guardian)}


def test_grading_scheme() -> None:
    ranks = [key for key, _ in RANKS]
    ladder = [key for key, _ in KIDS_LADDER]
    assert ranks == ["white", "blue", "purple", "brown", "black"]
    assert ladder[:3] == ["grey-white", "grey", "grey-black"]
    assert len(ladder) == 12
    assert GRADING["ranks"][1] == {"key": "blue", "label": "Azul", "sub_ranks": 4}
    assert GRADING["kids_ladder"][-1] == {
        "key": "green-black",
        "label": "Verde y negra",
        "sub_ranks": 4,
    }
    for member in MEMBERS:
        belt, stripes = member.rank
        assert 0 <= stripes <= STRIPES
        assert belt in (["white", *ladder] if member.is_kid else ranks), member.key


def test_design_overdue(seed: Seed) -> None:
    # "Vencido $270.000 · 6 alumnos · 5,3 días promedio"
    found = overdue(seed)
    assert len(found) == 6
    assert sum(amount for _, amount in found.values()) == 270_000
    assert round(sum(days for days, _ in found.values()) / len(found), 1) == 5.3
    assert found["Felipe Díaz"] == (9, 45_000)
    assert found["Javiera Silva"] == (4, 45_000)
    assert found["Tomás Pérez"] == (2, 30_000)


def test_design_pending_proofs(seed: Seed) -> None:
    # "Por validar $162.000 · 3 comprobantes"
    pending = [e for e in seed.ledger_entries if e["status"] == "pending"]
    assert all(e["kind"] == "payment" for e in pending)
    assert sum(e["amount_clp"] for e in pending) == 162_000
    who = names(seed)
    by_payer = Counter(who[e["claimed_by"]] for e in pending)
    assert by_payer == {"Diego Morales": 1, "Camila Ortiz": 2, "Catalina Reyes": 1}
    # Camila's one transfer covers Mateo and Sofía.
    memberships = by_id(seed.memberships)
    camila = {
        who[memberships[e["membership_id"]]["person_id"]]
        for e in pending
        if who[e["claimed_by"]] == "Camila Ortiz"
    }
    assert camila == {"Mateo Ortiz", "Sofía Ortiz"}


def test_design_credit_adjustment(seed: Seed) -> None:
    adjustments = [e for e in seed.ledger_entries if e["kind"] == "adjustment"]
    assert [(e["amount_clp"], e["note"]) for e in adjustments] == [
        (5_000, "Pagó $50.000, quedan $5.000 a favor")
    ]


def test_ledger_matches_billing_periods(seed: Seed) -> None:
    charges = Counter(e["billing_period_id"] for e in seed.ledger_entries if e["kind"] == "charge")
    assert set(charges) == {p["id"] for p in seed.billing_periods}
    assert set(charges.values()) == {1}
    periods = by_id(seed.billing_periods)
    for e in seed.ledger_entries:
        assert e["amount_clp"] > 0
        assert e["gym_id"] == GYM_ID
        if e["kind"] == "charge":
            assert e["amount_clp"] == periods[e["billing_period_id"]]["amount_due_clp"]
    for period_id, payments in validated_payments(seed).items():
        assert len(payments) == 1
        assert payments[0]["amount_clp"] >= periods[period_id]["amount_due_clp"]
    starts = Counter((p["membership_id"], p["period_start"]) for p in seed.billing_periods)
    assert set(starts.values()) == {1}


def test_memberships_follow_the_domain(seed: Seed) -> None:
    """Nobody is due to lapse who is not lapsed, and every lapse is past grace."""
    kinds = plan_kinds(seed)
    for row in seed.memberships:
        status = S(row["status"])
        membership = Membership(
            kinds[row["plan_id"]],
            S.ACTIVE if status is S.LAPSED else status,
            row["current_period_end"],
            row["credits_remaining"],
        )
        due = is_due_to_lapse(membership, seed.as_of, GRACE_DAYS)
        assert due is (status is S.LAPSED), row["id"]


def test_monthly_paid_through_and_generation(seed: Seed) -> None:
    kinds = plan_kinds(seed)
    paid = validated_payments(seed)
    periods: dict[object, list[Row]] = defaultdict(list)
    for p in seed.billing_periods:
        periods[p["membership_id"]].append(p)
    for m in seed.memberships:
        if kinds[m["plan_id"]] is not PlanKind.MONTHLY:
            continue
        own = sorted(periods[m["id"]], key=lambda p: p["period_start"])
        ends = [p["period_end"] for p in own if p["id"] in paid]
        if ends:
            assert m["current_period_end"] == ends[-1]
        if m["status"] == "active":
            # The nightly job would already have generated the next one (#31).
            last = own[-1]["period_start"]
            assert isinstance(last, date)
            next_start = add_months(last, 1, anchor_day=m["anchor_day"])
            assert next_start > seed.as_of + timedelta(days=GENERATE_AHEAD_DAYS)


def test_people_are_valid(seed: Seed) -> None:
    phones = [p["phone"] for p in seed.people if p["phone"] is not None]
    assert len(phones) == len(set(phones))
    for phone in phones:
        assert isinstance(phone, str)
        assert normalize_phone(phone) == phone
    for person in seed.people:
        assert isinstance(person["rut"], str)
        assert is_valid_rut(person["rut"])
    assert next(p for p in seed.people if p["name"] == "Felipe Díaz")["phone"] == "+56998214417"


def test_nothing_happens_after_the_seed_date(seed: Seed) -> None:
    end = local(seed.as_of + timedelta(days=1))
    for _, rows in seed.tables():
        for row in rows:
            for column in ("created_at", "claimed_at", "validated_at", "started_at"):
                value = row.get(column)
                if isinstance(value, datetime):
                    assert value < end, (row, column)


# --- Postgres ---


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def load_as_owner(db: Database, today: date | None) -> Loaded:
    async def go(conn: asyncpg.Connection) -> Loaded:
        return await load(conn, today)

    loaded: Loaded = run(db.owner_url, go)
    return loaded


@pytest.mark.postgres
def test_load_is_idempotent(db: Database) -> None:
    first = load_as_owner(db, DESIGN_DAY)
    assert first.inserted == {table: len(rows) for table, rows in first.seed.tables()}

    again = load_as_owner(db, None)
    assert again.seed == first.seed
    assert set(again.inserted.values()) == {0}
    assert again.ignored_today is None

    # The first load fixed the date the rows depict.
    later = load_as_owner(db, DESIGN_DAY + timedelta(days=30))
    assert later.seed.as_of == DESIGN_DAY
    assert later.ignored_today == DESIGN_DAY + timedelta(days=30)
    assert set(later.inserted.values()) == {0}


@pytest.mark.postgres
def test_api_user_reads_the_whole_gym(db: Database) -> None:
    seed = load_as_owner(db, DESIGN_DAY).seed
    for table, rows in seed.tables():
        found = run(db.api_url, in_gym(GYM_ID, f"SELECT count(*) AS n FROM {table}"))
        # Every person has a membership or staff row, so RLS hides none of them.
        assert found[0]["n"] == len(rows), table
    assert run(db.api_url, in_gym(None, "SELECT count(*) AS n FROM person"))[0]["n"] == 0
