"""Mis datos (#371): everything the gym holds on the signed-in person, on `/me/datos`,
and the same as a JSON file to download.

The law gives every member a right of access (art. 5, Ley 19.628 as amended by Ley
21.719) and, where the processing rests on consent, of portability (art. 9):
docs/legal-research.md. `GET /api/me/data` answers both: the person signed in, and for
a guardian each dependent, with every row the gym holds on them. `?download=1` sends
the same document as an attachment.

It runs in the person's own session (`TenantSession`), so RLS keeps it to this gym, and
every query names the people it reads: the person acting and their dependents, never
anyone else. `history_payment_own` (0098) lets a member read their history payments;
every other table here a member could already read.

`EXPORTED` names every table that holds a person's rows by a `person_id` (or a column
ending in it, as `guardian_link`'s), and `NOT_EXPORTED` the few that are not data about
them; `tests/test_my_data.py` fails when such a table is in neither, so a new one is a
decision, not a gap.

The notes and reasons the staff write about the person are theirs too, so they are in:
a ledger entry's note, a history payment's, a requirement record's (opened when it is
sealed), a promotion's, and the reasons a plan was cancelled, voided or discounted, a
freeze request answered and the person left. Out: who wrote or recorded each row, which
is the staff member's own data; a coach's notes on a class as a whole, which are about
no one person; and a failed message's error, which is the provider's and the server's
(its status says it failed). Asking to fix a datum is not built here: the page names the
gym's privacy email.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.custom_fields import field_cipher
from app.api.extra_lines import line_title_sql
from app.api.grades import readable_scheme
from app.api.requirements import bound_to
from app.domain import custom_fields as cf
from app.domain.dates import gym_today
from app.schemas.grades import Rank
from app.schemas.gym import Privacy
from app.schemas.my_data import (
    MyConsentEvent,
    MyData,
    MyDataGym,
    MyEntry,
    MyExtraCharge,
    MyField,
    MyFreeze,
    MyFreezeRequest,
    MyGrade,
    MyHistoryPayment,
    MyMembership,
    MyMessage,
    MyPeriod,
    MyPlanEvent,
    MyRecord,
    MyRequirement,
    MyStaff,
    MyTitle,
    MyVisit,
    PersonData,
    Someone,
)
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(prefix="/api/me", tags=["me"])

# Every table with a `person_id` column, or one ending in it, and the part of
# `PersonData` that holds its rows.
EXPORTED: Mapping[str, str] = {
    "gym_person": "record",
    "guardian_link": "guardians, dependents",
    "person_field_value": "fields",
    "membership": "memberships",
    "charge_group_member": "charge_groups",
    "extra_line": "extra_charges",
    "history_payment": "history_payments",
    "grade_event": "grades",
    "person_requirement": "requirements",
    "consent_event": "consents",
    "message_log": "messages",
    "mail_unsubscribe": "unsubscribed_at",
    "staff": "staff",
    "staff_title": "staff",
}

# The tables with a `person_id` that hold no data about the person, and why.
NOT_EXPORTED: Mapping[str, str] = {
    "auth_link": "a sign-in link's hash, valid for minutes: a credential, not data about them",
    "auth_session": "a signed-in session's hash: a credential, not data about them",
    "idempotency_key": "a request's answer kept a day so a retry is not run twice",
    "audit_event": "the staff's record of what they changed, read only with money_read",
    "terms_acceptance": "the gym's acceptance of Rakin's terms, which the titular signs for it",
    "person_anonymisation": "empty but while an anonymisation runs (#372), which deletes its row",
}

# Whose data the page shows: the person acting, then each dependent, by name.
PEOPLE = text("""
    SELECT gp.person_id FROM gym_person gp WHERE gp.person_id = :me
    UNION ALL
    (SELECT gp.person_id FROM guardian_link gl
     JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
     WHERE gl.guardian_person_id = :me AND gl.dependent_person_id <> :me
     ORDER BY lower(gp.name), gp.person_id)
""")

RECORDS = """
    SELECT person_id, name, rut, email, phone, dob, no_whatsapp, member_since,
           prior_classes, left_on, left_reason, created_at AS added_at, updated_at
    FROM gym_person WHERE person_id = ANY(:people)
"""

GUARDIANS = """
    SELECT gl.dependent_person_id AS person_id, gp.person_id AS other_id, gp.name
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.guardian_person_id
    WHERE gl.dependent_person_id = ANY(:people)
    ORDER BY lower(gp.name), gp.person_id
