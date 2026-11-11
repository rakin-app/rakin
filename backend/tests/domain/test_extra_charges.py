import uuid

import pytest

from app.domain.extra_charges import AmountMode, LineStatus, Person, amounts, line_status, split


def people(*names: str) -> list[Person]:
    return [Person(uuid.uuid4(), name) for name in names]


def by_name(shares: dict[uuid.UUID, int], who: list[Person]) -> dict[str, int]:
    return {p.name: shares[p.id] for p in who}


def test_a_total_divides_evenly() -> None:
    nine = people(*[f"P{i}" for i in range(9)])
    shares = split(180_000, nine)
    assert set(shares.values()) == {20_000}


def test_the_remainder_goes_a_peso_each_to_the_first_alphabetically() -> None:
    who = people("Carla", "álvaro", "Bea")
    assert by_name(split(100, who), who) == {"álvaro": 34, "Bea": 33, "Carla": 33}
    assert by_name(split(101, who), who) == {"álvaro": 34, "Bea": 34, "Carla": 33}


def test_a_split_always_adds_up_to_the_total() -> None:
    who = people("Ana", "Bea", "Carla", "Dani", "Eva", "Fran", "Gabi")
    for total in (7, 100, 99_999, 180_001):
        assert sum(split(total, who).values()) == total


def test_a_split_needs_someone_and_a_peso_each() -> None:
    with pytest.raises(ValueError):
        split(100, [])
    with pytest.raises(ValueError):
        split(2, people("Ana", "Bea", "Carla"))


def test_fixed_charges_everyone_the_amount() -> None:
    who = people("Ana", "Bea")
    assert set(amounts(AmountMode.FIXED, 25_000, who).values()) == {25_000}


def test_an_override_replaces_ones_share_and_leaves_the_rest() -> None:
    ana, bea, carla = who = people("Ana", "Bea", "Carla")
    shares = amounts(AmountMode.SPLIT, 90_000, who, {bea.id: 0})
    assert by_name(shares, who) == {"Ana": 30_000, "Bea": 0, "Carla": 30_000}
    with pytest.raises(ValueError):
        amounts(AmountMode.SPLIT, 90_000, [ana, carla], {bea.id: 10})
    with pytest.raises(ValueError):
        amounts(AmountMode.FIXED, 90_000, who, {ana.id: -1})


@pytest.mark.parametrize(
    ("due", "paid", "pending", "cancelled", "status"),
    [
        (20_000, 0, 0, False, LineStatus.OPEN),
        (20_000, 5_000, 0, False, LineStatus.OPEN),
        (20_000, 0, 20_000, False, LineStatus.IN_REVIEW),
        (20_000, 20_000, 0, False, LineStatus.PAID),
        (0, 0, 0, False, LineStatus.PAID),
        (20_000, 20_000, 0, True, LineStatus.CANCELLED),
    ],
)
def test_a_lines_status(
    due: int, paid: int, pending: int, cancelled: bool, status: LineStatus
) -> None:
    assert (
        line_status(amount_due_clp=due, paid_clp=paid, pending_clp=pending, cancelled=cancelled)
        is status
    )
