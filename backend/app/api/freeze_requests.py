"""Freeze requests (#270): a student asks for a freeze from their page, and the owner
or an admin approves or rejects it.

- `/api/me/freeze-requests` is the asking side, for anyone signed in to the gym: the
  member asks for their own membership, a guardian for a dependent's, and nobody for
  anyone else's (a 404, as for a membership that is not there). Only an Active
  membership with no freeze running or booked and no request waiting takes one, from
  today at the earliest, for as long as a freeze can last. Each owner and admin with
  an email is told of it, with a link to the member's ficha. Whoever asked may
  withdraw it while it waits.
- `/api/freeze-requests` is the answering side, for the owner and admins, as
  freezing is: the requests waiting, oldest first; approving one, which freezes the
  membership through `app.api.memberships.freeze`, the admin's own freeze, on the
  dates asked for or others the admin gives; and rejecting one, with a note for the
  member. Either answer emails the member, or their guardian.

The student page shows each running membership's request and the last one answered
(`my_plans`).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.memberships import SELECT_MEMBERSHIP, freeze, membership_of
from app.contacts import contact_for
from app.domain import membership as domain
from app.domain.dates import gym_today
from app.domain.membership import MAX_FREEZE_DAYS, MembershipStatus
from app.notices import (
    FREEZE_APPROVED,
    FREEZE_REJECTED,
    FREEZE_REQUESTED,
    Notice,
    Notices,
    Template,
    get_notices,
)
from app.roles import ADMIN_ROLES, AdminSession
from app.schemas.freeze_requests import (
    REASON_LABELS,
    FreezeApproval,
    FreezeRefusal,
    FreezeRejection,
    FreezeRequest,
    FreezeRequestCreate,
    MyPlan,
)
from app.schemas.memberships import FreezeCreate, Membership
from app.tenancy import Tenant, TenantSession, current_tenant

mine = APIRouter(prefix="/api/me/freeze-requests", tags=["me"])
router = APIRouter(prefix="/api/freeze-requests", tags=["freeze requests"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "freeze request not found")
NO_MEMBERSHIP = HTTPException(status.HTTP_404_NOT_FOUND, "membership not found")

# RLS keeps every table to the current gym.
SELECT_REQUEST = """
    SELECT r.id, r.membership_id, m.person_id, gp.name AS person_name,
           r.requested_by, coalesce(rp.name, '') AS requested_by_name, pl.name AS plan_name,
           r.from_date, r.to_date, r.reason, r.note, r.status, r.decision_note,
           r.decided_at, r.created_at
    FROM freeze_request r
    JOIN membership m ON m.id = r.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    LEFT JOIN gym_person rp ON rp.gym_id = r.gym_id AND rp.person_id = r.requested_by
"""

# Whose memberships the person acting may ask for: their own and their dependents'.
ASKS_FOR = """
    SELECT CAST(:me AS uuid) AS person_id
    UNION ALL
    SELECT dependent_person_id FROM guardian_link WHERE guardian_person_id = :me
"""

# How long the student page shows an answer for.
DECIDED_SHOWN_DAYS = 30

# The owner and admins, each with the email they are told at.
ADMINS = """
    SELECT gp.person_id, gp.name, gp.email FROM staff s
    JOIN gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
    WHERE s.role = ANY(CAST(:roles AS text[])) AND gp.email IS NOT NULL
    ORDER BY gp.person_id
