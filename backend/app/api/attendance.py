"""Attendance: a session's roster, marking it, a trial guest at the mat, a person's counts.

A session's roster is everyone who may train at it: a membership that is not cancelled
(a frozen member who turns up trains, for nothing, and stays frozen), open to its class
type's program, one row per person, plus anyone already marked
(`app.schemas.attendance.Roster`). A mark or a trial guest is held to the same rule.
Someone on two plans the class admits, a monthly plan open to every class and a course
of credits, say, is listed on the one with credits left, else the one started first
(`ROSTER_PICK`, #354), and the screen marks that one.
A coach taps names on and off and sends what changed (`PATCH .../attendance`);
marking takes what the membership pays the class with (`app.domain.attendance`) and
unmarking gives it back. Each change is idempotent, so a
phone that lost signal resends its queue without double-counting anyone.

The roster flags an overdue member with a dot and never says what they owe: a coach
may not read the ledger (migration 0006), so it asks `overdue_memberships()` (0023)
for the ids alone.

A trial guest is someone trying a class: the screen adds them by RUT or email, with
their phone (`POST /api/people`), then starts them on one of the gym's trial plans,
present at the class (`POST .../trials`). A trial charges nothing, which is why a coach
may start one where only an owner or admin may start any other membership. No welcome
is sent: the person added at the mat has nothing to pay yet.

A drop-in visitor pays for this one class, "Clase suelta" (#130): the screen adds them by
name and phone, the phone finding someone the gym has (`POST .../visitors`). The visit
is a one-day membership on a drop-in plan, ended as it starts, marked present, with its
one period and charge (`app.domain.membership.drop_in`, docs/adr/0002-drop-in-visits.md).
A coach adds one, and its charge is written for them (`dropin_charge`, migration 0061);
recording that they paid at the desk is an owner's or admin's, as any payment is.
Unmarking the visit on the day it was added gives the charge back, voided, never
deleted (`dropin_void`); it is refused once the gym has kept a payment for it or a proof
waits, and on any later day: the payment book corrects it then.

A cancelled class (migration 0033) takes no attendance: marking at it, or adding a
trial guest or a visitor to it, is a 409. Cancelling is refused once anyone is marked,
so it has none to count. Deleting a class removes its attendance (`remove_attendance`),
giving back what each mark took, as unmarking would, and a drop-in's charge while
nothing was paid on it.

A class may be marked on a later day than its own, a class registered after it
happened included (#407). It is marked as on the day: each mark takes what the
membership pays the class with now, credits from what is left of a pack, an unlimited
plan just counting it, and touches no billing period, so a period already closed or
paid is never rewritten; nothing in the ledger reads attendance. Nor does the day a
membership started limit the classes it is marked at: a gym that starts on Rakin
mid-month adds its members as of today and fills in the classes they came to before, on
the membership each has. A drop-in visitor added to it is a visit on the class's day,
as on any day (#130). A trial guest is not: a trial starts the day it is
given, at the mat, so adding one to a class of an earlier day is a 409. Marking at a
class on another day than its own, a visitor included, writes an
`attendance_backfilled` row in the gym's log (migration 0070) for each person it
marks, so a month filled in afterwards is told apart from one taken live.

Each person on the roster names the requirements they lack or whose record expired
(`app.api.requirements.requirement_flags`, #350), those the caller's role sees: a
warning, never a refusal, so marking them still works.

Any staff role may use it, coaches included; members may not. A member reads their own
counts on the student page (`/api/me/page`).
"""

import json
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.grades import readable_scheme
from app.api.ledger import record_payment
from app.api.memberships import HAS_LEFT, PersonHasLeft, insert_membership
from app.api.people import NOT_FOUND as PERSON_NOT_FOUND
from app.api.people import in_gym, join_gym
from app.api.requirements import requirement_flags
from app.domain import membership as memberships
from app.domain.attendance import credits_to_consume
from app.domain.dates import gym_today, local_date, start_of_local_day
from app.domain.membership import Membership, MembershipStatus, PlanKind, PlanTerms
from app.notices import Notices, get_notices
from app.permissions import FORBIDDEN, AttendanceSession, Permission, StaffSession, holds
from app.schemas.attendance import (
    AlreadyMember,
    AttendanceChange,
    DropinKept,
    DropinRefusal,
    DropinVisitor,
    PersonAttendance,
    Roster,
    RosterMember,
    TrialGuest,
)
from app.schemas.grades import Rank
from app.schemas.ledger import PaymentRecord
from app.schemas.memberships import HasLeft
from app.tenancy import Tenant, current_tenant

