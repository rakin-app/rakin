"""Sheet rows and a column mapping in, the people they describe out, each with its errors.

Pure: no database. Every check that needs only the row is made here, so a dry run
reports them all at once. What needs the gym's data (is that guardian already here, do
they already have someone of that name in their care) is checked as the row is written
(`app.api.member_import`).

A row is someone found again by their RUT, or by their email when it has none (#165),
or a dependent with neither, found by their guardian and their own name. A guardian is
found by their RUT or email the same way. Someone with a RUT or email may have a
guardian too (a teenager). Old sheets often have neither: an adult row with no RUT and
no email still imports, found again in this gym by their name, and so does a guardian
the sheet names with no RUT or email. The phone is a contact and finds nobody. A row
with a plan gets a membership, starting as of its due date.
"""

import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from app.domain.dates import add_months
from app.domain.membership import RECURRING, PlanKind, PlanTerms
from app.domain.phone import InvalidPhoneError, normalize_phone
from app.domain.rut import normalize_rut
from app.schemas.memberships import STARTED_ON_WINDOW_YEARS
from app.schemas.people import Email, Name


class Field(StrEnum):
    NAME = "name"
    # Joined to the name, for the sheets that split them.
    LAST_NAME = "last_name"
    PHONE = "phone"
    EMAIL = "email"
    RUT = "rut"
    DOB = "dob"
    PLAN = "plan"
    # The day the next payment falls due; a pack's or trial's last day.
    DUE_ON = "due_on"
    STARTED_ON = "started_on"
    GUARDIAN_NAME = "guardian_name"
    GUARDIAN_RUT = "guardian_rut"
    GUARDIAN_EMAIL = "guardian_email"
    GUARDIAN_PHONE = "guardian_phone"


# `required`: the cell is empty and the row needs it. `repeated`: an earlier row has the
# same RUT or email, or the same guardian and name. `own_guardian`: the guardian's RUT
# is the row's own. `unknown_plan`, `inactive_plan`, `dropin_plan`: no such plan, a deactivated
# one, or a drop-in, which is not a membership. `due_before_start`: the due date is
# before the start. `has_guardian`, `one_level`: the link is refused (migration 0010).
# `has_left`: the member was dado de baja, and starts no plan until reactivated (0032).
# `ambiguous_name`: a row with no RUT and no email names someone the gym has two of, and
# neither the birth date nor the phone says which (#165). `rut_in_gym`, `email_in_gym`:
# the RUT or email the row would give someone is another person's in this gym.
ErrorCode = Literal[
    "required",
    "repeated",
    "invalid_phone",
    "invalid_email",
    "invalid_rut",
    "invalid_date",
    "own_guardian",
    "unknown_plan",
    "inactive_plan",
    "dropin_plan",
    "due_before_start",
    "has_guardian",
    "one_level",
    "has_left",
    "ambiguous_name",
    "rut_in_gym",
    "email_in_gym",
]


@dataclass(frozen=True)
class RowError:
    field: Field
    code: ErrorCode


@dataclass(frozen=True)
class Plan:
    id: uuid.UUID
    name: str
    active: bool
    terms: PlanTerms


@dataclass
class Member:
    """One sheet row, read. Its fields are valid wherever `errors` names none."""

    number: int
    name: str
    phone: str | None = None
    email: str | None = None
    rut: str | None = None
    dob: date | None = None
    plan: Plan | None = None
    due_on: date | None = None
    started_on: date | None = None
    guardian_name: str | None = None
    guardian_rut: str | None = None
    guardian_email: str | None = None
    guardian_phone: str | None = None
    # "No tiene WhatsApp" for the row's contact: its guardian when it has one, else
    # itself. No sheet column gives it; the join link's form does (`app.api.join`).
    no_whatsapp: bool = False
    errors: list[RowError] = field(default_factory=list)

    def refuse(self, on: Field, code: ErrorCode) -> None:
        self.errors.append(RowError(on, code))

    @property
    def has_guardian(self) -> bool:
        """Whether the row names someone who answers for them."""
        return self.guardian_key is not None or self.guardian_name is not None

    @property
    def is_dependent(self) -> bool:
        """A row with neither a RUT nor an email of its own, under a guardian: found by
        the guardian and their name, as kids are."""
        return self.key is None and self.has_guardian

    @property
    def missing_phone(self) -> bool:
        """The row's contact has no phone, and nothing says they have no WhatsApp: it
        imports, flagged "Falta teléfono" (#165)."""
        phone = self.guardian_phone if self.has_guardian else self.phone
        return phone is None and not self.no_whatsapp

    @property
    def missing_identity(self) -> bool:
        """An adult with neither a RUT nor an email: imported, found again by name in
        this gym, but nothing says who they are elsewhere."""
        return self.key is None and not self.has_guardian

    @property
    def guardian_ident(self) -> tuple[str, str] | None:
        """The guardian, by RUT or email, else by name: as the sheet tells them apart."""
        if self.guardian_key is not None:
            return self.guardian_key
        return None if self.guardian_name is None else ("name", fold(self.guardian_name))

    @property
    def key(self) -> tuple[str, str] | None:
        """Who the row is, by its own RUT, else its email; `None` for a dependent."""
        return identity(self.rut, self.email)

    @property
    def guardian_key(self) -> tuple[str, str] | None:
        """Who the row's guardian is, the same way."""
        return identity(self.guardian_rut, self.guardian_email)


