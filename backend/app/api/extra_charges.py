"""Cobros extra: one-off charges, fixed per person or a total split among a group (#195).

A rifa, a seminar, gear, or a cost the team splits, such as the fuel to a final divided
among the athletes going. The admin drafts it in a wizard and previews it
(`POST /api/extra-charges/preview`): each person the target names, with their amount,
whom the notice goes to and, for whoever has no email, a WhatsApp link. Creating it
writes one line per person, and emails each their own amount, the due date and the
gym's bank details, with a sign-in link to upload the proof (their guardian, for a
dependent).

A line is paid as a billing period is (`app.domain.billing`), through the same ledger:
the student's proof is a pending payment on it (`app.api.proofs`), which Validar
comprobante validates or rejects (`app.api.proof_review`); an admin records a payment
the gym received, adjusts the line or refunds a payment of it (`app.api.ledger`). Its
money counts in Cobrado and the ledger book. It never touches a membership: an unpaid
line lapses no plan and is not "Vencido".

An admin may change a person's amount (an override), cancel a line that has no money
on it, and, while nobody has paid any line of a split, divide the total again among the
lines left. "Recordar a los pendientes" emails again everyone who still owes and has no
proof waiting.

Owner and admin only (`LedgerSession`): coaches never see money, and RLS holds them to
it (migration 0037). Each person reads their own lines and their dependents' on the
student page (`app.api.me`).
"""

