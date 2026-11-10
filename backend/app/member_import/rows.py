"""Sheet rows and a column mapping in, the people they describe out, each with its errors.

Pure: no database. Every check that needs only the row is made here, so a dry run
reports them all at once. What needs the gym's data (is that guardian already here, do
they already have someone of that name in their care) is checked as the row is written
(`app.api.member_import`).

A row is an adult, found again by their phone, or a dependent with no phone, found by
their guardian's phone and their own name. Someone with a phone may have a guardian
too (a teenager). A row with a plan gets a membership, starting as of its due date.
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
    GUARDIAN_PHONE = "guardian_phone"


# `required`: the cell is empty and the row needs it. `repeated`: an earlier row has the
# same phone, or the same guardian and name. `own_guardian`: the guardian's phone is the
# row's own. `unknown_plan`, `inactive_plan`, `dropin_plan`: no such plan, a deactivated
# one, or a drop-in, which is not a membership. `due_before_start`: the due date is
# before the start. `has_guardian`, `one_level`: the link is refused (migration 0010).
# `has_left`: the member was dado de baja, and starts no plan until reactivated (0032).
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
    guardian_phone: str | None = None
    # No sheet column gives one; the join link's form does (`app.api.join`).
    guardian_email: str | None = None
    errors: list[RowError] = field(default_factory=list)

    def refuse(self, on: Field, code: ErrorCode) -> None:
        self.errors.append(RowError(on, code))


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
# In order: the first field whose words a header holds is the one suggested.
_HEADER_WORDS: tuple[tuple[Field, tuple[str, ...]], ...] = (
    (Field.DOB, ("nacimiento", "cumpleanos", "f nac", "fecha nac", "birth", "dob")),
    (Field.DUE_ON, ("vencimiento", "vence", "proximo pago", "fecha de pago", "fecha pago")),
    (Field.STARTED_ON, ("fecha de ingreso", "ingreso", "inicio", "alta")),
    (Field.PHONE, _PHONE_WORDS),
    (Field.EMAIL, ("correo", "email", "e mail", "mail")),
    (Field.RUT, ("rut", "run")),
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
        return Field.GUARDIAN_PHONE if _holds(words, _PHONE_WORDS) else Field.GUARDIAN_NAME
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
    member.guardian_phone = _phone(member, Field.GUARDIAN_PHONE, cell(Field.GUARDIAN_PHONE))
    member.guardian_name = " ".join(cell(Field.GUARDIAN_NAME).split()) or None
    if not cell(Field.PHONE) and not cell(Field.GUARDIAN_PHONE):
        # Guardians are found by phone, so a dependent needs theirs.
        member.refuse(Field.GUARDIAN_PHONE if member.guardian_name else Field.PHONE, "required")
    if member.phone is not None and member.phone == member.guardian_phone:
        member.refuse(Field.GUARDIAN_PHONE, "own_guardian")

    if email := cell(Field.EMAIL):
        try:
            member.email = _EMAIL.validate_python(email)
        except ValidationError:
            member.refuse(Field.EMAIL, "invalid_email")
    if rut := cell(Field.RUT):
        try:
            member.rut = normalize_rut(rut)
        except ValueError:
            member.refuse(Field.RUT, "invalid_rut")
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


def read_members(
    rows: Sequence[tuple[int, Sequence[str]]],
    mapping: Mapping[Field, int],
    plans: PlanFinder,
    today: date,
) -> list[Member]:
    """Every row read, and each phone or dependent that an earlier row already has
    flagged `repeated`, so the sheet's first mention is the one imported."""
    members = [read_member(n, cells, mapping, plans, today) for n, cells in rows]
    seen: set[object] = set()
    for member in members:
        if member.phone is not None:
            key: object = member.phone
            on = Field.PHONE
        elif member.guardian_phone is not None:
            key = (member.guardian_phone, fold(member.name))
            on = Field.NAME
        else:
            continue
        if key in seen:
            member.refuse(on, "repeated")
        seen.add(key)
    return members
