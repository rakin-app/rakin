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
an email (`missing_identity`): both import. A row that leaves a minor, by birth date, with
no guardian is refused `minor`, as Nuevo alumno refuses one (#368).

A row's history from before Rakin (#297) is the one exception to never overwriting:
"Alumno desde", the day they left and why, and their classes before Rakin are written
where the gym's record has none, and `ignored` where it has something else, so a
second run of a sheet already imported fills them. A row with the day they left is a
former student: someone new is created already gone, with no membership, and someone
here who has not left is never given a baja by a sheet (`ignored`). Each person whose
history a row writes gets a `history_set` row in the gym's log, and an import that
writes anything one `history_imported` row, with the file's name and SHA-256 and the
counts, whose id the others carry as `import_id`. A dry run writes neither.

A workbook's Pagos tab (#298), one row per payment received before Rakin, is read after
the Alumnos tab in the same transaction, so a payment finds a student that tab adds, in
the dry run too. Like a grade it never creates anyone (`unknown_person`,
`ambiguous_name`). A payment for a month (else a day) on or after the person's first plan
here is refused `covers_plan`, as on the ficha: "Pagado hasta" pays that. One equal to a
payment they already have (day, amount and month) is `existing`, and one an earlier row
gives them is `repeated`, so a second run adds none. Each row is checked on its own, and
those it adds are written together once the import's own row is in, since an imported
`history_payment` names that row (0055); a dry run writes that row too, and rolls it
back with the rest. Each is `source` `import`. Nothing billing reads is touched.

A workbook's Grados tab (#299), one row per belt or stripe earned, is written after the
Alumnos tab in the same transaction, each row in its own savepoint, so a grade finds a
student that tab adds, in the dry run too. A grade row never creates anyone: it finds
them as the Alumnos tab does, by RUT, else email, else name, and is refused
`unknown_person` when nobody is the row, `ambiguous_name` when two people are. A grade
the person already has (rank, sub-rank and day) is `existing`, and one an earlier row
gives them is `repeated`, so a second run adds none. Each is written `source` `import`
with the run's `import_id`, and no `promoted` event: their latest is their rank now.

`GET /api/import/template.xlsx` is the sheet to fill in (`app.member_import.template`),
every header one the mapping suggests by itself.

Only an owner or admin may import, since a membership sets what a member is charged.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.grades import readable_scheme
from app.api.grading import stored_scheme
from app.api.guardians import family, link
from app.api.history import LOCK_PERSON, PLAN_FROM, changes, in_plan, record_history_set
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
from app.domain.dates import gym_today, is_minor, start_of_local_day
from app.domain.membership import PlanKind, PlanTerms
from app.member_import.grades import (
    Grade,
    GradeErrorCode,
    GradeField,
    RankFinder,
    read_grades,
    suggest_grade_mapping,
)
from app.member_import.payments import (
    Payment,
    PaymentErrorCode,
    PaymentField,
    read_payments,
    suggest_payment_mapping,
)
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
from app.member_import.sheet import SheetError, Tab, read_book
from app.member_import.template import TEMPLATE_NAME, template
from app.roles import AdminSession
from app.schemas.member_import import (
    FileName,
    GradeImport,
    GradeReport,
    GradeRowError,
    GradeRowResult,
    GradeSheet,
    GradeSummary,
    ImportReport,
    ImportSummary,
    MemberImport,
    Outcome,
    PaymentImport,
    PaymentReport,
    PaymentRowError,
    PaymentRowResult,
    PaymentSheet,
    PaymentSummary,
    RowError,
    RowResult,
    Sheet,
    SheetFile,
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

# Whether a row leaves someone a minor with no guardian, still here (#368): by the
# gym's birth date for them, else the row's.
UNGUARDED = """
    SELECT coalesce(gp.dob, CAST(:dob AS date)) AS dob, gp.left_on,
           EXISTS (
               SELECT FROM guardian_link d WHERE d.dependent_person_id = gp.person_id
           ) AS guarded
    FROM gym_person gp WHERE gp.person_id = :id
"""
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

    @cached_property
    def folded(self) -> str:
        """The name folded once, not once per keyless row that compares against it."""
        return fold(self.name)


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
LOCK_HISTORY = """
    SELECT member_since, prior_classes, left_on, left_reason FROM gym_person
    WHERE person_id = :id FOR UPDATE
"""
# The fields a row writes; `{fields}` names columns, never a value from the sheet.
SET_HISTORY = "UPDATE gym_person SET {fields}, updated_at = now() WHERE person_id = :id"
# One import at a time per gym, and no undo of one meanwhile (#300); released when the
# transaction ends.
IMPORT_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('rakin.import'), hashtext(:gym))")
# The import's own row in the gym's log (0053); `now()` is the transaction's.
INSERT_IMPORTED = text(
    "INSERT INTO audit_event (id, gym_id, at, actor_id, action, detail)"
    " VALUES (:id, current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, 'history_imported', CAST(:detail AS jsonb))"
)
MISSING_PHONE = f"SELECT {missing_phone('gp')} FROM gym_person gp WHERE person_id = :id"

# A grade the person already has: the same rank and sub-rank on the same day.
HAS_GRADE = """
    SELECT EXISTS (
        SELECT FROM grade_event
        WHERE person_id = :person AND rank_key = :rank_key AND awarded_on = :awarded_on
          AND coalesce(sub_rank, '') = coalesce(CAST(:sub_rank AS text), '')
    )
"""
# The payments from before Rakin someone already has, as a Pagos row is told apart.
PAID = "SELECT paid_on, amount_clp, covers_month FROM history_payment WHERE person_id = :id"
# Recorded by whoever imports, naming the import's own row (0055).
INSERT_PAYMENT = """
    INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, method, covers_month,
                                 plan_name, note, source, import_id, created_by)
    VALUES (current_setting('app.gym_id')::uuid, :person, :paid_on, :amount_clp, :method,
            :covers_month, :plan_name, :note, 'import', :import_id,
            current_setting('app.person_id')::uuid)
"""

# Recorded by whoever imports, with no membership (0054).
INSERT_GRADE = """
    INSERT INTO grade_event (gym_id, person_id, rank_key, sub_rank, awarded_on, awarded_by,
                             note, source, import_id)
    VALUES (current_setting('app.gym_id')::uuid, :person, :rank_key, :sub_rank, :awarded_on,
            current_setting('app.person_id')::uuid, :note, 'import', :import_id)
"""


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
async def upload_sheet(
    request: Request,
    session: AdminSession,
    # The file's name, which the import's record keeps beside its hash.
    name: Annotated[FileName | None, Query()] = None,
    # The tab a CSV is; a workbook says by its tabs' names.
    tab: Annotated[Tab, Query()] = "alumnos",
) -> Sheet:
    """The spreadsheet in the body, as each tab's rows of text and a suggested mapping,
    with its SHA-256 for the import to send back."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise _refused(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        book = read_book(bytes(data), tab)
    except SheetError as error:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
    alumnos, pagos, grados = book.get("alumnos"), book.get("pagos"), book.get("grados")
    return Sheet(
        headers=[] if alumnos is None else alumnos.headers,
        rows=[] if alumnos is None else _sheet_rows(alumnos.rows),
        mapping={} if alumnos is None else suggest_mapping(alumnos.headers),
        file=SheetFile(name=name, sha256=hashlib.sha256(data).hexdigest()),
        pagos=None
        if pagos is None
        else PaymentSheet(
            headers=pagos.headers,
            rows=_sheet_rows(pagos.rows),
            mapping=suggest_payment_mapping(pagos.headers),
        ),
        grados=None
        if grados is None
        else GradeSheet(
            headers=grados.headers,
            rows=_sheet_rows(grados.rows),
            mapping=suggest_grade_mapping(grados.headers),
        ),
    )


def _sheet_rows(rows: list[Any]) -> list[SheetRow]:
    return [SheetRow(number=row.number, cells=row.cells) for row in rows]


@router.get(
    "/template.xlsx",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}
        }
    },
)
async def download_template(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> Response:
    """ "Descargar plantilla": the Alumnos sheet to fill in, with the gym's active plans
    as the Plan column's choices, and in a gym that grades a Grados tab, its ranks the
    Grado column's."""
    # A drop-in is not a membership, so no row starts one (`dropin_plan`). A name two
    # plans share is offered once: the sheet matches it by name either way.
    plans = {
        fold(plan.name): plan.name
        for plan in await _plans(session)
        if plan.active and plan.terms.kind is not PlanKind.DROPIN
    }
    settings = await session.scalar(
        text("SELECT settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    scheme = readable_scheme(settings)
    return Response(
        content=template([plans[key] for key in sorted(plans)], scheme),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_NAME}"'},
    )


class RowRefused(Exception):
    """The database's answer for a row: it writes nothing."""

    def __init__(self, on: Field, code: ErrorCode) -> None:
        super().__init__(on, code)
        self.on = on
        self.code: ErrorCode = code


class PaymentRefused(Exception):
    """A Pagos row the gym's data refuses: it writes nothing."""

    def __init__(self, on: PaymentField, code: PaymentErrorCode) -> None:
        super().__init__(on, code)
        self.on = on
        self.code: PaymentErrorCode = code


class GradeRefused(Exception):
    """A Grados row the gym's data refuses: it writes nothing."""

    def __init__(self, on: GradeField, code: GradeErrorCode) -> None:
        super().__init__(on, code)
        self.on = on
        self.code: GradeErrorCode = code


class Writer:
    """Writes rows into the current gym: the importer's, and the join link's approvals
    (`app.api.join`), so a person is added one way however they come."""

    def __init__(
        self,
        session: AsyncSession,
        timezone: str,
        today: date,
        import_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.timezone = timezone
        self.today = today
        # The import's `history_imported` row, which each `history_set` row names.
        self.import_id = import_id
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
        dependents: bool = False,
    ) -> uuid.UUID | None:
        """Whoever this gym has under `name`, told apart by `dob` and `phone` when
        several are; with `sheet`, first whoever this sheet's own row of the name is.
        With `keyless`, only those with no RUT and no email; with `dependents`, someone's
        dependents too. `AmbiguousName` when nothing tells them apart."""
        if sheet and (written := self.written.get(fold(name))):
            return told_apart(written, dob, phone)
        folded = fold(name)
        found = [
            Named(r.person_id, r.dob, r.phone)
            for r in (await self._people_by_name()).values()
            if r.folded == folded and (dependents or not r.dependent) and (r.keyless or not keyless)
        ]
        return told_apart(found, dob, phone)

    async def find(self, rut: str | None, email: str | None, name: str) -> uuid.UUID | None:
        """Whoever a row of another tab names: by the RUT, else the email, else, among
        those with neither when it gives one, by `name`, dependents included. This gym's
        people and those this run wrote; nobody is created or changed. `AmbiguousName`
        when two of the name are."""
        if (rut or email) and (found := await find_in_gym(self.session, rut, email)):
            return found.person_id
        if not name:
            return None
        return await self._named(
            name, None, None, keyless=rut is not None or email is not None, dependents=True
        )

    async def _in_gym(self, rut: str | None, email: str | None, field: Field) -> uuid.UUID | None:
        """Whoever this gym has under the RUT, or the email (`find_in_gym`): one with no
        RUT, given one now, takes it. An email someone with another RUT has is refused
        on `field`: one gym holds each once."""
        found = await find_in_gym(self.session, rut, email)
        if found is None:
            if await email_holder(self.session, email) is not None:
                raise RowRefused(field, "email_in_gym")
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
        self.ignored = list(member.unapplied)
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

        history = await self._history(member, person_id, created=person == "created")
        await self._refuse_unguarded(member, person_id)
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
            history=history,
            former=member.left_on is not None,
        )

    async def _history(self, member: Member, person_id: uuid.UUID, *, created: bool) -> bool:
        """Write the row's history where the gym's record of `person_id` has none, and
        note where it has something else. The day they left only for someone the row
        created: a sheet never gives someone here a baja. Whether it wrote any."""
        if not member.has_history:
            return False
        record = (await self.session.execute(text(LOCK_HISTORY), {"id": person_id})).one()
        before = record._asdict()
        after: dict[str, Any] = {}

        def fill(on: Field, value: Any, empty: Any = None, *, allowed: bool = True) -> None:
            if value is None or value == before[on.value]:
                return
            if allowed and before[on.value] == empty:
                after[on.value] = value
            else:
                self.ignored.append(on)

        fill(Field.MEMBER_SINCE, member.member_since)
        fill(Field.PRIOR_CLASSES, member.prior_classes, 0)
        fill(Field.LEFT_ON, member.left_on, allowed=created)
        left = after.get("left_on", before["left_on"])
        # Why they left, only for someone who has.
        fill(Field.LEFT_REASON, member.left_reason, allowed=left is not None)
        since = after.get("member_since", before["member_since"])
        if since is not None and left is not None and left < since:
            raise RowRefused(Field.LEFT_ON, "left_before_start")
        if not after:
            return False
        fields = ", ".join(f"{name} = :{name}" for name in after)
        await self.session.execute(
            text(SET_HISTORY.format(fields=fields)), {**after, "id": person_id}
        )
        await record_history_set(
            self.session, person_id, changes(before, after), import_id=self.import_id
        )
        return True

    async def _refuse_unguarded(self, member: Member, person_id: uuid.UUID) -> None:
        """A minor on the gym's today needs a guardian, as Nuevo alumno asks: with none,
        the gym's notices would reach the child (#368). Not a former student, whom
        nobody writes to."""
        found = (
            await self.session.execute(text(UNGUARDED), {"id": person_id, "dob": member.dob})
        ).one()
        if (
            found.dob is not None
            and found.left_on is None
            and not found.guarded
            and is_minor(found.dob, self.today)
        ):
            raise RowRefused(Field.GUARDIAN_NAME, "minor")

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
        elif (found := await self._in_gym(member.rut, member.email, Field.EMAIL)) is None:
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
            found = await self._in_gym(
                member.guardian_rut, member.guardian_email, Field.GUARDIAN_EMAIL
            )
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


@dataclass(frozen=True)
class Payer:
    """Someone a Pagos row names: their first plan's start here, if any, and the payments
    from before Rakin they already have, by day, amount and month."""

    plan_from: date | None
    paid: frozenset[tuple[date, int, date | None]]


class PaymentWriter:
    """Checks Pagos rows for the people `writer` finds, after the Alumnos tab's, and
    writes those it adds once the import's own row is in (`write`)."""

    def __init__(self, writer: Writer) -> None:
        self.writer = writer
        self.session = writer.session
        # Whom each way of naming someone found: a sheet names a few hundred people over
        # thousands of payments, and nobody is added while this tab is read.
        self.found: dict[tuple[str | None, str | None, str], uuid.UUID | None] = {}
        self.payers: dict[uuid.UUID, Payer] = {}
        # The payments this run's rows have given, so an equal later row is `repeated`.
        self.given: set[tuple[uuid.UUID, date, int, date | None]] = set()
        self.adds: list[dict[str, Any]] = []

    async def _who(self, payment: Payment) -> uuid.UUID:
        key = (payment.rut, payment.email, fold(payment.name))
        if key not in self.found:
            try:
                self.found[key] = await self.writer.find(payment.rut, payment.email, payment.name)
            except AmbiguousName:
                raise PaymentRefused(PaymentField.NAME, "ambiguous_name") from None
        if (person_id := self.found[key]) is None:
            on = PaymentField.NAME if payment.key is None else _payment_key_field(payment)
            raise PaymentRefused(on, "unknown_person")
        return person_id

    async def _payer(self, person_id: uuid.UUID) -> Payer:
        """Read under the person's lock, as the ficha's form is, and held to the end of
        the import: a plan started for them meanwhile waits, and cannot move the line."""
        if person_id not in self.payers:
            await self.session.execute(LOCK_PERSON, {"id": person_id})
            rows = await self.session.execute(text(PAID), {"id": person_id})
            self.payers[person_id] = Payer(
                plan_from=await self.session.scalar(PLAN_FROM, {"id": person_id}),
                paid=frozenset((r.paid_on, r.amount_clp, r.covers_month) for r in rows),
            )
        return self.payers[person_id]

    async def row(self, payment: Payment) -> PaymentRowResult:
        entry = payment.entry
        assert entry is not None
        person_id = await self._who(payment)
        payer = await self._payer(person_id)
        if payer.plan_from is not None and in_plan(entry, payer.plan_from):
            on = PaymentField.PAID_ON if entry.covers_month is None else PaymentField.COVERS_MONTH
            raise PaymentRefused(on, "covers_plan")
        paid = (entry.paid_on, entry.amount_clp, entry.covers_month)
        if (person_id, *paid) in self.given:
            raise PaymentRefused(PaymentField.PAID_ON, "repeated")
        self.given.add((person_id, *paid))
        outcome: Outcome = "existing"
        if paid not in payer.paid:
            self.adds.append({**entry.model_dump(), "person": person_id})
            outcome = "created"
        return PaymentRowResult(
            row=payment.number, name=_who_name(payment), errors=[], payment=outcome
        )

    async def write(self, import_id: uuid.UUID) -> None:
        """The payments the rows add, naming the import's row, which is in by now."""
        if self.adds:
            await self.session.execute(
                text(INSERT_PAYMENT), [{**add, "import_id": import_id} for add in self.adds]
            )


def _payment_key_field(payment: Payment) -> PaymentField:
    return PaymentField.RUT if payment.rut is not None else PaymentField.EMAIL


def _payment_refusal(payment: Payment) -> PaymentRowResult:
    return PaymentRowResult(
        row=payment.number,
        name=_who_name(payment),
        errors=[PaymentRowError(field=e.field, code=e.code) for e in payment.errors],
        payment=None,
    )


class GradeWriter:
    """Writes Grados rows for the people `writer` finds, after the Alumnos tab's."""

    def __init__(self, writer: Writer) -> None:
        self.writer = writer
        self.session = writer.session
        # The grades this run's rows have given, so an equal later row is `repeated`.
        self.given: set[tuple[uuid.UUID, str, str | None, date]] = set()

    async def row(self, grade: Grade) -> GradeRowResult:
        assert grade.rank is not None and grade.awarded_on is not None
        try:
            person_id = await self.writer.find(grade.rut, grade.email, grade.name)
        except AmbiguousName:
            raise GradeRefused(GradeField.NAME, "ambiguous_name") from None
        if person_id is None:
            on = GradeField.NAME if grade.key is None else _key_field(grade)
            raise GradeRefused(on, "unknown_person")
        given = (person_id, grade.rank.key, grade.sub_rank, grade.awarded_on)
        if given in self.given:
            raise GradeRefused(GradeField.RANK, "repeated")
        values = {
            "person": person_id,
            "rank_key": grade.rank.key,
            "sub_rank": grade.sub_rank,
            "awarded_on": grade.awarded_on,
        }
        outcome: Outcome = "existing"
        if not await self.session.scalar(text(HAS_GRADE), values):
            await self.session.execute(
                text(INSERT_GRADE),
                {**values, "note": grade.note, "import_id": self.writer.import_id},
            )
            outcome = "created"
        self.given.add(given)
        return GradeRowResult(row=grade.number, name=_who_name(grade), errors=[], grade=outcome)


def _key_field(grade: Grade) -> GradeField:
    return GradeField.RUT if grade.rut is not None else GradeField.EMAIL


def _who_name(row: Grade | Payment) -> str:
    return row.name or row.rut or row.email or ""


def _grade_refusal(grade: Grade) -> GradeRowResult:
    return GradeRowResult(
        row=grade.number,
        name=_who_name(grade),
        errors=[GradeRowError(field=e.field, code=e.code) for e in grade.errors],
        grade=None,
    )


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
    if not body.dry_run:
        # One import at a time per gym, so a second waits and matches the first's people
        # instead of creating them again: a person matched by name has no key to stop it
        # (#203). Released when the transaction ends.
        await session.execute(IMPORT_LOCK, {"gym": str(tenant.gym_id)})
    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    today = gym_today(timezone)
    finder = PlanFinder(await _plans(session), body.plans)
    members = read_members(
        [(row.number, row.cells) for row in body.rows], body.mapping, finder, today
    )

    import_id = None if body.dry_run else uuid.uuid4()
    writer = Writer(session, timezone, today, import_id)
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
    rows = [results[index] for index in range(len(members))]
    summary = _summary(rows)
    payments, pagos = None, None
    if body.pagos is not None:
        payments = PaymentWriter(writer)
        pagos = await _import_payments(payments, body.pagos, today)
    grados = None
    if body.grados is not None:
        grados = await _import_grades(session, tenant, writer, body.grados, today)
    if _wrote(summary, pagos, grados):
        # A dry run's record too, rolled back with the rest: an imported payment names it.
        record_id = import_id or uuid.uuid4()
        await _record_import(session, record_id, body.file, summary, pagos, grados)
        if payments is not None:
            await payments.write(record_id)
    else:
        # Nothing written, so nothing recorded.
        import_id = None
    if body.dry_run:
        await everything.rollback()
    else:
        await everything.commit()
    return ImportReport(
        dry_run=body.dry_run,
        import_id=import_id,
        summary=summary,
        rows=rows,
        pagos=pagos,
        grados=grados,
    )


async def _import_payments(writer: PaymentWriter, tab: PaymentImport, today: date) -> PaymentReport:
    """The Pagos tab's rows, each checked on its own after every Alumnos row."""
    rows: list[PaymentRowResult] = []
    for payment in read_payments([(row.number, row.cells) for row in tab.rows], tab.mapping, today):
        if not payment.errors:
            try:
                rows.append(await writer.row(payment))
                continue
            except PaymentRefused as refused:
                payment.refuse(refused.on, refused.code)
        rows.append(_payment_refusal(payment))
    refused_rows = sum(1 for row in rows if row.errors)
    return PaymentReport(
        summary=PaymentSummary(
            rows=len(rows),
            imported=len(rows) - refused_rows,
            refused=refused_rows,
            payments_created=len(writer.adds),
            amount_clp=sum(add["amount_clp"] for add in writer.adds),
        ),
        rows=rows,
    )


async def _import_grades(
    session: AsyncSession, tenant: Tenant, writer: Writer, tab: GradeImport, today: date
) -> GradeReport:
    """The Grados tab's rows, each in its own savepoint, after every Alumnos row."""
    settings = await session.scalar(
        text("SELECT settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    finder = RankFinder(stored_scheme(tenant.gym_id, settings), tab.ranks)
    grades = read_grades([(row.number, row.cells) for row in tab.rows], tab.mapping, finder, today)
    grade_writer = GradeWriter(writer)
    rows: list[GradeRowResult] = []
    for grade in grades:
        if not grade.errors:
            try:
                async with session.begin_nested():
                    rows.append(await grade_writer.row(grade))
                continue
            except GradeRefused as refused:
                grade.refuse(refused.on, refused.code)
        rows.append(_grade_refusal(grade))
    refused_rows = sum(1 for row in rows if row.errors)
    return GradeReport(
        summary=GradeSummary(
            rows=len(rows),
            imported=len(rows) - refused_rows,
            refused=refused_rows,
            grades_created=sum(row.grade == "created" for row in rows),
        ),
        rows=rows,
    )


def _wrote(summary: ImportSummary, pagos: PaymentReport | None, grados: GradeReport | None) -> bool:
    return (
        summary.people_created
        + summary.links_created
        + summary.memberships_created
        + summary.history_set
        + (0 if pagos is None else pagos.summary.payments_created)
        + (0 if grados is None else grados.summary.grades_created)
    ) > 0


async def _record_import(
    session: AsyncSession,
    import_id: uuid.UUID,
    file: SheetFile | None,
    summary: ImportSummary,
    pagos: PaymentReport | None,
    grados: GradeReport | None,
) -> None:
    """The import's `history_imported` row: which file, and what each tab wrote."""
    counts: dict[str, Any] = {}
    if summary.rows:
        counts["alumnos"] = summary.model_dump(
            include={
                "rows",
                "imported",
                "refused",
                "people_created",
                "links_created",
                "memberships_created",
                "history_set",
                "former_created",
            }
        )
    if pagos is not None:
        counts["pagos"] = pagos.summary.model_dump()
    if grados is not None:
        counts["grados"] = grados.summary.model_dump()
    detail = {
        "file_name": None if file is None else file.name,
        "sha256": None if file is None else file.sha256,
        "tabs": list(counts),
        "counts": counts,
    }
    result = await session.execute(INSERT_IMPORTED, {"id": import_id, "detail": json.dumps(detail)})
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(f"no audit row for import {import_id}")


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
        history_set=sum(r.history for r in rows),
        former_created=sum(r.former and r.person == "created" for r in rows),
    )
