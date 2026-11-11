"""Cobros extra: one-off charges beside the membership's billing periods (#195).

A cobro charges each person it targets one line. In `fixed` mode every line owes the
cobro's amount; in `split` mode the amount is a total divided among the lines in whole
pesos, the remainder a peso more for each of the first people alphabetically, so the
lines always add up to the total (`split`). An admin may then override any person's
amount (a scholarship, someone who pays less), which a later re-split keeps.

A line settles as a billing period does (`app.domain.billing`): validated payments and
adjustments less refunds. Its status is what the screens show (`line_status`): a line
at nothing is exento, not pagado. Nothing
here touches a membership: an unpaid line never lapses a plan.
"""

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    RIFA = "rifa"
    SEMINARIO = "seminario"
    EQUIPAMIENTO = "equipamiento"
    GASTO_COMPARTIDO = "gasto_compartido"
    OTRO = "otro"


class AmountMode(StrEnum):
    # The amount, from each person.
    FIXED = "fixed"
    # The amount in all, divided among them.
    SPLIT = "split"


class TargetKind(StrEnum):
    # Everyone with an active membership.
    ACTIVE = "active"
    PROGRAM = "program"
    GROUP = "group"
    # Hand-picked.
    PEOPLE = "people"


class LineStatus(StrEnum):
    # Pendiente: something is owed and no proof waits.
    OPEN = "open"
    # Comprobante enviado: a proof waits for review.
    IN_REVIEW = "in_review"
    # Pagado.
    PAID = "paid"
    # Exento: let off it at nothing, a scholarship. Owes nothing, paid nothing, and is
    # not counted among who paid.
    WAIVED = "waived"
    # Anulado.
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    name: str


def alphabetical_key(person: Person) -> tuple[str, str]:
    """How a remainder is handed out: by name, ignoring case and accents, then by id."""
    folded = unicodedata.normalize("NFKD", person.name).encode("ascii", "ignore").decode()
    return folded.casefold().strip(), str(person.id)


def split(total_clp: int, people: Sequence[Person]) -> dict[uuid.UUID, int]:
    """`total_clp` divided among `people` in whole pesos: each the same, and the
    remainder a peso more for each of the first of them alphabetically."""
    if not people:
        raise ValueError("a split needs someone to divide it among")
    if total_clp < len(people):
        raise ValueError("a split leaves everyone at least a peso")
    share, remainder = divmod(total_clp, len(people))
    ordered = sorted(people, key=alphabetical_key)
    return {p.id: share + (1 if i < remainder else 0) for i, p in enumerate(ordered)}


def amounts(
    mode: AmountMode,
    amount_clp: int,
    people: Sequence[Person],
    overrides: Mapping[uuid.UUID, int] | None = None,
) -> dict[uuid.UUID, int]:
    """What each of `people` owes: the cobro's amount, or their share of it, unless an
    override says otherwise."""
    base = (
        split(amount_clp, people)
        if mode is AmountMode.SPLIT
        else {p.id: amount_clp for p in people}
    )
    for person_id, amount in (overrides or {}).items():
        if person_id not in base:
            raise ValueError(f"an override for someone the cobro does not charge: {person_id}")
        if amount < 0:
            raise ValueError("an override is not below zero")
        base[person_id] = amount
    return base


def settled_paid(paid_clp: int, amount_due_clp: int) -> int:
    """What a line shows as paid: no more than it owes."""
    return max(min(paid_clp, amount_due_clp), 0)


def line_status(
    *, amount_due_clp: int, paid_clp: int, pending_clp: int, cancelled: bool
) -> LineStatus:
    """The line as the screens show it."""
    if cancelled:
        return LineStatus.CANCELLED
    if amount_due_clp == 0:
        return LineStatus.WAIVED
    if paid_clp >= amount_due_clp:
        return LineStatus.PAID
    if pending_clp > 0:
        return LineStatus.IN_REVIEW
    return LineStatus.OPEN