router = APIRouter(tags=["classes"])

SESSION_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
CANCELLED = HTTPException(status.HTTP_409_CONFLICT, "the class is cancelled")
# A trial starts the day it is given (#407).
PAST_TRIAL = HTTPException(
    status.HTTP_409_CONFLICT, "a trial starts at the mat: not at a class of an earlier day"
)

# The gym's log of classes registered after they happened and attendance marked on
# another day (migration 0070).
CLASS_BACKFILLED = "class_backfilled"
ATTENDANCE_BACKFILLED = "attendance_backfilled"

INSERT_BACKFILL = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :person, :action, CAST(:detail AS jsonb))"
)

SELECT_SESSION = """
    SELECT s.id, s.starts_at, s.cancelled_at, s.class_type_id, c.program_id, c.credit_cost,
           g.timezone, g.settings
    FROM session s
    JOIN class_type c ON c.id = s.class_type_id
    JOIN gym g ON g.id = s.gym_id
    WHERE s.id = :id
"""

# The statuses that may train: everyone but a cancelled membership. A frozen member
# who turns up is marked, spends nothing (`app.domain.attendance`) and stays frozen.
ON_ROSTER = ("active", "trial", "lapsed", "frozen")

# Days before a class in which coming to one of its type makes someone a regular of it.
REGULAR_DAYS = 30

# Which of a person's memberships stands for them on a roster, as `ORDER BY` terms after
# `m.person_id`, with `a` their attendance at the class: the one marked present, else by
# `ON_ROSTER`'s order, then one with credits left, then the earliest started (#354). A
# member on a monthly plan open to every class who also takes a course of credits is
# marked on the course at its classes, and once it is spent on the plan started first.
# Status orders first, so credits left only decide between memberships of one status: a
# frozen course beside an active plan falls to the plan.
ROSTER_PICK = (
    f"a.membership_id IS NOT NULL DESC, array_position(ARRAY{list(ON_ROSTER)}, m.status),"
    " coalesce(m.credits_remaining > 0, false) DESC, m.started_at, m.created_at"
)

# One row per person: the membership marked present, else the one the program admits
# that `ROSTER_PICK` puts first. `days_absent` counts from their last class
# before this one, on the gym's calendar, once per person kept. `regular` is whether
# they came to a class of this one's type in the `REGULAR_DAYS` before it, which the
# screen lists first (#178). RLS keeps every table to the current gym.
ROSTER = f"""
SELECT roster.*,
       (:starts_at AT TIME ZONE :zone)::date - (
           SELECT max((ps.starts_at AT TIME ZONE :zone)::date)
           FROM attendance pa
           JOIN session ps ON ps.id = pa.session_id
           JOIN membership pm ON pm.id = pa.membership_id
           WHERE pm.person_id = roster.person_id AND ps.starts_at < :starts_at
       ) AS days_absent,
       EXISTS (
           SELECT FROM attendance ra
           JOIN session rs ON rs.id = ra.session_id
           JOIN membership rm ON rm.id = ra.membership_id
           WHERE rm.person_id = roster.person_id AND rs.class_type_id = :class_type
             AND rs.starts_at < :starts_at
             AND rs.starts_at >= :starts_at - make_interval(days => {REGULAR_DAYS})
       ) AS regular
FROM (
    SELECT DISTINCT ON (m.person_id)
           m.id AS membership_id, m.person_id, gp.name, gp.rut, pl.name AS plan_name,
           pl.kind AS plan_kind, m.status, m.credits_remaining,
           a.membership_id IS NOT NULL AS present,
           m.id IN (SELECT overdue_memberships()) AS overdue,
           r.rank_key, r.sub_rank, r.awarded_on
    FROM membership m
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.person_id = m.person_id
    LEFT JOIN attendance a ON a.session_id = :session AND a.membership_id = m.id
    LEFT JOIN LATERAL (
        SELECT ge.rank_key, ge.sub_rank, ge.awarded_on
        FROM grade_event ge
        WHERE ge.person_id = m.person_id
        ORDER BY ge.awarded_on DESC, ge.created_at DESC, ge.id
        LIMIT 1
    ) r ON true
    WHERE a.membership_id IS NOT NULL
       OR (m.status IN {ON_ROSTER}
           AND (pl.program_id IS NULL OR pl.program_id = :program))
    ORDER BY m.person_id, {ROSTER_PICK}
) roster
ORDER BY lower(name), person_id
"""

