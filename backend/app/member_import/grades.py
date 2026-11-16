"""The Grados tab (#299): one row per belt or stripe earned, read with no database.

A row names someone by RUT, else email, else name, as the Alumnos tab does, and never
creates anyone: who they are is looked up as the row is written (`app.api.member_import`),
after the Alumnos tab, so a grade finds a student that tab adds. The rank is matched as a
plan is (`rows.PlanFinder`): by the admin's choice for that value on the mapping step
("Café" → Marrón), else by the scheme's label, accents and case ignored. A sub-rank is a
label of the rank's, or a number of stripes, as the belt counts them
(`schemas.grades.Belt`): the rank's first sub-rank is none, so "2" is its third ("2
grados"). A rank with sub-ranks and an empty Sub-grado is its first. The day may go
back `HISTORY_WINDOW_YEARS`, never past today.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from app.domain.rut import normalize_rut
from app.member_import.rows import (
    EMAIL_WORDS,
    RUT_WORDS,
    Cells,
    fold,
    header_words,
    holds,
    identity,
    in_history,
    parse_date,
)
from app.schemas.grading import GradingScheme, Rank
from app.schemas.people import Email


class GradeField(StrEnum):
    RUT = "rut"
    EMAIL = "email"
    NAME = "name"
    RANK = "rank"
    SUB_RANK = "sub_rank"
    AWARDED_ON = "awarded_on"
    NOTE = "note"


# As a grade's note takes it (`schemas.grades.Note`).
MAX_NOTE = 500

# `required`: the cell is empty and the row needs it; on `name`, the row says nobody.
# `unknown_rank`: no rank of the scheme by that label and none chosen, or, on
# `sub_rank`, no sub-rank of the rank by that label or number. `unknown_person`: nobody
# in the gym or on the Alumnos tab is the row. `ambiguous_name`: two people of the name.
# `repeated`: an earlier row gives the same person the same grade on the same day.
GradeErrorCode = Literal[
    "required",
    "invalid_rut",
    "invalid_email",
    "invalid_date",
    "unknown_rank",
    "unknown_person",
    "ambiguous_name",
    "repeated",
    "too_long",
]


@dataclass(frozen=True)
class GradeRowError:
    field: GradeField
    code: GradeErrorCode


@dataclass
class Grade:
    """One Grados row, read. Its fields are valid wherever `errors` names none."""

    number: int
    name: str
    rut: str | None = None
    email: str | None = None
    rank: Rank | None = None
    sub_rank: str | None = None
    awarded_on: date | None = None
    note: str | None = None
    errors: list[GradeRowError] = field(default_factory=list)

    def refuse(self, on: GradeField, code: GradeErrorCode) -> None:
        self.errors.append(GradeRowError(on, code))

    @property
    def key(self) -> tuple[str, str] | None:
        """Who the row is, by RUT, else email."""
        return identity(self.rut, self.email)


# In order: the first field whose words a header holds is the one suggested. The
# sub-rank's "sub grado" before the rank's "grado".
_HEADER_WORDS: tuple[tuple[GradeField, tuple[str, ...]], ...] = (
    (GradeField.SUB_RANK, ("sub grado", "subgrado", "franja", "raya", "barra", "stripe")),
    (GradeField.RANK, ("grado", "cinturon", "faja", "rango", "belt", "rank")),
    (GradeField.AWARDED_ON, ("fecha", "graduacion", "date")),
    (GradeField.NOTE, ("nota", "observacion", "observaciones", "comentario")),
    (GradeField.EMAIL, EMAIL_WORDS),
    (GradeField.RUT, RUT_WORDS),
    (GradeField.NAME, ("nombre", "alumno", "alumna", "name")),
)


def suggest_grade_mapping(headers: Sequence[str]) -> dict[GradeField, int]:
    """The column each field most likely is, by its header; the first column wins."""
    mapping: dict[GradeField, int] = {}
    for column, header in enumerate(headers):
        words = header_words(header)
        suggested = next((f for f, keys in _HEADER_WORDS if holds(words, keys)), None)
        if suggested is not None and suggested not in mapping:
            mapping[suggested] = column
    return mapping


class RankFinder:
    """A sheet's Grado cell to a rank of the gym's scheme: by the admin's choice for that
    value, else by label, accents and case ignored, the adult ranks first."""

    def __init__(self, scheme: GradingScheme, chosen: Mapping[str, str]) -> None:
        self._chosen = {fold(value): scheme.rank(key) for value, key in chosen.items()}
        self._by_label: dict[str, Rank] = {}
        for rank in (*scheme.ranks, *scheme.kids_ladder):
            self._by_label.setdefault(fold(rank.label), rank)

    def find(self, value: str) -> Rank | None:
        key = fold(value)
        if key in self._chosen:
            return self._chosen[key]
        return self._by_label.get(key)


_EMAIL = TypeAdapter(Email)
_STRIPES = re.compile(r"\d{1,2}")


def sub_rank(rank: Rank, value: str) -> str | None:
    """The key of `rank`'s sub-rank `value` names: its label, else its number of stripes.
    Empty is the first; `None` for none the rank has (or any, on a rank with none)."""
    if not rank.sub_ranks:
        return None
    if not value:
        return rank.sub_ranks[0].key
    folded = fold(value)
    if found := next((s for s in rank.sub_ranks if fold(s.label) == folded), None):
        return found.key
    if _STRIPES.fullmatch(folded) and int(folded) < len(rank.sub_ranks):
        return rank.sub_ranks[int(folded)].key
    return None


def _rut(grade: Grade, raw: str) -> str | None:
    if not raw:
        return None
    try:
        return normalize_rut(raw)
    except ValueError:
        grade.refuse(GradeField.RUT, "invalid_rut")
        return None


def _email(grade: Grade, raw: str) -> str | None:
    if not raw:
        return None
    try:
        return _EMAIL.validate_python(raw)
    except ValidationError:
        grade.refuse(GradeField.EMAIL, "invalid_email")
        return None


def _awarded_on(grade: Grade, raw: str, today: date) -> date | None:
    if not raw:
        grade.refuse(GradeField.AWARDED_ON, "required")
        return None
    try:
        day = parse_date(raw, today)
    except ValueError:
        day = None
    if day is None or not in_history(day, today):
        grade.refuse(GradeField.AWARDED_ON, "invalid_date")
        return None
    return day


def read_grade(
    number: int,
    cells: Sequence[str],
    mapping: Mapping[GradeField, int],
    ranks: RankFinder,
    today: date,
) -> Grade:
    """One row, every check that needs nothing but the row made."""
    cell = Cells(cells, mapping)
    grade = Grade(number, " ".join(cell(GradeField.NAME).split()))
    grade.rut = _rut(grade, cell(GradeField.RUT))
    grade.email = _email(grade, cell(GradeField.EMAIL))
    if grade.key is None and not grade.name and not grade.errors:
        grade.refuse(GradeField.NAME, "required")

    rank_value = cell(GradeField.RANK)
    sub_value = cell(GradeField.SUB_RANK)
    if not rank_value:
        grade.refuse(GradeField.RANK, "required")
    elif (rank := ranks.find(rank_value)) is None:
        grade.refuse(GradeField.RANK, "unknown_rank")
    else:
        grade.rank = rank
        grade.sub_rank = sub_rank(rank, sub_value)
        if grade.sub_rank is None and (rank.sub_ranks or sub_value):
            grade.refuse(GradeField.SUB_RANK, "unknown_rank")

    grade.awarded_on = _awarded_on(grade, cell(GradeField.AWARDED_ON), today)
    note = " ".join(cell(GradeField.NOTE).split()) or None
    if note is not None and len(note) > MAX_NOTE:
        grade.refuse(GradeField.NOTE, "too_long")
        note = None
    grade.note = note
    return grade


def read_grades(
    rows: Sequence[tuple[int, Sequence[str]]],
    mapping: Mapping[GradeField, int],
    ranks: RankFinder,
    today: date,
) -> list[Grade]:
    return [read_grade(n, cells, mapping, ranks, today) for n, cells in rows]
