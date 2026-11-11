"""Who stopped coming: the inactive list, and the WhatsApp nudge from it (#50).

`v_inactive` (migration 0023) has each person with a trial or Active membership and
the day they last came. The list is those away for 14 days or more, in two buckets, 14
and 30, nearest the line first: the ones still easiest to bring back. Someone who has
not come to a class yet counts from the day their membership started, so a member who
joined yesterday is not on it.

Each says whether they are up to date on their payments, so it is money, and owner and
admin only (`LedgerSession`), as the rest of "Hoy" is. Coaches never see money.

The nudge goes to them, or to their guardian for a dependent (`app.contacts`): a
`wa.me` link with the message prefilled (`app.notices.whatsapp`), which the admin opens
and sends from their own phone. Opening it posts `.../nudge`, which records it in
`message_log` (migration 0024), and the list says when the last one was. With the
gym's WhatsApp channel off, or no phone to send to, there is no link.
"""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts import contact_query
from app.integrations.messenger import Message, wa_me_link
from app.notices.whatsapp import INACTIVE_NUDGE, inactive_nudge
from app.roles import LedgerSession
from app.schemas.gym import Channels
from app.schemas.inactive import Bucket, InactiveMember, Nudged, PaymentStatus
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/inactive", tags=["retention"])

NOT_INACTIVE = HTTPException(status.HTTP_404_NOT_FOUND, "not on the inactive list")
NO_WHATSAPP = HTTPException(status.HTTP_409_CONFLICT, "no WhatsApp to send it to")

# Each person on `v_inactive` with how long they have been away: since their last class,
# or since their membership started when they have not come to one. RLS holds every
# table to the gym. The member list's "Sin venir" filter reads it too.
AWAY = """
SELECT i.gym_id, i.person_id, i.last_attended_on,
       coalesce(i.days_absent, t.today - (l.since AT TIME ZONE g.timezone)::date) AS days_absent,
       l.trial_only
FROM v_inactive i
JOIN gym g ON g.id = i.gym_id
CROSS JOIN LATERAL (SELECT (now() AT TIME ZONE g.timezone)::date AS today) t
CROSS JOIN LATERAL (
    SELECT min(m.started_at) AS since, bool_and(m.status = 'trial') AS trial_only
    FROM membership m
    WHERE m.gym_id = i.gym_id AND m.person_id = i.person_id
      AND m.status IN ('trial', 'active')
) l
"""

# The ids of everyone away 14 days or more, as a subquery: those "A quién llamar" lists.
AWAY_IDS = f"SELECT person_id FROM ({AWAY}) a WHERE a.days_absent >= {int(Bucket.DAYS_14)}"

# Each of them as the list shows them: away how long, owing what, whom to write to and
# when they were last nudged.
INACTIVE = f"""
SELECT * FROM (
    SELECT a.person_id, gp.name, a.last_attended_on, a.days_absent,
           a.trial_only, coalesce(o.owed, 0) AS overdue_clp,
           c.person_id AS contact_id, c.name AS contact_name, c.phone, c.on_behalf_of,
           g.name AS gym_name, g.settings, n.nudged_at
    FROM ({AWAY}) a
    JOIN gym g ON g.id = a.gym_id
    JOIN gym_person gp ON gp.gym_id = a.gym_id AND gp.person_id = a.person_id
    LEFT JOIN LATERAL (
        SELECT sum(o.outstanding_clp)::bigint AS owed FROM v_overdue o
        WHERE o.gym_id = a.gym_id AND o.person_id = a.person_id
          AND o.membership_status = 'active'
    ) o ON true
    LEFT JOIN LATERAL ({contact_query("a.person_id")}) c ON true
    LEFT JOIN LATERAL (
        SELECT max(ml.sent_at) AS nudged_at FROM message_log ml
        WHERE ml.template = :template AND ml.status = 'sent'
          AND ml.payload ->> 'about' = a.person_id::text
    ) n ON true
) r
WHERE r.days_absent >= :threshold AND (CAST(:person AS uuid) IS NULL OR r.person_id = :person)
ORDER BY r.days_absent, r.name, r.person_id
"""

LOG_NUDGE = text(
    """
    INSERT INTO message_log (gym_id, person_id, channel, template, to_address, status, payload)
    VALUES (:gym_id, :person_id, 'whatsapp', :template, :to, 'sent', CAST(:payload AS jsonb))
    RETURNING id AS message_id, sent_at
    """
)


def bucket(days_absent: int) -> Bucket:
    return Bucket.DAYS_30 if days_absent >= Bucket.DAYS_30 else Bucket.DAYS_14


def payment_status(row: Any) -> PaymentStatus:
    if row.overdue_clp > 0:
        return PaymentStatus.OVERDUE
    return PaymentStatus.TRIAL if row.trial_only else PaymentStatus.UP_TO_DATE


def nudge_message(row: Any) -> Message | None:
    """The nudge about `row`, to the phone it goes to; `None` when there is no WhatsApp
    to send it on."""
    channels = Channels.model_validate(row.settings.get("channels", {}))
    if not channels.whatsapp or row.phone is None:
        return None
    body = inactive_nudge(
        to_name=row.contact_name,
        about_name=row.name if row.on_behalf_of is not None else None,
        gym_name=row.gym_name,
        days_absent=row.days_absent,
        attended=row.last_attended_on is not None,
    )
    try:
        return Message(to_phone=row.phone, text=body)
    except ValueError:
        # A phone from before numbers were checked, which WhatsApp cannot reach.
        return None


def member(row: Any) -> InactiveMember:
    message = nudge_message(row)
    return InactiveMember(
        person_id=row.person_id,
        name=row.name,
        last_attended_on=row.last_attended_on,
        days_absent=row.days_absent,
        bucket=bucket(row.days_absent),
        payment_status=payment_status(row),
        overdue_clp=row.overdue_clp,
        contact_name=row.contact_name,
        whatsapp_url=None if message is None else wa_me_link(message),
        nudged_at=row.nudged_at,
    )


async def inactive_rows(session: AsyncSession, person: uuid.UUID | None = None) -> list[Any]:
    params = {"template": INACTIVE_NUDGE, "threshold": int(Bucket.DAYS_14), "person": person}
    return list((await session.execute(text(INACTIVE), params)).all())


@router.get("")
async def inactive(session: LedgerSession) -> list[InactiveMember]:
    """Everyone away 14 days or more, nearest the line first: "A quién llamar"."""
    return [member(row) for row in await inactive_rows(session)]


@router.post("/{person_id}/nudge", status_code=status.HTTP_201_CREATED)
async def nudge(
    person_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: LedgerSession,
) -> Nudged:
    """Record that the admin opened the nudge to `person_id`, or to their guardian, in
    `message_log`: what it was rendered from, and the phone it went to."""
    rows = await inactive_rows(session, person_id)
    if not rows:
        raise NOT_INACTIVE
    row = rows[0]
    message = nudge_message(row)
    if message is None:
        raise NO_WHATSAPP
    payload = {
        "about": str(row.person_id),
        "days_absent": row.days_absent,
        "attended": row.last_attended_on is not None,
    }
    logged = (
        await session.execute(
            LOG_NUDGE,
            {
                "gym_id": tenant.gym_id,
                "person_id": row.contact_id,
                "template": INACTIVE_NUDGE,
                "to": message.to_phone,
                "payload": json.dumps(payload),
            },
        )
    ).one()
    return Nudged.model_validate(logged, from_attributes=True)
