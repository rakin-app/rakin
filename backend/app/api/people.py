"""People in the current gym: list and search them, add one by RUT or email, read and
edit this gym's record.

Identity is global by RUT (docs/technical.md#domain-model), so adding someone whose
RUT another gym already has attaches that person rather than duplicating them. The
answer gives no sign of it: the same 201, carrying what this gym entered and this
gym's timestamps, whether the RUT was new or known (migrations 0004, 0036). Someone
with no RUT is keyed by their email in this gym alone: an email never links two
gyms' people. Only a RUT already in *this* gym, or the email of someone added here
with none, is refused, with a 409 naming that person, so the admin can open them
instead. The phone is a contact, edited like the email, and finds nobody.

The list leaves out whoever has left the gym (dado de baja, migration 0032) unless
asked for them: `left=only` is the "Dados de baja" list, `left=any` everyone, for a
picker that must still find them (a payment they owe).

Every staff role may use it, coaches included; members may not.
"""

import re
import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.membership import MembershipStatus
from app.roles import StaffSession
from app.schemas.people import (
    PHONE_REQUIRED,
    DuplicateCode,
    MemberPage,
    MemberRow,
    MembershipSummary,
    Person,
    PersonConflict,
    PersonCreate,
    PersonInGym,
    PersonRef,
    PersonUpdate,
)