"""

DEPENDENTS = """
    SELECT gl.guardian_person_id AS person_id, gp.person_id AS other_id, gp.name
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
    WHERE gl.guardian_person_id = ANY(:people)
    ORDER BY lower(gp.name), gp.person_id
"""

FIELDS = """
    SELECT person_id, field_key, value, secret FROM person_field_value
    WHERE person_id = ANY(:people)
"""

MEMBERSHIPS = """
    SELECT m.person_id, m.id, pl.name AS plan_name, m.status, m.started_at,
           m.current_period_end, m.credits_remaining, m.discount_pct, m.discount_reason,
           np.name AS next_plan_name, m.next_plan_from, m.cancelled_at, m.cancel_reason,
           m.cancel_undone_at, m.reactivated_at, m.voided_at, m.void_reason, m.created_at
    FROM membership m
    JOIN plan pl ON pl.id = m.plan_id
    LEFT JOIN plan np ON np.id = m.next_plan_id
    WHERE m.person_id = ANY(:people)
    ORDER BY m.started_at, m.id
"""

PLAN_EVENTS = """
    SELECT m.person_id, e.membership_id, e.kind, e.occurred_on
    FROM plan_event e JOIN membership m ON m.id = e.membership_id
    WHERE m.person_id = ANY(:people)
    ORDER BY e.occurred_on, e.created_at, e.id
"""

FREEZES = """
    SELECT m.person_id, f.membership_id, f.from_date, f.to_date, f.reason, f.created_at
    FROM membership_freeze f JOIN membership m ON m.id = f.membership_id
    WHERE m.person_id = ANY(:people)
    ORDER BY f.from_date, f.id
"""

FREEZE_REQUESTS = """
    SELECT m.person_id, r.membership_id, r.from_date, r.to_date, r.reason, r.note, r.status,
           r.decision_note, r.decided_at, r.created_at
    FROM freeze_request r JOIN membership m ON m.id = r.membership_id
    WHERE m.person_id = ANY(:people)
    ORDER BY r.created_at, r.id
"""

PERIODS = """
    SELECT m.person_id, bp.id, bp.membership_id, pl.name AS plan_name, bp.period_start,
           bp.period_end, bp.due_date, bp.amount_due_clp, bp.discount_pct, bp.discount_reason
    FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    WHERE m.person_id = ANY(:people)
    ORDER BY bp.period_start, bp.id
"""

EXTRA_CHARGES = f"""
    SELECT l.person_id, l.id, {line_title_sql("x", "l")} AS title, l.amount_due_clp,
           coalesce(l.due_date, x.due_date) AS due_date, l.cancelled_at, l.cancel_reason,
           l.created_at
    FROM extra_line l JOIN extra_charge x ON x.id = l.extra_charge_id
    WHERE l.person_id = ANY(:people)
    ORDER BY l.created_at, l.id
"""

# A plan's entries by its membership, a cobro extra's by its line.
ENTRIES = """
    SELECT coalesce(m.person_id, l.person_id) AS person_id, e.id, e.kind, e.status,
           e.amount_clp, e.method, e.billing_period_id, e.extra_line_id, e.purpose,
           e.proof_object_key IS NOT NULL AS has_proof, e.note,
           e.claimed_at, e.validated_at, e.created_at
    FROM ledger_entry e
    LEFT JOIN membership m ON m.id = e.membership_id
    LEFT JOIN extra_line l ON l.id = e.extra_line_id
    WHERE coalesce(m.person_id, l.person_id) = ANY(:people)
    ORDER BY e.created_at, e.id
"""

HISTORY_PAYMENTS = """
    SELECT person_id, id, paid_on, amount_clp, method, covers_month, plan_name, note,
           source, created_at
    FROM history_payment WHERE person_id = ANY(:people)
    ORDER BY paid_on, id
"""

# No `notes`: a coach's notes on the class as a whole, about no one person.
ATTENDANCE = """
    SELECT m.person_id, s.id AS session_id, s.starts_at, c.name AS class_type_name,
           p.name AS program_name, a.credits_consumed, a.marked_at
    FROM attendance a
    JOIN membership m ON m.id = a.membership_id
    JOIN session s ON s.id = a.session_id
    JOIN class_type c ON c.id = s.class_type_id
    JOIN program p ON p.id = c.program_id
    WHERE m.person_id = ANY(:people)
    ORDER BY s.starts_at, s.id