import logging
import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entries import CURRENT_PERSON, insert_entry
from app.api.extra_lines import (
    CANCELLED,
    NO_LINE,
    NOT_FOUND,
    PAYMENT,
    PENDING,
    REFUND,
    SETTLING,
    VALIDATED,
    line_after,
    locked_line,
)
from app.contacts import Contact, contact_for, contact_query
from app.domain import billing
from app.domain.billing import Settlement, settled_amount
from app.domain.errors import InvalidTransition
from app.domain.extra_charges import (
    AmountMode,
    LineStatus,
    Person,
    TargetKind,
    amounts,
    line_status,
    settled_paid,
    split,
)
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.money import format_clp
from app.integrations.messenger import Message, wa_me_link
from app.notices import EXTRA_CHARGE, RECEIPT, Notice, Notices, get_notices
from app.notices.whatsapp import extra_charge_reminder
from app.roles import LedgerSession
from app.schemas.extra_charges import (
    AmountDraft,
    CancelPreview,
    ExtraCharge,
    ExtraChargeCreate,
    ExtraChargePreview,
    ExtraChargeSummary,
    Line,
    LineAdjustment,
    LineAmountChange,
    LineCancel,
    LinePayment,
    MyExtraLine,
    Preview,
    PreviewLine,
    RefundableLinePayment,
    Reminded,
)
from app.schemas.gym import Channels
from app.schemas.ledger import (
    Entry,
    PersonRef,
    RecordedAdjustment,
    RecordedPayment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extra-charges", tags=["extra charges"])
people_router = APIRouter(prefix="/api/people", tags=["extra charges"])

NOBODY = HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the target names nobody")
NO_PERSON = HTTPException(status.HTTP_404_NOT_FOUND, "person not found")

# What the entries on the line `l` add up to: validated settlements, as a period's
# (`app.api.ledger.locked_period`), payments that proofs claim and await review, and
# the first of those proofs, for "Validar comprobante" to open. `kept` is the money the
# gym holds for it, its validated payments less their refunds, which an adjustment is
# not; `money_entries` counts the payments, validated or waiting, and the refunds, which
# a re-split must not move the amounts under.
LINE_SUMS = f"""
    LEFT JOIN LATERAL (
        SELECT (sum({settled_amount("e")}) FILTER (
                    WHERE e.status = {VALIDATED} AND e.kind IN ({SETTLING})))::bigint AS paid,
               (sum(e.amount_clp) FILTER (
                    WHERE e.status = {PENDING} AND e.kind = {PAYMENT}))::bigint AS pending,
               (array_agg(e.id ORDER BY e.claimed_at, e.id) FILTER (
                    WHERE e.status = {PENDING} AND e.kind = {PAYMENT}
                      AND e.proof_object_key IS NOT NULL))[1] AS pending_id,
               (sum({settled_amount("e")}) FILTER (
                    WHERE e.status = {VALIDATED} AND e.kind IN ({PAYMENT}, {REFUND})))::bigint
                   AS kept,
               count(*) FILTER (
                    WHERE (e.kind = {PAYMENT} AND e.status IN ({VALIDATED}, {PENDING}))
                       OR (e.kind = {REFUND} AND e.status = {VALIDATED})) AS money_entries
        FROM ledger_entry e WHERE e.extra_line_id = l.id
    ) s ON true
"""

# --- whom a target names ----------------------------------------------------------

# Who is in the gym and has not left it, with an active membership.
ACTIVE = """
    SELECT DISTINCT gp.person_id, gp.name FROM membership m
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    JOIN plan pl ON pl.id = m.plan_id
    WHERE m.status = 'active' AND gp.left_on IS NULL
"""

TARGETS = {
    TargetKind.ACTIVE: ACTIVE,
    TargetKind.PROGRAM: ACTIVE + " AND pl.program_id = :program_id",
    TargetKind.GROUP: """
        SELECT gp.person_id, gp.name FROM charge_group_member cm
        JOIN gym_person gp ON gp.gym_id = cm.gym_id AND gp.person_id = cm.person_id
        WHERE cm.group_id = :group_id AND gp.left_on IS NULL
    """,
    TargetKind.PEOPLE: """
        SELECT gp.person_id, gp.name FROM gym_person gp
        WHERE gp.person_id = ANY(CAST(:person_ids AS uuid[])) AND gp.left_on IS NULL
    """,
}

# Each of them with whom to tell: them, or their guardian (`app.contacts`).
WITH_CONTACTS = f"""
    SELECT t.person_id, t.name, c.name AS contact_name, c.email, c.phone, c.on_behalf_of
    FROM ({{target}}) t
    LEFT JOIN LATERAL ({contact_query("t.person_id")}) c ON true
    ORDER BY lower(t.name), t.person_id
"""

LABELS = {
    TargetKind.PROGRAM: ("SELECT name FROM program WHERE id = :program_id", "program_id"),
    TargetKind.GROUP: ("SELECT name FROM charge_group WHERE id = :group_id", "group_id"),
}


async def targeted(session: AsyncSession, draft: AmountDraft) -> tuple[list[Any], str | None]:
    """The people `draft` targets, each with whom to tell, and the target's label: the
    program's or group's name. A program or group not in this gym is a 404; someone
    picked by hand who is not in it, or has left it, a 422."""
    target = draft.target
    params: dict[str, Any] = {
        "program_id": target.program_id,
        "group_id": target.group_id,
        "person_ids": sorted(set(target.person_ids)),
    }
    label = None
    if target.kind in LABELS:
        sql, key = LABELS[target.kind]
        label = await session.scalar(text(sql), {key: params[key]})
        if label is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{target.kind} not found")
    rows = list(
        (
            await session.execute(text(WITH_CONTACTS.format(target=TARGETS[target.kind])), params)
        ).all()
    )
    if target.kind is TargetKind.PEOPLE and len(rows) != len(params["person_ids"]):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "someone picked is not in this gym or has left"
        )
    if not rows:
        raise NOBODY
    return rows, label


def shares(draft: AmountDraft, rows: list[Any]) -> dict[uuid.UUID, int]:
    """Each person's amount, as the domain says; a split too small for everyone, or an
    override for someone not targeted, is a 422."""
    try:
        return amounts(
            draft.amount_mode,
            draft.amount_clp,
            [Person(row.person_id, row.name) for row in rows],
            {o.person_id: o.amount_clp for o in draft.overrides},
        )
    except ValueError as refused:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(refused)) from None


# --- the gym, and what it tells people --------------------------------------------

GYM = text("SELECT id, name, settings FROM gym WHERE id = current_setting('app.gym_id')::uuid")


def whatsapp(
    gym: Any, row: Any, *, name: str, title: str | None, amount_clp: int, due: date | None
) -> str | None:
    """A `wa.me` link with the cobro's message, to the phone the notice goes to; `None`
    when the gym does not use WhatsApp, there is no phone, or nothing to say yet."""
    channels = Channels.model_validate((gym.settings or {}).get("channels", {}))
    if not channels.whatsapp or row.phone is None or title is None or due is None:
        return None
    body = extra_charge_reminder(
        to_name=row.contact_name,
        about_name=name if row.on_behalf_of is not None else None,
        gym_name=gym.name,
        title=title,
        amount=format_clp(amount_clp),
        due=f"{due:%d-%m-%Y}",
    )
    try:
        return wa_me_link(Message(to_phone=row.phone, text=body))
    except ValueError:
        # A phone from before numbers were checked, which WhatsApp cannot reach.
        return None


