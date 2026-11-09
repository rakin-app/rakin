"""One-click unsubscribe from a gym's non-essential notices (#52).

Every non-essential notice links here, in its footer and in `List-Unsubscribe`, with a
token naming the gym and the person (`app.notices.unsubscribe`). A `POST` records the
unsubscribe: what a mail client sends for `List-Unsubscribe-Post:
List-Unsubscribe=One-Click` (RFC 8058), and what the button on the `GET` page sends. A
`GET` alone never unsubscribes, since mail scanners fetch every link in a message.

No session is needed: the token is the authority, and all it can do is stop that
gym's non-essential notices to that person. It acts in the token's gym, so RLS holds
it there like any request.
"""

import html
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.magiclink.web import PAGE_HEADERS
from app.notices.unsubscribe import UNSUBSCRIBE_PATH, UnsubscribeSigner

router = APIRouter(prefix=UNSUBSCRIBE_PATH, tags=["mail"])

TITLE = "Avisos por correo"


def page(body: str, status_code: int = status.HTTP_200_OK) -> HTMLResponse:
    document = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{TITLE}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:28rem;margin:4rem auto;"
        "padding:0 1rem;line-height:1.5}button{font:inherit;padding:.75rem 1.5rem}</style>"
        f"</head><body><h1>{TITLE}</h1>{body}</body></html>"
    )
    return HTMLResponse(document, status_code=status_code, headers=PAGE_HEADERS)


def invalid() -> HTMLResponse:
    return page(
        "<p>Este enlace no es válido. Si sigues recibiendo avisos que no quieres,"
        " escríbele a tu academia.</p>",
        status.HTTP_404_NOT_FOUND,
    )


@asynccontextmanager
async def in_gym(request: Request, gym_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.gym_id', :gym_id, true)"), {"gym_id": str(gym_id)}
        )
        yield session


def verify(request: Request, token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    return UnsubscribeSigner(request.app.state.settings.secret_key).verify(token)


# The gym's name, when the person is still one of its people.
GYM_OF = """
    SELECT g.name FROM gym g JOIN gym_person gp ON gp.gym_id = g.id
    WHERE g.id = :gym_id AND gp.person_id = :person_id
"""


@router.get("/{token}", response_class=HTMLResponse)
async def confirm(request: Request, token: str) -> HTMLResponse:
    """A button that unsubscribes. Opening the link does not."""
    found = verify(request, token)
    if found is None:
        return invalid()
    gym_id, person_id = found
    async with in_gym(request, gym_id) as session:
        gym = await session.scalar(text(GYM_OF), {"gym_id": gym_id, "person_id": person_id})
    if gym is None:
        return invalid()
    action = html.escape(f"{UNSUBSCRIBE_PATH}/{token}")
    return page(
        f"<p>¿Dejar de recibir los avisos opcionales de {html.escape(gym)}? Seguirás"
        " recibiendo los correos sobre tus pagos y tus enlaces para entrar.</p>"
        f'<form method="post" action="{action}">'
        '<button type="submit">Dejar de recibirlos</button></form>'
    )


@router.post("/{token}", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str) -> HTMLResponse:
    """Stop the gym's non-essential notices to the person. Doing it twice is fine."""
    found = verify(request, token)
    if found is None:
        return invalid()
    gym_id, person_id = found
    params = {"gym_id": gym_id, "person_id": person_id}
    async with in_gym(request, gym_id) as session:
        gym = await session.scalar(text(GYM_OF), params)
        if gym is None:
            return invalid()
        await session.execute(
            text(
                "INSERT INTO mail_unsubscribe (gym_id, person_id) VALUES (:gym_id, :person_id)"
                " ON CONFLICT DO NOTHING"
            ),
            params,
        )
    return page(
        f"<p>Listo: {html.escape(gym)} no te enviará más avisos opcionales por correo."
        " Seguirás recibiendo los correos sobre tus pagos y tus enlaces para entrar.</p>"
    )
