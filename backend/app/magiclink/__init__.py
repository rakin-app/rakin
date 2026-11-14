"""Magic-link sign-in for FastAPI: email a link, open it (or type the code that came
with it), get a session cookie.

A link is a signed token that expires in 15 minutes, or later if issued so, and works
once; only its hash is stored. It may name a page to land on, from the router's list.
Opening it starts a 30-day session, sent as an `HttpOnly`, `Secure`, `SameSite=Lax`
cookie (not `Secure`, under another name, for an `http://` base URL: local dev).
Requests are rate-limited per address and per IP.

Self-contained, to be extracted as a package later: nothing here imports from the
rest of `app`. The application plugs in its accounts, storage and delivery through
the protocols in `service`; `app.auth` is Rakin's.
"""

from app.magiclink.ratelimit import MemoryRateLimiter, RateLimiter
from app.magiclink.service import (
    CodeExpired,
    CodeLink,
    Directory,
    Link,
    MagicLinks,
    Pending,
    RateLimited,
    Recipient,
    Sender,
    Session,
    Store,
    Unreachable,
)
from app.magiclink.web import (
    COOKIE_NAME,
    DEV_COOKIE_NAME,
    SessionMiddleware,
    Site,
    Texts,
    build_router,
    callback_url,
    session_cookie_name,
)

__all__ = [
    "COOKIE_NAME",
    "DEV_COOKIE_NAME",
    "CodeExpired",
    "CodeLink",
    "Directory",
    "Link",
    "MagicLinks",
    "MemoryRateLimiter",
    "Pending",
    "RateLimited",
    "RateLimiter",
    "Recipient",
    "Sender",
    "Session",
    "SessionMiddleware",
    "Site",
    "Store",
    "Texts",
    "Unreachable",
    "build_router",
    "callback_url",
    "session_cookie_name",
]
