from pydantic import BaseModel


class HostGymInfo(BaseModel):
    slug: str
    name: str


class HostInfo(BaseModel):
    # The gym this host is, or None on the base host.
    gym: HostGymInfo | None
