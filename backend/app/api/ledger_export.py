"""The month's ledger for the gym's accountant, as CSV or XLSX (#40): "Exportar" on
Pagos ("Libro de pagos", #39). Export only; it issues no SII boleta.

`GET /api/ledger/export?month=2026-11-01&format=xlsx` lists every ledger entry of the
month, in the gym's timezone, by the day it counts on: a charge by the day its period
starts, as the book files it (#206); a validated payment or refund by the day it was
validated, as "Cobrado" (`v_monthly_income`) counts it, so the export's paid less
refunded is the book's collected for the month; anything else by the day it was made.
Entries on cobro extra lines (#195) are among them, labelled by category, with no
period. Proofs still waiting are listed on their own; the totals count validated
entries alone (`app.ledger_export`).

It carries no email or phone, and no custom field that is sensitive, archived, or one
the caller's role may not see.

`money_read` only (`LedgerReadSession`); RLS keeps it to the gym (migration 0006).
Whoever also holds `expenses_read` gets the XLSX with the month's Gastos and a Resumen
of Entradas, Salidas by category and Resultado, as Finanzas counts them (#317); anyone
else gets the same three sheets as before, and the CSV is the same for everyone.

`GET /api/ledger/export/expenses?month=2026-11-01` is "Gastos del mes (CSV)": the
month's expenses by the day they were paid, the voided ones apart, and the totals by
category. It needs `expenses_read` alone, since it carries no income.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger_export as export
from app.api.custom_fields import reach_of
from app.api.finances import EXPENSES, INCOME
from app.api.ledger import ENTRY_DAY, GYM_CLOCK, book_rows
from app.domain import custom_fields as cf
from app.domain.billing import SETTLING_KINDS
from app.domain.dates import add_months
from app.domain.vocabulary import Words, words_in
from app.permissions import (
    ExpensesReadSession,
    LedgerReadSession,
    Permission,
    holds,
    standing_in_gym,
)
from app.schemas.ledger import ExportFormat
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The day the export files an entry under, for `e`, `t` and `bp`, as the module says.
# Nothing holds a validated entry to a `validated_at`; one without it, which
# `v_monthly_income` leaves out, falls back to the day it was made rather than being
# lost from every month's file.
EXPORT_DAY = f"""CASE
    WHEN e.kind = 'charge' AND bp.id IS NOT NULL THEN bp.period_start
    WHEN e.kind IN ('payment', 'refund') AND e.status = 'validated'
        THEN (coalesce(e.validated_at, e.created_at) AT TIME ZONE t.timezone)::date
    ELSE {ENTRY_DAY} END"""

EXPORT_ROWS = text(
    f"""
    {book_rows(f"{EXPORT_DAY} AS day, mp.rut AS person_rut, e.bank_tx_ref, e.billing_period_id, ")}
    WHERE {EXPORT_DAY} >= :month AND {EXPORT_DAY} < (:month + interval '1 month')::date
    ORDER BY day, e.created_at, e.id
    """
)

FIELD_VALUES = text(
    """
    SELECT person_id, field_key, value FROM person_field_value
    WHERE secret IS NULL AND person_id = ANY(CAST(:people AS uuid[]))
      AND field_key = ANY(CAST(:keys AS text[]))
    """
)

# The month's expenses, voided ones included, by the day they were paid.
EXPENSE_ROWS = text(
    """
    SELECT e.spent_on, c.name AS category, e.payee, e.method, e.amount_clp, e.note,
           e.receipt_object_key IS NOT NULL AS has_receipt, e.voided_at IS NOT NULL AS voided
    FROM expense e
    JOIN expense_category c ON c.id = e.category_id
    WHERE e.spent_on >= :month AND e.spent_on < (:month + interval '1 month')::date
    ORDER BY e.spent_on, e.created_at, e.id
    """
)

MEDIA_TYPES = {
    ExportFormat.CSV: export.CSV_MEDIA_TYPE,
    ExportFormat.XLSX: export.XLSX_MEDIA_TYPE,
}


async def exported_fields(
    session: AsyncSession, tenant: Tenant
) -> tuple[list[dict[str, Any]], Words]:
    """The custom fields the export carries: those the caller sees that are neither
    sensitive nor archived, in the gym's order; and the gym's words (#345)."""
    settings = await session.scalar(
        text("SELECT settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    reach = reach_of(await standing_in_gym(session, tenant))
    fields = [
        d
        for d in cf.visible(reach, cf.definitions(settings or {}))
        if not d["sensitive"] and not d["archived"]
    ]
    return fields, words_in(settings)


def field_value(definition: dict[str, Any], value: Any) -> str | int | float | date | None:
    """A stored value as the export writes it: a date field's as a day."""
    if value is None:
        return None
    if definition["type"] is cf.FieldType.DATE:
        return date.fromisoformat(value)
    if definition["type"] is cf.FieldType.NUMBER:
        return value  # type: ignore[no-any-return]
    return str(value)


def export_row(row: Any, values: tuple[str | int | float | date | None, ...]) -> export.Row:
    return export.Row(
        day=row.day,
        member=row.person_name,
        rut=row.person_rut,
        concept=export.concept(row.plan_name, row.charge_category, row.charge_title),
        period=None if row.period_start is None else (row.period_start, row.period_end),
        kind=export.kind_label(row.kind, row.voids, row.purpose, row.period_start is not None),
        method=None if row.method is None else export.METHODS[row.method],
        amount_clp=row.amount_clp,
        status=export.STATUSES[row.status],
        bank_ref=row.bank_tx_ref,
        note=row.note,
        fields=values,
        extra=row.extra_charge_id is not None,
    )


async def month_expenses(
    session: AsyncSession, month: date, with_income: bool
) -> export.MonthExpenses:
    """The month's expenses, and its Entradas when `with_income`, read by the queries
    Finanzas reads them by, so the two never disagree."""
    rows = [
        export.ExpenseRow(
            day=r.spent_on,
            category=r.category,
            payee=r.payee,
            method=None if r.method is None else export.EXPENSE_METHODS[r.method],
            amount_clp=r.amount_clp,
            note=r.note,
            receipt=r.has_receipt,
            voided=r.voided,
        )
        for r in await session.execute(EXPENSE_ROWS, {"month": month})
    ]
    window = {"start": month, "end": add_months(month, 1)}
    by_category = tuple(
        (r.name, int(r.amount_clp)) for r in await session.execute(EXPENSES, window)
    )
    income = None
    if with_income:
        found = (await session.execute(INCOME, window)).first()
        income = 0 if found is None else int(found.income_clp)
    return export.MonthExpenses(
        month=month,
        expenses=tuple(r for r in rows if not r.voided),
        voided=tuple(r for r in rows if r.voided),
        by_category=by_category,
        income_clp=income,
    )


async def export_month(session: AsyncSession, month: date | None) -> date:
    """The first of `month`, or of the gym's current one."""
    clock = (await session.execute(text(GYM_CLOCK))).one()
    return (month or clock.today).replace(day=1)


@router.get("/export/expenses")
async def expenses_export(
    session: ExpensesReadSession,
    # Any day of the month to export; the current one in the gym's timezone by default.
    month: date | None = None,
) -> Response:
    """The month's expenses and their totals, as a CSV to download."""
    shown = await export_month(session, month)
    body = export.expenses_csv(await month_expenses(session, shown, with_income=False))
    name = export.expenses_filename(shown)
    return Response(
        content=body,
        media_type=export.CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/export")
async def ledger_export(
    session: LedgerReadSession,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    # Any day of the month to export; the current one in the gym's timezone by default.
    month: date | None = None,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    """The month's ledger entries and totals, as a file to download."""
    shown = await export_month(session, month)
    rows = (
        await session.execute(
            EXPORT_ROWS,
            {"month": shown, "settling": sorted(k.value for k in SETTLING_KINDS)},
        )
    ).all()

    fields, words = await exported_fields(session, tenant)
    values: dict[tuple[uuid.UUID, str], Any] = {}
    if fields and rows:
        found = await session.execute(
            FIELD_VALUES,
            {
                "people": sorted({str(r.person_id) for r in rows}),
                "keys": [d["key"] for d in fields],
            },
        )
        values = {(v.person_id, v.field_key): v.value for v in found}

    entries: list[export.Row] = []
    pending: list[export.Row] = []
    for row in rows:
        shown_values = tuple(field_value(d, values.get((row.person_id, d["key"]))) for d in fields)
        (pending if row.status == "pending" else entries).append(export_row(row, shown_values))
    # What the periods charged in the month still owe today.
    outstanding = sum(
        {
            r.billing_period_id: r.outstanding_clp
            for r in rows
            if r.kind == "charge" and r.status == "validated" and r.billing_period_id
        }.values()
    )
    month_export = export.MonthExport(
        month=shown,
        fields=tuple(d["label"] for d in fields),
        entries=tuple(entries),
        pending=tuple(pending),
        totals=export.totals(entries, outstanding),
        words=words,
    )

    if export_format is ExportFormat.XLSX:
        expenses = None
        if await holds(session, tenant, Permission.EXPENSES_READ):
            expenses = await month_expenses(session, shown, with_income=True)
        body = export.to_xlsx(month_export, expenses)
    else:
        body = export.to_csv(month_export)
    name = export.filename(shown, export_format.value)
    return Response(
        content=body,
        media_type=MEDIA_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
