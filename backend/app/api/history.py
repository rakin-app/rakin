"""A person's history from before Rakin, typed on the ficha (#293).

`PUT /api/people/{id}/history` writes "Fecha de inicio y clases": `member_since`, the
day they first trained here, and `prior_classes`, how many classes they had before
Rakin (migration 0051). Both are facts about the person, kept on `gym_person` and never
on a plan, so no billing code, job, view or export reads them
(docs/design/historical-data.md, section 2). The ficha's "Alumno desde" reads the
earliest of `member_since` and their first plan's start, and its class total adds
`prior_classes` (`app.api.attendance`).

A write that changes either records one `history_set` row in `audit_event`, with each
changed field's before and after, in the same transaction: the write and its record
are both kept or neither is. Owner and admin only, as the policy on `audit_event`
holds the app role to as well (0051).
"""

import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND, read_person
from app.domain.dates import add_months, gym_today
from app.roles import AdminSession
from app.schemas.people import HISTORY_WINDOW_YEARS, Person, PersonHistory
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/people", tags=["people"])

HISTORY_SET = "history_set"

LOCK_HISTORY = text(
    "SELECT member_since, prior_classes FROM gym_person WHERE person_id = :id FOR UPDATE"
)

SET_HISTORY = text(
    "UPDATE gym_person SET member_since = :member_since, prior_classes = :prior_classes,"
    " updated_at = now() WHERE person_id = :id"
)

# `now()` is the transaction's, as the policy wants it.
INSERT_HISTORY_SET = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :person, :action, CAST(:detail AS jsonb))"
)


async def _today(session: AsyncSession, tenant: Tenant) -> date:
    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(timezone)


def _shown(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


@router.put("/{person_id}/history")
async def set_history(
    person_id: uuid.UUID,
    body: PersonHistory,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Person:
    """Their start and their classes before Rakin, as given. Writing what is already
    there records nothing."""
    record = (await session.execute(LOCK_HISTORY, {"id": person_id})).one_or_none()
    if record is None:
        raise NOT_FOUND
    if body.member_since is not None:
        today = await _today(session, tenant)
        if body.member_since > today:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "member_since is today at the latest"
            )
        if body.member_since < add_months(today, -12 * HISTORY_WINDOW_YEARS):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"member_since must be within {HISTORY_WINDOW_YEARS} years of today",
            )
    after = body.model_dump()
    changed = {
        field: {"before": _shown(getattr(record, field)), "after": _shown(value)}
        for field, value in after.items()
        if getattr(record, field) != value
    }
    if changed:
        await session.execute(SET_HISTORY, {**after, "id": person_id})
        result = await session.execute(
            INSERT_HISTORY_SET,
            {"person": person_id, "action": HISTORY_SET, "detail": json.dumps(changed)},
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise RuntimeError(f"no audit row for the history of person {person_id}")
    return await read_person(session, person_id)
