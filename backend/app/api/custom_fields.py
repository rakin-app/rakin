"""The gym's custom fields, and each person's values for them.

Definitions (`/api/custom-fields`): every staff role reads the ones it may see; owner
and admin (`AdminSession`) define, rename, reorder and archive them. Who sees a field
(`visible_to`) and whether it is `sensitive` are the owner's alone: an admin who sends
either gets a 403, so an admin can define fields but never widen who sees them.

Values (`/api/people/{id}/fields`): every staff role reads and writes the values of
the fields it may see. A field the caller may not see is answered exactly as one that
does not exist, so a coach learns neither its value nor that it is there. Archived
fields keep their values but are not shown or written. A sensitive field's value is
stored sealed (`FieldCipher`).

The definitions are a list in `gym.settings`; a change reads it `FOR UPDATE`, so two
admins editing at once take turns rather than losing each other's change.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND, in_gym
from app.domain import custom_fields as cf
from app.roles import FORBIDDEN, AdminSession, Role, StaffSession, role_in_gym
from app.schemas.custom_fields import (
    FieldCreate,
    FieldDefinition,
    FieldOrder,
    FieldUpdate,
    PersonField,
    PersonFieldsUpdate,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(tags=["custom-fields"])

FIELD_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "field not found")

CurrentTenant = Annotated[Tenant, Depends(current_tenant)]


def _cipher(request: Request) -> cf.FieldCipher:
    return cf.FieldCipher(request.app.state.settings.secret_key)


async def _role(session: AsyncSession, tenant: Tenant) -> Role:
    role = await role_in_gym(session, tenant)
    # The session dependency already refused anyone without a staff role.
    assert role is not None
    return role


async def _definitions(
    session: AsyncSession, tenant: Tenant, lock: bool = False
) -> list[dict[str, Any]]:
    sql = "SELECT settings FROM gym WHERE id = :id" + (" FOR UPDATE" if lock else "")
    settings = await session.scalar(text(sql), {"id": tenant.gym_id})
    return cf.definitions(settings or {})


async def _store(session: AsyncSession, tenant: Tenant, defs: Sequence[dict[str, Any]]) -> None:
    await session.execute(
        text(
            "UPDATE gym SET settings = jsonb_set(settings, '{custom_fields}', CAST(:defs AS jsonb))"
            " WHERE id = :id"
        ),
        {"defs": json.dumps(list(defs)), "id": tenant.gym_id},
    )


def _answer(defs: Sequence[dict[str, Any]], role: Role) -> list[FieldDefinition]:
    return [FieldDefinition.model_validate(d) for d in cf.visible(role, defs)]


def _only_the_owner(role: Role, sent: set[str]) -> None:
    if role is not Role.OWNER and sent & {"sensitive", "visible_to"}:
        raise FORBIDDEN


@router.get("/api/custom-fields")
async def list_fields(tenant: CurrentTenant, session: StaffSession) -> list[FieldDefinition]:
    """The fields the caller sees, in order, archived ones included."""
    return _answer(await _definitions(session, tenant), await _role(session, tenant))


@router.post("/api/custom-fields", status_code=status.HTTP_201_CREATED)
async def create_field(
    body: FieldCreate, tenant: CurrentTenant, session: AdminSession
) -> FieldDefinition:
    role = await _role(session, tenant)
    _only_the_owner(role, body.model_fields_set)
    defs = await _definitions(session, tenant, lock=True)
    # Keys of fields the caller cannot see count too, but are never named back.
    definition = cf.normalize(
        {
            "key": cf.key_for(body.label, (d["key"] for d in defs)),
            "label": body.label,
            "type": body.type,
            "options": body.options,
            "sensitive": body.sensitive,
            "visible_to": body.visible_to,
        }
    )
    await _store(session, tenant, [*defs, definition])
    return FieldDefinition.model_validate(definition)


@router.put("/api/custom-fields/order")
async def reorder_fields(
    body: FieldOrder, tenant: CurrentTenant, session: AdminSession
) -> list[FieldDefinition]:
    role = await _role(session, tenant)
    defs = await _definitions(session, tenant, lock=True)
    try:
        defs = cf.reorder(defs, body.keys, role)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    await _store(session, tenant, defs)
    return _answer(defs, role)


@router.patch("/api/custom-fields/{key}")
async def update_field(
    key: str,
    body: FieldUpdate,
    request: Request,
    tenant: CurrentTenant,
    session: AdminSession,
) -> FieldDefinition:
    role = await _role(session, tenant)
    defs = await _definitions(session, tenant, lock=True)
    found = next((d for d in defs if d["key"] == key and cf.sees(role, d)), None)
    if found is None:
        raise FIELD_NOT_FOUND
    changes = body.model_dump(exclude_unset=True)
    _only_the_owner(role, set(changes))
    if "options" in changes and found["type"] is not cf.FieldType.ENUM:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "options are for enum fields")
    if changes.get("sensitive") and not found["sensitive"] and "visible_to" not in changes:
        changes["visible_to"] = cf.VisibleTo.OWNER
    updated = cf.normalize({**found, **changes})
    if updated["sensitive"] != found["sensitive"]:
        await _reseal(session, tenant, _cipher(request), key, sealed=updated["sensitive"])
    await _store(session, tenant, [updated if d is found else d for d in defs])
    return FieldDefinition.model_validate(updated)


async def _reseal(
    session: AsyncSession, tenant: Tenant, cipher: cf.FieldCipher, key: str, sealed: bool
) -> None:
    """Move the field's stored values to `secret` (sealed) or back to `value`."""
    rows = await session.execute(
        text("SELECT person_id, value, secret FROM person_field_value WHERE field_key = :key"),
        {"key": key},
    )
    for row in rows.all():
        if sealed:
            value, secret = None, cipher.seal(tenant.gym_id, row.person_id, key, row.value)
        else:
            plain = cipher.open(tenant.gym_id, row.person_id, key, row.secret)
            value, secret = json.dumps(plain), None
        await session.execute(
            text(
                "UPDATE person_field_value SET value = CAST(:value AS jsonb), secret = :secret"
                " WHERE person_id = :person AND field_key = :key"
            ),
            {"value": value, "secret": secret, "person": row.person_id, "key": key},
        )


