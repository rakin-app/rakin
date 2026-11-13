"""Payment reminders by WhatsApp from the admin's lists (#55).

Each is a `wa.me` link with the message prefilled (`app.notices.whatsapp`), which the
admin opens and sends from their own phone, with no Meta account involved. It goes to
the member, or to their guardian for a dependent (`app.contacts`).

`GET /api/reminders` lists every period of an Active membership not paid in full and
with no proof waiting for review that is due by today, or whose latest proof was
rejected and not yet followed up. Each is one of three messages:

- `proof_rejected_followup` while a rejection is newer than the period's last reminder:
  the admin's note, and a request for another proof. Once sent, the period goes back
  to the next two.
- `payment_due_today` on the due date.
- `payment_overdue` after it, on the due date then every `reminder_every_days` (the
  gym's setting, 3 by default) while it stays unpaid (docs/technical.md).

Each says how many reminders about the period were opened so far, for the "2.º aviso"
on the list, and whether the next one is due by that cadence. Opening one posts
`.../{billing_period_id}`, which records it in `message_log` (migration 0024). With the
gym's WhatsApp channel off, or no phone to send to, there is no link. Hoy's overdue
rows, its "Por avisar", the proof review after a rejection and the member's ficha read
this list.

Beside each overdue one, "Enviar recordatorio" (#260): `POST .../{billing_period_id}/email`
sends the overdue email (`app.jobs.overdue`) now, to the member or their guardian, as
the nightly job does on its own days. Each reminder says when the last of those went
out (`emailed_at`), and whether one already did today: a period gets one a day, so a
second is a 409. "Today" here is the job's: the date in `jobs_timezone`, which the
nightly run keys its emails by, so the job and the button never both send one on a day
a gym in another timezone would split differently. A double tap sends once, by the
request's `Idempotency-Key` (#201).
WhatsApp's count and cadence are WhatsApp's alone; the emails do not move them.

Owner and admin only (`LedgerSession`): it is money.
"""

import json
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts import contact_query
from app.domain.billing import SETTLING_KINDS, settled_amount
from app.domain.dates import gym_today
from app.integrations.messenger import Message, wa_me_link
from app.jobs.overdue import overdue_notice
from app.notices import PAYMENT_OVERDUE, Notices, Outcome, get_notices
from app.notices.whatsapp import (
    PAYMENT_REMINDERS,
    payment_due_today,
    payment_overdue,
    proof_rejected_followup,
)
from app.roles import LedgerSession
from app.schemas.gym import DEFAULT_REMINDER_EVERY_DAYS, Channels
from app.schemas.reminders import Emailed, PaymentReminder, Reminded, ReminderKind
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/reminders", tags=["comms"])

NOT_DUE = HTTPException(status.HTTP_404_NOT_FOUND, "no reminder due for this period")
NO_WHATSAPP = HTTPException(status.HTTP_409_CONFLICT, "no WhatsApp to send it to")
NOT_OVERDUE = HTTPException(status.HTTP_404_NOT_FOUND, "the period is not due yet")
NO_EMAIL = HTTPException(
    status.HTTP_409_CONFLICT, {"code": "no_email", "message": "No tiene correo."}
)
EMAILED_TODAY = HTTPException(
    status.HTTP_409_CONFLICT,
    {"code": "emailed_today", "message": "Ya se envió un recordatorio hoy."},
)
NOT_SENT = HTTPException(
    status.HTTP_502_BAD_GATEWAY,
    {"code": "not_sent", "message": "No se pudo enviar el correo."},
)

