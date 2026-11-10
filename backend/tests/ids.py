"""Made-up identities for tests: a RUT, an email, a phone no other test is likely to
hold. A person is their RUT, or an email in one gym (migration 0034), so most tests that
add someone need one of the two."""

import random
import uuid

from app.domain.rut import check_digit


def random_rut() -> str:
    """A valid RUT in the stored form (`12345678-5`)."""
    body = random.randrange(5_000_000, 99_999_999)
    return f"{body}-{check_digit(body)}"


def random_email() -> str:
    return f"p{uuid.uuid4().hex[:12]}@example.com"


def random_phone() -> str:
    return f"+569{random.randrange(10**7, 10**8)}"
