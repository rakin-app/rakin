"""Member import from the gym's spreadsheet: read the file, then dry-run and import rows.

`POST /api/import/sheet` takes the file itself as the body (CSV or XLSX, up to
`MAX_UPLOAD_BYTES`) and answers its header, its rows and a suggested mapping; nothing
is stored. `POST /api/import/members` takes those rows back with the admin's mapping
and writes, for each row, the person, their guardian and the link between them, and a
membership with its plan and current due date.

Each row is written in a savepoint of its own: a row the database refuses writes
nothing and is reported with its errors, and the other rows still import. A dry run
writes every row exactly as the import would and then rolls the lot back, so it
reports what the database itself would refuse, and a row that names a guardian an
earlier row adds finds them.

Running it again creates nothing twice. An adult is found by their phone, as
`join_gym_by_phone` finds anyone (0004); a dependent, with no phone, by their
guardian's phone and their own name. Whoever is found is left as this gym has them,
and so is a membership they already hold that is not cancelled: an import never
overwrites what the gym already has. Each row says which of its fields that leaves
unapplied (`ignored`), so the dry run shows it before anything is written.

Only an owner or admin may import, since a membership sets what a member is charged.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.guardians import NEW_GYM_PERSON, NEW_PERSON, family, link
from app.api.memberships import insert_membership
from app.domain import membership as domain
from app.domain.dates import local_date, start_of_local_day
from app.domain.membership import PlanKind, PlanTerms
from app.member_import.rows import (
    ErrorCode,
    Field,
    Member,
    Plan,
    PlanFinder,
    fold,
    read_members,
    suggest_mapping,
)
from app.member_import.sheet import SheetError, read_sheet
from app.roles import AdminSession
from app.schemas.member_import import (
    ImportReport,
    ImportSummary,
    MemberImport,
    Outcome,
    RowError,
    RowResult,
    Sheet,
    SheetRefusal,
    SheetRefusalCode,
    SheetRefused,
    SheetRow,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/import", tags=["import"])

# A spreadsheet of a few hundred members is tens of kilobytes.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

SPREADSHEET_BODY = {"schema": {"type": "string", "format": "binary"}}

PLANS = "SELECT id, name, active, kind, anchor, credits, credit_expiry_days FROM plan"

# RLS keeps every table to the current gym.
BY_PHONE = """
    SELECT gp.person_id FROM gym_person gp JOIN person p ON p.id = gp.person_id
    WHERE p.phone = :phone
"""
GUARDIAN_OF = "SELECT guardian_person_id FROM guardian_link WHERE dependent_person_id = :id"
LIVE_MEMBERSHIP = """
    SELECT plan_id, current_period_end FROM membership
    WHERE person_id = :id AND status <> 'cancelled'
    ORDER BY started_at DESC, created_at DESC
    LIMIT 1
"""
RECORD = "SELECT name, email, rut, dob FROM gym_person WHERE person_id = :id"
JOIN = "SELECT person_id FROM join_gym_by_phone(:phone, :name, :email, :rut, :dob)"


def _refused(status_code: int, code: SheetRefusalCode) -> HTTPException:
    return HTTPException(status_code, SheetRefusal(code=code).model_dump())


@router.post(
    "/sheet",
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": SheetRefused},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": SheetRefused},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "text/csv": SPREADSHEET_BODY,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
                    SPREADSHEET_BODY
                ),
            },
        }
    },
)
async def upload_sheet(request: Request, session: AdminSession) -> Sheet:
    """The spreadsheet in the body, as rows of text and a suggested mapping."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise _refused(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        sheet = read_sheet(bytes(data))
    except SheetError as error:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
    return Sheet(
        headers=sheet.headers,
        rows=[SheetRow(number=row.number, cells=row.cells) for row in sheet.rows],
        mapping=suggest_mapping(sheet.headers),
    )


class RowRefused(Exception):
    """The database's answer for a row: it writes nothing."""

    def __init__(self, on: Field, code: ErrorCode) -> None:
        super().__init__(on, code)
        self.on = on
        self.code: ErrorCode = code


