from pydantic import BaseModel

from app.schemas.theme import Theme


class HostGymInfo(BaseModel):
    slug: str
    name: str
    theme: Theme
    # Its logo's files (`app.logos.logo_path`), or None with no logo (#223).
    logo: str | None = None


class HostInfo(BaseModel):
    # The gym this host is, or None on the base host.
    gym: HostGymInfo | None