# --- a person's values ------------------------------------------------------------


async def _person_fields(
    session: AsyncSession, tenant: Tenant, cipher: cf.FieldCipher, person_id: uuid.UUID
) -> list[PersonField]:
    role = await _role(session, tenant)
    shown = [d for d in cf.visible(role, await _definitions(session, tenant)) if not d["archived"]]
    rows = await session.execute(
        text(
            "SELECT field_key, value, secret FROM person_field_value"
            " WHERE person_id = :id AND field_key = ANY(CAST(:keys AS text[]))"
        ),
        {"id": person_id, "keys": [d["key"] for d in shown]},
    )
    values = {
        r.field_key: r.value
        if r.secret is None
        else cipher.open(tenant.gym_id, person_id, r.field_key, r.secret)
        for r in rows
    }
    return [PersonField.model_validate({**d, "value": values.get(d["key"])}) for d in shown]


@router.get("/api/people/{person_id}/fields")
async def get_person_fields(
    person_id: uuid.UUID, request: Request, tenant: CurrentTenant, session: StaffSession
) -> list[PersonField]:
    """The person's values for the fields the caller sees, in the gym's order."""
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    return await _person_fields(session, tenant, _cipher(request), person_id)


@router.patch("/api/people/{person_id}/fields")
async def update_person_fields(
    person_id: uuid.UUID,
    body: PersonFieldsUpdate,
    request: Request,
    tenant: CurrentTenant,
    session: StaffSession,
) -> list[PersonField]:
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    role = await _role(session, tenant)
    writable = {
        d["key"]: d
        for d in cf.visible(role, await _definitions(session, tenant))
        if not d["archived"]
    }
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    for key, raw in body.values.items():
        definition = writable.get(key)
        if definition is None:
            errors[key] = "unknown field"
            continue
        try:
            values[key] = cf.validate_value(definition, raw)
        except cf.InvalidValue as e:
            errors[key] = str(e)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"fields": errors})

    cipher = _cipher(request)
    for key, value in values.items():
        if value is None:
            await session.execute(
                text(
                    "DELETE FROM person_field_value WHERE person_id = :person AND field_key = :key"
                ),
                {"person": person_id, "key": key},
            )
            continue
        sealed = writable[key]["sensitive"]
        await session.execute(
            text(
                "INSERT INTO person_field_value (gym_id, person_id, field_key, value, secret)"
                " VALUES (:gym, :person, :key, CAST(:value AS jsonb), :secret)"
                " ON CONFLICT (gym_id, person_id, field_key) DO UPDATE"
                " SET value = excluded.value, secret = excluded.secret, updated_at = now()"
            ),
            {
                "gym": tenant.gym_id,
                "person": person_id,
                "key": key,
                "value": None if sealed else json.dumps(value),
                "secret": cipher.seal(tenant.gym_id, person_id, key, value) if sealed else None,
            },
        )
    return await _person_fields(session, tenant, cipher, person_id)
