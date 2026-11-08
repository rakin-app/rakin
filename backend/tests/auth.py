"""A stand-in for the auth layer: the `X-Test-Gym` header's gym becomes the tenant."""

import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from app.tenancy import Tenant

GYM_HEADER = b"x-test-gym"


class FakeAuth:
    """The auth layer's job, for the tests: header in, `request.state.tenant` out."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            gym = dict(scope["headers"]).get(GYM_HEADER)
            if gym is not None:
                scope.setdefault("state", {})["tenant"] = Tenant(uuid.UUID(gym.decode()))
        await self.app(scope, receive, send)


def as_gym(gym_id: uuid.UUID) -> dict[str, str]:
    return {GYM_HEADER.decode(): str(gym_id)}
