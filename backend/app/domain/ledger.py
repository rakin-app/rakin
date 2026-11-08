"""Ledger-entry state machine: pending → validated | rejected.

Entries are append-only. Validated and rejected are terminal; a correction is a
new entry, never an edit of an old one.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from app.domain.errors import InvalidTransition


class EntryKind(StrEnum):
    CHARGE = "charge"
    PAYMENT = "payment"
    ADJUSTMENT = "adjustment"
    REFUND = "refund"


class EntryStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"


TRANSITIONS: dict[EntryStatus, frozenset[EntryStatus]] = {
    EntryStatus.PENDING: frozenset({EntryStatus.VALIDATED, EntryStatus.REJECTED}),
    EntryStatus.VALIDATED: frozenset(),
    EntryStatus.REJECTED: frozenset(),
}


@dataclass(frozen=True)
class LedgerEntry:
    kind: EntryKind
    amount_clp: int
    status: EntryStatus = EntryStatus.PENDING
    note: str | None = None

    def __post_init__(self) -> None:
        if self.amount_clp <= 0:
            raise ValueError("amount_clp must be positive; the kind says which way it goes")


def _move(entry: LedgerEntry, to: EntryStatus) -> None:
    if to not in TRANSITIONS[entry.status]:
        raise InvalidTransition(f"ledger entry: {entry.status} → {to}")


def validate(entry: LedgerEntry) -> LedgerEntry:
    """An admin taps validate (v2: a bank match)."""
    _move(entry, EntryStatus.VALIDATED)
    return replace(entry, status=EntryStatus.VALIDATED)


def reject(entry: LedgerEntry, note: str) -> LedgerEntry:
    """An admin rejects a proof; the note is what the student is told."""
    if not note.strip():
        raise ValueError("a rejection needs a note for the student")
    _move(entry, EntryStatus.REJECTED)
    return replace(entry, status=EntryStatus.REJECTED, note=note)
