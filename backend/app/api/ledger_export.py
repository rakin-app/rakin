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

Owner and admin only (`LedgerSession`); RLS keeps it to the gym (migration 0006).
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger_export as export
from app.api.ledger import ENTRY_DAY, GYM_CLOCK, book_rows
from app.domain import custom_fields as cf
from app.domain.billing import SETTLING_KINDS
from app.roles import LedgerSession, role_in_gym
from app.schemas.ledger import ExportFormat
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The day the export files an entry under, for `e`, `t` and `bp`, as the module says.
EXPORT_DAY = f"""CASE
    WHEN e.kind = 'charge' AND bp.id IS NOT NULL THEN bp.period_start
    WHEN e.kind IN ('payment', 'refund') AND e.status = 'validated'
        THEN (e.validated_at AT TIME ZONE t.timezone)::date
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

MEDIA_TYPES = {
    ExportFormat.CSV: export.CSV_MEDIA_TYPE,
    ExportFormat.XLSX: export.XLSX_MEDIA_TYPE,
}


async def exported_fields(session: AsyncSession, tenant: Tenant) -> list[dict[str, Any]]:
    """The custom fields the export carries: those the caller sees that are neither
    sensitive nor archived, in the gym's order."""
    settings = await session.scalar(
        text("SELECT settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    role = await role_in_gym(session, tenant)
    return [
        d
        for d in cf.visible(role, cf.definitions(settings or {}))
        if not d["sensitive"] and not d["archived"]
    ]


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
        kind=export.kind_label(row.kind, row.voids),
        method=None if row.method is None else export.METHODS[row.method],
        amount_clp=row.amount_clp,
        status=export.STATUSES[row.status],
        bank_ref=row.bank_tx_ref,
        note=row.note,
        fields=values,
        extra=row.extra_charge_id is not None,
    )


@router.get("/export")
async def ledger_export(
    session: LedgerSession,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    # Any day of the month to export; the current one in the gym's timezone by default.
    month: date | None = None,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    """The month's ledger entries and totals, as a file to download."""
    clock = (await session.execute(text(GYM_CLOCK))).one()
    shown = (month or clock.today).replace(day=1)
    rows = (
        await session.execute(
            EXPORT_ROWS,
            {"month": shown, "settling": sorted(k.value for k in SETTLING_KINDS)},
        )
    ).all()

    fields = await exported_fields(session, tenant)
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
    )

    if export_format is ExportFormat.XLSX:
        body = export.to_xlsx(month_export)
    else:
        body = export.to_csv(month_export)
    name = export.filename(shown, export_format.value)
    return Response(
        content=body,
        media_type=MEDIA_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