LOCK_MEMBERSHIP = """
    SELECT pl.kind, pl.program_id, m.status, m.credits_remaining, m.person_id
    FROM membership m JOIN plan pl ON pl.id = m.plan_id
    WHERE m.id = :id FOR UPDATE OF m
"""

INSERT_ATTENDANCE = """
    INSERT INTO attendance (gym_id, session_id, membership_id, marked_by, credits_consumed)
    VALUES (current_setting('app.gym_id')::uuid, :session, :membership, :marked_by, :credits)
    ON CONFLICT (session_id, membership_id) DO NOTHING
    RETURNING credits_consumed
"""

DELETE_ATTENDANCE = """
    DELETE FROM attendance WHERE session_id = :session AND membership_id = :membership
    RETURNING credits_consumed
"""

SPEND = "UPDATE membership SET credits_remaining = credits_remaining - :credits WHERE id = :id"

# A cancelled membership never changes again (0009), so it keeps what it had.
REFUND = """
    UPDATE membership SET credits_remaining = credits_remaining + :credits
    WHERE id = :id AND credits_remaining IS NOT NULL AND status <> 'cancelled'
"""

LIVE_MEMBERSHIP = """
    SELECT id FROM membership
    WHERE person_id = :person AND status IN ('trial', 'active', 'frozen')
    ORDER BY started_at DESC, created_at DESC
    LIMIT 1
"""

# The person's classes over every membership they hold here, in all and from each of
# two instants: sessions of a class type that counts as a class, so not an open mat by
# default (migration 0028). RLS keeps it to the current gym.
COUNTS = """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE s.starts_at >= :recent) AS recent,
           count(*) FILTER (WHERE s.starts_at >= :since) AS since
    FROM attendance a
    JOIN session s ON s.id = a.session_id
    JOIN class_type c ON c.id = s.class_type_id
    JOIN membership m ON m.id = a.membership_id
    WHERE m.person_id = :person AND c.counts_as_class
"""


@dataclass(frozen=True)
class HeldClass:
    id: uuid.UUID
    starts_at: datetime
    cancelled_at: datetime | None
    class_type_id: uuid.UUID
    program_id: uuid.UUID
    credit_cost: int
    timezone: str
    settings: Any

    @property
    def day(self) -> date:
        """The class's own day, in the gym's timezone."""
        return local_date(self.starts_at, self.timezone)

    @property
    def other_day(self) -> bool:
        """Whether today, in the gym's timezone, is not the class's own day."""
        return self.day != gym_today(self.timezone)


def _unprocessable(field: str, kind: str, msg: str) -> RequestValidationError:
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", field)}])


def _admits(program_id: uuid.UUID | None, held: HeldClass) -> bool:
    """Whether a plan in `program_id` covers the class: one in its program, or a plan
    open to any class. The roster's rule, which marks and trials are held to too."""
    return program_id is None or program_id == held.program_id


async def class_of(
    session: AsyncSession, session_id: uuid.UUID, *, lock: bool = False
) -> HeldClass:
    """The session with what the roster needs; locked, every change to its attendance
    waits for this one's."""
    sql = f"{SELECT_SESSION}{' FOR UPDATE OF s' if lock else ''}"
    row = (await session.execute(text(sql), {"id": session_id})).one_or_none()
    if row is None:
        raise SESSION_NOT_FOUND
    return HeldClass(**row._mapping)


def require_open(held: HeldClass) -> None:
    """A 409 if the class is cancelled: it takes no attendance."""
    if held.cancelled_at is not None:
        raise CANCELLED