def charge_notice(
    gym: Any,
    charge: Any,
    contact: Contact,
    *,
    person_name: str,
    amount_clp: int,
    reminder: bool,
) -> Notice:
    """The cobro's email to one person, or their guardian: their own amount."""
    assert contact.email is not None
    return Notice(
        EXTRA_CHARGE,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym.id,
        context={
            "name": contact.name,
            "gym": gym.name,
            "title": charge.title,
            "message": charge.message,
            "amount_clp": amount_clp,
            "due_date": charge.due_date,
            "bank_account": (gym.settings or {}).get("bank_account"),
            "dependent_name": person_name if contact.on_behalf_of else None,
            "reminder": reminder,
            "extra_charge_id": str(charge.id),
        },
    )


def row_contact(row: Any) -> Contact | None:
    """Whom to email about the line `row` (`LINES`), as `contact_for` answers it, from
    the columns the row already carries; `None` with no email to send to."""
    if not row.email:
        return None
    return Contact(
        person_id=row.contact_id,
        name=row.contact_name,
        email=row.email,
        phone=row.phone,
        on_behalf_of=row.on_behalf_of,
    )


def row_status(row: Any) -> LineStatus:
    return line_status(
        amount_due_clp=row.amount_due_clp,
        paid_clp=row.paid,
        pending_clp=row.pending,
        cancelled=row.cancelled_at is not None,
    )


async def notify(
    session: AsyncSession,
    charge: Any,
    rows: list[Any],
    notices: Notices,
    background: BackgroundTasks,
    *,
    reminder: bool,
) -> Reminded:
    """Email each of the lines `rows` (`LINES`) its amount, or on a reminder what is left
    of it, after the response, which is after whatever wrote them has committed."""
    gym = (await session.execute(GYM)).one()
    sent = without = 0
    for row in rows:
        contact = row_contact(row)
        if contact is None:
            without += 1
            continue
        owed = row.amount_due_clp - settled_paid(row.paid, row.amount_due_clp)
        notice = charge_notice(
            gym,
            charge,
            contact,
            person_name=row.person_name,
            amount_clp=owed if reminder else row.amount_due_clp,
            reminder=reminder,
        )
        # An address the gym typed wrong is a failed send in `message_log`.
        background.add_task(notices.send, notice)
        sent += 1
    return Reminded(sent=sent, without_email=without)


async def open_rows(session: AsyncSession, charge_id: uuid.UUID) -> list[Any]:
    """The cobro's lines still owed with no proof waiting: who a notice is for."""
    rows = await session.execute(text(LINES + LINES_ORDER), {"id": charge_id, "line": None})
    return [row for row in rows if row_status(row) is LineStatus.OPEN]


# --- the preview and creating a cobro ---------------------------------------------


@router.post("/preview")
async def preview(body: ExtraChargePreview, session: LedgerSession) -> Preview:
    """The draft as it would charge: each person's amount, with a split's share and
    remainder, and who would get no email."""
    rows, _ = await targeted(session, body)
    owed = shares(body, rows)
    overridden = {o.person_id for o in body.overrides}
    gym = (await session.execute(GYM)).one()
    share = remainder = None
    if body.amount_mode is AmountMode.SPLIT:
        share, remainder = divmod(body.amount_clp, len(rows))
    return Preview(
        lines=[
            PreviewLine(
                person=PersonRef(id=row.person_id, name=row.name),
                amount_clp=owed[row.person_id],
                overridden=row.person_id in overridden,
                contact_name=row.contact_name or row.name,
                on_behalf=row.on_behalf_of is not None,
                has_email=bool(row.email),
                whatsapp_url=None
                if row.email
                else whatsapp(
                    gym,
                    row,
                    name=row.name,
                    title=body.title,
                    amount_clp=owed[row.person_id],
                    due=body.due_date,
                ),
            )
            for row in rows
        ],
        total_clp=sum(owed.values()),
        remainder_clp=remainder or 0,
        share_clp=share,
    )