"""

GRADES = """
    SELECT g.person_id, g.id, g.rank_key, g.sub_rank, g.awarded_on, g.note
    FROM grade_event g WHERE g.person_id = ANY(:people)
    ORDER BY g.awarded_on, g.created_at, g.id
"""

REQUIREMENTS = """
    SELECT pr.person_id, pr.id, r.name AS requirement_name, pr.done_on, pr.recorded_at,
           pr.note, pr.note_secret
    FROM person_requirement pr JOIN requirement r ON r.id = pr.requirement_id
    WHERE pr.person_id = ANY(:people)
    ORDER BY pr.recorded_at, pr.id
"""

CONSENTS = """
    SELECT c.person_id, c.id, c.action, c.source, b.name AS by_name, c.template_on,
           c.details_on, c.at
    FROM consent_event c
    LEFT JOIN gym_person b ON b.gym_id = c.gym_id AND b.person_id = c.by_person_id
    WHERE c.person_id = ANY(:people)
    ORDER BY c.at, c.id
"""

MESSAGES = """
    SELECT person_id, id, channel, template, to_address, status, payload, sent_at
    FROM message_log WHERE person_id = ANY(:people)
    ORDER BY sent_at, id
"""

CHARGE_GROUPS = """
    SELECT m.person_id, g.name FROM charge_group_member m
    JOIN charge_group g ON g.id = m.group_id
    WHERE m.person_id = ANY(:people)
    ORDER BY lower(g.name), g.id
"""

UNSUBSCRIBED = """
    SELECT person_id, created_at FROM mail_unsubscribe WHERE person_id = ANY(:people)
"""

STAFF = """
    SELECT person_id, role, account_holder, created_at AS added_at FROM staff
    WHERE person_id = ANY(:people)
"""

TITLES = """
    SELECT person_id, title_name, starts_on, ends_on, public_contact FROM staff_title
    WHERE person_id = ANY(:people)
    ORDER BY starts_on, id
"""


def _by_person(rows: Iterable[Any]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Each row as a dict without its `person_id`, under that person."""
    grouped: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = dict(row._mapping)
        grouped[values.pop("person_id")].append(values)
    return grouped


