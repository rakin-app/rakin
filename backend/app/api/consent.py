"""The consent register (#370, migration 0057): what a member's data rest on, and who
accepted which privacy notice when.

An adult's data rest on the membership contract; the join form's box is evidence that
they were shown the notice, kept as `notice_accepted`. A minor's, and a dependent's
with no birth date, rest on their guardian's consent (docs/legal-research.md, row 1),
an act of its own apart from the membership: the guardian gives it on the join form
or on their own page, and withdraws it there, and the membership stays as it is either
way. Every member under 18 needs it, those added by hand or by import too; the welcome
and `join_approved` tell a guardian whose consent is missing where to give it.

- `GET /api/people/{id}/consent`, for every staff role: the ficha's basis, the
  guardian's consent when it is the basis, and every act.
- `/api/me/consents`, for the signed-in guardian: each dependent whose data rest on
  their consent, giving it (`POST`, naming the notice's version) and withdrawing it
  (`DELETE`).

The version is the notice's two dates (`NoticeVersion`). One older than the notice now,
such as a form opened before the gym saved its details, is a 409 `stale_notice`: the
person accepts the notice as it is, or nothing.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND
from app.contacts import minor_today
from app.roles import StaffSession
from app.schemas.consent import (
    ConsentEvent,
    ConsentState,
    DependentConsent,
    NoticeVersion,
    PersonConsent,
)
from app.schemas.people import PersonRef
from app.schemas.privacy import TEMPLATE_UPDATED_ON
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(prefix="/api/people", tags=["people"])
mine = APIRouter(prefix="/api/me/consents", tags=["me"])

STALE_NOTICE = HTTPException(status.HTTP_409_CONFLICT, "stale_notice")
NOT_YOURS = HTTPException(status.HTTP_404_NOT_FOUND, "dependent not found")
ALREADY_GIVEN = HTTPException(status.HTTP_409_CONFLICT, "already_given")
NOT_GIVEN = HTTPException(status.HTTP_409_CONFLICT, "not_given")


def needs_consent(record: str) -> str:
    """Whether the `gym_person` row `record`'s data rest on their guardian's consent: a
    minor by birth date on the gym's today, or, with no birth date, someone's dependent
    here, as a kid added by name alone is."""
    return f"""(CASE WHEN {record}.dob IS NOT NULL THEN {minor_today(record)}
        ELSE EXISTS (
            SELECT FROM guardian_link d
            WHERE d.gym_id = {record}.gym_id AND d.dependent_person_id = {record}.person_id
        ) END)"""


def latest_consent(record: str) -> str:
    """A lateral join, `c`, on the guardian's latest act of consent for the `gym_person`
    row `record`: none before any. The latest by `at`: a join request approved late
    records its consent at the time it was sent."""
    return f"""
    LEFT JOIN LATERAL (
        SELECT ce.action, ce.at FROM consent_event ce
        WHERE ce.gym_id = {record}.gym_id AND ce.person_id = {record}.person_id
          AND ce.action IN ('consent_given', 'consent_withdrawn')
        ORDER BY ce.at DESC, ce.id DESC LIMIT 1
    ) c ON true
"""


def state_of(action: str | None) -> ConsentState:
    if action == "consent_given":
        return "given"
    return "withdrawn" if action == "consent_withdrawn" else "missing"


async def check_notice(session: AsyncSession, version: NoticeVersion) -> None:
    """A 409 `stale_notice` unless `version` is the current gym's notice now."""
    details_on = await session.scalar(
        text(
            "SELECT (settings -> 'privacy' ->> 'updated_on')::date FROM gym"
            " WHERE id = current_setting('app.gym_id')::uuid"
        )
    )
    if version.template_on != TEMPLATE_UPDATED_ON or version.details_on != details_on:
        raise STALE_NOTICE


INSERT = """
    INSERT INTO consent_event (gym_id, person_id, action, by_person_id, source,
                               template_on, details_on, at)
    VALUES (current_setting('app.gym_id')::uuid, :person, :action, :by, :source,
            :template_on, :details_on, coalesce(:at, now()))
"""


async def record_join(session: AsyncSession, request: Any, person_id: uuid.UUID) -> None:
    """What an approved join request said, kept on `person_id`: the notice accepted when
    it was sent, and for a minor, by their guardian, with the guardian's consent when
    they gave it. The guardian is whoever approving linked."""
    by = person_id
    if request.guardian_name is not None:
        guardian: uuid.UUID | None = await session.scalar(
            text("SELECT guardian_person_id FROM guardian_link WHERE dependent_person_id = :id"),
            {"id": person_id},
        )
        # A minor's request always links one (`app.member_import.Writer`).
        assert guardian is not None, "a minor's approved request has a guardian"
        by = guardian
    values = {
        "person": person_id,
        "by": by,
        "source": "join",
        "template_on": request.notice_template_on,
        "details_on": request.notice_details_on,
        "at": request.consented_at,
    }
    await session.execute(text(INSERT), {**values, "action": "notice_accepted"})
    if request.guardian_name is not None and request.guardian_consent:
        await session.execute(text(INSERT), {**values, "action": "consent_given"})


