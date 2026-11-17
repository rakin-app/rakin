"""Matrícula: a plan's enrolment fee, charged once as a membership on it starts (#355).

A plan may carry an enrolment fee (`plan.enrolment_fee_clp`). Starting a membership on
it, by hand (Asignar plan, Nuevo alumno), from the join link or, when the import is
asked to, by import, writes a cobro extra of category `matricula` for it: one line, the
fee, for the person, due on the day the plan starts. "Ya pagó matrícula" on Asignar plan
starts it without one. Reactivating a person or a lapsed plan, and a plan change, start
no new membership and charge none.

From then on it is a cobro extra like any other (`app.api.extra_charges`): paid by a
proof or at the desk, reminded with "Recordar a los pendientes", cancelled by "Anular".
It is one line in one instalment: a fee charged once is paid at once, not in cuotas.
The cobro names its membership (`extra_charge.membership_id`, migration 0072), which
holds it to one per membership. Voiding the membership, a plan started by mistake,
cancels its matrícula too while nothing has been paid on it; one with money on it stays,
for the gym to refund from the cobro.
"""

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entries import CURRENT_PERSON
from app.api.extra_charges import INSERT_LINES, line_row
from app.api.extra_lines import locked_line
from app.domain.extra_charges import AmountMode, Category, TargetKind

TITLE = "Matrícula"

FEE = text(
    "SELECT pl.enrolment_fee_clp, pl.name AS plan_name, m.person_id, gp.name AS person_name"
    " FROM membership m JOIN plan pl ON pl.id = m.plan_id"
    " JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id"
    " WHERE m.id = :id"
)

INSERT_MATRICULA = text(
    f"""
    INSERT INTO extra_charge (gym_id, title, description, category, due_date, amount_mode,
                              amount_clp, target_kind, target_label, membership_id, created_by)
    VALUES (current_setting('app.gym_id')::uuid, :title, :description, :category, :due_date,
            :amount_mode, :amount_clp, :target_kind, :target_label, :membership_id,
            {CURRENT_PERSON})
    ON CONFLICT (membership_id) DO NOTHING
    RETURNING id
    """
)


async def charge_enrolment(
    session: AsyncSession, membership_id: uuid.UUID, due_on: date
) -> uuid.UUID | None:
    """The matrícula of `membership_id`, just started, due `due_on`, when its plan has a
    fee: the cobro's id, or `None` for a plan with none or a membership charged it
    already."""
    row = (await session.execute(FEE, {"id": membership_id})).one()
    if row.enrolment_fee_clp is None:
        return None
    charge_id: uuid.UUID | None = await session.scalar(
        INSERT_MATRICULA,
        {
            # Whose it is, so the cobros list tells one matrícula from the next.
            "title": f"{TITLE} · {row.person_name}",
            "description": row.plan_name,
            "category": Category.MATRICULA.value,
            "due_date": due_on,
            "amount_mode": AmountMode.FIXED.value,
            "amount_clp": row.enrolment_fee_clp,
            "target_kind": TargetKind.PEOPLE.value,
            "target_label": row.plan_name,
            "membership_id": membership_id,
        },
    )
    if charge_id is None:
        return None
    await session.execute(
        INSERT_LINES,
        {
            "charge": charge_id,
            "people": [row.person_id],
            # One instalment: a matrícula is paid at once, never in cuotas (#356).
            "instalments": [1],
            "due_dates": [due_on],
            "amounts": [row.enrolment_fee_clp],
            "overridden": [False],
        },
    )
    return charge_id


MATRICULA_LINE = text(
    "SELECT x.id AS charge_id, l.id AS line_id FROM extra_charge x"
    " JOIN extra_line l ON l.extra_charge_id = x.id"
    " WHERE x.membership_id = :id AND l.cancelled_at IS NULL"
)


async def cancel_enrolment(session: AsyncSession, membership_id: uuid.UUID, reason: str) -> bool:
    """Cancel the matrícula of `membership_id`, being voided, for `reason`, while no
    money is on it: whether it was. Under the cobro's lock, as "Anular" takes it."""
    found = (await session.execute(MATRICULA_LINE, {"id": membership_id})).one_or_none()
    if found is None:
        return False
    await locked_line(session, found.charge_id, found.line_id)
    row = await line_row(session, found.charge_id, found.line_id)
    if row.cancelled_at is not None or row.pending or row.kept:
        return False
    await session.execute(
        text(
            "UPDATE extra_line SET cancelled_at = now(),"
            f" cancelled_by = {CURRENT_PERSON}, cancel_reason = :reason WHERE id = :id"
        ),
        {"id": found.line_id, "reason": reason},
    )
    return True