router = APIRouter(prefix="/api/people", tags=["people"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "person not found")


def missing_phone(record: str) -> str:
    """Whether the `gym_person` row `record` is a member the gym cannot reach (#165): no
    phone, "No tiene WhatsApp" unticked, and neither staff, who need none, nor a
    dependent, whose guardian's phone is the one used. "Falta teléfono"."""
    return f"""(
        {record}.phone IS NULL AND NOT {record}.no_whatsapp
        AND NOT EXISTS (
            SELECT FROM staff s
            WHERE s.gym_id = {record}.gym_id AND s.person_id = {record}.person_id
        )
        AND NOT EXISTS (
            SELECT FROM guardian_link d
            WHERE d.gym_id = {record}.gym_id AND d.dependent_person_id = {record}.person_id
        )
    )"""


def missing_rut(record: str) -> str:
    """Whether the `gym_person` row `record` says nothing of who they are: no RUT and no
    email, neither staff nor a dependent, whose guardian answers for them. "Falta RUT": an import
    row from an old sheet, found again only by name (#165)."""
    return f"""(
        {record}.rut IS NULL AND {record}.email IS NULL
        AND NOT EXISTS (
            SELECT FROM staff s
            WHERE s.gym_id = {record}.gym_id AND s.person_id = {record}.person_id
        )
        AND NOT EXISTS (
            SELECT FROM guardian_link d
            WHERE d.gym_id = {record}.gym_id AND d.dependent_person_id = {record}.person_id
        )
    )"""


# This gym's record. RLS on `gym_person` keeps it to the current gym.
SELECT_PERSON = f"""
    SELECT gp.person_id AS id, gp.phone, gp.no_whatsapp, {missing_phone("gp")} AS missing_phone,
           {missing_rut("gp")} AS missing_rut,
           gp.name, gp.email, gp.rut, gp.dob, gp.left_on, gp.created_at, gp.updated_at
    FROM gym_person gp
    WHERE gp.person_id = :id
"""


# Accents and case ignored, so "martin" finds "Martín" and "nunez" finds "Núñez".
def _fold(sql: str) -> str:
    return f"lower(translate({sql}, 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun'))"


# The membership a list row shows for `gp`, a `gym_person` (`MembershipSummary`):
# `m` and its plan `pl`.
SHOWN_MEMBERSHIP = """
    LEFT JOIN LATERAL (
        SELECT id, status, plan_id FROM membership
        WHERE gym_id = gp.gym_id AND person_id = gp.person_id
        ORDER BY status = 'cancelled', started_at DESC, created_at DESC
        LIMIT 1
    ) m ON true
    LEFT JOIN plan pl ON pl.id = m.plan_id
"""

# Everyone this gym has a record of, except staff who hold no membership here, each
# with the membership the list shows and their family (0010). RLS keeps every table to
# the current gym.
MEMBERS = f"""
    SELECT gp.person_id AS id, gp.name, gp.phone, gp.no_whatsapp,
           {missing_phone("gp")} AS missing_phone, {missing_rut("gp")} AS missing_rut,
           gp.rut, gp.left_on,
           m.id AS membership_id, m.status, m.plan_id, pl.name AS plan_name,
           g.person_id AS guardian_id, g.name AS guardian_name,
           (SELECT count(*) FROM guardian_link d
            WHERE d.guardian_person_id = gp.person_id) AS dependents
    FROM gym_person gp
    {SHOWN_MEMBERSHIP}
    LEFT JOIN guardian_link gl ON gl.dependent_person_id = gp.person_id
    LEFT JOIN gym_person g ON g.gym_id = gl.gym_id AND g.person_id = gl.guardian_person_id
    WHERE m.id IS NOT NULL
       OR NOT EXISTS (SELECT FROM staff s WHERE s.person_id = gp.person_id)
"""

_LIKE_SPECIALS = re.compile(r"([\\%_])")


def _contains(value: str) -> str:
    return "%" + _LIKE_SPECIALS.sub(r"\\\1", value) + "%"


def _search(q: str) -> tuple[str, dict[str, Any]]:
    """`q` matched against the name, and, when it holds a digit, the phone and RUT as
    typed in any format (`9 8765 4321`, `7.654.321-6`), of rows with a `name`, `phone`
    and `rut`."""
    where = [f"{_fold('name')} LIKE {_fold(':name')} ESCAPE '\\'"]
    params: dict[str, Any] = {"name": _contains(q)}
    digits = re.sub(r"[^0-9]", "", q)
    if digits:
        where.append("phone LIKE :phone")
        params["phone"] = _contains(digits)
        where.append("replace(rut, '-', '') LIKE :rut")
        params["rut"] = _contains(re.sub(r"[^0-9K]", "", q.upper()))
    return "(" + " OR ".join(where) + ")", params


# Everyone this gym has a record of, as `_search` reads them.
SEARCHABLE = """
    SELECT gp.person_id AS id, gp.name, gp.phone, gp.rut
    FROM gym_person gp
"""


def people_matching(q: str) -> tuple[str, dict[str, Any]]:
    """The ids of the people the member list's search finds for `q`, as a subquery,
    for whatever else lists people (the ledger book, #107)."""
    clause, params = _search(q)
    return f"SELECT id FROM ({SEARCHABLE}) people WHERE {clause}", params


@router.get("")
async def list_people(
    session: StaffSession,
    q: Annotated[str, Query(max_length=100)] = "",
    # Repeatable, `?status=active&status=trial`. FastAPI copies the defaults per request.
    statuses: Annotated[list[MembershipStatus], Query(alias="status")] = [],  # noqa: B006
    plan_ids: Annotated[list[uuid.UUID], Query(alias="plan_id")] = [],  # noqa: B006
    program_ids: Annotated[list[uuid.UUID], Query(alias="program_id")] = [],  # noqa: B006
    left: Literal["no", "only", "any"] = "no",
    # Only the members with "Falta teléfono", or "Falta RUT".
    missing_phone: bool = False,
    missing_rut: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemberPage:
    """The member list, by name. Filters combine with AND; several values of one filter
    with OR. `status`, `plan_id` and `program_id` match the membership each row shows:
    a member is in a program through their plan (migration 0016)."""
    where: list[str] = []
    params: dict[str, Any] = {}
    if left == "no":
        where.append("left_on IS NULL")
    elif left == "only":
        where.append("left_on IS NOT NULL")
    if missing_phone:
        where.append("missing_phone")
    if missing_rut:
        where.append("missing_rut")
    if q.strip():
        clause, params = _search(q.strip())
        where.append(clause)
    if statuses:
        where.append("status = ANY(CAST(:statuses AS text[]))")
        params["statuses"] = [s.value for s in statuses]
    if plan_ids:
        where.append("plan_id = ANY(CAST(:plan_ids AS uuid[]))")
        params["plan_ids"] = plan_ids
    if program_ids:
        where.append(
            "plan_id IN (SELECT id FROM plan WHERE program_id = ANY(CAST(:program_ids AS uuid[])))"
        )
        params["program_ids"] = program_ids
    filtered = f"SELECT * FROM ({MEMBERS}) members"
    if where:
        filtered += " WHERE " + " AND ".join(where)

    total = await session.scalar(text(f"SELECT count(*) FROM ({filtered}) f"), params)
    rows = await session.execute(
        text(f"{filtered} ORDER BY {_fold('name')}, id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    items = [
        MemberRow(
            id=row.id,
            name=row.name,
            phone=row.phone,
            no_whatsapp=row.no_whatsapp,
            missing_phone=row.missing_phone,
            missing_rut=row.missing_rut,
            rut=row.rut,
            membership=shown_membership(row),
            guardian=None
            if row.guardian_id is None
            else PersonRef(id=row.guardian_id, name=row.guardian_name),
            dependents=row.dependents,
            left_on=row.left_on,
        )
        for row in rows
    ]
    return MemberPage(items=items, total=total or 0)


def shown_membership(row: Any) -> MembershipSummary | None:
    """A row's `SHOWN_MEMBERSHIP` columns, as the API answers them."""
    if row.membership_id is None:
        return None
    return MembershipSummary(
        id=row.membership_id, status=row.status, plan_id=row.plan_id, plan_name=row.plan_name
    )


async def in_gym(session: AsyncSession, person_id: uuid.UUID) -> bool:
    """Whether this gym has a record of `person_id`."""
    found = await session.scalar(
        text("SELECT EXISTS (SELECT FROM gym_person WHERE person_id = :id)"), {"id": person_id}
    )
    return bool(found)


async def read_person(session: AsyncSession, person_id: uuid.UUID) -> Person:
    row = (await session.execute(text(SELECT_PERSON), {"id": person_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Person.model_validate(row, from_attributes=True)


def in_gym_conflict(conflict: PersonConflict) -> HTTPException:
    """The 409 naming who in this gym already has the RUT or email. Raised, not
    returned, so the transaction rolls back and nothing is written."""
    return HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))


async def refuse_rut_in_gym(
    session: AsyncSession, rut: str | None, *, person_id: uuid.UUID | None = None
) -> None:
    """Refuse a RUT someone else in this gym already has."""
    if rut is None:
        return
    holder = await session.scalar(
        text(
            "SELECT person_id FROM gym_person"
            " WHERE rut = :rut AND person_id IS DISTINCT FROM CAST(:id AS uuid)"
        ),
        {"rut": rut, "id": person_id},
    )
    if holder is not None:
        raise in_gym_conflict(PersonConflict(code="rut_in_gym", person_id=holder))


JOIN_GYM = "SELECT person_id, joined FROM join_gym(:rut, :email, :name, :phone, :dob)"


async def join_gym(
    session: AsyncSession,
    *,
    name: str,
    rut: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    no_whatsapp: bool = False,
    dob: date | None = None,
) -> tuple[uuid.UUID, bool]:
    """The person `rut` is, or with none the one this gym has under `email`, else
    someone new, and whether this call added them to the gym (`join_gym`, 0036). With
    neither, always someone new: a dependent. A record new here takes `no_whatsapp`; a
    known one is left as the gym has it."""
    result = await session.execute(
        text(JOIN_GYM), {"rut": rut, "email": email, "name": name, "phone": phone, "dob": dob}
    )
    person_id, joined = result.one()
    if joined and no_whatsapp:
        await session.execute(
            text("UPDATE gym_person SET no_whatsapp = true WHERE person_id = :id"),
            {"id": person_id},
        )
    found: uuid.UUID = person_id
    return found, joined


async def claim_rut(session: AsyncSession, person_id: uuid.UUID, rut: str) -> None:
    """Make `rut` who someone with none is, when nobody has it yet (`claim_rut`, 0036).
    It answers nothing: whether the RUT was free, or someone else's in another gym, is
    no business of this gym's. Linking two people who turn out to be one is a merge."""
    await session.execute(text("SELECT claim_rut(:id, :rut)"), {"id": person_id, "rut": rut})


async def add_to_gym(
    session: AsyncSession,
    *,
    name: str,
    rut: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    no_whatsapp: bool = False,
    dob: date | None = None,
) -> uuid.UUID:
    """Add someone new to this gym, refusing a RUT, or the email of someone with no
    RUT, already someone's here."""
    await refuse_rut_in_gym(session, rut)
    person_id, joined = await join_gym(
        session, name=name, rut=rut, email=email, phone=phone, no_whatsapp=no_whatsapp, dob=dob
    )
    if not joined:
        code: DuplicateCode = "rut_in_gym" if rut is not None else "email_in_gym"
        raise in_gym_conflict(PersonConflict(code=code, person_id=person_id))
    return person_id


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": PersonInGym}},
)
async def create_person(body: PersonCreate, session: StaffSession) -> Person:
    return await read_person(session, await add_to_gym(session, **body.model_dump()))


@router.get("/{person_id}")
async def get_person(person_id: uuid.UUID, session: StaffSession) -> Person:
    return await read_person(session, person_id)


@router.patch("/{person_id}", responses={status.HTTP_409_CONFLICT: {"model": PersonInGym}})
async def update_person(person_id: uuid.UUID, body: PersonUpdate, session: StaffSession) -> Person:
    changes = body.model_dump(exclude_unset=True)
    await refuse_rut_in_gym(session, changes.get("rut"), person_id=person_id)
    if changes:
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        result = await session.execute(
            text(f"UPDATE gym_person SET {assignments}, updated_at = now() WHERE person_id = :id"),
            {**changes, "id": person_id},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NOT_FOUND
    if changes.get("rut") is not None:
        await claim_rut(session, person_id, changes["rut"])
    person = await read_person(session, person_id)
    # A member's phone is cleared, or "No tiene WhatsApp" unticked, only with a phone in
    # its place. Raised, so the update rolls back. Editing anything else leaves a
    # member already missing one as they were ("Falta teléfono").
    if person.missing_phone and changes.keys() & {"phone", "no_whatsapp"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, PHONE_REQUIRED)
    return person