async def record_backfill(
    session: AsyncSession, action: str, person_id: uuid.UUID | None, **detail: Any
) -> None:
    """Write `action` in the gym's log, by the person acting, now (migration 0070)."""
    await session.execute(
        INSERT_BACKFILL, {"person": person_id, "action": action, "detail": json.dumps(detail)}
    )


async def _record_marked(
    session: AsyncSession, held: HeldClass, membership_id: uuid.UUID, person_id: uuid.UUID
) -> None:
    """An `attendance_backfilled` row for a mark at a class of another day."""
    if held.other_day:
        await record_backfill(
            session,
            ATTENDANCE_BACKFILLED,
            person_id,
            session_id=str(held.id),
            membership_id=str(membership_id),
            day=held.day.isoformat(),
        )


async def _roster(session: AsyncSession, tenant: Tenant, held: HeldClass) -> Roster:
    scheme = readable_scheme(held.settings)
    rows = await session.execute(
        text(ROSTER),
        {
            "session": held.id,
            "program": held.program_id,
            "class_type": held.class_type_id,
            "starts_at": held.starts_at,
            "zone": held.timezone,
        },
    )
    members = []
    for row in rows:
        fields = dict(row._mapping)
        rank_key, sub_rank, awarded_on = (
            fields.pop(k) for k in ("rank_key", "sub_rank", "awarded_on")
        )
        rank = None if rank_key is None else Rank.labelled(scheme, rank_key, sub_rank, awarded_on)
        members.append(RosterMember(**fields, rank=rank))
    flags = await requirement_flags(session, tenant, [m.person_id for m in members])
    for m in members:
        m.unmet_requirements = flags.get(m.person_id, [])
    return Roster(session_id=held.id, present=sum(m.present for m in members), members=members)


async def mark_present(
    session: AsyncSession, held: HeldClass, membership_id: uuid.UUID, marked_by: uuid.UUID
) -> None:
    row = (await session.execute(text(LOCK_MEMBERSHIP), {"id": membership_id})).one_or_none()
    if row is None:
        raise _unprocessable("mark", "unknown_membership", f"no membership {membership_id}")
    if row.status == MembershipStatus.CANCELLED:
        raise _unprocessable(
            "mark", "cancelled_membership", f"membership {membership_id} is cancelled"
        )
    if row.status not in ON_ROSTER:
        raise _unprocessable(
            "mark", "not_on_roster", f"membership {membership_id} is {row.status}, not on a roster"
        )
    if not _admits(row.program_id, held):
        raise _unprocessable(
            "mark", "not_in_program", f"membership {membership_id} is not for this class"
        )
    state = Membership(
        PlanKind(row.kind), MembershipStatus(row.status), credits_remaining=row.credits_remaining
    )
    credits = credits_to_consume(state, held.credit_cost)
    inserted = await session.scalar(
        text(INSERT_ATTENDANCE),
        {
            "session": held.id,
            "membership": membership_id,
            "marked_by": marked_by,
            "credits": credits,
        },
    )
    if inserted is not None:
        if inserted:
            await session.execute(text(SPEND), {"id": membership_id, "credits": inserted})
        await _record_marked(session, held, membership_id, row.person_id)


def _kept(code: DropinRefusal, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, DropinKept(code=code, message=message).model_dump()
    )


# Whether the membership marked at the session is a drop-in visit, and whether it was
# added today, in the gym's timezone: the day unmarking it gives its charge back.
MARKED_VISIT = """
    SELECT pl.kind = 'dropin' AS dropin,
           (m.created_at AT TIME ZONE g.timezone)::date
               = (now() AT TIME ZONE g.timezone)::date AS today
    FROM attendance a
    JOIN membership m ON m.id = a.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym g ON g.id = m.gym_id
    WHERE a.session_id = :session AND a.membership_id = :membership
"""

# The void's reason, in the ledger and in the record of corrections.
UNMARKED_REASON = "Clase suelta desmarcada el día de la visita"
DELETED_REASON = "Clase suelta de una clase eliminada"

VOID_VISIT = "SELECT dropin_void(:id, :reason)"


