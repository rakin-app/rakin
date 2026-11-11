"""The HTTP side: request a link, open it, end the session; and the cookie middleware.

Opening a link is two steps. The `GET` the email links to only shows a page with a
button, and the button's `POST` spends the link. Mail scanners fetch every link in a
message before the person does, and a single-use link spent on a `GET` would be
gone by the time they tap it. Both steps are plain HTML forms, so a link works in
any browser tab, JavaScript or not.

The middleware never refuses a request. It reads the session cookie, and if the
session is live hands it to `bind`, which puts what the application needs on
`request.state`; deciding what an anonymous request may do is left to the routes.

An application serving several sites (a tenant per host) passes `site`, which says
for each request where its links point and what a session started from it must start
in (`Site`). A link opened on a site whose scope its account may not reach says so,
and signs nobody in.
"""

import html
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from app.magiclink.service import MagicLinks, RateLimited, Session, Unreachable

# `__Host-`: browsers accept it only Secure, on Path=/ and with no Domain.
COOKIE_NAME = "__Host-session"
# For an `http://` base URL, local development only. Chrome and Firefox keep a Secure
# cookie on `http://localhost`, Safari drops it; and a `__Host-` name must be Secure.
DEV_COOKIE_NAME = "session"
CALLBACK = "/callback"

# The page carries the token; keep it out of caches, other sites' referrers and frames.
# Not `no-referrer`: that would make the form's POST say `Origin: null`.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; font-src 'self'; "
    "img-src 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


@dataclass(frozen=True)
class Texts:
    """Everything the pages say, for an application to translate. `{name}` is the
    site's, or `name` on a site that has none."""

    lang: str = "en"
    name: str = ""
    title: str = "Sign in"
    confirm: str = "Tap the button to sign in."
    button: str = "Sign in"
    invalid_title: str = "This link no longer works"
    invalid: str = "It has expired or was already used. Ask for a new one."
    again: str = "Ask for a new link"
    back: str = "Back to the start"
    unreachable: str = "This address has no access to {name}."


# The pages' look, unless the application brings its own: plain and unbranded, with no
# variants. The markup an application's `stylesheet` styles: a `main` with an optional
# `img.mark` (the site's logo) and `.eyebrow` (the site's name), an `h1`, and a `.card`
# holding a paragraph and one `.button`, a `button` or a link, also marked
# `.button--primary` or `.button--secondary`.
STYLESHEET = (
    "body{font-family:system-ui,sans-serif;max-width:28rem;margin:4rem auto;padding:0 1rem;"
    "line-height:1.5}.eyebrow{margin:0;text-transform:uppercase;font-size:.75rem}"
    ".card p{margin:0 0 1rem}"
    ".button{display:block;width:100%;padding:.75rem 1.5rem;font:inherit;text-align:center}"
)


@dataclass(frozen=True)
class Site:
    """Where a request was made: the base URL its links point back to, and the scope a
    session signed in there must start in (None: whatever the directory says), with
    its name for the pages to say, and the theme they wear (`data-theme` on the page's
    root, None for the stylesheet's own), and the URL of the logo they show, if any."""

    base_url: str
    scope: str | None = None
    name: str = ""
    theme: str | None = None
    logo: str | None = None


class LinkRequest(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=254)]

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        value = value.strip()
        local, at, domain = value.rpartition("@")
        if not (at and local and domain) or any(c.isspace() for c in value):
            raise ValueError("not an email address")
        return value


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def is_secure(base_url: str) -> bool:
    """Whether the session cookie is `Secure`: for every base URL but an `http://` one."""
    return urlsplit(base_url).scheme != "http"


def session_cookie_name(base_url: str) -> str:
    """`__Host-session`, or the plain `session` the `http://` base URL of local dev needs."""
    return COOKIE_NAME if is_secure(base_url) else DEV_COOKIE_NAME


def callback_url(base_url: str, prefix: str) -> str:
    """Where links point, for `MagicLinks(callback_url=...)` and a router on `prefix`."""
    return f"{base_url.rstrip('/')}{prefix}{CALLBACK}"


