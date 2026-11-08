"""Incoming transactions on the gym's bank account (v2: Fintoc / Khipu).

The reconciliation matcher compares them with pending proofs. With no feed configured,
`NoBankFeed` reports nothing and every payment is validated by an admin's tap.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class BankTransaction:
    ref: str  # the bank's id, unique per account; stored as `ledger_entry.bank_tx_ref`
    amount_clp: int  # positive for money in
    posted_at: datetime
    description: str
    counterparty_rut: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount_clp, int) or isinstance(self.amount_clp, bool):
            raise TypeError("amount_clp is an integer number of pesos")
        if not self.ref:
            raise ValueError("ref is empty")
        _require_aware("posted_at", self.posted_at)


class BankFeed(Protocol):
    async def transactions(self, since: datetime) -> list[BankTransaction]:
        """Transactions posted at or after `since` (timezone-aware), oldest first."""
        ...


class NoBankFeed:
    async def transactions(self, since: datetime) -> list[BankTransaction]:
        _require_aware("since", since)
        return []
