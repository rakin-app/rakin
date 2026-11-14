"""Rakin's side of magic-link sign-in (`app.magiclink`): people, Postgres and email.

An address's links go to every person with that email who belongs to some gym, one
link each: on its roster, or with a membership, a staff row or a dependent there
(migration 0042). A sign-in reaches only the gyms whose own record of the person holds the
address the link went to (migration 0029), never every gym the person is in: the email
one gym writes signs nobody in to another. A session starts in that gym when there is
exactly one; with several it starts in none until they pick (#16), and gym-scoped
routes answer 401.

On a gym's own host (`app.hosts`) sign-in is that gym's: the link goes back to that
host, and opening it starts a session in that gym, or, for someone whose address does
not reach it, none at all and a page that says so. A session on a gym's host works
only in that gym, whatever it names. Who the link goes to is decided as on the base
host, so the answer to asking for one is the same whoever is at the address.

The session middleware sets `request.state.person_id` and, when the session has a
gym, `request.state.tenant`. It never answers 401 itself: `app.tenancy` stays the one
place a gym-scoped route refuses an anonymous request.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.hosts import Hosts, host_gym
from app.integrations.mailer import Mailer
from app.magiclink import (
    CodeLink,
    Link,
    MagicLinks,
    MemoryRateLimiter,
    Pending,
    Recipient,
    Session,
    Site,
    Texts,
    callback_url,
)
from app.notices import MAGIC_LINK, STUDENT_PAGE, Notice, Notices
from app.settings import Settings
from app.tenancy import Tenant

PREFIX = "/api/auth"

# Where a link may land other than "/": the student page, for the links in notices.
LANDINGS = frozenset({STUDENT_PAGE})

# A link is good for 15 minutes, so five per address covers a person who keeps
# asking; thirty per IP leaves room for a gym's shared wifi.
PER_ADDRESS = (5, 15 * 60)
PER_IP = (30, 15 * 60)
# Codes typed (#276), apart from links asked for: five per address, as many as one
# code takes before it is spent; sixty per IP, for a gym's shared wifi.
CODE_PER_ADDRESS = (5, 15 * 60)
CODE_PER_IP = (60, 15 * 60)

# Rakin's logo (#224, docs/brand): the tatami symbol, drawn on docs/brand/build.py's
# grid, and the wordmark in the display font, ending in the centre mat's square. In
# the theme's colours, as the SPA's `RakinLogo` draws it.
_MATS = ((4, 4, 16, 6), (22, 4, 6, 16), (12, 22, 16, 6), (4, 12, 6, 16))
LOGO = (
    '<span class="logo" role="img" aria-label="Rakin">'
    '<svg class="logo__symbol" viewBox="0 0 32 32" aria-hidden="true">'
    '<rect class="logo__tile" width="32" height="32" rx="7"/>'
    '<rect class="logo__ring" x="1" y="1" width="30" height="30" rx="6"/>'
    + "".join(
        f'<rect class="logo__mat" x="{x}" y="{y}" width="{w}" height="{h}" rx="1"/>'
        for x, y, w, h in _MATS
    )
    + '<rect class="logo__centre" x="12" y="12" width="8" height="8" rx="1"/></svg>'
    '<span aria-hidden="true">rakin<span class="logo__square"></span></span></span>'
)

TEXTS = Texts(
    lang="es",
    name="Rakin",
    logo=LOGO,
    title="Entrar a {name}",
    confirm="Toca el botón para entrar.",
    button="Entrar",
    invalid_title="Este link ya no sirve",
    invalid="Venció o ya se usó: cada link dura 15 minutos y sirve una sola vez.",
    again="Pedir otro link",
    back="Volver al inicio",
    unreachable="Este correo no tiene acceso a {name}. Si entrenas ahí, pídele al gimnasio"
    " que lo registre.",
)

# Where "Pedir otro link" goes: the SPA's sign-in screen.
SIGN_IN = "/ingresar"

# The logo's file the sign-in link's pages show, at 56 px.
LOGO_VARIANT = "128.webp"

# The design tokens the pages use, as `frontend/src/styles/tokens.css` has them (a test
# holds them to it): the pages are plain HTML from here, with no SPA bundle to load.
# The colours come in the gym's theme (#199); the first theme is the default.
THEME_TOKENS = {
    "bosque": {
        "--color-bg": "#f6f8f1",
        "--color-surface": "#fcfdf9",
        "--color-surface-sunken": "#ebeee6",
        "--color-border": "#d8dfd4",
        "--color-border-input": "#818a7a",
        "--color-text": "#102719",
        "--color-text-muted": "#57685a",
        "--color-heading": "#153c25",
        "--color-inverse": "#153c25",
        "--color-inverse-raised": "#264c34",
        "--color-inverse-text": "#f5f6eb",
        "--color-moss": "#a0c79b",
        "--color-focus": "#4e7f58",
        "--shadow-card": "0 1px 2px rgb(16 39 25 / 0.06), 0 8px 24px -12px rgb(16 39 25 / 0.18)",
    },
    "oceano": {
        "--color-bg": "#f2f8fd",
        "--color-surface": "#fafdff",
        "--color-surface-sunken": "#e6eef5",
        "--color-border": "#d4dee7",
        "--color-border-input": "#7a8895",
        "--color-text": "#102334",
        "--color-text-muted": "#556574",
        "--color-heading": "#15364f",
        "--color-inverse": "#15364f",
        "--color-inverse-raised": "#254560",
        "--color-inverse-text": "#edf6ff",
        "--color-moss": "#85c5df",
        "--color-focus": "#47769d",
        "--shadow-card": "0 1px 2px rgb(16 35 52 / 0.06), 0 8px 24px -12px rgb(16 35 52 / 0.18)",
    },
    "volcan": {
        "--color-bg": "#fdf4f4",
        "--color-surface": "#fffbfb",
        "--color-surface-sunken": "#f5eaea",
        "--color-border": "#e7d8d8",
        "--color-border-input": "#958080",
        "--color-text": "#32191a",
        "--color-text-muted": "#745d5d",
        "--color-heading": "#4d2527",
        "--color-inverse": "#4d2527",
        "--color-inverse-raised": "#5e3536",
        "--color-inverse-text": "#fff1f1",
        "--color-moss": "#e4ac93",
        "--color-focus": "#9b5e60",
        "--shadow-card": "0 1px 2px rgb(50 25 26 / 0.06), 0 8px 24px -12px rgb(50 25 26 / 0.18)",
    },
}
TOKENS = {
    "--font-sans": "'Figtree', system-ui, -apple-system, 'Segoe UI', sans-serif",
    "--font-display": "'Bricolage Grotesque', 'Figtree', system-ui, sans-serif",
    "--font-weight-display": "600",
    "--text-xs": "12px",
    "--text-base": "15px",
    "--text-3xl": "30px",
    "--tracking-eyebrow": "0.06em",
    "--tracking-title": "-0.02em",
    "--space-0-5": "2px",
    "--space-3": "12px",
    "--space-4": "16px",
    "--space-5": "20px",
    "--space-7": "28px",
    "--space-8": "32px",
    "--space-14": "56px",
    "--radius-md": "10px",
    "--radius-xl": "20px",
    "--control-height-lg": "52px",
    "--content-max-width": "480px",
}

# Fixed-name copies of the SPA's fonts, which `frontend/vite.config.ts` serves.
FONTS = (
    ("Figtree", 400, "figtree-latin-400-normal"),
    ("Figtree", 600, "figtree-latin-600-normal"),
    ("Bricolage Grotesque", 600, "bricolage-grotesque-latin-600-normal"),
)

# The sign-in link's pages as `/ingresar` looks: the gym's name over the title, then a
# card with the text and one full-width 52px button. Light only, as the app is.
STYLESHEET = (
    "".join(
        f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
        f"font-display:swap;src:url(/fonts/{file}.woff2) format('woff2')}}"
        for family, weight, file in FONTS
    )
    + ":root{color-scheme:light;"
    + "".join(f"{name}:{value};" for name, value in TOKENS.items())
    + "}"
    + "".join(
        f"{':root,' if i == 0 else ''}[data-theme='{theme}']{{"
        + "".join(f"{name}:{value};" for name, value in colours.items())
        + "}"
        for i, (theme, colours) in enumerate(THEME_TOKENS.items())
    )
    + "*{box-sizing:border-box}"
    "html{-webkit-text-size-adjust:100%}"
    "body{margin:0;background:var(--color-bg);color:var(--color-text);"
    "font-family:var(--font-sans);font-size:var(--text-base);line-height:1.4;"
    "-webkit-font-smoothing:antialiased}"
    "main{max-width:var(--content-max-width);margin:0 auto;"
    "padding:var(--space-14) var(--space-5) calc(var(--space-8) + env(safe-area-inset-bottom))}"
    # The gym's logo (#223), round like the app's mark; `cover` fills the circle.
    ".mark{display:block;width:56px;height:56px;margin-bottom:var(--space-3);"
    "border-radius:50%;object-fit:cover}"
    ".eyebrow{margin:0 0 var(--space-0-5);color:var(--color-text-muted);font-size:var(--text-xs);"
    "font-weight:600;letter-spacing:var(--tracking-eyebrow);text-transform:uppercase}"
    ".eyebrow--logo{margin-bottom:var(--space-3);color:var(--color-heading);font-size:20px;"
    "text-transform:none}"
    ".logo{display:inline-flex;align-items:center;gap:.34em;font-family:var(--font-display);"
    "font-weight:var(--font-weight-display);letter-spacing:var(--tracking-title);line-height:1}"
    ".logo__symbol{width:1.22em;height:1.22em}"
    ".logo__tile{fill:var(--color-inverse)}.logo__mat{fill:var(--color-inverse-text)}"
    ".logo__centre{fill:var(--color-moss)}"
    ".logo__ring{fill:none;stroke:var(--color-moss);stroke-opacity:.6;stroke-width:2}"
    ".logo__square{display:inline-block;width:.21em;height:.21em;margin-left:.06em;"
    "border-radius:.02em;background:var(--color-focus)}"
    "h1{margin:0;padding-bottom:var(--space-3);font-family:var(--font-display);"
    "font-size:var(--text-3xl);font-weight:var(--font-weight-display);"
    "letter-spacing:var(--tracking-title);color:var(--color-heading);"
    "line-height:1.2}"
    ".card{display:flex;flex-direction:column;gap:var(--space-4);margin-top:var(--space-3);"
    "padding:var(--space-4);"
    "background:var(--color-surface);border:1px solid var(--color-border);"
    "border-radius:var(--radius-xl);box-shadow:var(--shadow-card)}"
    ".card p{margin:0;color:var(--color-text-muted)}"
    ".card form{margin:0}"
    ".button{display:flex;align-items:center;justify-content:center;width:100%;"
    "min-height:var(--control-height-lg);padding:0 var(--space-3);border:1px solid transparent;"
    "border-radius:var(--radius-md);font:inherit;font-size:var(--text-base);font-weight:600;"
    "line-height:1.2;text-align:center;text-decoration:none;cursor:pointer;"
    "-webkit-appearance:none;appearance:none}"
    ".button--primary{background:var(--color-inverse);border-color:var(--color-inverse);"
    "color:var(--color-inverse-text)}"
    ".button--primary:hover{background:var(--color-inverse-raised)}"
    ".button--secondary{background:var(--color-surface);border-color:var(--color-border-input);"
    "color:var(--color-text)}"
    ".button--secondary:hover{background:var(--color-surface-sunken)}"
    ":focus-visible{outline:2px solid var(--color-focus);outline-offset:2px}"
    "@media (min-width:960px){main{padding-top:var(--space-7)}}"
)

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]


class PeopleDirectory:
    """People by email, across gyms, through the `SECURITY DEFINER` lookups (0005)."""

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def recipients(self, address: str) -> Sequence[Recipient]:
        async with self._sessionmaker()() as session:
            rows = await session.execute(
                text("SELECT person_id, name, email FROM auth_people_by_email(:address)"),
                {"address": address},
            )
            return [Recipient(str(r.person_id), r.email, r.name) for r in rows]

    async def scope(self, subject: str, address: str, within: str | None = None) -> str | None:
        async with self._sessionmaker()() as session:
            gyms = [
                str(g)
                for g in (
                    await session.scalars(
                        text("SELECT auth_gyms_of(:person, :address)"),
                        {"person": uuid.UUID(subject), "address": address},
                    )
                ).all()
            ]
        if within is not None:
            return within if within in gyms else None
        return gyms[0] if len(gyms) == 1 else None


class PostgresStore:
    """`auth_link` and `auth_session`, keyed by token hash (0005), and a link's code
    (0046).

    A session is read and ended before any gym is set, so through the lookups 0005
    defines rather than the RLS-scoped table.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def _execute(self, sql: str, params: dict[str, Any]) -> None:
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(text(sql), params)

    async def _fetch(self, sql: str, params: dict[str, Any]) -> Any:
        async with self._sessionmaker()() as session, session.begin():
            return (await session.execute(text(sql), params)).one_or_none()

    async def add_link(
        self,
        token_hash: bytes,
        subject: str,
        address: str,
        expires_at: datetime,
        code_hash: bytes | None = None,
    ) -> None:
        params = {
            "h": token_hash,
            "p": uuid.UUID(subject),
            "a": address,
            "e": expires_at,
            "c": code_hash,
        }
        async with self._sessionmaker()() as session, session.begin():
            if code_hash is not None:
                await session.execute(
                    text(
                        "UPDATE auth_link SET code_hash = NULL WHERE person_id = :p"
                        " AND lower(email) = lower(:a) AND code_hash IS NOT NULL"
                    ),
                    params,
                )
            await session.execute(
                text(
                    "INSERT INTO auth_link (token_hash, person_id, email, expires_at, code_hash)"
                    " VALUES (:h, :p, :a, :e, :c)"
                ),
                params,
            )

    async def code_link(self, code_hash: bytes) -> CodeLink | None:
        row = await self._fetch(
            "SELECT token_hash, person_id, email, expires_at FROM auth_link"
            " WHERE code_hash = :c AND used_at IS NULL AND email IS NOT NULL"
            " ORDER BY created_at DESC LIMIT 1",
            {"c": code_hash},
        )
        if row is None:
            return None
        return CodeLink(bytes(row.token_hash), str(row.person_id), row.email, row.expires_at)

    async def miss_code(self, address: str, now: datetime, tries: int) -> None:
        await self._execute(
            "UPDATE auth_link SET code_misses = code_misses + 1,"
            " code_hash = CASE WHEN code_misses + 1 >= :tries THEN NULL ELSE code_hash END"
            " WHERE lower(email) = lower(:a) AND code_hash IS NOT NULL"
            " AND used_at IS NULL AND expires_at > :now",
            {"a": address, "now": now, "tries": tries},
        )

    async def pending_link(self, token_hash: bytes, now: datetime) -> Pending | None:
        row = await self._fetch(
            "SELECT person_id, email FROM auth_link"
            " WHERE token_hash = :h AND used_at IS NULL AND expires_at > :now"
            " AND email IS NOT NULL",
            {"h": token_hash, "now": now},
        )
        return None if row is None else Pending(str(row.person_id), row.email)

    async def redeem_link(
        self, token_hash: bytes, now: datetime, session_hash: bytes, session: Session
    ) -> bool:
        async with self._sessionmaker()() as db, db.begin():
            # Of two concurrent redemptions, the second waits on the row lock and then
            # finds it used.
            spent = await db.execute(
                text(
                    "UPDATE auth_link SET used_at = :now WHERE token_hash = :h"
                    " AND person_id = :p AND email = :a AND used_at IS NULL"
                    " AND expires_at > :now RETURNING 1"
                ),
                {
                    "h": token_hash,
                    "p": uuid.UUID(session.subject),
                    "a": session.address,
                    "now": now,
                },
            )
            if spent.one_or_none() is None:
                return False
            # Fails with the link: the transaction rolls both back.
            await db.execute(
                text(
                    "INSERT INTO auth_session (token_hash, person_id, email, gym_id, expires_at)"
                    " VALUES (:h, :p, :a, :g, :e)"
                ),
                {
                    "h": session_hash,
                    "p": uuid.UUID(session.subject),
                    "a": session.address,
                    "g": None if session.scope is None else uuid.UUID(session.scope),
                    "e": session.expires_at,
                },
            )
        return True

    async def session(self, token_hash: bytes, now: datetime) -> Session | None:
        row = await self._fetch(
            "SELECT person_id, email, gym_id, expires_at FROM auth_live_session(:h, :now)",
            {"h": token_hash, "now": now},
        )
        if row is None:
            return None
        gym = None if row.gym_id is None else str(row.gym_id)
        return Session(str(row.person_id), row.email, gym, row.expires_at)

    async def end_session(self, token_hash: bytes, now: datetime) -> None:
        await self._execute("SELECT auth_end_session(:h, :now)", {"h": token_hash, "now": now})