def build_router(
    links: MagicLinks,
    *,
    prefix: str,
    base_url: str,
    after_login: str = "/",
    landings: frozenset[str] = frozenset(),
    cookie_name: str | None = None,
    texts: Texts | None = None,
    site: Callable[[Request], Site] | None = None,
    sign_in: str | None = None,
    stylesheet: str = STYLESHEET,
) -> APIRouter:
    """The endpoints, under `prefix`. `base_url` is where browsers reach the app.

    Signing in lands on `after_login`, or on the link's `next` when it is one of
    `landings`: a fixed list, so a link can never send anyone off the app.

    `site` names each request's site, on `base_url` with no scope unless given. Every
    site's base URL must share `base_url`'s scheme, which decides the cookie.

    A link that no longer works offers a new one at `sign_in`, by default `after_login`.
    The pages' look is `stylesheet`, CSS for the markup `STYLESHEET` describes; fonts it
    names must be on the app's own origin.

    The cookie is `Secure` unless `base_url` is `http://`, whatever `cookie_name` says;
    by default it is named by `session_cookie_name`, as `SessionMiddleware` must read it.
    """
    if links.callback_url != callback_url(base_url, prefix):
        raise ValueError(f"links point at {links.callback_url}, not this router's callback")
    secure = is_secure(base_url)
    cookie_name = cookie_name or session_cookie_name(base_url)
    if not secure and cookie_name.startswith(("__Host-", "__Secure-")):
        raise ValueError(f"browsers drop a {cookie_name} cookie that is not Secure")
    texts = texts or Texts()
    router = APIRouter(prefix=prefix)
    callback_path = prefix + CALLBACK
    default_site = Site(base_url)

    def site_of(request: Request) -> Site:
        return default_site if site is None else site(request)

    def landing(next_: str) -> str:
        return next_ if next_ in landings else after_login

    def page(request: Request, title: str, body: str, status_code: int = 200) -> HTMLResponse:
        """A page of `body`, already HTML, under `title`, both after `{name}` is filled in."""
        here = site_of(request)
        name = here.name or texts.name
        heading = html.escape(title.format(name=name))
        eyebrow = f'<p class="eyebrow">{html.escape(name)}</p>' if name else ""
        theme = f' data-theme="{html.escape(here.theme)}"' if here.theme else ""
        # Beside the name, which says it: no alternative text of its own.
        mark = (
            f'<img class="mark" src="{html.escape(here.logo)}" alt="" width="56" height="56">'
            if here.logo
            else ""
        )
        document = (
            f'<!doctype html><html lang="{html.escape(texts.lang)}"{theme}><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{heading}</title><style>{stylesheet}</style></head>"
            f"<body><main>{mark}{eyebrow}<h1>{heading}</h1>"
            f'<div class="card">{body}</div></main></body></html>'
        )
        return HTMLResponse(document, status_code=status_code, headers=PAGE_HEADERS)

    def link_button(href: str, label: str, variant: str) -> str:
        return (
            f'<a class="button button--{variant}" href="{html.escape(href)}">'
            f"{html.escape(label)}</a>"
        )

    def unreachable(request: Request) -> HTMLResponse:
        name = site_of(request).name or texts.name
        return page(
            request,
            texts.title,
            f"<p>{html.escape(texts.unreachable.format(name=name))}</p>"
            f"{link_button(after_login, texts.back, 'secondary')}",
            status.HTTP_403_FORBIDDEN,
        )

    def invalid(request: Request) -> HTMLResponse:
        return page(
            request,
            texts.invalid_title,
            f"<p>{html.escape(texts.invalid)}</p>"
            f"{link_button(sign_in or after_login, texts.again, 'primary')}",
            status.HTTP_400_BAD_REQUEST,
        )

    @router.post(
        "/link",
        status_code=status.HTTP_202_ACCEPTED,
        responses={429: {"description": "Too many requests for this address or IP"}},
    )
    async def request_link(
        body: LinkRequest, request: Request, background: BackgroundTasks
    ) -> Response:
        """Email a sign-in link to every account at this address.

        The answer is the same whether or not anyone is at the address.
        """
        ip = request.client.host if request.client else "unknown"
        try:
            links.admit(body.email, ip)
        except RateLimited as exc:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests; try again later",
                headers={"Retry-After": str(math.ceil(exc.retry_after))},
            ) from exc
        # Looking the address up, storing and sending all wait until after the
        # response, so a known address takes no longer to answer than an unknown one.
        background.add_task(links.send_links, body.email, base_url=site_of(request).base_url)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    @router.get(CALLBACK, response_class=HTMLResponse)
    async def open_link(
        request: Request,
        token: Annotated[str, Query(max_length=512)] = "",
        next_: Annotated[str, Query(alias="next", max_length=512)] = "",
    ) -> HTMLResponse:
        """The page a link opens: a button that signs in. It does not spend the link."""
        if not links.looks_valid(token):
            return invalid(request)
        return page(
            request,
            texts.title,
            f"<p>{html.escape(texts.confirm)}</p>"
            f'<form method="post" action="{html.escape(callback_path)}">'
            f'<input type="hidden" name="token" value="{html.escape(token)}">'
            f'<input type="hidden" name="next" value="{html.escape(landing(next_))}">'
            f'<button class="button button--primary" type="submit">'
            f"{html.escape(texts.button)}</button></form>",
        )

    @router.post(CALLBACK, response_class=HTMLResponse)
    async def redeem_link(request: Request) -> Response:
        """Spend the link and start a session, set as an `HttpOnly` cookie."""
        # A browser names the page that posted; only this app's own form may sign in.
        here = site_of(request)
        sent_from = request.headers.get("origin")
        if sent_from is not None and sent_from != origin_of(here.base_url):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        form = parse_qs((await request.body())[:2048].decode("latin-1"))
        try:
            session_token = await links.redeem(form.get("token", [""])[0], within=here.scope)
        except Unreachable:
            return unreachable(request)
        if session_token is None:
            return invalid(request)
        destination = landing(form.get("next", [""])[0])
        response = RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            cookie_name,
            session_token,
            max_age=int(links.session_ttl.total_seconds()),
            path="/",
            secure=secure,
            httponly=True,
            samesite="lax",
        )
        return response

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        """End this browser's session, if it has one, and clear the cookie."""
        session_token = request.cookies.get(cookie_name)
        if session_token:
            await links.end_session(session_token)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(cookie_name, path="/", secure=secure, httponly=True, samesite="lax")
        return response

    return router


class SessionMiddleware:
    """Hands a request's live session to `bind(session, request.state)`."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        links: MagicLinks,
        bind: Callable[[Session, dict[str, Any]], None],
        cookie_name: str = COOKIE_NAME,
    ) -> None:
        self.app = app
        self.links = links
        self.bind = bind
        self.cookie_name = cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            token = cookie_parser(Headers(scope=scope).get("cookie", "")).get(self.cookie_name)
            if token:
                session = await self.links.session(token)
                if session is not None:
                    self.bind(session, scope.setdefault("state", {}))
        await self.app(scope, receive, send)