async def _void_visit(session: AsyncSession, membership_id: uuid.UUID, reason: str) -> None:
    """Give a drop-in visit's charge back (`dropin_void`); a 409 when the gym kept a
    payment for it or a proof waits on it, for the payment book to settle first."""
    refused = await session.scalar(text(VOID_VISIT), {"id": membership_id, "reason": reason})
    if refused == DropinRefusal.PAID:
        raise _kept(DropinRefusal.PAID, "the class was paid: refund it in the payment book")
    if refused == DropinRefusal.PENDING:
        raise _kept(DropinRefusal.PENDING, "a proof waits on it: review it in the payment book")


async def unmark(session: AsyncSession, held: HeldClass, membership_id: uuid.UUID) -> None:
    """Unmark the membership, giving back what the mark took: credits, or a drop-in
    visit's charge on the day it was added. On a later day a visit stays marked."""
    marked = (
        await session.execute(text(MARKED_VISIT), {"session": held.id, "membership": membership_id})
    ).one_or_none()
    if marked is not None and marked.dropin:
        if not marked.today:
            raise _kept(DropinRefusal.PAST, "added on an earlier day: void it in the payment book")
        await _void_visit(session, membership_id, UNMARKED_REASON)
    credits = await session.scalar(
        text(DELETE_ATTENDANCE), {"session": held.id, "membership": membership_id}
    )
    if credits:
        await session.execute(text(REFUND), {"id": membership_id, "credits": credits})


# The session's drop-in visits, in id order.
VISITS_AT = """
    SELECT a.membership_id FROM attendance a
    JOIN membership m ON m.id = a.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    WHERE a.session_id = :session AND pl.kind = 'dropin'
    ORDER BY a.membership_id
"""


async def remove_attendance(session: AsyncSession, session_id: uuid.UUID) -> None:
    """Everyone's attendance at the session, gone, each giving back what it took, and a
    drop-in visit its charge, unless the gym kept a payment for it or a proof waits:
    that money is the payment book's. The caller holds the session locked; memberships
    go in id order, as every change here takes them."""
    for row in (await session.execute(text(VISITS_AT), {"session": session_id})).all():
        # Its answer is why not, when it was paid; then the charge stays, as the money.
        await session.scalar(text(VOID_VISIT), {"id": row.membership_id, "reason": DELETED_REASON})
    rows = await session.execute(
        text(
            "DELETE FROM attendance WHERE session_id = :session"
            " RETURNING membership_id, credits_consumed"
        ),
        {"session": session_id},
    )
    for row in sorted(rows, key=lambda r: r.membership_id):
        if row.credits_consumed:
            await session.execute(
                text(REFUND), {"id": row.membership_id, "credits": row.credits_consumed}
            )


@router.get("/api/sessions/{session_id}/roster")
async def get_roster(
    session_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AttendanceSession,
) -> Roster:
    return await _roster(session, tenant, await class_of(session, session_id))


@router.patch(
    "/api/sessions/{session_id}/attendance",
    responses={status.HTTP_409_CONFLICT: {"description": "the class is cancelled"}},
)
async def change_attendance(
    session_id: uuid.UUID,
    body: AttendanceChange,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AttendanceSession,
) -> Roster:
    """Mark and unmark at once; the roster as it then stands."""
    held = await class_of(session, session_id, lock=True)
    require_open(held)
    marking = set(body.mark)
    # One membership at a time in id order, as every request here takes them, so two
    # changes to different sessions never wait on each other's locks in a cycle.
    for membership_id in sorted(marking | set(body.unmark)):
        if membership_id in marking:
            await mark_present(session, held, membership_id, tenant.person_id)
        else:
            await unmark(session, held, membership_id)
    return await _roster(session, tenant, held)


