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
from collections.abc import Mapping
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


def refuse_outside_history(field: str, day: date, today: date) -> None:
    """A 422 for a day of someone's history after the gym's today, or more than
    `HISTORY_WINDOW_YEARS` before it: a typo, not a rule."""
    if day > today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} is today at the latest"
        )
    if day < add_months(today, -12 * HISTORY_WINDOW_YEARS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{field} must be within {HISTORY_WINDOW_YEARS} years of today",
        )


def _shown(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Each field of `after` that differs from `before`, with both, as a `history_set`
    row's `detail` holds them."""
    return {
        field: {"before": _shown(before.get(field)), "after": _shown(value)}
        for field, value in after.items()
        if before.get(field) != value
    }


async def record_history_set(
    session: AsyncSession,
    person_id: uuid.UUID,
    changed: Mapping[str, Any],
    *,
    import_id: uuid.UUID | None = None,
) -> None:
    """The `history_set` row for `changed` (`changes`), in the write's transaction: the
    write and its record are both kept or neither is. Nothing changed, nothing recorded.
    Also why someone left and a former student's dates (#294), and what an import set,
    with the `history_imported` row's id as `import_id` (#297)."""
    if not changed:
        return
    detail = dict(changed) if import_id is None else {"import_id": str(import_id), **changed}
    result = await session.execute(
        INSERT_HISTORY_SET,
        {"person": person_id, "action": HISTORY_SET, "detail": json.dumps(detail)},
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(f"no audit row for the history of person {person_id}")


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
        refuse_outside_history("member_since", body.member_since, await _today(session, tenant))
    after = body.model_dump()
    changed = changes(record._asdict(), after)
    if changed:
        await session.execute(SET_HISTORY, {**after, "id": person_id})
        await record_history_set(session, person_id, changed)
    return await read_person(session, person_id, sees_reason=True)
