"""A stand-in for the auth layer: the `X-Test-Gym` header's gym becomes the tenant.

The person acting is `X-Test-Person`'s, or else the owner `tests.pg.seed_gym` gave
that gym.
"""

import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from app.tenancy import Tenant
from tests.pg import seeded_owner

GYM_HEADER = b"x-test-gym"
PERSON_HEADER = b"x-test-person"


class FakeAuth:
    """The auth layer's job, for the tests: headers in, `request.state.tenant` out."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            gym = headers.get(GYM_HEADER)
            if gym is not None:
                gym_id = uuid.UUID(gym.decode())
                person = headers.get(PERSON_HEADER)
                person_id = seeded_owner(gym_id) if person is None else uuid.UUID(person.decode())
                scope.setdefault("state", {})["tenant"] = Tenant(gym_id, person_id)
        await self.app(scope, receive, send)


def as_gym(gym_id: uuid.UUID, person_id: uuid.UUID | None = None) -> dict[str, str]:
    """Act in `gym_id` as `person_id`, or as the gym's seeded owner."""
    headers = {GYM_HEADER.decode(): str(gym_id)}
    if person_id is not None:
        headers[PERSON_HEADER.decode()] = str(person_id)
    return headers
