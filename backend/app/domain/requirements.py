"""What the gym asks before someone trains, and where a person stands on each (#349).

A requirement is done once (a signed waiver, an induction) or lasts `valid_months`
(a medical certificate of 12 months). One done on 1 March and valid for 12 months
lasts through 1 March of the next year and is expired from the 2nd. Pure functions, no
I/O; the dates are the gym's.
"""

from datetime import date
from enum import StrEnum

from app.domain.dates import add_months

# How close to its end a requirement reads as expiring soon.
EXPIRING_DAYS = 30


class RequirementState(StrEnum):
    # Done, and still in force: "al día".
    OK = "ok"
    # In force for at most `EXPIRING_DAYS` more days: "vence pronto".
    EXPIRING = "expiring"
    # Done once, and no longer in force: "vencido".
    EXPIRED = "expired"
    # Never done: "pendiente".
    PENDING = "pending"


def expires_on(done_on: date, valid_months: int | None) -> date | None:
    """The last day a requirement done on `done_on` is in force; `None` when it is done
    once and never expires."""
    return None if valid_months is None else add_months(done_on, valid_months)


def state_of(done_on: date | None, valid_months: int | None, today: date) -> RequirementState:
    """Where someone stands on a requirement whose current record is of `done_on`."""
    if done_on is None:
        return RequirementState.PENDING
    last = expires_on(done_on, valid_months)
    if last is None:
        return RequirementState.OK
    if today > last:
        return RequirementState.EXPIRED
    if (last - today).days <= EXPIRING_DAYS:
        return RequirementState.EXPIRING
    return RequirementState.OK
