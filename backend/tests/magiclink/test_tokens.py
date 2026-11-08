from datetime import UTC, datetime, timedelta

import pytest

from app.magiclink.tokens import LinkSigner, hash_token, new_session_token

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=15)


def test_a_token_is_valid_until_it_expires() -> None:
    signer = LinkSigner("a" * 32)
    token = signer.issue(LATER)

    assert signer.expiry(token) == LATER
    assert signer.valid(token, NOW)
    assert signer.valid(token, LATER - timedelta(seconds=1))
    assert not signer.valid(token, LATER)


def test_tokens_are_unique() -> None:
    signer = LinkSigner("a" * 32)
    assert len({signer.issue(LATER) for _ in range(100)}) == 100


def test_another_secret_does_not_verify() -> None:
    token = LinkSigner("a" * 32).issue(LATER)
    assert LinkSigner("b" * 32).expiry(token) is None


def test_a_changed_expiry_breaks_the_signature() -> None:
    signer = LinkSigner("a" * 32)
    nonce, expiry, signature = signer.issue(LATER).split(".")
    pushed = f"{nonce}.{int(expiry) + 86400}.{signature}"
    assert signer.expiry(pushed) is None


@pytest.mark.parametrize("token", ["", ".", "..", "a.b.c", "a.1.", "ñ.1.ñ", "x" * 600])
def test_garbage_is_refused_without_raising(token: str) -> None:
    assert LinkSigner("a" * 32).expiry(token) is None


def test_the_stored_hash_is_a_fixed_size_digest() -> None:
    token = new_session_token()
    assert len(hash_token(token)) == 32
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != hash_token(new_session_token())
