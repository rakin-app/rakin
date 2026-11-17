"""Cobros extra: one-off charges beside the membership's billing periods (#195).

A cobro charges each person it targets one line. In `fixed` mode every line owes the
cobro's amount; in `split` mode the amount is a total divided among the lines in whole
pesos, the remainder a peso more for each of the first people alphabetically, so the
lines always add up to the total (`split`). An admin may then override any person's
amount (a scholarship, someone who pays less), which a later re-split keeps.

A cobro may be paid in instalments (#356): each person's amount is then divided into
N lines, evenly in whole pesos with the remainder on the first (`instalments`), due
monthly from the cobro's due date (`instalment_dates`).

A line settles as a billing period does (`app.domain.billing`): validated payments and
adjustments less refunds. Its status is what the screens show (`line_status`): a line
at nothing is exento, not pagado. Nothing
here touches a membership: an unpaid line never lapses a plan.
"""

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.dates import add_months

# A cobro is paid at once, or in 2 to this many instalments.
MAX_INSTALMENTS = 12


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


def instalments(amount_clp: int, count: int) -> list[int]:
    """`amount_clp` in `count` instalments of whole pesos: each the same, and the
    remainder on the first. Nothing stays nothing in each; anything else leaves every
    instalment at least a peso."""
    if not 1 <= count <= MAX_INSTALMENTS:
        raise ValueError(f"a cobro is paid in 1 to {MAX_INSTALMENTS} instalments")
    if 0 < amount_clp < count:
        raise ValueError("each instalment is at least a peso")
    share, remainder = divmod(amount_clp, count)
    return [share + remainder] + [share] * (count - 1)


def instalment_dates(first: date, count: int) -> list[date]:
    """When each of `count` instalments is due: `first`, then monthly after it, on the
    same day of the month or the last of a shorter one."""
    return [add_months(first, i) for i in range(count)]


def line_title(title: str, instalment: int, count: int) -> str:
    """What a line is called: its cobro's title and, in instalments, which of them,
    "Viaje a la regata · cuota 2 de 3". `app.api.extra_lines.line_title_sql` says it in
    SQL."""
    return title if count == 1 else f"{title} · cuota {instalment} de {count}"


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
