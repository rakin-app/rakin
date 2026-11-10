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

Running it again creates nothing twice. Someone is found by their RUT, or by their
email when they have none, as `join_gym` finds anyone (0036); a dependent with neither
by their guardian and their own name. A row with neither and no guardian, as old sheets
have, is found by its name among this gym's people with no RUT, and a guardian the sheet
names alone by theirs. The phone is a contact and finds nobody. Whoever is found is left
as this gym has them, and so is a membership they already hold that is not cancelled:
an import never overwrites what the gym already has. Each row says which of its fields
that leaves unapplied (`ignored`), so the dry run shows it before anything is written,
and flags a contact with no phone (`missing_phone`) and an adult with neither a RUT nor
an email (`missing_identity`): both import.

Only an owner or admin may import, since a membership sets what a member is charged.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.guardians import family, link
from app.api.memberships import PersonHasLeft, insert_membership
from app.api.people import (
    email_holder,
    find_in_gym,
    give_identity,
    join_gym,
    missing_phone,
    rut_holder,
)
from app.domain import membership as domain
from app.domain.dates import gym_today, start_of_local_day
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

GUARDIAN_OF = "SELECT guardian_person_id FROM guardian_link WHERE dependent_person_id = :id"
LIVE_MEMBERSHIP = """
    SELECT plan_id, current_period_end FROM membership
    WHERE person_id = :id AND status <> 'cancelled'
    ORDER BY started_at DESC, created_at DESC
    LIMIT 1
"""
# This gym's people, for finding a row that gives no RUT and no email by name (#165):
# what tells two of one name apart, whether they have a RUT or an email, and whether
# they are someone's dependent. The name is folded in Python (`rows.fold`), the one
# fold the sheet's own names get, so a name matches whatever its accents. RLS keeps it
# to the gym.
PEOPLE = """
    SELECT gp.person_id, gp.name, gp.dob, gp.phone,
           gp.rut IS NULL AND gp.email IS NULL AS keyless,
           EXISTS (
               SELECT FROM guardian_link d WHERE d.dependent_person_id = gp.person_id
           ) AS dependent
    FROM gym_person gp
"""


@dataclass(frozen=True)
class Record:
    """One of this gym's people, as a by-name lookup sees them."""

    person_id: uuid.UUID
    name: str
    dob: date | None
    phone: str | None
    keyless: bool
    dependent: bool


@dataclass(frozen=True)
class Named:
    """Someone found by name, and what tells them apart from another of that name."""

    person_id: uuid.UUID
    dob: date | None
    phone: str | None


class AmbiguousName(Exception):
    """Two or more people of the name, and neither the birth date nor the phone says
    which: the row needs a RUT or an email."""


def told_apart(found: list[Named], dob: date | None, phone: str | None) -> uuid.UUID | None:
    """The one of `found` a row is, by its birth date, then its phone: a value both give
    that differs says it is someone else, one that matches picks them out. Never more
    than a way to tell people apart inside one gym (#165)."""
    for column, value in (("dob", dob), ("phone", phone)):
        if value is None:
            continue
        same = [n for n in found if getattr(n, column) == value]
        if same:
            found = same
            # A birth date that matches settles it, whatever phone they have now.
            if column == "dob" and len(found) == 1:
                break
        else:
            found = [n for n in found if getattr(n, column) is None]
    if len(found) > 1:
        raise AmbiguousName
    return found[0].person_id if found else None


RECORD = "SELECT name, email, rut, phone, dob FROM gym_person WHERE person_id = :id"
MISSING_PHONE = f"SELECT {missing_phone('gp')} FROM gym_person gp WHERE person_id = :id"


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


