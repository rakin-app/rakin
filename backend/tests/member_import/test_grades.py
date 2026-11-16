"""Grados rows read with no database (#299): the mapping suggested, ranks and sub-ranks
matched, the row's own checks made."""

import copy
from datetime import date

import pytest

from app.member_import.grades import (
    Grade,
    GradeField,
    GradeRowError,
    RankFinder,
    read_grade,
    suggest_grade_mapping,
)
from app.member_import.template import GRADE_COLUMNS
from app.schemas.grading import PRESETS, GradingScheme

G = GradeField
TODAY = date(2026, 11, 9)
BJJ = next(p.scheme for p in PRESETS if p.key == "bjj")
MAPPING = {G.RUT: 0, G.NAME: 1, G.RANK: 2, G.SUB_RANK: 3, G.AWARDED_ON: 4, G.NOTE: 5}


def row(
    rank: str = "Azul",
    sub: str = "",
    day: str = "12-08-2023",
    *,
    rut: str = "",
    name: str = "Martina Soto",
    note: str = "",
    ranks: RankFinder | None = None,
) -> Grade:
    finder = ranks or RankFinder(BJJ, {})
    return read_grade(2, [rut, name, rank, sub, day, note], MAPPING, finder, TODAY)


def test_the_templates_headers_map_by_themselves() -> None:
    headers = [header for header, _, _ in GRADE_COLUMNS]
    assert suggest_grade_mapping(headers) == {f: i for i, (_, f, _) in enumerate(GRADE_COLUMNS)}


def test_a_gyms_own_headers_are_suggested() -> None:
    headers = ["Alumno", "Cinturón", "Rayas", "Fecha de graduación", "Observaciones"]
    assert suggest_grade_mapping(headers) == {
        G.NAME: 0,
        G.RANK: 1,
        G.SUB_RANK: 2,
        G.AWARDED_ON: 3,
        G.NOTE: 4,
    }


def test_a_rank_is_its_label_accents_and_case_ignored() -> None:
    grade = row("  CAFE ")
    assert grade.errors == []
    assert grade.rank is not None and grade.rank.key == "brown"
    # A kids belt is a rank too.
    kids = row("Gris y blanca")
    assert kids.rank is not None and kids.rank.key == "grey-white"


def test_a_label_the_scheme_lacks_is_refused_unless_the_admin_chose_its_rank() -> None:
    scheme = copy.deepcopy(BJJ)
    scheme.ranks[3].label = "Marrón"
    assert row("Café", ranks=RankFinder(scheme, {})).errors == [
        GradeRowError(G.RANK, "unknown_rank")
    ]
    chosen = row("Café", ranks=RankFinder(scheme, {"café": "brown"}))
    assert chosen.errors == []
    assert chosen.rank is not None and chosen.rank.key == "brown"
    # A choice of a key the scheme does not have matches nothing.
    assert row("Café", ranks=RankFinder(scheme, {"Café": "gone"})).errors == [
        GradeRowError(G.RANK, "unknown_rank")
    ]


@pytest.mark.parametrize(
    ("value", "key"),
    [("", "0"), ("2", "2"), ("2 grados", "2"), ("1 GRADO", "1"), ("sin grados", "0"), ("4", "4")],
)
def test_a_sub_rank_is_its_label_or_its_number_of_stripes(value: str, key: str) -> None:
    grade = row("Azul", value)
    assert grade.errors == []
    assert grade.sub_rank == key


@pytest.mark.parametrize("value", ["5", "dos", "-1"])
def test_a_sub_rank_the_rank_lacks_is_refused(value: str) -> None:
    assert row("Azul", value).errors == [GradeRowError(G.SUB_RANK, "unknown_rank")]


def test_a_rank_with_no_sub_ranks_takes_none() -> None:
    scheme = GradingScheme.model_validate({"ranks": [{"key": "white", "label": "Blanca"}]})
    finder = RankFinder(scheme, {})
    grade = row("Blanca", ranks=finder)
    assert (grade.errors, grade.sub_rank) == ([], None)
    assert row("Blanca", "1", ranks=finder).errors == [GradeRowError(G.SUB_RANK, "unknown_rank")]


@pytest.mark.parametrize(
    ("day", "code"),
    [
        ("", "required"),
        ("ayer", "invalid_date"),
        ("10-11-2026", "invalid_date"),  # after today
        ("01-01-1966", "invalid_date"),  # more than 60 years back
    ],
)
def test_the_day_is_required_and_within_sixty_years(day: str, code: str) -> None:
    assert row(day=day).errors == [GradeRowError(G.AWARDED_ON, code)]  # type: ignore[arg-type]


def test_sixty_years_back_is_still_a_grade() -> None:
    grade = row(day="09-11-1966")
    assert (grade.errors, grade.awarded_on) == ([], date(1966, 11, 9))


def test_a_row_must_say_who_and_which_rank() -> None:
    assert row("", name="").errors == [
        GradeRowError(G.NAME, "required"),
        GradeRowError(G.RANK, "required"),
    ]
    by_rut = row(name="", rut="12.345.678-5")
    assert (by_rut.errors, by_rut.rut) == ([], "12345678-5")
    assert row(rut="12.345.678-0").errors == [GradeRowError(G.RUT, "invalid_rut")]


def test_a_note_is_kept_up_to_its_limit() -> None:
    assert row(note="  Graduación   de invierno ").note == "Graduación de invierno"
    assert row(note="x" * 501).errors == [GradeRowError(G.NOTE, "too_long")]
