"""Gastos (`/api/expenses`): what the gym spends, apart from billing (#314).

Rent, power, the federation, coaches' pay: each expense is a date, an amount, a
category from the gym's own list, who was paid, how, a note and, if the gym wants, a
photo or PDF of the receipt (docs/design/expenses-and-officers.md, sections 10 and 12).
They live in `expense` and `expense_category` (migration 0083), which nothing in
billing reads: no balance, Esperado, Cobrado, overdue email or student page sees them.

- `GET` lists a month, newest first, optionally of one category, with the total of
  those that count. `POST` records one, `PATCH /{id}` edits it and writes
  `expense_changed` with the fields before and after, `POST /{id}/void` ("Anular")
  voids it with a reason and writes `expense_voided`. A voided expense stays in the
  list and counts nowhere, and is not changed again. Nothing deletes one.
- A receipt goes from the browser straight to object storage, as a student's proof
  does (`app.api.proofs`): `POST /receipt-upload` presigns a key under the gym's
  `receipts/<gym_id>/`, of the blob store's types and at most 10 MB, and recording or
  editing the expense claims it, once the file is there and no other expense holds it.
  `GET /{id}/receipt` presigns its download, so the key itself opens nothing.
- `/categories`: the gym's list, renamed, added to, reordered and archived. One is
  archived, never deleted, so the expenses under it still read; Otros cannot be.

Reading needs `expenses_read` ("Ver gastos"), writing `expenses_write` ("Registrar
gastos"); no role has either until the gym ticks it, so they start the titular's alone,
since Sueldos y honorarios is what the gym pays its own team. RLS holds the database to
the same (0083), and the log's expense rows to `expenses_read` (0067).
"""

import json
import re
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dates import add_months, gym_today
from app.integrations import Integrations, get_integrations
from app.integrations.blobstore import ALLOWED_CONTENT_TYPES, MAX_UPLOAD_BYTES
from app.permissions import ExpensesReadSession, ExpensesSession
from app.schemas.expenses import (
    CategoryIn,
    CategoryOrder,
    Expense,
    ExpenseCategory,
    ExpenseChange,
    ExpenseIn,
    ExpenseMonth,
    ExpenseVoid,
    Receipt,
)
from app.schemas.proofs import ProofUpload, ProofUploadRequest
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

Acting = Annotated[Tenant, Depends(current_tenant)]

EXPENSE_CHANGED = "expense_changed"
EXPENSE_VOIDED = "expense_voided"

NO_EXPENSE = HTTPException(status.HTTP_404_NOT_FOUND, "no such expense in this gym")
NO_CATEGORY = HTTPException(status.HTTP_404_NOT_FOUND, "no such category in this gym")
NO_RECEIPT = HTTPException(status.HTTP_404_NOT_FOUND, "this expense has no receipt")
VOIDED = HTTPException(
    status.HTTP_409_CONFLICT, {"code": "voided", "message": "this expense is voided"}
)
NAME_TAKEN = HTTPException(
    status.HTTP_409_CONFLICT,
    {"code": "name_taken", "message": "the gym has a category of that name"},
)
OTHER_KEPT = HTTPException(
    status.HTTP_409_CONFLICT, {"code": "other_kept", "message": "Otros cannot be archived"}
)
RECEIPT_TAKEN = HTTPException(
    status.HTTP_409_CONFLICT,
    {"code": "receipt_taken", "message": "this receipt belongs to another expense"},
)


def unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": code, "message": message})


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def receipt_prefix(gym_id: uuid.UUID) -> str:
    """Where the gym's receipts are stored; migration 0083 checks the same prefix."""
    return f"receipts/{gym_id}/"


def is_gym_receipt(gym_id: uuid.UUID, key: str) -> bool:
    return re.fullmatch(re.escape(receipt_prefix(gym_id)) + _UUID, key) is not None