class Writer:
    """Writes rows into the current gym: the importer's, and the join link's approvals
    (`app.api.join`), so a person is added one way however they come."""

    def __init__(self, session: AsyncSession, timezone: str, today: date) -> None:
        self.session = session
        self.timezone = timezone
        self.today = today
        # The current row's fields that something already here keeps it from applying.
        self.ignored: list[Field] = []
        # Whom this run's rows have written, by the name the sheet gives them: a
        # guardian the sheet names alone is the person their own row is.
        self.written: dict[str, list[Named]] = {}
        # This gym's people by folded name, read once and kept as rows are written.
        self._people: dict[uuid.UUID, Record] | None = None

    async def _scalar(self, sql: str, **params: Any) -> Any:
        return await self.session.scalar(text(sql), params)

    async def _people_by_name(self) -> dict[uuid.UUID, Record]:
        if self._people is None:
            rows = await self.session.execute(text(PEOPLE))
            self._people = {r.person_id: Record(**r._asdict()) for r in rows}
        return self._people

    async def _refresh(self, *person_ids: uuid.UUID | None) -> None:
        """Read again those a row wrote, once it is in: a refused row leaves them as they
        were, since its savepoint is rolled back."""
        if self._people is None:
            return
        ids = [i for i in person_ids if i is not None]
        rows = await self.session.execute(
            text(f"{PEOPLE} WHERE gp.person_id = ANY(:ids)"), {"ids": ids}
        )
        for r in rows:
            self._people[r.person_id] = Record(**r._asdict())

    async def _named(
        self,
        name: str,
        dob: date | None,
        phone: str | None,
        *,
        sheet: bool = False,
        keyless: bool = False,
    ) -> uuid.UUID | None:
        """Whoever this gym has under `name`, told apart by `dob` and `phone` when
        several are; with `sheet`, first whoever this sheet's own row of the name is.
        With `keyless`, only those with no RUT and no email. `AmbiguousName` when
        nothing tells them apart."""
        if sheet and (written := self.written.get(fold(name))):
            return told_apart(written, dob, phone)
        folded = fold(name)
        found = [
            Named(r.person_id, r.dob, r.phone)
            for r in (await self._people_by_name()).values()
            if fold(r.name) == folded and not r.dependent and (r.keyless or not keyless)
        ]
        return told_apart(found, dob, phone)

    async def _in_gym(self, rut: str | None, email: str | None) -> uuid.UUID | None:
        """Whoever this gym has under the RUT, or the email (`find_in_gym`): one with no
        RUT, given one now, takes it."""
        found = await find_in_gym(self.session, rut, email)
        if found is None:
            return None
        if found.by == "email_in_gym" and rut is not None:
            await give_identity(self.session, found.person_id, rut, None)
        return found.person_id

    async def _join(self, **fields: Any) -> tuple[uuid.UUID, Outcome]:
        """`join_gym`: someone new here, or, by a RUT this gym gave someone else's
        record, whoever that is."""
        person_id, joined = await join_gym(self.session, **fields)
        return person_id, "created" if joined else "existing"

    async def row(self, member: Member) -> RowResult:
        _, result = await self.write(member)
        return result

    async def write(self, member: Member) -> tuple[uuid.UUID, RowResult]:
        """`row`, and the id of the person the row is."""
        self.ignored = []
        guardian: Outcome | None = None
        link_outcome: Outcome | None = None
        guardian_id: uuid.UUID | None = None
        if member.has_guardian:
            guardian_id, guardian = await self._guardian(member)

        if member.is_dependent:
            assert guardian_id is not None
            person_id, person = await self._dependent(member, guardian_id)
            link_outcome = person
        else:
            person_id, person = await self._adult(member)
            if guardian_id is not None:
                link_outcome = await self._link(guardian_id, person_id)

        membership = None if member.plan is None else await self._membership(member, person_id)
        # Whom the gym messages about them, and whether it can: "Falta teléfono".
        contact = guardian_id if guardian_id is not None else person_id
        missing = bool(await self._scalar(MISSING_PHONE, id=contact))
        # Last, so a row refused part way leaves nobody here it rolled back.
        if not member.is_dependent:
            self.written.setdefault(fold(member.name), []).append(
                Named(person_id, member.dob, member.phone)
            )
        await self._refresh(person_id, guardian_id)
        return person_id, RowResult(
            row=member.number,
            name=member.name,
            errors=[],
            person=person,
            guardian=guardian,
            link=link_outcome,
            membership=membership,
            ignored=sorted(set(self.ignored), key=list(Field).index),
            missing_phone=missing,
            missing_identity=member.missing_identity,
        )

    async def _kept(self, person_id: uuid.UUID, member: Member) -> None:
        """Note the sheet's values that differ from this gym's record of `person_id`."""
        record = (await self.session.execute(text(RECORD), {"id": person_id})).one()
        sheet = {
            Field.NAME: (member.name, record.name),
            Field.EMAIL: (member.email, record.email),
            Field.RUT: (member.rut, record.rut),
            Field.PHONE: (member.phone, record.phone),
            Field.DOB: (member.dob, record.dob),
        }
        self.ignored += [f for f, (new, kept) in sheet.items() if new is not None and new != kept]

    async def _adult(self, member: Member) -> tuple[uuid.UUID, Outcome]:
        if member.key is None:
            try:
                found = await self._named(member.name, member.dob, member.phone)
            except AmbiguousName:
                raise RowRefused(Field.NAME, "ambiguous_name") from None
        elif (found := await self._in_gym(member.rut, member.email)) is None:
            # Someone an earlier sheet gave no RUT or email, given one now: it becomes
            # who they are. Unsure who, they are someone new: the RUT says so.
            try:
                found = await self._named(member.name, member.dob, member.phone, keyless=True)
            except AmbiguousName:
                found = None
            if found is not None:
                await self._key(found, member)
        if found is not None:
            await self._kept(found, member)
            return found, "existing"
        person_id, outcome = await self._join(
            name=member.name,
            rut=member.rut,
            email=member.email,
            phone=member.phone,
            # Their own, unless a guardian is the one the gym messages.
            no_whatsapp=member.no_whatsapp and not member.has_guardian,
            dob=member.dob,
        )
        if outcome == "existing":
            await self._kept(person_id, member)
        return person_id, outcome

    async def _guardian(self, member: Member) -> tuple[uuid.UUID, Outcome]:
        if member.guardian_key is not None:
            found = await self._in_gym(member.guardian_rut, member.guardian_email)
        else:
            # Named only: whoever this gym has under that name, as their own row may be.
            assert member.guardian_name is not None
            try:
                found = await self._named(
                    member.guardian_name, None, member.guardian_phone, sheet=True
                )
            except AmbiguousName:
                raise RowRefused(Field.GUARDIAN_NAME, "ambiguous_name") from None
        if found is not None:
            if member.guardian_name is not None:
                kept = await self._scalar(
                    "SELECT name FROM gym_person WHERE person_id = :id", id=found
                )
                if fold(kept) != fold(member.guardian_name):
                    self.ignored.append(Field.GUARDIAN_NAME)
            return found, "existing"
        if member.guardian_name is None:
            raise RowRefused(Field.GUARDIAN_NAME, "required")
        return await self._join(
            name=member.guardian_name,
            rut=member.guardian_rut,
            email=member.guardian_email,
            phone=member.guardian_phone,
            no_whatsapp=member.no_whatsapp,
        )

    async def _key(self, person_id: uuid.UUID, member: Member) -> None:
        """Give someone this gym had with no RUT and no email the row's: their record
        takes it, and a RUT nobody has yet becomes who they are (`claim_rut`). Never a
        RUT or an email someone else here has: one gym holds each once."""
        if await rut_holder(self.session, member.rut, person_id=person_id) is not None:
            raise RowRefused(Field.RUT, "rut_in_gym")
        if await email_holder(self.session, member.email, person_id=person_id) is not None:
            raise RowRefused(Field.EMAIL, "email_in_gym")
        await give_identity(self.session, person_id, member.rut, member.email)

    async def _dependent(self, member: Member, guardian_id: uuid.UUID) -> tuple[uuid.UUID, Outcome]:
        theirs = await family(self.session, guardian_id)
        if theirs.guardian is not None:
            # A dependent's guardian is never someone's dependent (0010).
            raise RowRefused(Field.GUARDIAN_NAME, "one_level")
        name = fold(member.name)
        if found := next((d.id for d in theirs.dependents if fold(d.name) == name), None):
            await self._kept(found, member)
            return found, "existing"
        # Neither a RUT nor an email: always someone new, known by their guardian.
        person_id, _ = await join_gym(
            self.session, name=member.name, phone=member.phone, dob=member.dob
        )
        await self._link(guardian_id, person_id)
        return person_id, "created"

    async def _link(self, guardian_id: uuid.UUID, dependent_id: uuid.UUID) -> Outcome:
        current = await self._scalar(GUARDIAN_OF, id=dependent_id)
        if current == guardian_id:
            return "existing"
        if current is not None:
            raise RowRefused(Field.GUARDIAN_NAME, "has_guardian")
        if (code := await link(self.session, guardian_id, dependent_id)) is not None:
            raise RowRefused(Field.GUARDIAN_NAME, code)
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
        try:
            await insert_membership(
                self.session,
                person_id,
                member.plan.id,
                started,
                start_of_local_day(started_on, self.timezone),
            )
        except PersonHasLeft:
            # Reactivated from their ficha, not by a sheet that still lists them.
            raise RowRefused(Field.PLAN, "has_left") from None
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
    today = gym_today(timezone)
    finder = PlanFinder(await _plans(session), body.plans)
    members = read_members(
        [(row.number, row.cells) for row in body.rows], body.mapping, finder, today
    )

    writer = Writer(session, timezone, today)
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
    """The order rows are written in: guardians' own rows first, then every other adult,
    then dependents, each in the sheet's order. So a row naming a guardian, by RUT,
    email or name alone, finds the guardian the sheet describes, with the name their own
    row gives them."""
    guardians = {m.guardian_ident for m in members if m.guardian_ident is not None}

    def key(pair: tuple[int, Member]) -> tuple[int, int]:
        index, member = pair
        if member.is_dependent:
            return 2, index
        own = member.key in guardians or ("name", fold(member.name)) in guardians
        return (0 if own else 1), index

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
        missing_phone=sum(r.missing_phone for r in rows),
        missing_identity=sum(r.missing_identity for r in rows),
    )