class MailSender:
    """Sends each link, with its code, as the `magic_link` notice. It belongs to no gym,
    and neither its URL nor its code is written to `message_log`."""

    def __init__(self, notices: Notices) -> None:
        self._notices = notices

    async def send(self, link: Link) -> None:
        recipient = link.recipient
        await self._notices.send(
            Notice(
                MAGIC_LINK,
                to=recipient.address,
                person_id=uuid.UUID(recipient.subject),
                gym_id=None,
                context={"name": recipient.name, "url": link.url, "code": link.code},
            )
        )


def bind_session(session: Session, state: dict[str, Any]) -> None:
    person_id = uuid.UUID(session.subject)
    state["person_id"] = person_id
    if session.scope is None:
        return
    # A gym's host is that gym's alone; the base host (None) takes any session's gym.
    here = host_gym(state)
    if here is not None and session.scope != str(here.id):
        return
    state["tenant"] = Tenant(uuid.UUID(session.scope), person_id)


def site_of(hosts: Hosts) -> Callable[[Request], Site]:
    """Each request's sign-in site: its host's gym (`app.hosts`), or the base host."""

    def site(request: Request) -> Site:
        gym = host_gym(request.state)
        if gym is None:
            return Site(hosts.base_url(None))
        logo = None if gym.logo is None else f"{gym.logo}/{LOGO_VARIANT}"
        return Site(hosts.base_url(gym.slug), str(gym.id), gym.name, gym.theme, logo)

    return site


