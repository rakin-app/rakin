"""Who a notice about a person goes to: them, or their guardian.

Kids never receive messages; all comms go to the guardian (docs/technical.md,
compliance). A dependent may have no phone or email at all, so every email, wa.me
link and reminder about someone is addressed through `contact_for`, which answers
with the guardian's own record in this gym when there is one (migration 0010). Links
are one level deep, so that is always one step.

A minor by birth date with no guardian here (`missing_guardian`, "Falta apoderado",
#368) is never written to: their contact has no phone, so no wa.me link is offered,
and `app.notices` records an email to them as `suppressed` instead of sending it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dates import AGE_OF_MAJORITY


def missing_guardian(record: str) -> str:
    """Whether the `gym_person` row `record` is a minor on the gym's today, by their
    birth date (`app.domain.dates.is_minor`), with no guardian in this gym, and still
    here: "Falta apoderado" (#368). Nothing is sent to them until one is added."""
    return f"""(
        {record}.left_on IS NULL AND {record}.dob IS NOT NULL
        AND ({record}.dob + interval '{AGE_OF_MAJORITY} years')::date > (
            SELECT (now() AT TIME ZONE g.timezone)::date FROM gym g WHERE g.id = {record}.gym_id
        )
        AND NOT EXISTS (
            SELECT FROM guardian_link d
            WHERE d.gym_id = {record}.gym_id AND d.dependent_person_id = {record}.person_id
        )
    )"""


def contact_query(person: str) -> str:
    """This gym's record of the person to address, the guardian's when there is one,
    for the person in the bind parameter `person` (`:id` or `$1`). A minor with no
    guardian has no phone here: nobody offers a wa.me link to a child. RLS keeps every
    table to the current gym."""
    return f"""
    SELECT r.person_id, r.name, r.email,
           CASE WHEN r.no_whatsapp OR {missing_guardian("r")} THEN NULL ELSE r.phone END
             AS phone,
           gl.dependent_person_id AS on_behalf_of
    FROM gym_person gp
    LEFT JOIN guardian_link gl ON gl.gym_id = gp.gym_id AND gl.dependent_person_id = gp.person_id
    JOIN gym_person r
      ON r.gym_id = gp.gym_id AND r.person_id = coalesce(gl.guardian_person_id, gp.person_id)
    WHERE gp.person_id = {person}
"""


CONTACT = contact_query(":id")


@dataclass(frozen=True)
class Contact:
    person_id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    # The dependent the notice is about, when it goes to their guardian.
    on_behalf_of: uuid.UUID | None


async def contact_for(session: AsyncSession, person_id: uuid.UUID) -> Contact | None:
    """Whom to tell about `person_id` in the current gym, or `None` if the gym has no
    record of them."""
    row = (await session.execute(text(CONTACT), {"id": person_id})).one_or_none()
    return None if row is None else Contact(**row._asdict())