def identity(rut: str | None, email: str | None) -> tuple[str, str] | None:
    """A RUT, else an email, case and outer spaces ignored: who someone is (0036)."""
    if rut is not None:
        return "rut", rut
    if email is not None:
        return "email", email.strip().lower()
    return None


def fold(value: str) -> str:
    """For matching names: accents, case and spacing ignored ("Martín  Núñez" is
    "martin nunez")."""
    decomposed = unicodedata.normalize("NFKD", value)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(bare.casefold().split())


# --- which column is which ----------------------------------------------------------

_GUARDIAN_WORDS = (
    "apoderado",
    "apoderada",
    "tutor",
    "responsable",
    "padre",
    "madre",
    "mama",
    "papa",
)
_PHONE_WORDS = ("telefono", "celular", "fono", "whatsapp", "movil", "phone", "cel")
_RUT_WORDS = ("rut", "run")
_EMAIL_WORDS = ("correo", "email", "e mail", "mail")
# In order: the first field whose words a header holds is the one suggested.
_HEADER_WORDS: tuple[tuple[Field, tuple[str, ...]], ...] = (
    (Field.DOB, ("nacimiento", "cumpleanos", "f nac", "fecha nac", "birth", "dob")),
    (Field.DUE_ON, ("vencimiento", "vence", "proximo pago", "fecha de pago", "fecha pago")),
    (Field.STARTED_ON, ("fecha de ingreso", "ingreso", "inicio", "alta")),
    (Field.PHONE, _PHONE_WORDS),
    (Field.EMAIL, _EMAIL_WORDS),
    (Field.RUT, _RUT_WORDS),
    (Field.LAST_NAME, ("apellido",)),
    (Field.NAME, ("nombre", "alumno", "alumna", "name")),
    (Field.PLAN, ("plan", "mensualidad")),
)


def _words(header: str) -> str:
    return " " + re.sub(r"[^0-9a-z]+", " ", fold(header)) + " "


def _holds(header: str, words: Sequence[str]) -> bool:
    """Whether `header`, as `_words` spaces it, holds one of `words`, or its plural."""
    return any(f" {word} " in header or f" {word}s " in header for word in words)


def _field_for(header: str) -> Field | None:
    words = _words(header)
    if _holds(words, _GUARDIAN_WORDS):
        for guardian_field, keys in (
            (Field.GUARDIAN_PHONE, _PHONE_WORDS),
            (Field.GUARDIAN_RUT, _RUT_WORDS),
            (Field.GUARDIAN_EMAIL, _EMAIL_WORDS),
        ):
            if _holds(words, keys):
                return guardian_field
        return Field.GUARDIAN_NAME
    return next((f for f, keys in _HEADER_WORDS if _holds(words, keys)), None)


def suggest_mapping(headers: Sequence[str]) -> dict[Field, int]:
    """The column each field most likely is, by its header; the first column wins."""
    mapping: dict[Field, int] = {}
    for column, header in enumerate(headers):
        suggested = _field_for(header)
        if suggested is not None and suggested not in mapping:
            mapping[suggested] = column
    return mapping


# --- reading cells ------------------------------------------------------------------

