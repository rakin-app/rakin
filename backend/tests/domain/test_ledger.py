import pytest

from app.domain import ledger
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry


def pending_payment(amount: int = 30_000) -> LedgerEntry:
    return LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=amount)


def test_a_new_entry_is_pending() -> None:
    assert pending_payment().status is EntryStatus.PENDING


def test_pending_can_be_validated() -> None:
    assert ledger.validate(pending_payment()).status is EntryStatus.VALIDATED


def test_pending_can_be_rejected_with_a_note() -> None:
    rejected = ledger.reject(pending_payment(), "the transfer amount does not match")

    assert rejected.status is EntryStatus.REJECTED
    assert rejected.note == "the transfer amount does not match"


def test_rejection_keeps_the_claim_note() -> None:
    claimed = LedgerEntry(
        kind=EntryKind.PAYMENT, amount_clp=1, note="pagué desde la cuenta de mi mamá"
    )

    rejected = ledger.reject(claimed, "monto no coincide")

    assert rejected.note == "pagué desde la cuenta de mi mamá — rechazado: monto no coincide"


def test_rejection_needs_a_note() -> None:
    with pytest.raises(ValueError, match="note"):
        ledger.reject(pending_payment(), "  ")


@pytest.mark.parametrize("terminal", [EntryStatus.VALIDATED, EntryStatus.REJECTED])
def test_validated_and_rejected_are_terminal(terminal: EntryStatus) -> None:
    entry = LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=1, status=terminal)

    with pytest.raises(InvalidTransition):
        ledger.validate(entry)
    with pytest.raises(InvalidTransition):
        ledger.reject(entry, "too late")


def test_transitions_match_the_diagram() -> None:
    expected = {
        EntryStatus.PENDING: {EntryStatus.VALIDATED, EntryStatus.REJECTED},
        EntryStatus.VALIDATED: set(),
        EntryStatus.REJECTED: set(),
    }

    assert expected == ledger.TRANSITIONS


@pytest.mark.parametrize("amount", [0, -1])
def test_amounts_are_positive(amount: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        pending_payment(amount)


def test_an_adjustments_sign_says_which_way_it_goes() -> None:
    assert LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=-5_000).amount_clp == -5_000
    with pytest.raises(ValueError, match="not zero"):
        LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=0)


@pytest.mark.parametrize("kind", [EntryKind.CHARGE, EntryKind.PAYMENT, EntryKind.REFUND])
def test_only_an_adjustment_is_negative(kind: EntryKind) -> None:
    with pytest.raises(ValueError, match="positive"):
        LedgerEntry(kind=kind, amount_clp=-5_000)