"""


def _request(row: Any) -> FreezeRequest:
    return FreezeRequest.model_validate(dict(row._mapping))


async def _get(session: AsyncSession, request_id: uuid.UUID) -> FreezeRequest:
    row = (
        await session.execute(text(f"{SELECT_REQUEST} WHERE r.id = :id"), {"id": request_id})
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    return _request(row)


async def _today(session: AsyncSession, tenant: Tenant) -> Any:
    timezone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(timezone)


def _refused(code: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        FreezeRefusal.model_validate({"code": code}).model_dump(),
    )


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def freeze_reason(request: FreezeRequest) -> str:
    """What the freeze it becomes says: the reason, and what they wrote."""
    if request.reason == "otro" and request.note:
        return request.note
    label = REASON_LABELS[request.reason]
    return f"{label}: {request.note}" if request.note else label


@mine.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": FreezeRefusal}},
)
async def request_freeze(
    body: FreezeRequestCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> FreezeRequest:
    """Ask for a freeze of their membership, or a dependent's."""
    # Locked, so a second request at once waits for this one and finds it pending.
    row = (
        await session.execute(
            text(
                f"{SELECT_MEMBERSHIP} WHERE m.id = :id"
                f" AND m.person_id IN ({ASKS_FOR}) FOR UPDATE OF m"
            ),
            {"id": body.membership_id, "me": tenant.person_id},
        )
    ).one_or_none()
    if row is None:
        raise NO_MEMBERSHIP
    membership = membership_of(row)
    if membership.status is MembershipStatus.FROZEN or membership.freeze is not None:
        raise _refused("has_freeze")
    if membership.status is not MembershipStatus.ACTIVE:
        raise _refused("not_active")
    waiting = await session.scalar(
        text("SELECT 1 FROM freeze_request WHERE membership_id = :id AND status = 'pending'"),
        {"id": membership.id},
    )
    if waiting is not None:
        raise _refused("has_pending")

    today = await _today(session, tenant)
    if body.from_date < today:
        raise _unprocessable("a freeze starts today at the earliest")
    if (body.from_date - today).days > MAX_FREEZE_DAYS:
        raise _unprocessable(f"a freeze starts within {MAX_FREEZE_DAYS} days of today")
    try:
        domain.freeze_days(body.from_date, body.to_date)
    except ValueError as error:
        raise _unprocessable(str(error)) from None

    request_id = await session.scalar(
        text(
            "INSERT INTO freeze_request"
            " (gym_id, membership_id, requested_by, from_date, to_date, reason, note)"
            " VALUES (current_setting('app.gym_id')::uuid, :membership, :by, :from, :to,"
            " :reason, :note) RETURNING id"
        ),
        {
            "membership": membership.id,
            "by": tenant.person_id,
            "from": body.from_date,
            "to": body.to_date,
            "reason": body.reason,
            "note": body.note,
        },
    )
    created = await _get(session, request_id)
    # After the response, which is after the request has committed.
    for notice in await _requested(session, tenant, created):
        background.add_task(notices.send, notice)
    return created


async def _requested(session: AsyncSession, tenant: Tenant, request: FreezeRequest) -> list[Notice]:
    """`freeze_requested`, to each owner and admin with an email."""
    gym = await session.scalar(text("SELECT name FROM gym WHERE id = :id"), {"id": tenant.gym_id})
    admins = await session.execute(text(ADMINS), {"roles": sorted(ADMIN_ROLES)})
    return [
        Notice(
            FREEZE_REQUESTED,
            to=admin.email,
            person_id=admin.person_id,
            gym_id=tenant.gym_id,
            context={
                "name": admin.name,
                "gym": gym,
                "member_name": request.person_name,
                "member_id": str(request.person_id),
                "requester_name": request.requested_by_name,
                "plan_name": request.plan_name,
                "from_date": request.from_date,
                "to_date": request.to_date,
                "reason": REASON_LABELS[request.reason],
                "note": request.note,
            },
        )
        for admin in admins
    ]