_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
# Day first, as Chile writes dates: 15/11/2026, 15-11-26, 15.11.2026.
_DAY_FIRST = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})")

_NAME = TypeAdapter(Name)
_EMAIL = TypeAdapter(Email)


def parse_date(raw: str, today: date) -> date:
    """A sheet's date, ISO or day first. A two-digit year is this century's unless that
    would put it more than a year ahead. Raises `ValueError`."""
    value = raw.strip().split(" ")[0]  # "2026-11-15 00:00:00", as some exports write
    if match := _ISO.fullmatch(value):
        year, month, day = (int(g) for g in match.groups())
    elif match := _DAY_FIRST.fullmatch(value):
        day, month, year = (int(g) for g in match.groups())
        if year < 100:
            year += 2000 if year <= today.year % 100 + 1 else 1900
    else:
        raise ValueError(f"not a date: {raw!r}")
    return date(year, month, day)


def _in_window(day: date, today: date) -> bool:
    months = 12 * STARTED_ON_WINDOW_YEARS
    return add_months(today, -months) <= day <= add_months(today, months)


# --- rows ---------------------------------------------------------------------------


@dataclass
class _Cells:
    cells: Sequence[str]
    mapping: Mapping[Field, int]

    def __call__(self, on: Field) -> str:
        column = self.mapping.get(on)
        if column is None or column >= len(self.cells):
            return ""
        return self.cells[column].strip()


def _phone(member: Member, on: Field, raw: str) -> str | None:
    if not raw:
        return None
    try:
        return normalize_phone(raw)
    except InvalidPhoneError:
        member.refuse(on, "invalid_phone")
        return None


def _rut(member: Member, on: Field, raw: str) -> str | None:
    if not raw:
        return None
    try:
        return normalize_rut(raw)
    except ValueError:
        member.refuse(on, "invalid_rut")
        return None


def _email(member: Member, on: Field, raw: str) -> str | None:
    if not raw:
        return None
    try:
        return _EMAIL.validate_python(raw)
    except ValidationError:
        member.refuse(on, "invalid_email")
        return None


def _date(member: Member, on: Field, raw: str, today: date) -> date | None:
    if not raw:
        return None
    try:
        day = parse_date(raw, today)
    except ValueError:
        member.refuse(on, "invalid_date")
        return None
    if not _in_window(day, today) and on is not Field.DOB:
        member.refuse(on, "invalid_date")
        return None
    if on is Field.DOB and day >= today:
        member.refuse(on, "invalid_date")
        return None
    return day


def read_member(
    number: int,
    cells: Sequence[str],
    mapping: Mapping[Field, int],
    plans: "PlanFinder",
    today: date,
) -> Member:
    """One row, every check that needs nothing but the row made."""
    cell = _Cells(cells, mapping)
    full_name = " ".join(part for part in (cell(Field.NAME), cell(Field.LAST_NAME)) if part)
    member = Member(number, " ".join(full_name.split()))
    try:
        member.name = _NAME.validate_python(member.name)
    except ValidationError:
        member.refuse(Field.NAME, "required")

    member.phone = _phone(member, Field.PHONE, cell(Field.PHONE))
    member.email = _email(member, Field.EMAIL, cell(Field.EMAIL))
    member.rut = _rut(member, Field.RUT, cell(Field.RUT))
    member.guardian_name = " ".join(cell(Field.GUARDIAN_NAME).split()) or None
    member.guardian_rut = _rut(member, Field.GUARDIAN_RUT, cell(Field.GUARDIAN_RUT))
    member.guardian_email = _email(member, Field.GUARDIAN_EMAIL, cell(Field.GUARDIAN_EMAIL))
    member.guardian_phone = _phone(member, Field.GUARDIAN_PHONE, cell(Field.GUARDIAN_PHONE))
    own_guardian(member)
    if cell(Field.GUARDIAN_PHONE) and not member.has_guardian:
        # A guardian's phone finds nobody: the sheet must say who the guardian is.
        member.refuse(Field.GUARDIAN_NAME, "required")
    if member.rut is not None and member.rut == member.guardian_rut:
        member.refuse(Field.GUARDIAN_RUT, "own_guardian")

    member.dob = _date(member, Field.DOB, cell(Field.DOB), today)
    plan_value = cell(Field.PLAN)
    if plan_value and plans.cleared(plan_value):
        # The admin said this value means no plan: the person alone, and the dates
        # that only a membership reads are not read either.
        return member
    member.due_on = _date(member, Field.DUE_ON, cell(Field.DUE_ON), today)
    member.started_on = _date(member, Field.STARTED_ON, cell(Field.STARTED_ON), today)
    if plan_value:
        _plan(member, plans, plan_value)
    return member