def build_notices(settings: Settings, mailer: Mailer, sessionmaker: Sessionmaker) -> Notices:
    """Notices with their own sign-in links, for code outside a request: the jobs."""
    return Notices(
        mailer,
        sessionmaker,
        base_url=settings.public_base_url,
        secret_key=settings.secret_key,
        links=build_magic_links(settings, mailer, sessionmaker),
        hosts=Hosts.of(settings),
    )


def build_magic_links(settings: Settings, mailer: Mailer, sessionmaker: Sessionmaker) -> MagicLinks:
    return MagicLinks(
        secret_key=settings.secret_key,
        callback_url=callback_url(settings.public_base_url, PREFIX),
        directory=PeopleDirectory(sessionmaker),
        store=PostgresStore(sessionmaker),
        sender=MailSender(
            Notices(
                mailer,
                sessionmaker,
                base_url=settings.public_base_url,
                secret_key=settings.secret_key,
            )
        ),
        per_address=MemoryRateLimiter(limit=PER_ADDRESS[0], window_seconds=PER_ADDRESS[1]),
        per_ip=MemoryRateLimiter(limit=PER_IP[0], window_seconds=PER_IP[1]),
        code_per_address=MemoryRateLimiter(
            limit=CODE_PER_ADDRESS[0], window_seconds=CODE_PER_ADDRESS[1]
        ),
        code_per_ip=MemoryRateLimiter(limit=CODE_PER_IP[0], window_seconds=CODE_PER_IP[1]),
    )