async def _read(
    session: AsyncSession, sql: str, people: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    return _by_person(await session.execute(text(sql), {"people": list(people)}))


def _fields(
    gym_id: uuid.UUID,
    person_id: uuid.UUID,
    rows: Sequence[Mapping[str, Any]],
    defs: Sequence[Mapping[str, Any]],
    cipher: cf.FieldCipher,
) -> list[MyField]:
    """Every value the gym holds for them, in the gym's order, sensitive ones opened.
    A value whose field is no longer defined keeps its key as its label."""
    by_key = {d["key"]: d for d in defs}
    order = {d["key"]: i for i, d in enumerate(defs)}
    out = []
    for row in sorted(rows, key=lambda r: (order.get(r["field_key"], len(order)), r["field_key"])):
        key = row["field_key"]
        found = by_key.get(key)
        value = (
            row["value"]
            if row["secret"] is None
            else cipher.open(gym_id, person_id, key, row["secret"])
        )
        out.append(
            MyField(
                key=key,
                label=found["label"] if found else key,
                value=value,
                sensitive=row["secret"] is not None or bool(found and found["sensitive"]),
                archived=found is None or bool(found["archived"]),
            )
        )
    return out


async def my_data(session: AsyncSession, tenant: Tenant, cipher: cf.FieldCipher) -> MyData:
    gym = (
        await session.execute(
            text("SELECT name, timezone, settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
        )
    ).one()
    settings = gym.settings or {}
    # As stored (`StoredPrivacy`), less the day it was saved.
    stored = settings.get("privacy")
    privacy = (
        Privacy.model_validate({k: stored[k] for k in Privacy.model_fields if k in stored})
        if stored
        else None
    )
    people = list(await session.scalars(PEOPLE, {"me": tenant.person_id}))

    read = {
        name: await _read(session, sql, people)
        for name, sql in {
            "records": RECORDS,
            "guardians": GUARDIANS,
            "dependents": DEPENDENTS,
            "fields": FIELDS,
            "memberships": MEMBERSHIPS,
            "plan_events": PLAN_EVENTS,
            "freezes": FREEZES,
            "freeze_requests": FREEZE_REQUESTS,
            "periods": PERIODS,
            "extra_charges": EXTRA_CHARGES,
            "entries": ENTRIES,
            "history_payments": HISTORY_PAYMENTS,
            "attendance": ATTENDANCE,
            "grades": GRADES,
            "requirements": REQUIREMENTS,
            "consents": CONSENTS,
            "messages": MESSAGES,
            "charge_groups": CHARGE_GROUPS,
            "unsubscribed": UNSUBSCRIBED,
            "staff": STAFF,
            "titles": TITLES,
        }.items()
    }
    defs = cf.definitions(settings)
    scheme = readable_scheme(settings)

    def someone(rows: list[dict[str, Any]]) -> list[Someone]:
        return [Someone(person_id=r["other_id"], name=r["name"]) for r in rows]

    out = []
    for person in people:

        def rows(name: str, person: uuid.UUID = person) -> list[dict[str, Any]]:
            return read[name].get(person, [])

        # `PEOPLE` reads the same table in the same transaction, so this holds; a 404
        # rather than a 500 should it ever not.
        records = rows("records")
        if len(records) != 1:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
        [record] = records
        staff = rows("staff")
        unsubscribed = rows("unsubscribed")
        out.append(
            PersonData(
                person_id=person,
                record=MyRecord.model_validate(record),
                guardians=someone(rows("guardians")),
                dependents=someone(rows("dependents")),
                fields=_fields(tenant.gym_id, person, rows("fields"), defs, cipher),
                memberships=[MyMembership.model_validate(r) for r in rows("memberships")],
                plan_events=[MyPlanEvent.model_validate(r) for r in rows("plan_events")],
                freezes=[MyFreeze.model_validate(r) for r in rows("freezes")],
                freeze_requests=[
                    MyFreezeRequest.model_validate(r) for r in rows("freeze_requests")
                ],
                periods=[MyPeriod.model_validate(r) for r in rows("periods")],
                extra_charges=[MyExtraCharge.model_validate(r) for r in rows("extra_charges")],
                entries=[MyEntry.model_validate(r) for r in rows("entries")],
                history_payments=[
                    MyHistoryPayment.model_validate(r) for r in rows("history_payments")
                ],
                attendance=[MyVisit.model_validate(r) for r in rows("attendance")],
                grades=[
                    MyGrade(
                        id=r["id"],
                        note=r["note"],
                        **Rank.labelled(
                            scheme, r["rank_key"], r["sub_rank"], r["awarded_on"]
                        ).model_dump(),
                    )
                    for r in rows("grades")
                ],
                requirements=[
                    MyRequirement(
                        id=r["id"],
                        requirement_name=r["requirement_name"],
                        done_on=r["done_on"],
                        recorded_at=r["recorded_at"],
                        note=r["note"]
                        if r["note_secret"] is None
                        else cipher.open(
                            tenant.gym_id, person, bound_to(r["id"]), r["note_secret"]
                        ),
                    )
                    for r in rows("requirements")
                ],
                consents=[MyConsentEvent.model_validate(r) for r in rows("consents")],
                messages=[MyMessage.model_validate(r) for r in rows("messages")],
                charge_groups=[r["name"] for r in rows("charge_groups")],
                unsubscribed_at=unsubscribed[0]["created_at"] if unsubscribed else None,
                staff=MyStaff(
                    **staff[0], titles=[MyTitle.model_validate(r) for r in rows("titles")]
                )
                if staff
                else None,
            )
        )
    return MyData(
        exported_at=datetime.now(UTC),
        gym=MyDataGym(name=gym.name, timezone=gym.timezone, privacy=privacy),
        people=out,
    )


@router.get("/data", response_model=MyData)
async def get_my_data(
    request: Request,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
    download: bool = False,
) -> MyData | Response:
    """Everything the gym holds on the signed-in person and their dependents: "Mis
    datos". With `download`, the same as a JSON file, `mis-datos-<gym>-<day>.json`."""
    data = await my_data(session, tenant, field_cipher(request))
    if not download:
        return data
    gym = (
        await session.execute(
            text("SELECT slug, timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
        )
    ).one()
    day = gym_today(str(gym.timezone)).isoformat()
    body = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mis-datos-{gym.slug}-{day}.json"'},
    )
