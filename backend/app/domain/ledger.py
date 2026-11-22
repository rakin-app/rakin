"""Ledger-entry state machine: pending → validated | rejected.

Entries are append-only. Validated and rejected are terminal; a correction is a
new entry, never an edit of an old one.

Amounts are positive and the kind says which way they go, except an adjustment's: its
sign says which way it goes, positive in the member's favour and negative owed (#38).
A void is an adjustment in the member's favour of whatever its period still owes, so
that nothing is owed on it any more (#256). A restore puts a void's amount back on its
period, as if the void had not happened (#278). A payment recorded by mistake is undone
with a refund of what is left of it (`mistake`, #281), and the credit it carried with
an adjustment of minus as much (`revert`). A payment moved to another period is a
refund out of its own and a payment into the other (`move`, #280). An adjustment made
by mistake is undone with one of minus as much (`revert`, #282), and a real debt that will
not be collected is forgiven with an adjustment of all its period owes (`write_off`).
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


class Purpose(StrEnum):
    """What a correcting entry is for (#278, docs/design/billing-corrections.md): each
    held to its kind and sign by the database (`ledger_entry_purpose`, migration 0049)."""

    VOID = "void"
    RESTORE = "restore"
    REVERT = "revert"
    WRITE_OFF = "write_off"
    MOVE = "move"
    MISTAKE = "mistake"
    # A month paid before the gym used Rakin ("Pagado hasta", #286): it settles its
    # period, and is no income of the month it is recorded in (0093).
    PAID_BEFORE = "paid_before"


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
    # Why a correction was written, its reason in `note`: a void of what its period
    # still owes (#256), a restore of a void (#278), a payment undone (#281) and the
    # credit it carried reverted, a payment moved (#280), an adjustment reverted and a
    # debt written off (#282); `None` for any other entry.
    purpose: Purpose | None = None

    def __post_init__(self) -> None:
        if self.kind is EntryKind.ADJUSTMENT:
            if self.amount_clp == 0:
                raise ValueError("an adjustment's amount_clp is not zero; its sign says which way")
        elif self.amount_clp <= 0:
            raise ValueError("amount_clp must be positive; the kind says which way it goes")
        if self.purpose is Purpose.VOID and (
            self.kind is not EntryKind.ADJUSTMENT or self.amount_clp <= 0
        ):
            raise ValueError("a void is an adjustment in the member's favour")
        if self.purpose is Purpose.RESTORE and (
            self.kind is not EntryKind.ADJUSTMENT or self.amount_clp >= 0
        ):
            raise ValueError("a restore is an adjustment owed by the member")
        if self.purpose is Purpose.WRITE_OFF and (
            self.kind is not EntryKind.ADJUSTMENT or self.amount_clp <= 0
        ):
            raise ValueError("a write-off is an adjustment in the member's favour")
        if self.purpose is Purpose.MISTAKE and self.kind is not EntryKind.REFUND:
            raise ValueError("a payment undone is a refund of it")
        if self.purpose is Purpose.REVERT and self.kind is not EntryKind.ADJUSTMENT:
            raise ValueError("a revert is an adjustment")
        if self.purpose is Purpose.MOVE and self.kind not in (EntryKind.PAYMENT, EntryKind.REFUND):
            raise ValueError("a move is a refund out of one period and a payment into another")
        if self.purpose is Purpose.PAID_BEFORE and self.kind is not EntryKind.PAYMENT:
            raise ValueError("a month paid before Rakin is a payment")


def _move(entry: LedgerEntry, to: EntryStatus) -> None:
    if to not in TRANSITIONS[entry.status]:
        raise InvalidTransition(f"ledger entry: {entry.status} → {to}")


def validate(entry: LedgerEntry) -> LedgerEntry:
    """An admin taps validate (v2: a bank match)."""
    _move(entry, EntryStatus.VALIDATED)
    return replace(entry, status=EntryStatus.VALIDATED)


def rejection_note(claim_note: str | None, note: str) -> str:
    """The rejected entry's note: the admin's reason, after whatever the claim said,
    which a rejection must not erase."""
    return f"{claim_note} — rechazado: {note}" if claim_note else note


def reject(entry: LedgerEntry, note: str) -> LedgerEntry:
    """An admin rejects a proof; the note is what the student is told. A note the claim
    already carried is kept ahead of it (`rejection_note`)."""
    if not note.strip():
        raise ValueError("a rejection needs a note for the student")
    _move(entry, EntryStatus.REJECTED)
    return replace(entry, status=EntryStatus.REJECTED, note=rejection_note(entry.note, note))
