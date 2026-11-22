"""Rows for the demo gym as it stands on a given seed date. Pure: no I/O.

Every id is a UUIDv5 of the row's natural key, so building twice gives the same rows
and loading them again inserts nothing new.
"""

import hashlib
import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.billing import GENERATE_AHEAD_DAYS, discounted, overpayment_note
from app.domain.dates import add_months
from app.domain.extra_charges import instalment_dates, instalments
from app.domain.ledger import EntryKind, EntryStatus
from app.domain.membership import CONVERTED_REASON, MembershipStatus, PlanKind
from app.domain.rut import check_digit
from app.domain.schedule import HORIZON_DAYS, horizon
from app.permissions import ACADEMIA, preset_title_id
from app.roles import TITLE_OF, Role
from app.seed.data import (
    ACTIVITY,
    ACTIVITY_PRESET,
    BANK_ACCOUNT,
    CLASS_DAYS,
    CLASS_PLANS,
    CLASS_TAGS,
    CLASS_TYPES,
    COACH,
    CUSTOM_FIELDS,
    GRACE_DAYS,
    GRADING,
    GYM_NAME,
    GYM_SLUG,
    HISTORY_PERIODS,
    INSTALMENT_CHARGES,
    MEDICAL_EXPIRING_AT,
    MEDICAL_EXPIRING_DAYS,
    MEDICAL_PENDING_EVERY,
    MEMBERS,
    OPEN_MAT_PLAN,
    PERSON_REQUIREMENTS,
    PLANS,
    PRIVACY,
    PROGRAMS,
    RANKS,
    REQUIREMENTS,
    SLOT_TAGS,
    SLOTS,
    STAFF,
    TIMEZONE,
    VALIDATOR,
    Block,
    MemberSpec,
    Method,
    PlanSpec,
    Standing,
    slug,
)

Row = dict[str, Any]

NAMESPACE = uuid.UUID("0ac7a356-11a0-4d87-b85f-6c8398b269c3")
ZONE = ZoneInfo(TIMEZONE)
CANCEL_REASON = "Se cambió de ciudad"

# A frozen member's freeze, in days from the seed date: started a week ago, ends in three.
FREEZE_DAYS = (-7, 21)
FREEZE_REASONS = ("Viaje familiar", "Vacaciones")


def seed_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join((GYM_SLUG, *parts)))


GYM_ID = seed_id("gym")


def default_block_kind_id(gym_id: uuid.UUID, key: str) -> uuid.UUID:
    """The id of a gym's default block kind, as migration 0028's
    `block_kind_default_id` derives it: every gym is given them when it is created."""
    return uuid.UUID(hashlib.md5(f"{gym_id}/block_kind/{key}".encode()).hexdigest())


def default_expense_category_id(gym_id: uuid.UUID, key: str) -> uuid.UUID:
    """The id of a gym's default expense category, as migration 0083's
    `add_default_expense_categories` derives it: every gym is given them when it is
    created."""
    return uuid.UUID(hashlib.md5(f"{gym_id}/expense_category/{key}".encode()).hexdigest())


@dataclass(frozen=True)
class Seed:
    as_of: date
    gym: Row
    people: list[Row]
    # The gym's own record of each person (migration 0004): what `person` holds.
    gym_people: list[Row]
    # Who pays for each kid (migration 0010).
    guardian_links: list[Row]
    staff: list[Row]
    # The admin's and the coach's appointments to the Academia roles every gym is
    # given; the owner holds the account instead (migration 0065).
    staff_titles: list[Row]
    # What it teaches (migration 0043): one activity, graded, with every class type.
    activities: list[Row]
    # Programs and their class types (migration 0017).
    programs: list[Row]
    class_types: list[Row]
    plans: list[Row]
    memberships: list[Row]
    billing_periods: list[Row]
    ledger_entries: list[Row]
    # The frozen members' freezes (migration 0017).
    freezes: list[Row]
    # Each member's current rank (migration 0018), and the promotions before it of
    # those who list them.
    grade_events: list[Row]
    # What the gym asks before someone trains, and when it was done for whom (0062).
    requirements: list[Row]
    person_requirements: list[Row]
    # Cobros extra in cuotas (0072), one line per person and cuota.
    extra_charges: list[Row]
    extra_lines: list[Row]
    # The adults' weekly schedule (migration 0035), the classes it made (0020): those of
    # the last weeks, who was at each (0023) and the blocks each ran (0028), of the kinds
    # every gym is given, and those from the seed date through the schedule's horizon.
    schedule_slots: list[Row]
    sessions: list[Row]
    attendance: list[Row]
    session_blocks: list[Row]
    # The gym's class tags, each slot's, and those on the classes held (0041).
    class_tags: list[Row]
    slot_tags: list[Row]
    session_tags: list[Row]
    # What the gym spent these three months (0083), under the categories every gym is
    # given: rent, power, water, internet and pay, and one voided as typed twice.
    expenses: list[Row]
    # The gastos fijos behind the monthly ones (0085): rent, internet and pay fixed,
    # power and water estimated. Those whose day has not come this month are on its card.
    recurring_expenses: list[Row]

    def tables(self) -> Iterator[tuple[str, list[Row]]]:
        """Each table's rows, in an order the foreign keys accept."""
        yield "gym", [self.gym]
        # A demo, no one's: it has no terms to accept (#499), and nothing waits on them.
        yield "gym_terms", [{"gym_id": self.gym["id"], "exempt": True}]
        yield "person", self.people
        yield "gym_person", self.gym_people
        yield "guardian_link", self.guardian_links
        yield "requirement", self.requirements
        yield "person_requirement", self.person_requirements
        yield "staff", self.staff
        yield "staff_title", self.staff_titles
        yield "gym_activity", self.activities
        yield "program", self.programs
        yield "class_type", self.class_types
        yield "plan", self.plans
        yield "membership", self.memberships
        yield "grade_event", self.grade_events
        yield "billing_period", self.billing_periods
        yield "extra_charge", self.extra_charges
        yield "extra_line", self.extra_lines
        yield "ledger_entry", self.ledger_entries
        yield "membership_freeze", self.freezes
        yield "schedule_slot", self.schedule_slots
        yield "session", self.sessions
        yield "attendance", self.attendance
        yield "session_block", self.session_blocks
        yield "class_tag", self.class_tags
        yield "schedule_slot_tag", self.slot_tags
        yield "session_tag", self.session_tags
        yield "expense_recurring", self.recurring_expenses
        yield "expense", self.expenses


