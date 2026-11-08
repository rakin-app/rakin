"""The contracts for `PaymentRail` and `BankFeed`, whose only v1 implementations are no-ops."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import build_bank_feed, build_payment_rail
from app.integrations.bankfeed import BankFeed, BankTransaction, NoBankFeed
from app.integrations.payments import NoPaymentRail, PaymentRail, PaymentRequest
from tests.conftest import make_settings

RAILS: list[PaymentRail] = [NoPaymentRail()]
FEEDS: list[BankFeed] = [NoBankFeed()]


@pytest.fixture(params=RAILS, ids=lambda r: type(r).__name__)
def rail(request: pytest.FixtureRequest) -> PaymentRail:
    r: PaymentRail = request.param
    return r


@pytest.fixture(params=FEEDS, ids=lambda f: type(f).__name__)
def feed(request: pytest.FixtureRequest) -> BankFeed:
    f: BankFeed = request.param
    return f


def test_a_payment_link_is_https_and_names_the_rails_id(rail: PaymentRail) -> None:
    request = PaymentRequest(reference="bp-1", amount_clp=45000, description="Cuota noviembre")

    link = asyncio.run(rail.create_payment(request))

    if link is not None:
        assert link.url.startswith("https://")
        assert link.external_id


@pytest.mark.parametrize("amount", [0, -1, 45000.0, True])
def test_a_payment_is_a_positive_whole_number_of_pesos(amount: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        PaymentRequest(reference="bp-1", amount_clp=amount, description="x")  # type: ignore[arg-type]


def test_a_feed_reports_aware_whole_peso_transactions_since_the_cutoff(feed: BankFeed) -> None:
    since = datetime.now(UTC) - timedelta(days=7)

    transactions = asyncio.run(feed.transactions(since))

    assert all(isinstance(t, BankTransaction) for t in transactions)
    assert all(t.posted_at >= since for t in transactions)
    assert [t.posted_at for t in transactions] == sorted(t.posted_at for t in transactions)
    assert len({t.ref for t in transactions}) == len(transactions)


def test_a_feed_refuses_a_naive_cutoff(feed: BankFeed) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(feed.transactions(datetime(2026, 11, 1)))


def test_a_transaction_is_aware_and_in_whole_pesos() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BankTransaction(ref="t1", amount_clp=1, posted_at=datetime(2026, 11, 1), description="")
    with pytest.raises(TypeError):
        BankTransaction(ref="t1", amount_clp=1.5, posted_at=datetime.now(UTC), description="")  # type: ignore[arg-type]


def test_rail_and_feed_are_selected_by_settings() -> None:
    assert isinstance(build_payment_rail(make_settings()), NoPaymentRail)
    assert isinstance(build_bank_feed(make_settings()), NoBankFeed)