INSERT_CHARGE = text(
    f"""
    INSERT INTO extra_charge (gym_id, title, description, message, category, due_date,
                              amount_mode, amount_clp, target_kind, target_label, created_by)
    VALUES (current_setting('app.gym_id')::uuid, :title, :description, :message, :category,
            :due_date, :amount_mode, :amount_clp, :target_kind, :target_label, {CURRENT_PERSON})
    RETURNING id
    """
)

INSERT_LINES = text(
    """
    INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp, overridden)
    SELECT current_setting('app.gym_id')::uuid, :charge, p, a, o
    FROM unnest(CAST(:people AS uuid[]), CAST(:amounts AS bigint[]), CAST(:overridden AS boolean[]))
        AS t (p, a, o)
    """
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: ExtraChargeCreate,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> ExtraCharge:
    """Charge everyone the target names their amount, and, with `notify`, email each."""
    rows, label = await targeted(session, body)
    owed = shares(body, rows)
    overridden = {o.person_id for o in body.overrides}
    charge_id = await session.scalar(
        INSERT_CHARGE,
        {
            "title": body.title,
            "description": body.description or None,
            "message": body.message or None,
            "category": body.category.value,
            "due_date": body.due_date,
            "amount_mode": body.amount_mode.value,
            "amount_clp": body.amount_clp,
            "target_kind": body.target.kind.value,
            "target_label": label,
        },
    )
    people = [row.person_id for row in rows]
    await session.execute(
        INSERT_LINES,
        {
            "charge": charge_id,
            "people": people,
            "amounts": [owed[p] for p in people],
            "overridden": [p in overridden for p in people],
        },
    )
    if body.notify:
        facts = await charge_facts(session, charge_id)
        # Someone let off it, at nothing, is not told to pay nothing.
        owing = await open_rows(session, charge_id)
        await notify(session, facts, owing, notices, background, reminder=False)
    return await read_charge(session, charge_id)


# --- reading cobros ---------------------------------------------------------------

SUMMARY = f"""
    SELECT x.id, x.title, x.category, x.due_date, x.amount_mode, x.amount_clp, x.target_kind,
           x.target_label, x.created_at, x.description, x.message,
           count(l.id) FILTER (WHERE l.cancelled_at IS NULL AND l.amount_due_clp > 0) AS lines,
           count(l.id) FILTER (
               WHERE l.cancelled_at IS NULL AND l.amount_due_clp > 0
                 AND coalesce(s.paid, 0) >= l.amount_due_clp
           ) AS paid_lines,
           count(l.id) FILTER (WHERE l.cancelled_at IS NULL AND l.amount_due_clp = 0)
               AS waived_lines,
           coalesce(sum(l.amount_due_clp) FILTER (WHERE l.cancelled_at IS NULL), 0)::bigint
               AS due_clp,
           coalesce(sum(least(greatest(coalesce(s.paid, 0), 0), l.amount_due_clp))
               FILTER (WHERE l.cancelled_at IS NULL), 0)::bigint AS collected_clp
    FROM extra_charge x
    LEFT JOIN extra_line l ON l.extra_charge_id = x.id
    {LINE_SUMS}
"""

SUMMARIES = text(f"{SUMMARY} GROUP BY x.id ORDER BY x.created_at DESC, x.id")
ONE_SUMMARY = text(f"{SUMMARY} WHERE x.id = :id GROUP BY x.id")

LINES = f"""
    SELECT l.id, l.person_id, gp.name AS person_name, l.amount_due_clp, l.overridden,
           l.cancelled_at, l.cancel_reason, coalesce(s.paid, 0) AS paid,
           coalesce(s.pending, 0) AS pending,
           s.pending_id, coalesce(s.kept, 0) AS kept, s.money_entries,
           gl.guardian_person_id AS guardian_id, ggp.name AS guardian_name,
           c.person_id AS contact_id, c.name AS contact_name, c.email, c.phone, c.on_behalf_of
    FROM extra_line l
    JOIN gym_person gp ON gp.gym_id = l.gym_id AND gp.person_id = l.person_id
    LEFT JOIN guardian_link gl ON gl.gym_id = l.gym_id AND gl.dependent_person_id = l.person_id
    LEFT JOIN gym_person ggp
        ON ggp.gym_id = gl.gym_id AND ggp.person_id = gl.guardian_person_id
    LEFT JOIN LATERAL ({contact_query("l.person_id")}) c ON true
    {LINE_SUMS}
    WHERE l.extra_charge_id = :id AND (CAST(:line AS uuid) IS NULL OR l.id = :line)
"""

LINES_ORDER = " ORDER BY lower(gp.name), l.id"

# The charge's validated payments with something left to give back, newest first;
# one line's, with `:line`.
REFUNDABLE = text(
    """
    SELECT p.id, p.extra_line_id, p.amount_clp, p.method, p.validated_at,
           p.amount_clp - coalesce(r.amount, 0) AS refundable_clp
    FROM ledger_entry p
    JOIN extra_line l ON l.id = p.extra_line_id
    LEFT JOIN LATERAL (
        SELECT sum(x.amount_clp)::bigint AS amount FROM ledger_entry x WHERE x.refund_of = p.id
    ) r ON true
    WHERE l.extra_charge_id = :id AND p.kind = 'payment' AND p.status = 'validated'
      AND (CAST(:line AS uuid) IS NULL OR l.id = :line)
      AND p.amount_clp > coalesce(r.amount, 0)
    ORDER BY p.validated_at DESC, p.id
    """
)


def summary(row: Any) -> ExtraChargeSummary:
    return ExtraChargeSummary.model_validate(row, from_attributes=True)


@router.get("")
async def list_charges(session: LedgerSession) -> list[ExtraChargeSummary]:
    """Every cobro, newest first, with how far along it is: "7 de 9 pagaron · $140.000 de
    $180.000"."""
    return [summary(row) for row in await session.execute(SUMMARIES)]


def to_line(row: Any, gym: Any, charge: Any, refundable: list[RefundableLinePayment]) -> Line:
    paid = settled_paid(row.paid, row.amount_due_clp)
    state = row_status(row)
    outstanding = row.amount_due_clp - paid
    return Line(
        id=row.id,
        person=PersonRef(id=row.person_id, name=row.person_name),
        guardian=None
        if row.guardian_id is None
        else PersonRef(id=row.guardian_id, name=row.guardian_name),
        amount_due_clp=row.amount_due_clp,
        overridden=row.overridden,
        paid_clp=paid,
        outstanding_clp=0 if state is LineStatus.CANCELLED else outstanding,
        pending_clp=row.pending,
        status=state,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        has_email=bool(row.email),
        whatsapp_url=whatsapp(
            gym,
            row,
            name=row.person_name,
            title=charge.title,
            amount_clp=outstanding,
            due=charge.due_date,
        )
        if state is LineStatus.OPEN
        else None,
        pending_proof_id=row.pending_id,
        refundable_payments=refundable,
    )


async def charge_facts(session: AsyncSession, charge_id: uuid.UUID) -> Any:
    found = (
        await session.execute(
            text(
                "SELECT id, title, message, due_date, amount_mode, amount_clp"
                " FROM extra_charge WHERE id = :id"
            ),
            {"id": charge_id},
        )
    ).one_or_none()
    if found is None:
        raise NOT_FOUND
    return found


async def read_charge(session: AsyncSession, charge_id: uuid.UUID) -> ExtraCharge:
    row = (await session.execute(ONE_SUMMARY, {"id": charge_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    gym = (await session.execute(GYM)).one()
    refundable: dict[uuid.UUID, list[RefundableLinePayment]] = defaultdict(list)
    for payment in await session.execute(REFUNDABLE, {"id": charge_id, "line": None}):
        refundable[payment.extra_line_id].append(
            RefundableLinePayment.model_validate(payment, from_attributes=True)
        )
    lines = await session.execute(text(LINES + LINES_ORDER), {"id": charge_id, "line": None})
    return ExtraCharge(
        **summary(row).model_dump(),
        description=row.description,
        message=row.message,
        people=[to_line(line, gym, row, refundable[line.id]) for line in lines],
    )


@router.get("/{charge_id}")
async def get_charge(charge_id: uuid.UUID, session: LedgerSession) -> ExtraCharge:
    """The cobro, with each person's line: status, amount, what they paid and any proof."""
    return await read_charge(session, charge_id)


# --- changing lines ---------------------------------------------------------------


async def line_of(session: AsyncSession, charge_id: uuid.UUID, line_id: uuid.UUID) -> Line:
    gym = (await session.execute(GYM)).one()
    charge = await charge_facts(session, charge_id)
    row = await line_row(session, charge_id, line_id)
    refundable = [
        RefundableLinePayment.model_validate(p, from_attributes=True)
        for p in await session.execute(REFUNDABLE, {"id": charge_id, "line": line_id})
    ]
    return to_line(row, gym, charge, refundable)


async def line_row(session: AsyncSession, charge_id: uuid.UUID, line_id: uuid.UUID) -> Any:
    row = (await session.execute(text(LINES), {"id": charge_id, "line": line_id})).one_or_none()
    if row is None:
        raise NO_LINE
    return row


@router.patch("/{charge_id}/lines/{line_id}")
async def change_amount(
    charge_id: uuid.UUID, line_id: uuid.UUID, body: LineAmountChange, session: LedgerSession
) -> Line:
    """Override what one person owes: a scholarship, or someone who pays less. Never
    below what they have already paid; a re-split leaves it as it is."""
    _, line, period = await locked_line(session, charge_id, line_id)
    if line.cancelled_at is not None:
        raise CANCELLED
    if body.amount_clp < period.paid_clp:
        raise HTTPException(status.HTTP_409_CONFLICT, "less than they have already paid")
    await session.execute(
        text("UPDATE extra_line SET amount_due_clp = :amount, overridden = true WHERE id = :id"),
        {"id": line_id, "amount": body.amount_clp},
    )
    return await line_of(session, charge_id, line_id)


async def resplit(
    session: AsyncSession, charge: Any, charge_id: uuid.UUID, without: uuid.UUID
) -> dict[uuid.UUID, int] | None:
    """Each other line's amount once the total is divided again without `without`, the
    overrides kept: `None` when it cannot be, for a cobro that is not a split, one
    someone has paid, claimed or been refunded on, or one with nobody left. An
    adjustment moves no money and does not stand in the way. Run under the cobro's lock,
    which every entry on its lines waits for (`app.api.extra_lines`)."""
    if AmountMode(charge.amount_mode) is not AmountMode.SPLIT:
        return None
    rows = (await session.execute(text(LINES + LINES_ORDER), {"id": charge_id, "line": None})).all()
    if any(row.money_entries for row in rows):
        return None
    left = [row for row in rows if row.cancelled_at is None and row.id != without]
    if not left:
        return None
    try:
        # By person, as `create` divided it, so a tie in names breaks the same way.
        divided = split(charge.amount_clp, [Person(row.person_id, row.person_name) for row in left])
    except ValueError:
        return None
    return {
        row.id: row.amount_due_clp if row.overridden else divided[row.person_id] for row in left
    }


SHARE_CHARGE = text("SELECT amount_mode, amount_clp FROM extra_charge WHERE id = :id FOR SHARE")


@router.get("/{charge_id}/lines/{line_id}/cancel")
async def cancel_preview(
    charge_id: uuid.UUID, line_id: uuid.UUID, session: LedgerSession
) -> CancelPreview:
    """What cancelling the line would leave: whether the total may be divided again
    among the others, and how. It reads under the cobro's lock, shared, so no payment
    or claim lands halfway through what it counts."""
    charge = (await session.execute(SHARE_CHARGE, {"id": charge_id})).one_or_none()
    if charge is None:
        raise NOT_FOUND
    await line_row(session, charge_id, line_id)
    divided = await resplit(session, charge, charge_id, line_id)
    return CancelPreview(resplit_allowed=divided is not None, amounts=divided or {})


@router.post("/{charge_id}/lines/{line_id}/cancel")
async def cancel_line(
    charge_id: uuid.UUID, line_id: uuid.UUID, body: LineCancel, session: LedgerSession
) -> ExtraCharge:
    """Anular: the person no longer owes it, for `reason` (#256). Only a line the gym
    holds no money for and no proof waits on; refund a payment first. An adjustment is
    not money and does not stand in the way. With `resplit`, the total is divided again
    among the lines left, while nobody has paid any.

    Under the cobro's lock, which a student's claim waits for too
    (`ledger_entry_line_open`, 0037): a claim either lands before this reads the line
    and is seen, or after it commits and is refused."""
    charge, line, _ = await locked_line(session, charge_id, line_id)
    if line.cancelled_at is not None:
        raise CANCELLED
    row = await line_row(session, charge_id, line_id)
    if row.pending or row.kept:
        raise HTTPException(status.HTTP_409_CONFLICT, "the line has money on it: refund it first")
    divided = None
    if body.resplit:
        divided = await resplit(session, charge, charge_id, line_id)
        if divided is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "this cobro cannot be divided again")
    await session.execute(
        text(
            "UPDATE extra_line SET cancelled_at = now(),"
            f" cancelled_by = {CURRENT_PERSON}, cancel_reason = :reason WHERE id = :id"
        ),
        {"id": line_id, "reason": body.reason},
    )
    for other, amount in (divided or {}).items():
        await session.execute(
            text("UPDATE extra_line SET amount_due_clp = :amount WHERE id = :id"),
            {"id": other, "amount": amount},
        )
    return await read_charge(session, charge_id)


# --- money on a line --------------------------------------------------------------

LINE_FACTS = text(
    """
    SELECT l.person_id, gp.name AS person_name, x.title, g.id AS gym_id, g.name AS gym_name
    FROM extra_line l
    JOIN extra_charge x ON x.id = l.extra_charge_id
    JOIN gym_person gp ON gp.gym_id = l.gym_id AND gp.person_id = l.person_id
    JOIN gym g ON g.id = l.gym_id
    WHERE l.id = :id
    """
)


async def line_facts(session: AsyncSession, line_id: uuid.UUID) -> tuple[Any, Contact | None]:
    """The line a notice is about, and whom to send it to: `None` if no one."""
    facts = (await session.execute(LINE_FACTS, {"id": line_id})).one()
    contact = await contact_for(session, facts.person_id)
    return facts, (contact if contact is not None and contact.email else None)


async def send_line_receipt(
    session: AsyncSession,
    line_id: uuid.UUID,
    payment: Entry,
    outstanding_clp: int,
    notices: Notices,
    background: BackgroundTasks,
) -> None:
    """The "Pago validado" receipt for a payment on a line, after the response."""
    facts, contact = await line_facts(session, line_id)
    if contact is None:
        logger.info("receipt: no email to send it to", extra={"entry_id": str(payment.id)})
        return
    notice = Notice(
        RECEIPT,
        to=str(contact.email),
        person_id=contact.person_id,
        gym_id=facts.gym_id,
        context={
            "name": contact.name,
            "gym": facts.gym_name,
            "amount_clp": payment.amount_clp,
            "charge_title": facts.title,
            "period_outstanding_clp": outstanding_clp,
            "dependent_name": facts.person_name if contact.on_behalf_of else None,
        },
    )
    background.add_task(notices.send, notice)


async def settled_line(
    session: AsyncSession,
    line_id: uuid.UUID,
    payment: Entry,
    settlement: Settlement,
    notices: Notices,
    background: BackgroundTasks,
) -> RecordedPayment:
    """The line as `payment` leaves it, and its receipt. An overpayment stays on the
    line, counted in full, rather than becoming credit: a cobro has no next period to
    carry it to, so the admin refunds what is beyond it."""
    result = RecordedPayment(
        payment=payment, credit=None, period=line_after(line_id, settlement.period)
    )
    await send_line_receipt(
        session, line_id, payment, result.period.outstanding_clp, notices, background
    )
    return result


@router.post("/{charge_id}/lines/{line_id}/payments", status_code=status.HTTP_201_CREATED)
async def record_line_payment(
    charge_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LinePayment,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> RecordedPayment:
    """Marcar pagado: money the gym received for the line in cash, by a transfer it saw
    arrive, or otherwise, validated as the admin records it."""
    _, line, period = await locked_line(session, charge_id, line_id)
    if line.cancelled_at is not None:
        raise CANCELLED
    payment = LedgerEntry(
        kind=EntryKind.PAYMENT,
        amount_clp=body.amount_clp,
        status=EntryStatus.VALIDATED,
        note=body.note,
    )
    try:
        settlement = billing.apply(period, payment)
    except InvalidTransition:
        raise HTTPException(status.HTTP_409_CONFLICT, "the line is already paid in full") from None
    recorded = await insert_entry(
        session, settlement.entry, extra_line_id=line_id, method=body.method.value
    )
    return await settled_line(session, line_id, recorded, settlement, notices, background)


@router.post("/{charge_id}/lines/{line_id}/adjustments", status_code=status.HTTP_201_CREATED)
async def record_line_adjustment(
    charge_id: uuid.UUID, line_id: uuid.UUID, body: LineAdjustment, session: LedgerSession
) -> RecordedAdjustment:
    """Correct what a line owes with a note saying why, as a period's (#38)."""
    _, line, period = await locked_line(session, charge_id, line_id)
    if line.cancelled_at is not None:
        raise CANCELLED
    try:
        settlement = billing.adjust(period, body.amount_clp, body.note)
    except InvalidTransition:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the adjustment exceeds what the line owes"
        ) from None
    adjustment = await insert_entry(session, settlement.entry, extra_line_id=line_id)
    return RecordedAdjustment(adjustment=adjustment, period=line_after(line_id, settlement.period))


# --- telling people again ---------------------------------------------------------


@router.post("/{charge_id}/lines/{line_id}/notify")
async def notify_line(
    charge_id: uuid.UUID,
    line_id: uuid.UUID,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Reminded:
    """Reenviar aviso: email this one person their amount again."""
    facts = await charge_facts(session, charge_id)
    row = await line_row(session, charge_id, line_id)
    if row.cancelled_at is not None:
        raise CANCELLED
    return await notify(session, facts, [row], notices, background, reminder=True)


@router.post("/{charge_id}/remind")
async def remind(
    charge_id: uuid.UUID,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Reminded:
    """Recordar a los pendientes: email everyone who still owes and has no proof
    waiting what is left of their amount."""
    facts = await charge_facts(session, charge_id)
    owing = await open_rows(session, charge_id)
    return await notify(session, facts, owing, notices, background, reminder=True)


# --- a person's lines -------------------------------------------------------------

# Lines not cancelled, with their cobro and what has been paid and claimed on them.
# Everything is held to the current gym by RLS, and a member to their own lines and
# their dependents' (`extra_line_own`, 0037).
PERSON_LINES = f"""
    SELECT l.id, l.extra_charge_id, x.title, x.category, x.message, x.due_date, l.person_id,
           gp.name AS person_name, l.amount_due_clp, coalesce(s.paid, 0) AS paid,
           coalesce(s.pending, 0) AS pending
    FROM extra_line l
    JOIN extra_charge x ON x.id = l.extra_charge_id
    JOIN gym_person gp ON gp.gym_id = l.gym_id AND gp.person_id = l.person_id
    {LINE_SUMS}
    WHERE l.cancelled_at IS NULL
"""

# Not yet paid in full.
OWED = " AND coalesce(s.paid, 0) < l.amount_due_clp"

PERSON_ORDER = " ORDER BY x.due_date, lower(gp.name), l.id"

# The person's own and their dependents'.
MINE = (
    " AND (l.person_id = :me OR l.person_id IN ("
    "SELECT g.dependent_person_id FROM guardian_link g WHERE g.guardian_person_id = :me))"
)

OPEN_LINES = PERSON_LINES + OWED + MINE + PERSON_ORDER
ONE_LINE = PERSON_LINES + MINE + " AND l.id = :id"


def my_line(row: Any) -> MyExtraLine:
    paid = settled_paid(row.paid, row.amount_due_clp)
    return MyExtraLine(
        id=row.id,
        extra_charge_id=row.extra_charge_id,
        title=row.title,
        category=row.category,
        message=row.message,
        due_date=row.due_date,
        person_id=row.person_id,
        person_name=row.person_name,
        amount_due_clp=row.amount_due_clp,
        paid_clp=paid,
        outstanding_clp=row.amount_due_clp - paid,
        pending_clp=row.pending,
        status=line_status(
            amount_due_clp=row.amount_due_clp,
            paid_clp=row.paid,
            pending_clp=row.pending,
            cancelled=False,
        ),
    )


async def open_lines(session: AsyncSession, me: uuid.UUID) -> list[MyExtraLine]:
    """The lines `me` can pay, theirs and their dependents', earliest due first."""
    return [my_line(row) for row in await session.execute(text(OPEN_LINES), {"me": me})]


@people_router.get("/{person_id}/extra-lines")
async def person_lines(person_id: uuid.UUID, session: LedgerSession) -> list[MyExtraLine]:
    """The person's cobros extra still owed: "Cobros extra pendientes" on their ficha."""
    known = await session.scalar(
        text("SELECT EXISTS (SELECT FROM gym_person WHERE person_id = :id)"), {"id": person_id}
    )
    if not known:
        raise NO_PERSON
    rows = await session.execute(
        text(PERSON_LINES + OWED + " AND l.person_id = :person" + PERSON_ORDER),
        {"person": person_id},
    )
    return [my_line(row) for row in rows]