def own_guardian(member: Member) -> None:
    """A contact the row shares with its guardian is the guardian's: a child given their
    parent's email or phone has none of their own, and is not found by it."""
    if not member.has_guardian:
        return
    if member.email is not None and identity(None, member.email) == identity(
        None, member.guardian_email
    ):
        member.email = None
    if member.phone is not None and member.phone == member.guardian_phone:
        member.phone = None


def _plan(member: Member, plans: "PlanFinder", value: str) -> None:
    plan = plans.find(value)
    if plan is None:
        member.refuse(Field.PLAN, "unknown_plan")
        return
    if not plan.active:
        member.refuse(Field.PLAN, "inactive_plan")
    elif plan.terms.kind is PlanKind.DROPIN:
        member.refuse(Field.PLAN, "dropin_plan")
    elif (
        plan.terms.kind in RECURRING
        and member.due_on is None
        # Unless the cell holds a bad date, which says as much.
        and not any(e.field is Field.DUE_ON for e in member.errors)
    ):
        member.refuse(Field.DUE_ON, "required")
    started_on = member.started_on
    if member.due_on is not None and started_on is not None and member.due_on < started_on:
        member.refuse(Field.DUE_ON, "due_before_start")
    member.plan = plan


class PlanFinder:
    """A sheet's plan cell to one of the gym's plans: by the admin's choice for that
    value, else by name, accents and case ignored, an active plan first.

    A choice of `None` means no plan: the row's person is imported with no membership,
    whatever plan that value names (`cleared`).
    """

    def __init__(self, plans: Sequence[Plan], chosen: Mapping[str, uuid.UUID | None]) -> None:
        by_id = {plan.id: plan for plan in plans}
        self._cleared = {fold(value) for value, plan_id in chosen.items() if plan_id is None}
        self._chosen = {
            fold(value): by_id.get(plan_id)
            for value, plan_id in chosen.items()
            if plan_id is not None
        }
        self._by_name: dict[str, Plan] = {}
        for plan in sorted(plans, key=lambda p: not p.active):
            self._by_name.setdefault(fold(plan.name), plan)

    def cleared(self, value: str) -> bool:
        return fold(value) in self._cleared

    def find(self, value: str) -> Plan | None:
        key = fold(value)
        if key in self._chosen:
            return self._chosen[key]
        return self._by_name.get(key)


def _alike(one: Member, other: Member) -> bool:
    """Whether two rows of one name may be one person: neither the birth date nor the
    phone, where both give one, tells them apart."""
    return all(
        a is None or b is None or a == b
        for a, b in ((one.dob, other.dob), (one.phone, other.phone))
    )


def read_members(
    rows: Sequence[tuple[int, Sequence[str]]],
    mapping: Mapping[Field, int],
    plans: PlanFinder,
    today: date,
) -> list[Member]:
    """Every row read, and each person or dependent that an earlier row already has
    flagged `repeated`, so the sheet's first mention is the one imported."""
    members = [read_member(n, cells, mapping, plans, today) for n, cells in rows]
    seen: set[object] = set()
    # Adults by name: a row with no RUT and no email is whoever an earlier row of the
    # name is, unless the birth date or the phone tells them apart, as the import would.
    names: dict[str, list[Member]] = {}
    for member in members:
        if member.key is not None:
            key: object = member.key
            on = Field.RUT if member.rut is not None else Field.EMAIL
        elif member.guardian_ident is not None:
            key = (member.guardian_ident, fold(member.name))
            on = Field.NAME
        elif member.name:
            key = None
            on = Field.NAME
        else:
            continue
        if member.missing_identity:
            # Only the name: repeated when nothing else tells them apart.
            repeated = any(_alike(member, other) for other in names.get(fold(member.name), []))
        else:
            repeated = key in seen
            seen.add(key)
        if repeated:
            member.refuse(on, "repeated")
        if not member.is_dependent:
            names.setdefault(fold(member.name), []).append(member)
    return members