# Each period that may be reminded, with what it still owes settled as
# `app.api.ledger.OPEN_PERIODS` settles it, its latest rejected proof, the reminders
# about it so far and whom to write to. RLS holds every table to the gym.
REMINDERS = f"""
SELECT * FROM (
    SELECT bp.id AS billing_period_id, bp.membership_id, m.person_id,
           gp.name AS person_name, pl.name AS plan_name, bp.period_start, bp.period_end,
           bp.due_date,
           bp.amount_due_clp - coalesce(paid.amount, 0) AS outstanding_clp,
           t.today - bp.due_date AS days_overdue, t.today,
           rj.id AS rejected_id, rj.amount_clp AS rejected_clp, rj.note AS rejection_note,
           rj.validated_at AS rejected_at,
           sent.count AS reminders_sent, sent.last_at AS reminded_at,
           (sent.last_at AT TIME ZONE g.timezone)::date AS reminded_on,
           emailed.last_at AS emailed_at, emailed.today AS emailed_today,
           c.person_id AS contact_id, c.name AS contact_name, c.phone, c.email,
           c.on_behalf_of, g.id AS gym_id, g.name AS gym_name, g.settings
    FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym g ON g.id = bp.gym_id
    JOIN gym_person gp ON gp.gym_id = bp.gym_id AND gp.person_id = m.person_id
    CROSS JOIN LATERAL (SELECT (now() AT TIME ZONE g.timezone)::date AS today) t
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("e")})::bigint AS amount FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = 'validated'
          AND e.kind = ANY(CAST(:settling AS text[]))
    ) paid ON true
    LEFT JOIN LATERAL (
        SELECT e.id, e.amount_clp, e.note, e.validated_at FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.kind = 'payment' AND e.status = 'rejected'
        ORDER BY e.validated_at DESC, e.id DESC
        LIMIT 1
    ) rj ON true
    CROSS JOIN LATERAL (
        SELECT count(*) AS count, max(ml.sent_at) AS last_at FROM message_log ml
        WHERE ml.channel = 'whatsapp' AND ml.template = ANY(CAST(:templates AS text[]))
          AND ml.status = 'sent' AND ml.payload ->> 'billing_period_id' = bp.id::text
    ) sent
    CROSS JOIN LATERAL (
        SELECT max(ml.sent_at) AS last_at,
               coalesce(bool_or(ml.payload ->> 'on' = CAST(:emailed_on AS date)::text), false)
                   AS today
        FROM message_log ml
        WHERE ml.channel = 'email' AND ml.template = :emailed AND ml.status = 'sent'
          AND ml.payload ->> 'billing_period_id' = bp.id::text
    ) emailed
    LEFT JOIN LATERAL ({contact_query("m.person_id")}) c ON true
    WHERE m.status = 'active'
      AND NOT EXISTS (
          SELECT FROM ledger_entry e
          WHERE e.billing_period_id = bp.id AND e.kind = 'payment' AND e.status = 'pending'
      )
      AND (CAST(:person AS uuid) IS NULL OR m.person_id = :person)
      AND (CAST(:period AS uuid) IS NULL OR bp.id = :period)
) r
WHERE r.outstanding_clp > 0
  AND (r.days_overdue >= 0
       OR (r.rejected_at IS NOT NULL AND (r.reminded_at IS NULL OR r.rejected_at > r.reminded_at)))
ORDER BY r.days_overdue DESC, r.person_name, r.billing_period_id
"""

LOG_REMINDER = text(
    """
    INSERT INTO message_log (gym_id, person_id, channel, template, to_address, status, payload)
    VALUES (:gym_id, :person_id, 'whatsapp', :template, :to, 'sent', CAST(:payload AS jsonb))
    RETURNING id AS message_id, sent_at
    """
)


def kind_of(row: Any) -> ReminderKind:
    if row.rejected_at is not None and (
        row.reminded_at is None or row.rejected_at > row.reminded_at
    ):
        return ReminderKind.REJECTED
    return ReminderKind.DUE_TODAY if row.days_overdue == 0 else ReminderKind.OVERDUE


def is_due(row: Any, kind: ReminderKind) -> bool:
    """Whether the cadence calls for a reminder today."""
    if kind is ReminderKind.REJECTED or row.reminded_on is None:
        return True
    every = row.settings.get("reminder_every_days", DEFAULT_REMINDER_EVERY_DAYS)
    return bool((row.today - row.reminded_on).days >= every)


def reminder_text(row: Any, kind: ReminderKind) -> str:
    about = row.person_name if row.on_behalf_of is not None else None
    common = {"to_name": row.contact_name, "about_name": about, "gym_name": row.gym_name}
    if kind is ReminderKind.REJECTED:
        return proof_rejected_followup(
            **common,
            plan_name=row.plan_name,
            amount_clp=row.rejected_clp,
            note=row.rejection_note or "",
        )
    if kind is ReminderKind.DUE_TODAY:
        return payment_due_today(
            **common, plan_name=row.plan_name, outstanding_clp=row.outstanding_clp
        )
    return payment_overdue(
        **common,
        plan_name=row.plan_name,
        outstanding_clp=row.outstanding_clp,
        due_date=row.due_date,
    )


def reminder_message(row: Any, kind: ReminderKind) -> Message | None:
    """The reminder about `row`, to the phone it goes to; `None` when there is no
    WhatsApp to send it on."""
    channels = Channels.model_validate(row.settings.get("channels", {}))
    if not channels.whatsapp or row.phone is None:
        return None
    try:
        return Message(to_phone=row.phone, text=reminder_text(row, kind))
    except ValueError:
        # A phone from before numbers were checked, which WhatsApp cannot reach.
        return None