def local(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """A gym-local wall time as an aware UTC instant (see `start_of_local_day` on DST)."""
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE).astimezone(UTC)


def season(as_of: date) -> tuple[date, date]:
    """The seed's fixed-period plan's first and last day: the calendar year of `as_of`."""
    return date(as_of.year, 1, 1), date(as_of.year, 12, 31)


def _rng(*parts: object) -> random.Random:
    return random.Random("/".join((GYM_SLUG, *map(str, parts))))


def _person(key: str, name: str, *, joined: date, kid: bool, phone: str | None = None) -> Row:
    rng = _rng("person", key)
    age = rng.randrange(5, 14) if kid else rng.randrange(19, 49)
    dob = joined.replace(
        year=joined.year - age, month=rng.randrange(1, 13), day=rng.randrange(1, 29)
    )
    # Kids have no phone or email: everything goes to the guardian.
    if not kid and phone is None:
        phone = f"+569{rng.randrange(10**7, 10**8):08d}"
    body = rng.randrange(23_000_000, 26_000_000) if kid else rng.randrange(8_000_000, 21_000_000)
    return {
        "id": seed_id("person", key),
        "phone": phone,
        "email": None if kid else f"{slug(name).replace('-', '.')}@example.com",
        "name": name,
        "rut": f"{body}-{check_digit(body)}",
        "dob": dob,
        "created_at": local(joined),
    }


@dataclass(frozen=True)
class _Period:
    start: date
    end: date
    due: date
    # `None` for a period generated ahead that is not due yet.
    standing: Standing | None
    # Days before `due` the period and its charge were generated.
    lead_days: int = GENERATE_AHEAD_DAYS
    # The member's latest period, which `MemberSpec.at` times.
    latest: bool = False


