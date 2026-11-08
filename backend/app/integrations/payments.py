"""Online payment initiation (v2: Khipu and the like).

With no rail configured, students pay by bank transfer and upload a proof, so
`NoPaymentRail` offers no link and the student page shows the gym's bank details.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentRequest:
    reference: str  # our id for what is being paid, e.g. the billing period
    amount_clp: int
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_clp, int) or isinstance(self.amount_clp, bool):
            raise TypeError("amount_clp is an integer number of pesos")
        if self.amount_clp <= 0:
            raise ValueError("amount_clp must be positive")
        if not self.reference:
            raise ValueError("reference is empty")


@dataclass(frozen=True)
class PaymentLink:
    url: str  # where the payer completes the payment
    external_id: str  # the rail's id, matched when it reports the payment


class PaymentRail(Protocol):
    async def create_payment(self, request: PaymentRequest) -> PaymentLink | None:
        """A link to pay `request` online, or None when this rail offers none."""
        ...


class NoPaymentRail:
    async def create_payment(self, request: PaymentRequest) -> PaymentLink | None:
        return None