# Each expense with its category and who recorded and voided it, by the names the gym
# has for them.
EXPENSE_COLUMNS = """
    SELECT e.id, e.spent_on, e.amount_clp, e.category_id, c.name AS category_name, e.payee,
           e.method, e.note, e.receipt_object_key IS NOT NULL AS has_receipt,
           cb.name AS created_by_name, e.created_at, e.updated_at, e.voided_at,
           vb.name AS voided_by_name, e.void_reason
    FROM expense e
    JOIN expense_category c ON c.id = e.category_id
    LEFT JOIN gym_person cb ON cb.gym_id = e.gym_id AND cb.person_id = e.created_by
    LEFT JOIN gym_person vb ON vb.gym_id = e.gym_id AND vb.person_id = e.voided_by
"""

MONTH = text(
    EXPENSE_COLUMNS
    + """
    WHERE e.spent_on >= :start AND e.spent_on < :end
      AND (CAST(:category AS uuid) IS NULL OR e.category_id = CAST(:category AS uuid))
    ORDER BY e.spent_on DESC, e.created_at DESC, e.id DESC
    """
)
ONE = text(EXPENSE_COLUMNS + " WHERE e.id = :id")

LOCK = text(
    "SELECT id, spent_on, amount_clp, category_id, payee, method, note, receipt_object_key,"
    " voided_at FROM expense WHERE id = :id FOR UPDATE"
)

INSERT = text(
    "INSERT INTO expense (gym_id, spent_on, amount_clp, category_id, payee, method, note,"
    " receipt_object_key, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :spent_on, :amount_clp, :category_id,"
    " :payee, :method, :note, :receipt, current_setting('app.person_id')::uuid)"
    " RETURNING id"
)

# `now()` is the transaction's, as the policy wants it (0083).
INSERT_AUDIT = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, action, reason, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :action, :reason, CAST(:detail AS jsonb))"
)

CATEGORY = text("SELECT id, name, archived_at FROM expense_category WHERE id = :id")

TIMEZONE = text("SELECT timezone FROM gym WHERE id = :id")


async def _today(session: AsyncSession, tenant: Tenant) -> date:
    return gym_today(await session.scalar(TIMEZONE, {"id": tenant.gym_id}))


def _constraint(error: IntegrityError) -> str | None:
    return getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)


async def _read(session: AsyncSession, expense_id: uuid.UUID) -> Expense:
    row = (await session.execute(ONE, {"id": expense_id})).one_or_none()
    if row is None:
        raise NO_EXPENSE
    return Expense.model_validate(row._asdict())


async def _live_category(session: AsyncSession, category_id: uuid.UUID) -> Any:
    """A category an expense may be recorded under: the gym's, and not archived."""
    row = (await session.execute(CATEGORY, {"id": category_id})).one_or_none()
    if row is None:
        raise unprocessable("no_category", "no such category in this gym")
    if row.archived_at is not None:
        raise unprocessable("category_archived", "the category is archived")
    return row


def _refuse_future(spent_on: date, today: date) -> None:
    if spent_on > today:
        raise unprocessable("future", "an expense is recorded once it is paid")


async def _usable_receipt(tenant: Tenant, key: str, integrations: Integrations) -> None:
    """Refuse a key outside the gym's receipts or a file that never landed. One held by
    another expense is the unique index's to refuse."""
    if not is_gym_receipt(tenant.gym_id, key):
        raise unprocessable("not_a_receipt", "not one of the gym's uploads")
    stored = await integrations.blob_store.stat(key)
    # The store already refused anything else at upload; checked again, since an
    # upload URL is only as strict as the store that signed it.
    if (
        stored is None
        or stored.content_type not in ALLOWED_CONTENT_TYPES
        or stored.size > MAX_UPLOAD_BYTES
    ):
        raise unprocessable("receipt_missing", "receipt not uploaded")