class _Writer:
    """Writes rows into the current gym."""

    def __init__(self, session: AsyncSession, timezone: str, today: date) -> None:
        self.session = session
        self.timezone = timezone
        self.today = today
        # The current row's fields that something already here keeps it from applying.
        self.ignored: list[Field] = []

    async def _scalar(self, sql: str, **params: Any) -> Any:
        return await self.session.scalar(text(sql), params)

    async def _join(
        self,
        phone: str,
        name: str,
        email: str | None = None,
        rut: str | None = None,
        dob: date | None = None,
    ) -> uuid.UUID:
        params = {"phone": phone, "name": name, "email": email, "rut": rut, "dob": dob}
        person_id: uuid.UUID = await self._scalar(JOIN, **params)
        return person_id

    async def row(self, member: Member) -> RowResult:
        self.ignored = []
        guardian: Outcome | None = None
        link_outcome: Outcome | None = None
        guardian_id: uuid.UUID | None = None
        if member.guardian_phone is not None:
            guardian_id, guardian = await self._guardian(member)

        if member.phone is not None:
            person_id, person = await self._adult(member)
            if guardian_id is not None:
                link_outcome = await self._link(guardian_id, person_id)
        else:
            assert guardian_id is not None  # `read_members` refuses a row with neither
            person_id, person = await self._dependent(member, guardian_id)
            link_outcome = person

        membership = None if member.plan is None else await self._membership(member, person_id)
        return RowResult(
            row=member.number,
            name=member.name,
            errors=[],
            person=person,
            guardian=guardian,
            link=link_outcome,
            membership=membership,
            ignored=sorted(set(self.ignored), key=list(Field).index),
        )

    async def _kept(self, person_id: uuid.UUID, member: Member) -> None:
        """Note the sheet's values that differ from this gym's record of `person_id`."""
        record = (await self.session.execute(text(RECORD), {"id": person_id})).one()
        sheet = {
            Field.NAME: (member.name, record.name),
            Field.EMAIL: (member.email, record.email),
            Field.RUT: (member.rut, record.rut),
            Field.DOB: (member.dob, record.dob),
        }
        self.ignored += [f for f, (new, kept) in sheet.items() if new is not None and new != kept]

    async def _adult(self, member: Member) -> tuple[uuid.UUID, Outcome]:
        assert member.phone is not None
        if (found := await self._scalar(BY_PHONE, phone=member.phone)) is not None:
            await self._kept(found, member)
            return found, "existing"
        person_id = await self._join(
            member.phone, member.name, member.email, member.rut, member.dob
        )
        return person_id, "created"

    async def _guardian(self, member: Member) -> tuple[uuid.UUID, Outcome]:
        assert member.guardian_phone is not None
        if (found := await self._scalar(BY_PHONE, phone=member.guardian_phone)) is not None:
            if member.guardian_name is not None:
                kept = await self._scalar(
                    "SELECT name FROM gym_person WHERE person_id = :id", id=found
                )
                if fold(kept) != fold(member.guardian_name):
                    self.ignored.append(Field.GUARDIAN_NAME)
            return found, "existing"
        if member.guardian_name is None:
            raise RowRefused(Field.GUARDIAN_NAME, "required")
        return await self._join(member.guardian_phone, member.guardian_name), "created"

    async def _dependent(self, member: Member, guardian_id: uuid.UUID) -> tuple[uuid.UUID, Outcome]:
        theirs = await family(self.session, guardian_id)
        if theirs.guardian is not None:
            # A dependent's guardian is never someone's dependent (0010).
            raise RowRefused(Field.GUARDIAN_PHONE, "one_level")
        name = fold(member.name)
        if found := next((d.id for d in theirs.dependents if fold(d.name) == name), None):
            await self._kept(found, member)
            return found, "existing"
        person_id = uuid.uuid4()
        values = {
            "id": person_id,
            "name": member.name,
            "email": member.email,
            "rut": member.rut,
            "dob": member.dob,
        }
        await self.session.execute(text(NEW_PERSON), values)
        await self.session.execute(text(NEW_GYM_PERSON), values)
        await self._link(guardian_id, person_id)
        return person_id, "created"

    async def _link(self, guardian_id: uuid.UUID, dependent_id: uuid.UUID) -> Outcome:
        current = await self._scalar(GUARDIAN_OF, id=dependent_id)
        if current == guardian_id:
            return "existing"
        if current is not None:
            raise RowRefused(Field.GUARDIAN_PHONE, "has_guardian")
        if (code := await link(self.session, guardian_id, dependent_id)) is not None:
            raise RowRefused(Field.GUARDIAN_PHONE, code)
        return "created"

    async def _membership(self, member: Member, person_id: uuid.UUID) -> Outcome:
        assert member.plan is not None
        started_on = member.started_on or self.today
        if member.due_on is not None and member.started_on is None:
            # An overdue member started no later than the payment they owe.
            started_on = min(started_on, member.due_on)
        started = domain.imported(member.plan.terms, started_on, member.due_on)
        live = (await self.session.execute(text(LIVE_MEMBERSHIP), {"id": person_id})).first()
        if live is not None:
            if live.plan_id != member.plan.id:
                self.ignored.append(Field.PLAN)
            elif (
                member.due_on is not None and live.current_period_end != started.current_period_end
            ):
                self.ignored.append(Field.DUE_ON)
            return "existing"
        await insert_membership(
            self.session,
            person_id,
            member.plan.id,
            started,
            start_of_local_day(started_on, self.timezone),
        )
        return "created"