@router.post(
    "/api/sessions/{session_id}/trials",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": AlreadyMember | HasLeft,
            "description": "already a member, has left, or the class is cancelled",
        }
    },
)
async def add_trial_guest(
    session_id: uuid.UUID,
    body: TrialGuest,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AttendanceSession,
) -> Roster:
    """Start the person on a trial plan from today, marked present at the session. A
    409 names the membership of someone who already has a live one, to mark instead, or
    says `has_left` for someone dado de baja, whom an admin reactivates; a cancelled
    class is a 409 too."""
    held = await class_of(session, session_id, lock=True)
    require_open(held)
    if held.day < gym_today(held.timezone):
        raise PAST_TRIAL
    if not await in_gym(session, body.person_id):
        raise _unprocessable("person_id", "unknown_person", "no such person")
    plan = (
        await session.execute(
            text(
                "SELECT kind, program_id, credits, credit_expiry_days, active"
                " FROM plan WHERE id = :id"
            ),
            {"id": body.plan_id},
        )
    ).one_or_none()
    if plan is None or plan.kind != PlanKind.TRIAL:
        raise _unprocessable("plan_id", "not_a_trial_plan", "not one of the gym's trial plans")
    if not plan.active:
        raise _unprocessable("plan_id", "inactive_plan", "the plan is deactivated")
    if not _admits(plan.program_id, held):
        raise _unprocessable("plan_id", "not_in_program", "the plan is not for this class")
    live = await session.scalar(text(LIVE_MEMBERSHIP), {"person": body.person_id})
    if live is not None:
        conflict = AlreadyMember(membership_id=live)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))

    today = gym_today(held.timezone)
    terms = PlanTerms(
        PlanKind.TRIAL, credits=plan.credits, credit_expiry_days=plan.credit_expiry_days
    )
    started = memberships.start(terms, today)
    try:
        membership_id = await insert_membership(
            session, body.person_id, body.plan_id, started, start_of_local_day(today, held.timezone)
        )
    except PersonHasLeft:
        # Someone dado de baja comes back through Reactivar, not a trial.
        raise HAS_LEFT from None
    await mark_present(session, held, membership_id, tenant.person_id)
    return await _roster(session, tenant, held)


# Everyone here with the phone, oldest record first. RLS keeps it to the current gym.
BY_PHONE = "SELECT person_id, name FROM gym_person WHERE phone = :phone ORDER BY created_at"


def _folded(name: str) -> str:
    """A name with case and accents ignored: "Martín" is "martin"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(plain.casefold().split())


async def visitor(session: AsyncSession, name: str, phone: str) -> uuid.UUID:
    """Who a visitor is: the one person here with `phone`, or among several sharing it
    (a family) the one called `name`; else someone new, by name and phone, with no RUT
    or email yet, as an import's row with neither (`join_gym`)."""
    rows = (await session.execute(text(BY_PHONE), {"phone": phone})).all()
    named = [row for row in rows if _folded(row.name) == _folded(name)]
    if len(rows) == 1 or named:
        found: uuid.UUID = (named or rows)[0].person_id
        return found
    person_id, _ = await join_gym(session, name=name, phone=phone)
    return person_id


# The person's membership this roster already marks them by: one present at the class,
# else one the class's program admits, as the roster picks it (`ROSTER`).
ON_THIS_ROSTER = f"""
    SELECT m.id FROM membership m
    JOIN plan pl ON pl.id = m.plan_id
    LEFT JOIN attendance a ON a.session_id = :session AND a.membership_id = m.id
    WHERE m.person_id = :person
      AND (a.membership_id IS NOT NULL
           OR (m.status IN {ON_ROSTER}
               AND (pl.program_id IS NULL OR pl.program_id = :program)))
    ORDER BY a.membership_id IS NOT NULL DESC,
             array_position(ARRAY{list(ON_ROSTER)}, m.status), m.created_at DESC
    LIMIT 1
"""

VISIT_PERIOD = "SELECT dropin_charge(:id)"

PERIOD_DUE = "SELECT amount_due_clp FROM billing_period WHERE id = :id"