@router.get("")
async def month_of_expenses(
    tenant: Acting,
    session: ExpensesReadSession,
    month: Annotated[date | None, Query()] = None,
    category: Annotated[uuid.UUID | None, Query()] = None,
) -> ExpenseMonth:
    """A month of expenses (the current one by default), newest first, of one category
    or all, with what those not voided add up to."""
    current = (await _today(session, tenant)).replace(day=1)
    shown = current if month is None else month
    if shown.day != 1:
        raise unprocessable("not_a_month", "month is the first day of a month")
    if shown > current:
        raise unprocessable("future", "no expenses are recorded for a later month")
    rows = await session.execute(
        MONTH,
        {
            "start": shown,
            "end": add_months(shown, 1),
            "category": None if category is None else str(category),
        },
    )
    items = [Expense.model_validate(row._asdict()) for row in rows]
    counted = [e for e in items if e.voided_at is None]
    return ExpenseMonth(
        month=shown,
        current_month=current,
        category_id=category,
        total_clp=sum(e.amount_clp for e in counted),
        count=len(counted),
        items=items,
    )


@router.post("/receipt-upload", status_code=status.HTTP_201_CREATED)
async def request_receipt_upload(
    body: ProofUploadRequest,
    tenant: Acting,
    session: ExpensesSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
    request: Request,
) -> ProofUpload:
    """A URL to PUT one receipt to, of exactly this type and size, under the gym's
    receipts. Nothing is recorded until an expense claims its key."""
    key = receipt_prefix(tenant.gym_id) + str(uuid.uuid4())
    upload = integrations.blob_store.presign_upload(key, body.content_type, body.size_bytes)
    return ProofUpload(
        key=key,
        url=upload.url,
        headers=upload.headers,
        expires_in_seconds=request.app.state.settings.blob_url_ttl_seconds,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_expense(
    body: ExpenseIn,
    tenant: Acting,
    session: ExpensesSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> Expense:
    """Record what the gym paid: on a day up to today, under a live category, with the
    receipt uploaded for it, if any."""
    _refuse_future(body.spent_on, await _today(session, tenant))
    await _live_category(session, body.category_id)
    if body.receipt_key is not None:
        await _usable_receipt(tenant, body.receipt_key, integrations)
    try:
        # A savepoint, so a refusal leaves the request's transaction usable for the 409.
        async with session.begin_nested():
            expense_id = await session.scalar(
                INSERT,
                {
                    **body.model_dump(exclude={"receipt_key"}),
                    "receipt": body.receipt_key,
                },
            )
    except IntegrityError as error:
        if _constraint(error) != "expense_receipt_object_key_key":
            raise
        raise RECEIPT_TAKEN from None
    return await _read(session, expense_id)


# What an edit may change, as the columns hold them.
EDITABLE = ("spent_on", "amount_clp", "category_id", "payee", "method", "note")


def _shown(value: Any) -> Any:
    """A value as the log keeps it."""
    if isinstance(value, uuid.UUID | date):
        return str(value)
    return value


@router.patch("/{expense_id}")
async def change_expense(
    expense_id: uuid.UUID,
    body: ExpenseChange,
    tenant: Acting,
    session: ExpensesSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> Expense:
    """Correct an expense: the fields sent, and `expense_changed` with each changed
    one before and after, in the same transaction. Nothing that changes nothing is
    written or logged. A voided expense is not changed (409)."""
    row = (await session.execute(LOCK, {"id": expense_id})).one_or_none()
    if row is None:
        raise NO_EXPENSE
    if row.voided_at is not None:
        raise VOIDED
    sent = body.model_fields_set
    if body.remove_receipt and body.receipt_key is not None:
        raise unprocessable("receipt_both", "a receipt is either replaced or removed")

    after: dict[str, Any] = {field: getattr(body, field) for field in EDITABLE if field in sent}
    if "spent_on" in after:
        _refuse_future(after["spent_on"], await _today(session, tenant))
    if "receipt_key" in sent and body.receipt_key is not None:
        after["receipt_object_key"] = body.receipt_key
    elif body.remove_receipt:
        after["receipt_object_key"] = None
    changed = {field: value for field, value in after.items() if getattr(row, field) != value}
    if not changed:
        return await _read(session, expense_id)

    before = {field: getattr(row, field) for field in changed}
    if "category_id" in changed:
        old = (await session.execute(CATEGORY, {"id": row.category_id})).one()
        new = await _live_category(session, changed["category_id"])
        before["category_name"], changed["category_name"] = old.name, new.name
    if changed.get("receipt_object_key") is not None:
        await _usable_receipt(tenant, changed["receipt_object_key"], integrations)

    columns = [f for f in changed if f != "category_name"]
    assignments = ", ".join(f"{f} = :{f}" for f in columns)
    try:
        async with session.begin_nested():
            await session.execute(
                text(f"UPDATE expense SET {assignments}, updated_at = now() WHERE id = :id"),
                {**{f: changed[f] for f in columns}, "id": expense_id},
            )
    except IntegrityError as error:
        if _constraint(error) != "expense_receipt_object_key_key":
            raise
        raise RECEIPT_TAKEN from None
    detail = {
        "expense_id": str(expense_id),
        "before": {k: _shown(v) for k, v in before.items()},
        "after": {k: _shown(v) for k, v in changed.items()},
    }
    await _audit(session, EXPENSE_CHANGED, None, detail)
    return await _read(session, expense_id)


async def _audit(
    session: AsyncSession, action: str, reason: str | None, detail: dict[str, Any]
) -> None:
    result = await session.execute(
        INSERT_AUDIT, {"action": action, "reason": reason, "detail": json.dumps(detail)}
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(f"no audit row for {action} of expense {detail['expense_id']}")


VOID = text(
    "UPDATE expense SET voided_at = now(), voided_by = current_setting('app.person_id')::uuid,"
    " void_reason = :reason WHERE id = :id"
)


@router.post("/{expense_id}/void")
async def void_expense(
    expense_id: uuid.UUID, body: ExpenseVoid, session: ExpensesSession
) -> Expense:
    """Anular: the expense stays, struck through, and counts nowhere; `expense_voided`
    keeps the reason and what it was. Voiding one twice is a 409."""
    row = (await session.execute(LOCK, {"id": expense_id})).one_or_none()
    if row is None:
        raise NO_EXPENSE
    if row.voided_at is not None:
        raise VOIDED
    await session.execute(VOID, {"id": expense_id, "reason": body.reason})
    category = (await session.execute(CATEGORY, {"id": row.category_id})).one()
    detail = {
        "expense_id": str(expense_id),
        "spent_on": str(row.spent_on),
        "amount_clp": row.amount_clp,
        "category_name": category.name,
    }
    await _audit(session, EXPENSE_VOIDED, body.reason, detail)
    return await _read(session, expense_id)


@router.get("/{expense_id}/receipt")
async def expense_receipt(
    expense_id: uuid.UUID,
    session: ExpensesReadSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> Receipt:
    """Where the browser GETs the receipt: presigned here, for `expenses_read` alone."""
    key = await session.scalar(
        text("SELECT receipt_object_key FROM expense WHERE id = :id"), {"id": expense_id}
    )
    if key is None:
        raise NO_RECEIPT
    store = integrations.blob_store
    stored = await store.stat(key)
    if stored is None:
        raise NO_RECEIPT
    return Receipt(url=store.presign_download(key), content_type=stored.content_type)


# --- categories ----------------------------------------------------------------------

# Live ones in the gym's order, then the archived; each with how many expenses it has.
CATEGORIES = text(
    """
    SELECT c.id, c.name, c.sort, c.is_other, c.archived_at IS NOT NULL AS archived,
           (SELECT count(*) FROM expense e WHERE e.category_id = c.id) AS expenses
    FROM expense_category c
    ORDER BY c.archived_at IS NOT NULL, c.sort, lower(c.name), c.id
    """
)


async def _categories(session: AsyncSession) -> list[ExpenseCategory]:
    rows = await session.execute(CATEGORIES)
    return [ExpenseCategory.model_validate(row._asdict()) for row in rows]


async def _named(session: AsyncSession, statement: str, params: dict[str, Any]) -> Any:
    """Run a category write that may take a live category's name: a 409 if it does."""
    try:
        async with session.begin_nested():
            return (await session.execute(text(statement), params)).one_or_none()
    except IntegrityError as error:
        if _constraint(error) != "expense_category_name":
            raise
        raise NAME_TAKEN from None


@router.get("/categories")
async def expense_categories(session: ExpensesReadSession) -> list[ExpenseCategory]:
    """The gym's categories: the live ones in its order, then the archived."""
    return await _categories(session)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def add_category(body: CategoryIn, session: ExpensesSession) -> list[ExpenseCategory]:
    """A new category, last of the live ones."""
    await _named(
        session,
        "INSERT INTO expense_category (gym_id, name, sort)"
        " SELECT current_setting('app.gym_id')::uuid, :name,"
        " coalesce(max(sort), 0) + 1 FROM expense_category RETURNING id",
        {"name": body.name},
    )
    return await _categories(session)


@router.patch("/categories/{category_id}")
async def rename_category(
    category_id: uuid.UUID, body: CategoryIn, session: ExpensesSession
) -> list[ExpenseCategory]:
    """Rename a category: every expense under it reads the new name."""
    if (
        await _named(
            session,
            "UPDATE expense_category SET name = :name WHERE id = :id RETURNING id",
            {"id": category_id, "name": body.name},
        )
        is None
    ):
        raise NO_CATEGORY
    return await _categories(session)


@router.post("/categories/order")
async def order_categories(body: CategoryOrder, session: ExpensesSession) -> list[ExpenseCategory]:
    """Put the live categories in this order: every one of them, once."""
    live = set(
        (
            await session.execute(
                text("SELECT id FROM expense_category WHERE archived_at IS NULL FOR UPDATE")
            )
        ).scalars()
    )
    if len(body.ids) != len(set(body.ids)) or set(body.ids) != live:
        raise unprocessable("not_every_category", "order every live category, once")
    await session.execute(
        text("UPDATE expense_category SET sort = :sort WHERE id = :id"),
        [{"id": category_id, "sort": n} for n, category_id in enumerate(body.ids, start=1)],
    )
    return await _categories(session)


@router.post("/categories/{category_id}/archive")
async def archive_category(
    category_id: uuid.UUID, session: ExpensesSession
) -> list[ExpenseCategory]:
    """Hide a category from the form, keeping it on the expenses already under it.
    Otros is kept (409): it is where anything else goes."""
    row = (
        await session.execute(
            text("SELECT is_other FROM expense_category WHERE id = :id FOR UPDATE"),
            {"id": category_id},
        )
    ).one_or_none()
    if row is None:
        raise NO_CATEGORY
    if row.is_other:
        raise OTHER_KEPT
    await session.execute(
        text(
            "UPDATE expense_category SET archived_at = now() WHERE id = :id AND archived_at IS NULL"
        ),
        {"id": category_id},
    )
    return await _categories(session)


@router.post("/categories/{category_id}/restore")
async def restore_category(
    category_id: uuid.UUID, session: ExpensesSession
) -> list[ExpenseCategory]:
    """Bring an archived category back, last of the live ones; a 409 if a live one has
    taken its name meanwhile."""
    if (
        await _named(
            session,
            "UPDATE expense_category SET archived_at = NULL,"
            " sort = (SELECT coalesce(max(sort), 0) + 1 FROM expense_category"
            "         WHERE archived_at IS NULL)"
            " WHERE id = :id RETURNING id",
            {"id": category_id},
        )
        is None
    ):
        raise NO_CATEGORY
    return await _categories(session)