async def consent_pending(session: AsyncSession, person_id: uuid.UUID) -> bool:
    """Whether `person_id`'s data rest on a guardian's consent that is not given: what the
    welcome and `join_approved` ask the guardian for."""
    pending: bool | None = await session.scalar(
        text(f"""
            SELECT {needs_consent("gp")} AND c.action IS DISTINCT FROM 'consent_given'
            FROM gym_person gp {latest_consent("gp")}
            WHERE gp.person_id = :id
        """),
        {"id": person_id},
    )
    return bool(pending)


# --- the ficha (every staff role) -----------------------------------------------------

EVENTS = """
    SELECT ce.action, ce.at, ce.source, ce.template_on, ce.details_on,
           ce.by_person_id, b.name AS by_name
    FROM consent_event ce
    LEFT JOIN gym_person b ON b.gym_id = ce.gym_id AND b.person_id = ce.by_person_id
    WHERE ce.person_id = :id
    ORDER BY ce.at DESC, ce.id DESC
"""


@router.get("/{person_id}/consent")
async def get_consent(person_id: uuid.UUID, session: StaffSession) -> PersonConsent:
    row = (
        await session.execute(
            text(f"""
                SELECT {needs_consent("gp")} AS needs, c.action
                FROM gym_person gp {latest_consent("gp")}
                WHERE gp.person_id = :id
            """),
            {"id": person_id},
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    events = [
        ConsentEvent(
            action=e.action,
            at=e.at,
            by=None if e.by_name is None else PersonRef(id=e.by_person_id, name=e.by_name),
            source=e.source,
            template_on=e.template_on,
            details_on=e.details_on,
        )
        for e in await session.execute(text(EVENTS), {"id": person_id})
    ]
    return PersonConsent(
        basis="guardian_consent" if row.needs else "contract",
        consent=state_of(row.action) if row.needs else None,
        events=events,
    )


# --- the guardian's page --------------------------------------------------------------

# The signed-in guardian's dependents whose data rest on their consent, or the one
# `:dependent` names. RLS keeps every table to the current gym.
DEPENDENTS = f"""
    SELECT gp.person_id AS id, gp.name, c.action, c.at
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
    {latest_consent("gp")}
    WHERE gl.guardian_person_id = :guardian AND {needs_consent("gp")}
      AND (CAST(:dependent AS uuid) IS NULL OR gp.person_id = CAST(:dependent AS uuid))
    ORDER BY lower(gp.name), gp.person_id
"""


def _dependent(row: Any) -> DependentConsent:
    return DependentConsent(id=row.id, name=row.name, consent=state_of(row.action), at=row.at)


async def _consents(
    session: AsyncSession, guardian: uuid.UUID, dependent: uuid.UUID | None = None
) -> list[DependentConsent]:
    rows = await session.execute(text(DEPENDENTS), {"guardian": guardian, "dependent": dependent})
    return [_dependent(row) for row in rows]


async def _mine(session: AsyncSession, tenant: Tenant, dependent_id: uuid.UUID) -> DependentConsent:
    """`dependent_id`, locked against a second act at once; a 404 unless they are the
    signed-in guardian's and their data rest on the guardian's consent."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('consent:' || CAST(:id AS text)))"),
        {"id": str(dependent_id)},
    )
    found = await _consents(session, tenant.person_id, dependent_id)
    if not found:
        raise NOT_YOURS
    return found[0]


@mine.get("")
async def my_consents(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> list[DependentConsent]:
    """Each of the signed-in guardian's dependents whose data rest on their consent."""
    return await _consents(session, tenant.person_id)


@mine.post(
    "/{dependent_id}",
    responses={status.HTTP_409_CONFLICT: {"description": "stale_notice or already_given"}},
)
async def give_consent(
    dependent_id: uuid.UUID,
    body: NoticeVersion,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
) -> DependentConsent:
    """The guardian consents to the processing of `dependent_id`'s data, under the
    notice `body` names."""
    if (await _mine(session, tenant, dependent_id)).consent == "given":
        raise ALREADY_GIVEN
    await check_notice(session, body)
    await session.execute(
        text(INSERT),
        {
            "person": dependent_id,
            "action": "consent_given",
            "by": tenant.person_id,
            "source": "page",
            **body.model_dump(),
            "at": None,
        },
    )
    return (await _consents(session, tenant.person_id, dependent_id))[0]


@mine.delete("/{dependent_id}", responses={status.HTTP_409_CONFLICT: {"description": "not_given"}})
async def withdraw_consent(
    dependent_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
) -> DependentConsent:
    """The guardian withdraws their consent. The membership stays as it is."""
    if (await _mine(session, tenant, dependent_id)).consent != "given":
        raise NOT_GIVEN
    await session.execute(
        text(INSERT),
        {
            "person": dependent_id,
            "action": "consent_withdrawn",
            "by": tenant.person_id,
            "source": "page",
            "template_on": None,
            "details_on": None,
            "at": None,
        },
    )
    return (await _consents(session, tenant.person_id, dependent_id))[0]