@router.post(
    "/api/sessions/{session_id}/visitors",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "a coach recording a payment"},
        status.HTTP_409_CONFLICT: {
            "model": AlreadyMember | HasLeft,
            "description": "on this roster already, has left, or the class is cancelled",
        },
    },
)
async def add_dropin_visitor(
    session_id: uuid.UUID,
    body: DropinVisitor,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AttendanceSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Roster:
    """A drop-in visitor (#130): the person their phone is, or someone new, on a one-day
    membership of the drop-in plan for the class's day, marked present, its charge
    written. `paid` records the payment too, validated, with its receipt, for an owner
    or admin; a coach sending it is a 403. A 409 names the membership of someone this
    roster already lists, to mark instead, or says `has_left` for someone dado de baja;
    a cancelled class is a 409 too."""
    if body.paid is not None and not await holds(session, tenant, Permission.MONEY_WRITE):
        raise FORBIDDEN
    held = await class_of(session, session_id, lock=True)
    require_open(held)
    plan = (
        await session.execute(
            text("SELECT kind, program_id, active FROM plan WHERE id = :id"), {"id": body.plan_id}
        )
    ).one_or_none()
    if plan is None or plan.kind != PlanKind.DROPIN:
        raise _unprocessable("plan_id", "not_a_dropin_plan", "not one of the gym's drop-in plans")
    if not plan.active:
        raise _unprocessable("plan_id", "inactive_plan", "the plan is deactivated")
    if not _admits(plan.program_id, held):
        raise _unprocessable("plan_id", "not_in_program", "the plan is not for this class")
    person_id = await visitor(session, body.name, body.phone)
    listed = await session.scalar(
        text(ON_THIS_ROSTER),
        {"session": held.id, "person": person_id, "program": held.program_id},
    )
    if listed is not None:
        conflict = AlreadyMember(membership_id=listed)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))

    day = held.day
    try:
        membership_id = await insert_membership(
            session,
            person_id,
            body.plan_id,
            memberships.drop_in(day),
            start_of_local_day(day, held.timezone),
        )
    except PersonHasLeft:
        raise HAS_LEFT from None
    period_id = await session.scalar(text(VISIT_PERIOD), {"id": membership_id})
    await session.execute(
        text(INSERT_ATTENDANCE),
        {
            "session": held.id,
            "membership": membership_id,
            "marked_by": tenant.person_id,
            "credits": 0,
        },
    )
    await _record_marked(session, held, membership_id, person_id)
    due = await session.scalar(text(PERIOD_DUE), {"id": period_id})
    if body.paid is not None and due > 0:
        payment = PaymentRecord(
            membership_id=membership_id,
            billing_period_id=period_id,
            amount_clp=due,
            method=body.paid,
        )
        await record_payment(payment, session, notices, background)
    return await _roster(session, tenant, held)


# "The last 30 days": today and the 29 before it, by the gym's calendar.
RECENT_DAYS = 30


def recent_from(today: date, zone: str) -> datetime:
    """The first instant of "the last 30 days" ending `today`, in the gym's timezone."""
    return start_of_local_day(today - timedelta(days=RECENT_DAYS - 1), zone)


async def attended(
    session: AsyncSession, person_id: uuid.UUID, *, recent: datetime, since: datetime | None
) -> tuple[int, int, int | None]:
    """The person's classes here: in all, from `recent`, and from `since` if given."""
    row = (
        await session.execute(text(COUNTS), {"person": person_id, "recent": recent, "since": since})
    ).one()
    return row.total, row.recent, None if since is None else row.since


async def _promoted_on(session: AsyncSession, person_id: uuid.UUID) -> date | None:
    """The day of the person's current rank: their latest promotion's."""
    day: date | None = await session.scalar(
        text("SELECT max(awarded_on) FROM grade_event WHERE person_id = :person"),
        {"person": person_id},
    )
    return day


@router.get("/api/people/{person_id}/attendance")
async def person_attendance(
    person_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> PersonAttendance:
    if not await in_gym(session, person_id):
        raise PERSON_NOT_FOUND
    zone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    today = gym_today(zone)
    promoted = await _promoted_on(session, person_id)
    total, recent, since = await attended(
        session,
        person_id,
        recent=recent_from(today, zone),
        since=None if promoted is None else start_of_local_day(promoted + timedelta(days=1), zone),
    )
    # Classes before Rakin count in the total alone: not in the last 30 days, and not
    # since a promotion Rakin recorded (#293).
    prior: int = await session.scalar(
        text("SELECT prior_classes FROM gym_person WHERE person_id = :id"), {"id": person_id}
    )
    return PersonAttendance(
        last_30_days=recent, total=total + prior, before_rakin=prior, since_promotion=since
    )
