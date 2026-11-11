from pydantic import BaseModel

from app.schemas.theme import Theme


class HostGymInfo(BaseModel):
    slug: str
    name: str
    theme: Theme


class HostInfo(BaseModel):
    # The gym this host is, or None on the base host.
    gym: HostGymInfo | None
