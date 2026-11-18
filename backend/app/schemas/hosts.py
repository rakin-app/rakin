from pydantic import BaseModel

from app.domain.vocabulary import DEFAULT, Vocabulary
from app.schemas.theme import Theme


class HostGymInfo(BaseModel):
    slug: str
    name: str
    theme: Theme
    # Its logo's files (`app.logos.logo_path`), or None with no logo (#223).
    logo: str | None = None
    # What the gym calls itself, its members and its coach (#344).
    vocabulary: Vocabulary = DEFAULT
    # Suspended from the platform's panel (#439): every page shows only a notice.
    suspended: bool = False


class HostInfo(BaseModel):
    # The gym this host is, or None on the base host.
    gym: HostGymInfo | None
