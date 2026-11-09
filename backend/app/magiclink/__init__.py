"""Magic-link sign-in for FastAPI: email a link, open it, get a session cookie.

A link is a signed token that expires in 15 minutes, or later if issued so, and works
once; only its hash is stored. It may name a page to land on, from the router's list.
Opening it starts a 30-day session, sent as an `HttpOnly`, `Secure`, `SameSite=Lax`
cookie. Requests are rate-limited per address and per IP.

Self-contained, to be extracted as a package later: nothing here imports from the
rest of `app`. The application plugs in its accounts, storage and delivery through
the protocols in `service`; `app.auth` is Rakin's.
"""

from app.magiclink.ratelimit import MemoryRateLimiter, RateLimiter
from app.magiclink.service import (
    Directory,
    Link,
    MagicLinks,
    RateLimited,
    Recipient,
    Sender,
    Session,
    Store,
)
from app.magiclink.web import COOKIE_NAME, SessionMiddleware, Texts, build_router, callback_url

__all__ = [
    "COOKIE_NAME",
    "Directory",
    "Link",
    "MagicLinks",
    "MemoryRateLimiter",
    "RateLimited",
    "RateLimiter",
    "Recipient",
    "Sender",
    "Session",
    "SessionMiddleware",
    "Store",
    "Texts",
    "build_router",
    "callback_url",
]