def _refusal(member: Member) -> RowResult:
    return RowResult(
        row=member.number,
        name=member.name,
        errors=[RowError(field=e.field, code=e.code) for e in member.errors],
        person=None,
        guardian=None,
        link=None,
        membership=None,
        ignored=[],
    )


async def _plans(session: AsyncSession) -> list[Plan]:
    rows = await session.execute(text(PLANS))
    return [
        Plan(
            id=row.id,
            name=row.name,
            active=row.active,
            terms=PlanTerms(PlanKind(row.kind), row.anchor, row.credits, row.credit_expiry_days),
        )
        for row in rows
    ]


@router.post("/members")
async def import_members(
    body: MemberImport,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> ImportReport:
    """Write the rows, or with `dry_run` (the default) only say what writing them would do."""
    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    today = local_date(datetime.now(UTC), timezone)
    finder = PlanFinder(await _plans(session), body.plans)
    members = read_members(
        [(row.number, row.cells) for row in body.rows], body.mapping, finder, today
    )

    writer = _Writer(session, timezone, today)
    results: dict[int, RowResult] = {}
    everything = await session.begin_nested()
    for index, member in sorted(enumerate(members), key=_guardians_first(members)):
        if not member.errors:
            try:
                async with session.begin_nested():
                    results[index] = await writer.row(member)
                continue
            except RowRefused as refused:
                member.refuse(refused.on, refused.code)
        results[index] = _refusal(member)
    if body.dry_run:
        await everything.rollback()
    else:
        await everything.commit()

    rows = [results[index] for index in range(len(members))]
    return ImportReport(dry_run=body.dry_run, summary=_summary(rows), rows=rows)


def _guardians_first(members: list[Member]) -> Callable[[tuple[int, Member]], tuple[int, int]]:
    """The order rows are written in: guardians' own rows first, then everyone else with
    a phone, then dependents, each in the sheet's order. So a row naming a guardian finds
    the guardian the sheet describes, with the name their own row gives them."""
    guardians = {m.guardian_phone for m in members if m.guardian_phone is not None}

    def key(pair: tuple[int, Member]) -> tuple[int, int]:
        index, member = pair
        if member.phone is None:
            return 2, index
        return (0 if member.phone in guardians else 1), index

    return key


def _summary(rows: list[RowResult]) -> ImportSummary:
    refused = sum(1 for row in rows if row.errors)
    return ImportSummary(
        rows=len(rows),
        imported=len(rows) - refused,
        refused=refused,
        # A guardian the sheet names on several rows is created on the first.
        people_created=sum((r.person == "created") + (r.guardian == "created") for r in rows),
        links_created=sum(r.link == "created" for r in rows),
        memberships_created=sum(r.membership == "created" for r in rows),
    )
