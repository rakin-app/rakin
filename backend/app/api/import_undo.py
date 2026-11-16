"""Importar's recent imports, and "Deshacer importación" (#300).

`GET /api/import/recent` lists this gym's latest imports, newest first: each
`history_imported` row (0053) with who imported, the file and the counts per tab, and
its undo when it has one. Owner and admin, who import.

`GET /api/import/{id}/undo` says what undoing it would remove, for the confirmation:
its history payments and grades, the people whose history fields go back, and how many
fields were changed since, which stay. `POST` there undoes it, with a reason, through
`undo_import` (0056): a `SECURITY DEFINER` function, as `forget_gym_person` is, since
grades are append-only to the app role. It deletes only the rows with that `import_id`,
puts back each field still holding the import's value, and records `import_undone`.
People and memberships the import created stay. The owner alone, and once: a second
undo is a 409 `undone`.
"""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text

from app.api.member_import import IMPORT_LOCK
from app.roles import AdminSession, OwnerSession
from app.schemas.member_import import (
    ImportUndone,
    RecentImport,
    UndoCounts,
    Undoing,
    UndoRefusal,
    UndoRefused,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/import", tags=["import"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "import not found")

# Enough to find the one to undo: an import is undone soon after, if at all.
RECENT_LIMIT = 20

# Whoever acted, by the name this gym has for them.
RECENT = text("""
    SELECT i.id, i.at, gi.name AS by, i.detail,
           u.at AS undone_at, gu.name AS undone_by, u.reason AS undone_reason,
           u.detail AS undone_detail
    FROM audit_event i
    LEFT JOIN gym_person gi ON gi.gym_id = i.gym_id AND gi.person_id = i.actor_id
    LEFT JOIN audit_event u ON u.gym_id = i.gym_id AND u.action = 'import_undone'
        AND u.detail ->> 'import_id' = i.id::text
    LEFT JOIN gym_person gu ON gu.gym_id = u.gym_id AND gu.person_id = u.actor_id
    WHERE i.action = 'history_imported'
    ORDER BY i.at DESC, i.id
    LIMIT :limit
""")


def _detail(value: Any) -> dict[str, Any]:
    detail: dict[str, Any] = value if isinstance(value, dict) else json.loads(value)
    return detail


@router.get("/recent")
async def recent_imports(session: AdminSession) -> list[RecentImport]:
    """This gym's latest imports, newest first, each with its undo if it has one."""
    rows = await session.execute(RECENT, {"limit": RECENT_LIMIT})
    recent = []
    for row in rows:
        detail = _detail(row.detail)
        undone = None
        if row.undone_at is not None:
            counts = _detail(row.undone_detail)
            undone = ImportUndone(
                at=row.undone_at,
                by=row.undone_by,
                reason=row.undone_reason,
                **{key: counts[key] for key in ("payments", "grades", "people", "kept")},
            )
        recent.append(
            RecentImport(
                id=row.id,
                at=row.at,
                by=row.by,
                file_name=detail.get("file_name"),
                tabs=detail.get("tabs", []),
                counts=detail.get("counts", {}),
                undone=undone,
            )
        )
    return recent


@router.get("/{import_id}/undo")
async def undo_counts(import_id: uuid.UUID, session: OwnerSession) -> UndoCounts:
    """What undoing the import would remove, and how many fields it would keep."""
    counts = await session.scalar(text("SELECT import_undo_counts(:id)"), {"id": import_id})
    if counts is None:
        raise NOT_FOUND
    return UndoCounts(**_detail(counts))


@router.post(
    "/{import_id}/undo",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_409_CONFLICT: {"model": UndoRefused}},
)
async def undo_import(
    import_id: uuid.UUID,
    body: Undoing,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: OwnerSession,
) -> Response:
    """Deshacer importación: the history the import wrote, gone, in one transaction, and
    an `import_undone` row with the reason and what it removed."""
    # Not while an import runs: one in this gym waits for the undo, and the other way round.
    await session.execute(IMPORT_LOCK, {"gym": str(tenant.gym_id)})
    code = await session.scalar(
        text("SELECT undo_import(:id, :reason)"), {"id": import_id, "reason": body.reason}
    )
    if code == "not_found":
        raise NOT_FOUND
    if code is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, UndoRefusal(code=code).model_dump())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