class _Builder:
    def __init__(self, as_of: date) -> None:
        self.as_of = as_of
        self.plans = {p.key: p for p in PLANS}
        self.people: list[Row] = []
        self.memberships: list[Row] = []
        self.periods: list[Row] = []
        self.entries: list[Row] = []
        self.freezes: list[Row] = []
        self.grades: list[Row] = []
        # When each member joined, by key.
        self.joined: dict[str, datetime] = {}
        self.validator = seed_id("person", VALIDATOR)

    def day(self, offset: int) -> date:
        return self.as_of + timedelta(days=offset)

    def member(self, spec: MemberSpec) -> None:
        plan = self.plans[spec.plan]
        membership_id = seed_id("membership", spec.key)
        payer = seed_id("person", spec.guardian or spec.key)
        periods, paid_through, since = self._periods(spec, plan)
        anchor_day = self.day(spec.due_in).day if plan.kind is PlanKind.MONTHLY else None
        if spec.status is MembershipStatus.FROZEN:
            periods, paid_through, anchor_day = self._frozen(periods, paid_through, anchor_day)
        self.people.append(
            _person(spec.key, spec.name, joined=since, kid=spec.is_kid, phone=spec.phone)
        )
        self.joined[spec.key] = local(since)
        cancelled = spec.status is MembershipStatus.CANCELLED
        trial_id = self._trial(spec, since) if spec.trial_before is not None else None
        credits = spec.credits_remaining
        if plan.kind is PlanKind.TRIAL:
            credits = plan.credits if credits is None else credits
        self.memberships.append(
            {
                "id": membership_id,
                "gym_id": GYM_ID,
                "person_id": seed_id("person", spec.key),
                "plan_id": seed_id("plan", plan.key),
                "status": spec.status.value,
                "anchor_day": anchor_day,
                "started_at": local(since),
                "current_period_end": paid_through,
                "credits_remaining": credits,
                "discount_pct": spec.discount_pct,
                "discount_reason": spec.discount_reason,
                "created_at": local(since),
                # On the due date of the period they did not pay.
                "cancel_reason": CANCEL_REASON if cancelled else None,
                "cancelled_at": local(self.day(spec.due_in), 20) if cancelled else None,
                "converted_from": trial_id,
            }
        )
        if spec.status is MembershipStatus.FROZEN:
            self._freeze(spec, membership_id)
        self.grades += self._promotions(spec, membership_id)
        self.grades.append(self._grade(spec, membership_id, since))
        amount = discounted(plan.price_clp, spec.discount_pct)
        for index, period in enumerate(periods):
            self._period(spec, membership_id, payer, index, period, amount)

    def _trial(self, spec: MemberSpec, since: date) -> uuid.UUID:
        """The trial `spec` came in on, `trial_before` days before their plan started: its
        free classes taken, ended by the plan as `domain.end_converted` ends one. Its id,
        for the plan's `converted_from`."""
        assert spec.trial_before is not None
        plan = self.plans["trial"]
        assert plan.credit_expiry_days is not None
        trial_id = seed_id("membership", spec.key, "trial")
        start = since - timedelta(days=spec.trial_before)
        self.memberships.append(
            {
                "id": trial_id,
                "gym_id": GYM_ID,
                "person_id": seed_id("person", spec.key),
                "plan_id": seed_id("plan", plan.key),
                "status": MembershipStatus.CANCELLED.value,
                "anchor_day": None,
                "started_at": local(start),
                "current_period_end": start + timedelta(days=plan.credit_expiry_days - 1),
                "credits_remaining": 0,
                "discount_pct": 0,
                "discount_reason": None,
                "created_at": local(start),
                "cancel_reason": CONVERTED_REASON,
                "cancelled_at": local(since),
                "converted_from": None,
            }
        )
        return trial_id

    def _promotions(self, spec: MemberSpec, membership_id: uuid.UUID) -> list[Row]:
        """The promotions `spec` lists before their current rank, each that night."""
        return [
            {
                "id": seed_id("grade_event", spec.key, rank, str(sub_rank)),
                "gym_id": GYM_ID,
                "person_id": seed_id("person", spec.key),
                "membership_id": membership_id,
                "rank_key": rank,
                "sub_rank": str(sub_rank),
                "awarded_on": self.day(offset),
                "awarded_by": seed_id("person", COACH),
                "note": None,
                "created_at": local(self.day(offset), 21, 15),
            }
            for rank, sub_rank, offset in spec.promotions
        ]

    def _frozen(
        self, periods: list[_Period], paid_through: date, anchor_day: int | None
    ) -> tuple[list[_Period], date, int | None]:
        """A frozen member's periods, paid-through date and anchor day, as
        `app.domain.membership.freeze` left them: a frozen membership is not billed, so
        no period starts once the freeze has, and the due date moved past the frozen
        days. A period starting before the freeze stands, as `freeze` keeps it."""
        start, end = (self.day(offset) for offset in FREEZE_DAYS)
        kept = [p for p in periods if p.start < start]
        billed_through = max(p.end for p in kept)
        paid_through = max(paid_through, billed_through) + (end - start)
        anchor = None if anchor_day is None else (paid_through + timedelta(days=1)).day
        return kept, paid_through, anchor

    def _freeze(self, spec: MemberSpec, membership_id: uuid.UUID) -> None:
        start, end = (self.day(offset) for offset in FREEZE_DAYS)
        self.freezes.append(
            {
                "id": seed_id("freeze", spec.key),
                "gym_id": GYM_ID,
                "membership_id": membership_id,
                "from_date": start,
                "to_date": end,
                "reason": FREEZE_REASONS[len(self.freezes) % len(FREEZE_REASONS)],
                "created_by": self.validator,
                "created_at": local(start, 18, 30),
            }
        )

    def _grade(self, spec: MemberSpec, membership_id: uuid.UUID, since: date) -> Row:
        """The promotion that gave the member their rank, recorded by a coach that night."""
        rank, stripes = spec.rank
        rng = _rng("grade", spec.key)
        if spec.ranked_in is not None:
            awarded = self.day(spec.ranked_in)
        elif rank == RANKS[0][0] and not stripes:
            awarded = since
        else:
            awarded = since + timedelta(days=rng.randrange(max((self.as_of - since).days, 1)))
        return {
            "id": seed_id("grade_event", spec.key),
            "gym_id": GYM_ID,
            "person_id": seed_id("person", spec.key),
            "membership_id": membership_id,
            "rank_key": rank,
            "sub_rank": str(stripes),
            "awarded_on": awarded,
            "awarded_by": seed_id("person", COACH),
            "note": None,
            "created_at": local(awarded, 21, rng.randrange(60)),
        }

    def _periods(self, spec: MemberSpec, plan: PlanSpec) -> tuple[list[_Period], date, date]:
        """The member's billing periods, paid-through date and start date."""
        anchor = self.day(spec.due_in)
        if plan.kind is PlanKind.FIXED_PERIOD:
            # Joined weeks before `due_in`'s day: one period, due when they joined or
            # on its first day if later, as `app.domain.billing` bills it.
            first, last = season(self.as_of)
            since = max(first, anchor - timedelta(days=45))
            owed = None if since > self.as_of else spec.standing
            period = _Period(first, last, since, owed, latest=True)
            paid_through = last if owed is Standing.PAID else since - timedelta(days=1)
            return [period], paid_through, since
        if plan.kind is PlanKind.TRIAL:
            assert plan.credit_expiry_days is not None
            return [], anchor + timedelta(days=plan.credit_expiry_days - 1), anchor
        if plan.kind is PlanKind.CREDITS:
            assert plan.credit_expiry_days is not None
            end = anchor + timedelta(days=plan.credit_expiry_days - 1)
            since = add_months(anchor, -spec.since_months)
            # A pack is charged when it is bought.
            pack = _Period(anchor, end, anchor, spec.standing, lead_days=0, latest=True)
            return [pack], end, since

        months = plan.period_months or 1
        if plan.kind is PlanKind.PREPAID:
            # `anchor` is when the next block falls due; it is generated once close.
            latest = anchor if spec.due_in <= GENERATE_AHEAD_DAYS else add_months(anchor, -months)
        else:
            latest = anchor
        # Whole periods: a membership starts on the first day of one.
        since_months = spec.since_months - spec.since_months % months
        since = add_months(latest, -since_months, anchor_day=latest.day)
        count = min(HISTORY_PERIODS, since_months // months) + 1
        periods: list[_Period] = []
        for back in reversed(range(count)):
            start = add_months(latest, -back * months, anchor_day=latest.day)
            end = add_months(start, months, anchor_day=latest.day) - timedelta(days=1)
            standing: Standing | None = spec.standing if back == 0 else Standing.PAID
            if standing is Standing.PAID and start > self.as_of:
                # Generated ahead and not due yet; a proof may already be in (PENDING).
                standing = None
            periods.append(_Period(start, end, start, standing, latest=not back))
        paid = [p.end for p in periods if p.standing is Standing.PAID]
        paid_through = paid[-1] if paid else periods[0].start - timedelta(days=1)
        return periods, paid_through, since

    def _period(
        self,
        spec: MemberSpec,
        membership_id: uuid.UUID,
        payer: uuid.UUID,
        index: int,
        period: _Period,
        amount: int,
    ) -> None:
        start, due = period.start, period.due
        period_id = seed_id("billing_period", spec.key, start.isoformat())
        generated = local(due - timedelta(days=period.lead_days), 0, 10)
        self.periods.append(
            {
                "id": period_id,
                "gym_id": GYM_ID,
                "membership_id": membership_id,
                "period_start": start,
                "period_end": period.end,
                "amount_due_clp": amount,
                "due_date": due,
                "created_at": generated,
            }
        )
        entry: Row = {
            "gym_id": GYM_ID,
            "membership_id": membership_id,
            "billing_period_id": period_id,
            "method": None,
            "claimed_by": None,
            "claimed_at": None,
            "validated_by": None,
            "validated_at": None,
            "proof_object_key": None,
            "note": None,
            "extra_line_id": None,
        }
        self.entries.append(
            {
                **entry,
                "id": seed_id("ledger_entry", spec.key, start.isoformat(), "charge"),
                "amount_clp": amount,
                "kind": EntryKind.CHARGE.value,
                "status": EntryStatus.VALIDATED.value,
                "validated_at": generated,
                "created_at": generated,
            }
        )
        state = period.standing
        if state not in (Standing.PAID, Standing.PENDING):
            return

        if period.latest and spec.at is not None:
            offset, hour, minute = spec.at
            claimed = local(self.day(offset), hour, minute)
        else:
            rng = _rng("payment", spec.key, index)
            # Around the due date, never before the charge nor after yesterday.
            early = due + timedelta(days=rng.randrange(-3, 3) if period.lead_days else 0)
            day = min(max(early, due - timedelta(days=period.lead_days)), self.day(-1))
            claimed = local(day, rng.randrange(9, 23), rng.randrange(60))
        payment_id = seed_id("ledger_entry", spec.key, start.isoformat(), "payment")
        cash = spec.method is Method.CASH
        payment: Row = {
            **entry,
            "id": payment_id,
            "amount_clp": amount + spec.overpaid_clp,
            "kind": EntryKind.PAYMENT.value,
            "status": EntryStatus.PENDING.value,
            "method": spec.method.value,
            # An admin records cash; a transfer's proof is sent by whoever pays.
            "claimed_by": self.validator if cash else payer,
            "claimed_at": claimed,
            "proof_object_key": None if cash else f"proofs/{GYM_ID}/{payment_id}.jpg",
            "created_at": claimed,
        }
        if state is Standing.PENDING:
            self.entries.append(payment)
            return
        validated = claimed if cash else claimed + timedelta(hours=3)
        self.entries.append(
            {
                **payment,
                "status": EntryStatus.VALIDATED.value,
                "validated_by": self.validator,
                "validated_at": validated,
            }
        )
        if spec.overpaid_clp:
            self.entries.append(
                {
                    **entry,
                    "id": seed_id("ledger_entry", spec.key, start.isoformat(), "credit"),
                    "billing_period_id": None,
                    "amount_clp": spec.overpaid_clp,
                    "kind": EntryKind.ADJUSTMENT.value,
                    "status": EntryStatus.VALIDATED.value,
                    "validated_by": self.validator,
                    "validated_at": validated,
                    "note": overpayment_note(amount + spec.overpaid_clp, spec.overpaid_clp),
                    "created_at": validated,
                }
            )


def _block(session_id: uuid.UUID, position: int, block: Block, rng: random.Random) -> Row:
    """One block of a class as it ran: on time give or take, or a round or two short."""
    key, planned = block
    row: Row = {
        "id": seed_id("session_block", str(session_id), str(position)),
        "gym_id": GYM_ID,
        "session_id": session_id,
        "position": position,
        "block_kind_id": default_block_kind_id(GYM_ID, key),
    }
    if isinstance(planned, int):
        actual = planned + rng.choice((-120, 0, 0, 0, 60))
        no_rounds = dict.fromkeys(
            ("rounds_planned", "rounds_completed", "round_seconds", "rest_seconds")
        )
        return {**row, "planned_seconds": planned, "actual_seconds": actual, **no_rounds}
    rounds, round_seconds, rest_seconds = planned
    completed = rounds - rng.choice((0, 0, 0, 1, 2))
    return {
        **row,
        "planned_seconds": rounds * round_seconds,
        "actual_seconds": completed * round_seconds,
        "rounds_planned": rounds,
        "rounds_completed": completed,
        "round_seconds": round_seconds,
        "rest_seconds": rest_seconds,
    }


def _classes(as_of: date, memberships: list[Row]) -> dict[str, list[Row]]:
    """The `SLOTS` of the schedule, held since `CLASS_DAYS` before `as_of` and run as
    `CLASS_PLANS`, with a slot's `turnout` share of the adults on a monthly, prepaid or season
    plan marked at each, which spends no credits; and the classes the schedule has made
    from `as_of` through its horizon, as the nightly `schedule` job would have, none
    marked yet."""
    adults = {
        seed_id("plan", p.key)
        for p in PLANS
        if p.program == "adults"
        and p.kind in (PlanKind.MONTHLY, PlanKind.PREPAID, PlanKind.FIXED_PERIOD)
    }
    regulars = [
        m
        for m in memberships
        if m["plan_id"] in adults and m["status"] == MembershipStatus.ACTIVE.value
    ]
    coach = seed_id("person", COACH)
    open_mats = {c.key for c in CLASS_TYPES if c.open_mat}
    valid_from = as_of - timedelta(days=CLASS_DAYS)
    # Written the evening before its first class, which made its classes through the
    # horizon at once; the nightly run made each later one as it came into it.
    written = local(valid_from - timedelta(days=1), 18)
    _, last = horizon(as_of)
    slots: list[Row] = []
    sessions: list[Row] = []
    attendance: list[Row] = []
    blocks: list[Row] = []
    tags = [
        {"id": seed_id("class_tag", name), "gym_id": GYM_ID, "name": name, "created_at": written}
        for name in CLASS_TAGS
    ]
    slot_tags = [
        {
            "gym_id": GYM_ID,
            "slot_id": seed_id("schedule_slot", key),
            "tag_id": seed_id("class_tag", n),
        }
        for key, names in SLOT_TAGS.items()
        for n in names
    ]
    session_tags: list[Row] = []
    for slot in SLOTS:
        slots.append(
            {
                "id": seed_id("schedule_slot", slot.key),
                "gym_id": GYM_ID,
                "class_type_id": seed_id("class_type", slot.class_type),
                "weekdays": list(slot.weekdays),
                "start_time": time(slot.hour),
                "duration_minutes": slot.duration_minutes,
                "coach_id": coach,
                "valid_from": valid_from,
                "generated_until": last,
                "created_at": written,
                "updated_at": written,
            }
        )
    days = (valid_from + timedelta(days=n) for n in range((last - valid_from).days + 1))
    for day in days:
        for slot, slot_row in zip(SLOTS, slots, strict=True):
            if day.isoweekday() not in slot.weekdays:
                continue
            starts_at = local(day, slot.hour)
            made = max(written, local(day - timedelta(days=HORIZON_DAYS - 1), 0, 5))
            session_id = seed_id("session", day.isoformat(), slot.key)
            sessions.append(
                {
                    "id": session_id,
                    "gym_id": GYM_ID,
                    "class_type_id": slot_row["class_type_id"],
                    "starts_at": starts_at,
                    "duration_minutes": slot.duration_minutes,
                    "coach_id": coach,
                    "slot_id": slot_row["id"],
                    "slot_date": day,
                    "created_at": made,
                    "updated_at": made,
                }
            )
            if day >= as_of:
                continue
            rng = _rng("session", session_id)
            session_tags += [
                {"gym_id": GYM_ID, "session_id": session_id, "tag_id": seed_id("class_tag", n)}
                for n in SLOT_TAGS.get(slot.key, ())
            ]
            alternate = CLASS_PLANS[len(sessions) % 2]
            plan = OPEN_MAT_PLAN if slot.class_type in open_mats else alternate
            blocks += [_block(session_id, i, block, rng) for i, block in enumerate(plan)]
            attendance += [
                {
                    "gym_id": GYM_ID,
                    "session_id": session_id,
                    "membership_id": m["id"],
                    "marked_by": coach,
                    "marked_at": starts_at + timedelta(minutes=10),
                    "credits_consumed": 0,
                }
                for m in regulars
                if m["started_at"] < starts_at and rng.random() < slot.turnout
            ]
    return {
        "schedule_slots": slots,
        "sessions": sessions,
        "attendance": attendance,
        "session_blocks": blocks,
        "class_tags": tags,
        "slot_tags": slot_tags,
        "session_tags": session_tags,
    }


def _requirements(as_of: date, joined: dict[str, datetime]) -> dict[str, list[Row]]:
    """`REQUIREMENTS`, in their order, and each member's records as the validator
    recorded them on the day each was done: the waiver on the day they `joined`, the
    certificate as `MEDICAL_PENDING_EVERY` has it, then `PERSON_REQUIREMENTS`."""
    validator = seed_id("person", VALIDATOR)
    opened = local(add_months(as_of, -60))
    requirements = [
        {
            "id": seed_id("requirement", r.key),
            "gym_id": GYM_ID,
            "name": r.name,
            "valid_months": r.valid_months,
            "position": position,
            "created_at": opened,
        }
        for position, r in enumerate(REQUIREMENTS)
    ]
    done: dict[tuple[str, str], tuple[date, str | None]] = {}
    for index, member in enumerate(MEMBERS):
        first = joined[member.key].astimezone(ZONE).date()
        done[member.key, "waiver"] = (first, None)
        if index % MEDICAL_PENDING_EVERY == MEDICAL_PENDING_EVERY - 1:
            continue
        if index % MEDICAL_PENDING_EVERY == MEDICAL_EXPIRING_AT:
            medical = as_of + timedelta(days=MEDICAL_EXPIRING_DAYS)
        else:
            medical = as_of - timedelta(days=_rng("medical", member.key).randrange(1, 300))
        done[member.key, "medical"] = (max(medical, first), None)
    for who, key, offset, note in PERSON_REQUIREMENTS:
        done[who, key] = (as_of + timedelta(days=offset), note)
    records = [
        {
            "id": seed_id("person_requirement", who, key),
            "gym_id": GYM_ID,
            "person_id": seed_id("person", who),
            "requirement_id": seed_id("requirement", key),
            "done_on": day,
            "note": note,
            "recorded_by": validator,
            "recorded_at": local(day, 19, 30),
        }
        for (who, key), (day, note) in done.items()
    ]
    return {"requirements": requirements, "person_requirements": records}


def _extra_charges(as_of: date) -> tuple[list[Row], list[Row], list[Row]]:
    """`INSTALMENT_CHARGES`: each cobro, its lines, and the cash payments of the first
    cuotas paid, the day before they fell due."""
    validator = seed_id("person", VALIDATOR)
    charges: list[Row] = []
    lines: list[Row] = []
    payments: list[Row] = []
    for c in INSTALMENT_CHARGES:
        first = as_of + timedelta(days=c.due_in)
        created = local(first - timedelta(days=20), 18)
        charge_id = seed_id("extra_charge", c.key)
        charges.append(
            {
                "id": charge_id,
                "gym_id": GYM_ID,
                "title": c.title,
                "category": c.category,
                "due_date": first,
                "amount_mode": "fixed",
                "amount_clp": c.amount_clp,
                "target_kind": "people",
                "instalments": c.instalments,
                "created_by": validator,
                "created_at": created,
            }
        )
        amounts = instalments(c.amount_clp, c.instalments)
        dates = instalment_dates(first, c.instalments)
        for who in c.people:
            for n, (amount, due) in enumerate(zip(amounts, dates, strict=True), start=1):
                line_id = seed_id("extra_line", c.key, who, str(n))
                lines.append(
                    {
                        "id": line_id,
                        "gym_id": GYM_ID,
                        "extra_charge_id": charge_id,
                        "person_id": seed_id("person", who),
                        "amount_due_clp": amount,
                        "instalment": n,
                        "due_date": due,
                        "created_at": created,
                    }
                )
                if n != 1 or who not in c.paid_first:
                    continue
                paid = local(due - timedelta(days=1), 19, 45)
                payments.append(
                    {
                        "id": seed_id("ledger_entry", "extra_line", str(line_id), "payment"),
                        "gym_id": GYM_ID,
                        "membership_id": None,
                        "billing_period_id": None,
                        "extra_line_id": line_id,
                        "amount_clp": amount,
                        "kind": EntryKind.PAYMENT.value,
                        "status": EntryStatus.VALIDATED.value,
                        "method": "cash",
                        "claimed_by": validator,
                        "claimed_at": paid,
                        "validated_by": validator,
                        "validated_at": paid,
                        "proof_object_key": None,
                        "note": None,
                        "created_at": paid,
                    }
                )
    return charges, lines, payments


# Each month's expenses: the category's key, the day of the month it is paid, the
# amounts of the month two before the seed's, the one before and the seed's own, the
# payee and the method. Each is recorded from its gasto fijo (`_recurring_expenses`).
MONTHLY_EXPENSES = (
    ("sueldos", 1, (600_000, 600_000, 600_000), "Sebastián Araya", "transfer"),
    ("arriendo", 5, (650_000, 650_000, 650_000), "Inmobiliaria Los Robles", "transfer"),
    ("internet", 10, (32_990, 32_990, 32_990), "Movistar", "card"),
    ("luz", 20, (78_400, 91_200, 84_000), "Enel", "transfer"),
    ("agua", 22, (18_500, 17_900, 19_300), "Aguas Andinas", "transfer"),
)
# The bills whose amount changes month to month: their template is an estimate.
ESTIMATED_EXPENSES = frozenset({"luz", "agua"})


def _recurring_expenses(as_of: date) -> list[Row]:
    """A gasto fijo for each of `MONTHLY_EXPENSES`, made before the first month the
    seed records, at the last amount the seed's month before had."""
    made = local(add_months(as_of.replace(day=1), -2), 9)
    return [
        {
            "id": seed_id("expense_recurring", key),
            "gym_id": GYM_ID,
            "category_id": default_expense_category_id(GYM_ID, key),
            "payee": payee,
            "method": method,
            "amount_clp": amounts[1],
            "amount_kind": "estimated" if key in ESTIMATED_EXPENSES else "fixed",
            "day_of_month": day_of_month,
            "active": True,
            "created_by": seed_id("person", VALIDATOR),
            "created_at": made,
        }
        for key, day_of_month, amounts, payee, method in MONTHLY_EXPENSES
    ]


def _expenses(as_of: date) -> list[Row]:
    """`MONTHLY_EXPENSES` up to the seed date, the federation's yearly fee last month,
    last month's internet typed twice, the second voided, and the polerones the gym
    bought, which their cobro extra recovers (#318)."""
    by = seed_id("person", VALIDATOR)
    this_month = as_of.replace(day=1)
    rows: list[Row] = []

    def spent(
        key: str, n: str, day: date, amount: int, payee: str, method: str, monthly: bool = True
    ) -> Row:
        recorded = local(day, 20)
        return {
            "id": seed_id("expense", key, n),
            "gym_id": GYM_ID,
            "spent_on": day,
            "amount_clp": amount,
            "category_id": default_expense_category_id(GYM_ID, key),
            "payee": payee,
            "method": method,
            "note": None,
            "receipt_object_key": None,
            "recurring_id": seed_id("expense_recurring", key) if monthly else None,
            "extra_charge_id": None,
            "created_by": by,
            "created_at": recorded,
            "voided_at": None,
            "voided_by": None,
            "void_reason": None,
        }

    for back in (2, 1, 0):
        month = add_months(this_month, -back)
        for key, day_of_month, amounts, payee, method in MONTHLY_EXPENSES:
            day = month.replace(day=day_of_month)
            if day <= as_of:
                rows.append(spent(key, month.isoformat(), day, amounts[2 - back], payee, method))
    last_month = add_months(this_month, -1)
    fee = spent(
        "federacion",
        last_month.isoformat(),
        last_month.replace(day=15),
        120_000,
        "Federación Nacional",
        "transfer",
        monthly=False,
    )
    rows.append({**fee, "note": "Cuota anual de afiliación"})
    twice = spent(
        "internet",
        f"{last_month.isoformat()}/twice",
        last_month.replace(day=10),
        32_990,
        "Movistar",
        "card",
    )
    voided = local(last_month.replace(day=12), 9)
    rows.append(
        {**twice, "voided_at": voided, "voided_by": by, "void_reason": "Registrado dos veces"}
    )
    # Bought before their cobro was made (`_extra_charges`: 20 days before its first
    # cuota), for less than the three people pay for them.
    [poleron] = [c for c in INSTALMENT_CHARGES if c.key == "poleron"]
    bought = as_of + timedelta(days=poleron.due_in - 25)
    polerones = spent(
        "equipamiento", "poleron", bought, 96_000, "Confecciones Andes", "transfer", monthly=False
    )
    rows.append(
        {
            **polerones,
            "note": "Polerones oficiales",
            "extra_charge_id": seed_id("extra_charge", poleron.key),
        }
    )
    return rows


def build(as_of: date) -> Seed:
    """The demo gym as it stands on `as_of`, a gym-local date."""
    builder = _Builder(as_of)
    for spec in MEMBERS:
        builder.member(spec)

    opened = add_months(as_of, -60)
    extra_charges, extra_lines, extra_payments = _extra_charges(as_of)
    staff_people = [_person(s.key, s.name, joined=opened, kid=False) for s in STAFF]
    people = [*staff_people, *builder.people]
    return Seed(
        as_of=as_of,
        gym={
            "id": GYM_ID,
            "name": GYM_NAME,
            "slug": GYM_SLUG,
            "timezone": TIMEZONE,
            "settings": {
                "grace_days": GRACE_DAYS,
                "bank_account": BANK_ACCOUNT,
                "privacy": {**PRIVACY, "updated_on": as_of.isoformat()},
                "grading": GRADING,
                "custom_fields": CUSTOM_FIELDS,
                # The date the rows depict; a re-run builds for this date again.
                "seed": {"as_of": as_of.isoformat()},
            },
            "created_at": local(opened),
        },
        # The phone is the gym's, a contact on its record (0036), not the person's.
        people=[{c: v for c, v in p.items() if c != "phone"} for p in people],
        gym_people=[
            {
                "gym_id": GYM_ID,
                "person_id": p["id"],
                **{c: p[c] for c in ("name", "email", "rut", "phone", "dob")},
                "created_at": p["created_at"],
                "updated_at": p["created_at"],
            }
            for p in people
        ],
        guardian_links=[
            {
                "gym_id": GYM_ID,
                "guardian_person_id": seed_id("person", m.guardian),
                "dependent_person_id": seed_id("person", m.key),
                "created_at": builder.joined[m.key],
            }
            for m in MEMBERS
            if m.guardian is not None
        ],
        staff=[
            {
                "gym_id": GYM_ID,
                "person_id": seed_id("person", s.key),
                "role": s.role.value,
                "account_holder": s.role is Role.OWNER,
                "created_at": local(opened),
            }
            for s in STAFF
        ],
        staff_titles=[
            {
                "id": seed_id("staff_title", s.key),
                "gym_id": GYM_ID,
                "person_id": seed_id("person", s.key),
                "title_id": preset_title_id(GYM_ID, ACADEMIA, TITLE_OF[s.role].key),
                "title_name": TITLE_OF[s.role].name,
                "starts_on": opened,
                "created_at": local(opened),
            }
            for s in STAFF
            if s.role in TITLE_OF
        ],
        activities=[
            {
                "id": seed_id("gym_activity", ACTIVITY),
                "gym_id": GYM_ID,
                "name": ACTIVITY,
                "uses_grades": True,
                "preset": ACTIVITY_PRESET,
                "created_at": local(opened),
            }
        ],
        programs=[
            {
                "id": seed_id("program", key),
                "gym_id": GYM_ID,
                "name": name,
                "active": True,
                "created_at": local(opened),
            }
            for key, name in PROGRAMS.items()
        ],
        class_types=[
            {
                "id": seed_id("class_type", c.key),
                "gym_id": GYM_ID,
                "program_id": seed_id("program", c.program),
                "activity_id": seed_id("gym_activity", ACTIVITY),
                "name": c.name,
                "credit_cost": c.credit_cost,
                "kind": "open_mat" if c.open_mat else "class",
                "counts_as_class": not c.open_mat,
                "active": True,
                "created_at": local(opened),
            }
            for c in CLASS_TYPES
        ],
        plans=[
            {
                "id": seed_id("plan", p.key),
                "gym_id": GYM_ID,
                "name": p.name,
                "kind": p.kind.value,
                "program_id": None if p.program is None else seed_id("program", p.program),
                "price_clp": p.price_clp,
                "enrolment_fee_clp": p.enrolment_fee_clp,
                "anchor": p.anchor,
                "period_months": p.period_months,
                "period_start": season(as_of)[0] if p.kind is PlanKind.FIXED_PERIOD else None,
                "period_end": season(as_of)[1] if p.kind is PlanKind.FIXED_PERIOD else None,
                "credits": p.credits,
                "credit_expiry_days": p.credit_expiry_days,
                "active": True,
                "created_at": local(opened),
            }
            for p in PLANS
        ],
        memberships=builder.memberships,
        billing_periods=builder.periods,
        ledger_entries=[*builder.entries, *extra_payments],
        freezes=builder.freezes,
        grade_events=builder.grades,
        **_requirements(as_of, builder.joined),
        extra_charges=extra_charges,
        extra_lines=extra_lines,
        **_classes(as_of, builder.memberships),
        expenses=_expenses(as_of),
        recurring_expenses=_recurring_expenses(as_of),
    )
