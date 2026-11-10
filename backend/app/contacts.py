"""Who a notice about a person goes to: them, or their guardian.

Kids never receive messages; all comms go to the guardian (docs/technical.md,
compliance). A dependent may have no phone or email at all, so every email, wa.me
link and reminder about someone is addressed through `contact_for`, which answers
with the guardian's own record in this gym when there is one (migration 0010). Links
are one level deep, so that is always one step.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def contact_query(person: str) -> str:
    """This gym's record of the person to address, the guardian's when there is one,
    for the person in the bind parameter `person` (`:id` or `$1`). RLS keeps every
    table to the current gym."""
    return f"""
    SELECT r.person_id, r.name, r.email,
           CASE WHEN r.no_whatsapp THEN NULL ELSE r.phone END AS phone,
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