@mine.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_freeze_request(
    request_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
) -> Response:
    """Withdraw a request still waiting, by whoever made it."""
    result = await session.execute(
        text(
            "UPDATE freeze_request SET status = 'withdrawn', decided_at = now()"
            " WHERE id = :id AND requested_by = :me AND status = 'pending'"
        ),
        {"id": request_id, "me": tenant.person_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NOT_FOUND
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("")
async def list_freeze_requests(session: AdminSession) -> list[FreezeRequest]:
    """The requests waiting for an answer, oldest first."""
    rows = await session.execute(
        text(f"{SELECT_REQUEST} WHERE r.status = 'pending' ORDER BY r.created_at, r.id")
    )
    return [_request(row) for row in rows]


async def _pending(session: AsyncSession, request_id: uuid.UUID) -> FreezeRequest:
    """A request still waiting, its row locked: a second answer at once waits for this
    one and then finds it answered."""
    found = await session.scalar(
        text("SELECT id FROM freeze_request WHERE id = :id AND status = 'pending' FOR UPDATE"),
        {"id": request_id},
    )
    if found is None:
        raise NOT_FOUND
    return await _get(session, request_id)


DECIDE = text(
    "UPDATE freeze_request SET status = :status, decided_by = :by, decided_at = now(),"
    " decision_note = :note WHERE id = :id"
)


@router.post("/{request_id}/approve")
async def approve_freeze_request(
    request_id: uuid.UUID,
    body: FreezeApproval,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Membership:
    """Freeze the membership as asked, or on the dates the admin gives, exactly as
    `POST /api/memberships/{id}/freeze` would, and refused as it would be."""
    request = await _pending(session, request_id)
    frozen = await freeze(
        session,
        tenant,
        request.membership_id,
        FreezeCreate(
            from_date=body.from_date or request.from_date,
            to_date=body.to_date or request.to_date,
            reason=freeze_reason(request),
        ),
    )
    await session.execute(
        DECIDE, {"id": request_id, "status": "approved", "by": tenant.person_id, "note": None}
    )
    assert frozen.freeze is not None
    notice = await _answered(
        session,
        tenant,
        request,
        FREEZE_APPROVED,
        {"from_date": frozen.freeze.from_date, "to_date": frozen.freeze.to_date},
    )
    if notice is not None:
        background.add_task(notices.send, notice)
    return frozen


@router.post("/{request_id}/reject")
async def reject_freeze_request(
    request_id: uuid.UUID,
    body: FreezeRejection,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> FreezeRequest:
    """Reject it, with a note for the member when the admin writes one."""
    request = await _pending(session, request_id)
    await session.execute(
        DECIDE,
        {"id": request_id, "status": "rejected", "by": tenant.person_id, "note": body.note},
    )
    notice = await _answered(
        session,
        tenant,
        request,
        FREEZE_REJECTED,
        {"from_date": request.from_date, "to_date": request.to_date, "note": body.note},
    )
    if notice is not None:
        background.add_task(notices.send, notice)
    return await _get(session, request_id)


async def _answered(
    session: AsyncSession,
    tenant: Tenant,
    request: FreezeRequest,
    template: Template,
    values: dict[str, Any],
) -> Notice | None:
    """The answer, to the member or their guardian, when there is an email."""
    contact = await contact_for(session, request.person_id)
    if contact is None or not contact.email:
        return None
    gym = await session.scalar(text("SELECT name FROM gym WHERE id = :id"), {"id": tenant.gym_id})
    return Notice(
        template,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=tenant.gym_id,
        context={
            "name": contact.name,
            "gym": gym,
            "dependent_name": request.person_name if contact.on_behalf_of else None,
            **values,
        },
    )


# The person's running memberships and their dependents', theirs first, then by name.
MY_MEMBERSHIPS = f"""
    {SELECT_MEMBERSHIP}
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    WHERE m.person_id IN ({ASKS_FOR}) AND m.status IN ('active', 'frozen')
    ORDER BY m.person_id <> :me, lower(gp.name), m.started_at, m.id
"""


async def my_plans(session: AsyncSession, tenant: Tenant) -> list[MyPlan]:
    """Each running membership the person may ask a freeze for, with its request
    waiting and the last one answered in `DECIDED_SHOWN_DAYS` days."""
    params = {"me": tenant.person_id}
    memberships = [
        membership_of(row) for row in await session.execute(text(MY_MEMBERSHIPS), params)
    ]
    rows = await session.execute(
        text("SELECT person_id, name FROM gym_person WHERE person_id = ANY(:ids)"),
        {"ids": list({m.person_id for m in memberships})},
    )
    names: dict[uuid.UUID, str] = {row.person_id: row.name for row in rows}
    plans = []
    for membership in memberships:
        rows = await session.execute(
            text(
                f"{SELECT_REQUEST} WHERE r.membership_id = :id AND (r.status = 'pending'"
                " OR (r.status IN ('approved', 'rejected')"
                " AND r.decided_at > now() - make_interval(days => :days)))"
                " ORDER BY r.status = 'pending' DESC, r.decided_at DESC"
            ),
            {"id": membership.id, "days": DECIDED_SHOWN_DAYS},
        )
        found = [_request(row) for row in rows]
        pending = next((r for r in found if r.status == "pending"), None)
        decided = next((r for r in found if r.status != "pending"), None)
        plans.append(
            MyPlan(
                membership_id=membership.id,
                person_id=membership.person_id,
                person_name=names[membership.person_id],
                plan_name=membership.plan_name,
                status=membership.status.value,
                freeze=membership.freeze,
                pending_request=pending,
                last_decided=decided,
            )
        )
    return plans
