"""Rows for the demo gym as it stands on a given seed date. Pure: no I/O.

Every id is a UUIDv5 of the row's natural key, so building twice gives the same rows
and loading them again inserts nothing new.
"""

import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.billing import GENERATE_AHEAD_DAYS, discounted, overpayment_note
from app.domain.dates import add_months
from app.domain.ledger import EntryKind, EntryStatus
from app.domain.membership import MembershipStatus, PlanKind
from app.domain.rut import check_digit
from app.seed.data import (
    BANK_ACCOUNT,
    CUSTOM_FIELDS,
    GRACE_DAYS,
    GRADING,
    GYM_NAME,
    GYM_SLUG,
    HISTORY_PERIODS,
    MEMBERS,
    PLANS,
    STAFF,
    TIMEZONE,
    VALIDATOR,
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
FREEZE_REASONS = ("Viaje familiar", "Lesión de rodilla")


def seed_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join((GYM_SLUG, *parts)))


GYM_ID = seed_id("gym")


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
    plans: list[Row]
    memberships: list[Row]
    billing_periods: list[Row]
    ledger_entries: list[Row]
    # The frozen members' freezes (migration 0016).
    freezes: list[Row]

    def tables(self) -> Iterator[tuple[str, list[Row]]]:
        """Each table's rows, in an order the foreign keys accept."""
        yield "gym", [self.gym]
        yield "person", self.people
        yield "gym_person", self.gym_people
        yield "guardian_link", self.guardian_links
        yield "staff", self.staff
        yield "plan", self.plans
        yield "membership", self.memberships
        yield "billing_period", self.billing_periods
        yield "ledger_entry", self.ledger_entries
        yield "membership_freeze", self.freezes


def local(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """A gym-local wall time as an aware UTC instant (see `start_of_local_day` on DST)."""
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE).astimezone(UTC)


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
        self.people.append(
            _person(spec.key, spec.name, joined=since, kid=spec.is_kid, phone=spec.phone)
        )
        self.joined[spec.key] = local(since)
        cancelled = spec.status is MembershipStatus.CANCELLED
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
                "anchor_day": self.day(spec.due_in).day if plan.kind is PlanKind.MONTHLY else None,
                "started_at": local(since),
                "current_period_end": paid_through,
                "credits_remaining": credits,
                "discount_pct": spec.discount_pct,
                "created_at": local(since),
                # On the due date of the period they did not pay.
                "cancel_reason": CANCEL_REASON if cancelled else None,
                "cancelled_at": local(self.day(spec.due_in), 20) if cancelled else None,
            }
        )
        if spec.status is MembershipStatus.FROZEN:
            self._freeze(spec, membership_id)
        amount = discounted(plan.price_clp, spec.discount_pct)
        for index, period in enumerate(periods):
            self._period(spec, membership_id, payer, index, period, amount)

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

    def _periods(self, spec: MemberSpec, plan: PlanSpec) -> tuple[list[_Period], date, date]:
        """The member's billing periods, paid-through date and start date."""
        anchor = self.day(spec.due_in)
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


def build(as_of: date) -> Seed:
    """The demo gym as it stands on `as_of`, a gym-local date."""
    builder = _Builder(as_of)
    for spec in MEMBERS:
        builder.member(spec)

    opened = add_months(as_of, -60)
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
                "grading": GRADING,
                "custom_fields": CUSTOM_FIELDS,
                # The date the rows depict; a re-run builds for this date again.
                "seed": {"as_of": as_of.isoformat()},
            },
            "created_at": local(opened),
        },
        people=people,
        gym_people=[
            {
                "gym_id": GYM_ID,
                "person_id": p["id"],
                **{c: p[c] for c in ("name", "email", "rut", "dob")},
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
                "created_at": local(opened),
            }
            for s in STAFF
        ],
        plans=[
            {
                "id": seed_id("plan", p.key),
                "gym_id": GYM_ID,
                "name": p.name,
                "kind": p.kind.value,
                "price_clp": p.price_clp,
                "anchor": p.anchor,
                "period_months": p.period_months,
                "credits": p.credits,
                "credit_expiry_days": p.credit_expiry_days,
                "active": True,
                "created_at": local(opened),
            }
            for p in PLANS
        ],
        memberships=builder.memberships,
        billing_periods=builder.periods,
        ledger_entries=builder.entries,
        freezes=builder.freezes,
    )
