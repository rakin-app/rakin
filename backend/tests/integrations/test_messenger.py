"""The contract every `Messenger` passes, and the `wa.me` links v1 hands to admins."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from app.integrations import build_messenger
from app.integrations.messenger import Message, Messenger, WaMeMessenger
from tests.conftest import make_settings

IMPLEMENTATIONS: list[Messenger] = [WaMeMessenger()]

TEXT = "Hola Ana 👋 tu cuota de $45.000 vence el 05-11. ¿Dudas? Responde aquí & listo #1"


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda m: type(m).__name__)
def messenger(request: pytest.FixtureRequest) -> Messenger:
    m: Messenger = request.param
    return m


def test_a_link_opens_a_chat_with_that_phone_and_that_text(messenger: Messenger) -> None:
    delivery = asyncio.run(messenger.deliver(Message(to_phone="+56912345678", text=TEXT)))

    # A messenger that sends by itself returns no link; one that does not, a link
    # that carries the message whole.
    if delivery.link is not None:
        url = urlsplit(delivery.link)
        assert url.scheme == "https"
        assert "56912345678" in url.path
        assert parse_qs(url.query)["text"] == [TEXT]


@pytest.mark.parametrize("phone", ["912345678", "+56 9 1234 5678", "+5622123456", "+14155550100"])
def test_only_e164_chilean_mobiles_are_addressable(phone: str) -> None:
    with pytest.raises(ValueError, match=r"E\.164"):
        Message(to_phone=phone, text="hola")


def test_an_empty_message_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        Message(to_phone="+56912345678", text="  \n")


def test_wame_link_format() -> None:
    delivery = asyncio.run(WaMeMessenger().deliver(Message(to_phone="+56912345678", text="a b&c")))

    assert delivery.link == "https://wa.me/56912345678?text=a%20b%26c"


def test_messenger_is_selected_by_settings() -> None:
    assert isinstance(build_messenger(make_settings()), WaMeMessenger)