def reminder(row: Any) -> PaymentReminder:
    kind = kind_of(row)
    message = reminder_message(row, kind)
    return PaymentReminder(
        billing_period_id=row.billing_period_id,
        membership_id=row.membership_id,
        person_id=row.person_id,
        person_name=row.person_name,
        plan_name=row.plan_name,
        period_start=row.period_start,
        due_date=row.due_date,
        outstanding_clp=row.outstanding_clp,
        days_overdue=row.days_overdue,
        kind=kind,
        rejection_note=row.rejection_note if kind is ReminderKind.REJECTED else None,
        contact_name=row.contact_name,
        whatsapp_url=None if message is None else wa_me_link(message),
        reminders_sent=row.reminders_sent,
        reminded_at=row.reminded_at,
        reminder_due=is_due(row, kind),
        can_email=row.days_overdue >= 0 and bool(row.email),
        emailed_at=row.emailed_at,
        emailed_today=row.emailed_today,
    )


def email_day(request: Request) -> date:
    """The day an overdue email goes out for: the nightly job's, in `jobs_timezone`
    (`app.jobs.daily.today`)."""
    return gym_today(request.app.state.settings.jobs_timezone)


EmailDay = Annotated[date, Depends(email_day)]


async def reminder_rows(
    session: AsyncSession,
    *,
    emailed_on: date | None = None,
    person: uuid.UUID | None = None,
    period: uuid.UUID | None = None,
) -> list[Any]:
    # `emailed_on`: the day `emailed_today` asks about (`email_day`); with none, it is
    # false.
    params = {
        "settling": sorted(k.value for k in SETTLING_KINDS),
        "templates": list(PAYMENT_REMINDERS),
        "emailed": PAYMENT_OVERDUE.name,
        "emailed_on": emailed_on,
        "person": person,
        "period": period,
    }
    return list((await session.execute(text(REMINDERS), params)).all())


@router.get("")
async def reminders(
    session: LedgerSession, emailed_on: EmailDay, person_id: uuid.UUID | None = None
) -> list[PaymentReminder]:
    """The periods to remind about, longest overdue first; with `person_id`, only that
    member's (the ficha's)."""
    rows = await reminder_rows(session, emailed_on=emailed_on, person=person_id)
    return [reminder(row) for row in rows]


@router.post("/{billing_period_id}", status_code=status.HTTP_201_CREATED)
async def remind(
    billing_period_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: LedgerSession,
) -> Reminded:
    """Record that the admin opened the reminder about the period in `message_log`:
    which message, what it was rendered from, and the phone it went to."""
    rows = await reminder_rows(session, period=billing_period_id)
    if not rows:
        raise NOT_DUE
    row = rows[0]
    kind = kind_of(row)
    message = reminder_message(row, kind)
    if message is None:
        raise NO_WHATSAPP
    ordinal = row.reminders_sent + 1
    payload = {
        "about": str(row.person_id),
        "billing_period_id": str(row.billing_period_id),
        "ordinal": ordinal,
        "outstanding_clp": row.outstanding_clp,
        "days_overdue": row.days_overdue,
    }
    if kind is ReminderKind.REJECTED:
        payload["rejected_entry_id"] = str(row.rejected_id)
    logged = (
        await session.execute(
            LOG_REMINDER,
            {
                "gym_id": tenant.gym_id,
                "person_id": row.contact_id,
                "template": kind.value,
                "to": message.to_phone,
                "payload": json.dumps(payload),
            },
        )
    ).one()
    return Reminded(
        message_id=logged.message_id, sent_at=logged.sent_at, kind=kind, ordinal=ordinal
    )


@router.post("/{billing_period_id}/email", status_code=status.HTTP_201_CREATED)
async def email_reminder(
    billing_period_id: uuid.UUID,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    on: EmailDay,
) -> Emailed:
    """Send the overdue email about the period now, unless one went out today."""
    rows = await reminder_rows(session, emailed_on=on, period=billing_period_id)
    if not rows or (on - rows[0].due_date).days < 0:
        raise NOT_OVERDUE
    row = rows[0]
    if not row.email:
        raise NO_EMAIL
    if row.emailed_today:
        raise EMAILED_TODAY
    notice = overdue_notice(
        to=row.email,
        contact_id=row.contact_id,
        contact_name=row.contact_name,
        dependent_name=row.person_name if row.on_behalf_of is not None else None,
        gym_id=row.gym_id,
        gym_name=row.gym_name,
        plan_name=row.plan_name,
        billing_period_id=row.billing_period_id,
        period_start=row.period_start,
        period_end=row.period_end,
        due_date=row.due_date,
        amount_clp=row.outstanding_clp,
        days_overdue=(on - row.due_date).days,
        bank_account=row.settings.get("bank_account"),
        on=on,
    )
    # Sent before answering, so the answer can say whether it went: `Notices` records
    # it on a connection of its own either way.
    if await notices.send(notice) is not Outcome.SENT:
        raise NOT_SENT
    return Emailed(sent_at=datetime.now(UTC), contact_name=row.contact_name)
