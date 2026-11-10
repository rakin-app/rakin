"""The demo gym: the roster the UI design shows, consistent with the domain rules.

Most of this checks `build` alone. The Postgres tests load it twice into a migrated
database, as the owner, and read it back as the API user under RLS.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import asyncpg
import pytest

from app.domain.billing import GENERATE_AHEAD_DAYS
from app.domain.dates import add_months
from app.domain.membership import Membership, MembershipStatus, PlanKind, is_due_to_lapse
from app.domain.phone import normalize_phone
from app.domain.rut import is_valid_rut
from app.seed import Loaded, load
from app.seed.build import (
    GYM_ID,
    ZONE,
    Row,
    Seed,
    build,
    default_block_kind_id,
    local,
    seed_id,
)
from app.seed.data import (
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
    # Each kid is linked to the member who pays for them, and nobody else is.
    assert {(g["guardian_person_id"], g["dependent_person_id"]) for g in seed.guardian_links} == {
        (seed_id("person", kid.guardian), seed_id("person", kid.key))
        for kid in kids
        if kid.guardian is not None
    }


def test_grading_scheme() -> None:
    ranks = [key for key, _ in RANKS]
    ladder = [key for key, _ in KIDS_LADDER]
    assert ranks == ["white", "blue", "purple", "brown", "black"]
    assert ladder[:3] == ["grey-white", "grey", "grey-black"]
    assert len(ladder) == 12
    assert GRADING["ranks"][1]["label"] == "Azul"
    assert GRADING["kids_ladder"][-1]["label"] == "Verde y negra"
    assert [s["key"] for s in GRADING["ranks"][1]["sub_ranks"]] == ["0", "1", "2", "3", "4"]
    for member in MEMBERS:
        belt, stripes = member.rank
        assert 0 <= stripes <= STRIPES
        assert belt in (["white", *ladder] if member.is_kid else ranks), member.key


def test_each_member_holds_their_rank_by_a_promotion(seed: Seed) -> None:
    memberships = by_id(seed.memberships)
    grades = {g["membership_id"]: g for g in seed.grade_events}
    assert len(grades) == len(seed.grade_events) == len(MEMBERS)
    for member in MEMBERS:
        membership = memberships[seed_id("membership", member.key)]
        grade = grades[membership["id"]]
        assert (grade["rank_key"], grade["sub_rank"]) == (member.rank[0], str(member.rank[1]))
        assert grade["awarded_by"] == seed_id("person", "sebastian")
        started = membership["started_at"].astimezone(ZONE).date()
        if member.ranked_in is None:
            assert started <= grade["awarded_on"] <= seed.as_of, member.key


def test_design_rank_dates() -> None:
    grades = {g["membership_id"]: g for g in build(DESIGN_DAY).grade_events}
    diego = grades[seed_id("membership", "diego-morales")]
    # "Morada · 1 grado, desde 14 jun 2025" on his student page.
    assert (diego["rank_key"], diego["sub_rank"]) == ("purple", "1")
    assert diego["awarded_on"] == date(2025, 6, 14)


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


def test_weeks_of_classes_ran_in_blocks(seed: Seed) -> None:
    """Every session ran blocks of the default kinds; an open mat ran one of rounds; the
    adults at each are active members of a plan for them that spends no credits."""
    assert len(seed.sessions) >= 15
    open_mat = seed_id("class_type", "open-mat")
    sparring = default_block_kind_id(GYM_ID, "sparring")
    by_session: defaultdict[object, list[Row]] = defaultdict(list)
    for block in seed.session_blocks:
        by_session[block["session_id"]].append(block)
        assert 0 < block["actual_seconds"] <= block["planned_seconds"] + 60
        if block["block_kind_id"] == sparring:
            assert block["actual_seconds"] == block["rounds_completed"] * block["round_seconds"]
    for session in seed.sessions:
        assert session["starts_at"] < local(seed.as_of)
        blocks = by_session[session["id"]]
        if session["class_type_id"] == open_mat:
            assert [b["block_kind_id"] for b in blocks] == [sparring]
        else:
            assert len(blocks) == 4
    memberships = {m["id"]: m for m in seed.memberships}
    for mark in seed.attendance:
        membership = memberships[mark["membership_id"]]
        assert membership["status"] == MembershipStatus.ACTIVE.value
        assert mark["credits_consumed"] == 0
    assert len(seed.attendance) >= 5 * len(seed.sessions)


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
    # As the gym's owner, who may read the ledger (migration 0006).
    owner = next(s["person_id"] for s in seed.staff if s["role"] == "owner")
    for table, rows in seed.tables():
        found = run(db.api_url, in_gym(GYM_ID, f"SELECT count(*) AS n FROM {table}", person=owner))
        # Every person has a membership or staff row, so RLS hides none of them.
        assert found[0]["n"] == len(rows), table
    assert run(db.api_url, in_gym(None, "SELECT count(*) AS n FROM person"))[0]["n"] == 0
