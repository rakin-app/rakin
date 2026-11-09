"""Reading a gym's spreadsheet: CSV as Excel and Google Sheets write it, and XLSX."""

import io
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.member_import import sheet as s
from app.member_import.sheet import Row, Sheet, SheetError, read_sheet

PILOT = Path(__file__).parent.parent / "fixtures" / "pilot_sheet.csv"


def xlsx(*rows: list[object], extra_sheet: bool = False) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    for row in rows:
        worksheet.append(row)
    if extra_sheet:
        workbook.create_sheet("Pagos").append(["no", "es", "esta"])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def test_the_pilot_sheet_reads_with_its_row_numbers() -> None:
    sheet = read_sheet(PILOT.read_bytes())
    assert sheet.headers[:3] == ["N°", "Nombre", "Apellido"]
    assert len(sheet.rows) == 13
    # The empty line 7 is skipped and the numbering keeps counting it.
    assert [row.number for row in sheet.rows[4:6]] == [6, 8]
    assert sheet.rows[0].cells[5] == "9 8765 4321"


@pytest.mark.parametrize(
    "data",
    [
        b"Nombre,Celular\nCamila,912345678\n",  # Google Sheets
        b"\xef\xbb\xbfNombre;Celular\r\nCamila;912345678\r\n",  # Excel, UTF-8
        b"Nombre\tCelular\nCamila\t912345678\n",
    ],
    ids=["comma", "semicolon-bom", "tab"],
)
def test_a_csv_is_read_whatever_its_delimiter(data: bytes) -> None:
    assert read_sheet(data) == Sheet(["Nombre", "Celular"], [Row(2, ["Camila", "912345678"])])


def test_a_windows_1252_csv_keeps_its_accents() -> None:
    data = "Nombre;Apellido\nSofía;Muñoz\n".encode("cp1252")
    assert read_sheet(data).rows == [Row(2, ["Sofía", "Muñoz"])]


def test_short_rows_are_padded_and_long_ones_cut_to_the_header() -> None:
    sheet = read_sheet(b"a,b,c\n1\n1,2,3,4\n")
    assert [row.cells for row in sheet.rows] == [["1", "", ""], ["1", "2", "3"]]


def test_the_header_is_the_first_row_with_anything_in_it() -> None:
    sheet = read_sheet(b",,\nNombre,Plan\n Camila , Mensual \n")
    assert sheet == Sheet(["Nombre", "Plan"], [Row(3, ["Camila", "Mensual"])])


def test_an_xlsx_reads_its_first_sheet_with_dates_and_numbers_as_text() -> None:
    data = xlsx(
        ["Nombre", "Celular", "Fecha de pago", None],
        ["Camila", 912345678, datetime(2026, 12, 5), None],
        [None, None, None, None],
        ["Diego", 56912340001.0, date(2027, 3, 15), None],
        extra_sheet=True,
    )
    assert read_sheet(data) == Sheet(
        ["Nombre", "Celular", "Fecha de pago"],
        [
            Row(2, ["Camila", "912345678", "2026-12-05"]),
            Row(4, ["Diego", "56912340001", "2027-03-15"]),
        ],
    )


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty"),
        (b"\n,,\n", "empty"),
        (b"Nombre,Celular\n", "empty"),
        (b"PK\x03\x04 not really a zip", "unreadable"),
        (b"\x00\x01\x02binary", "unreadable"),
    ],
    ids=["nothing", "blank", "header-only", "broken-zip", "binary"],
)
def test_a_sheet_is_refused(data: bytes, code: str) -> None:
    with pytest.raises(SheetError) as refused:
        read_sheet(data)
    assert refused.value.code == code


def test_a_zip_that_is_not_a_workbook_is_unreadable() -> None:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("hola.txt", "hola")
    with pytest.raises(SheetError) as refused:
        read_sheet(out.getvalue())
    assert refused.value.code == "unreadable"


def test_too_many_rows_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s, "MAX_ROWS", 2)
    assert len(read_sheet(b"n\na\nb\n").rows) == 2
    with pytest.raises(SheetError) as refused:
        read_sheet(b"n\na\nb\nc\n")
    assert refused.value.code == "too_many_rows"
