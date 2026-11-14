"""Resend's webhook (#104): hard bounces and spam complaints suppress an address.

Resend signs each delivery the Svix way: `svix-id`, `svix-timestamp` and
`svix-signature` headers, the last one or more `v1,<base64>` HMAC-SHA256 signatures of
`<id>.<timestamp>.<body>` under the endpoint's signing secret (`whsec_<base64>`, in
`RESEND_WEBHOOK_SECRET`). A delivery that is unsigned, signed with another secret, or
stamped more than five minutes from now (a replay) is a 400 and changes nothing. With
no secret set the endpoint is a 404: a self-hosted instance not on Resend has none.

`email.bounced` with a `Permanent` bounce and `email.complained` add each recipient
to `mail_suppression` (migration 0046), which `app.notices` then sends nothing to.
Every other event, a transient bounce included, is acknowledged and ignored, so
Resend does not retry it. Adding an address twice is fine, so a retried delivery is
too.

No session is needed: the signature is the authority. An address belongs to no gym,
so it runs with none set.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from app.integrations.svix import SignatureError, signing_key, verify
from app.notices import mail_address

logger = logging.getLogger(__name__)

RESEND_PATH = "/api/webhooks/resend"

router = APIRouter(tags=["webhooks"])

SUPPRESS = text(
    "INSERT INTO mail_suppression (address, reason, detail) VALUES (:address, :reason, :detail)"
    " ON CONFLICT DO NOTHING"
)


def suppressions(event: Any) -> tuple[str, str | None] | None:
    """The reason and detail an event suppresses its recipients for, if it does."""
    if not isinstance(event, dict) or not isinstance(data := event.get("data"), dict):
        return None
    kind = event.get("type")
    if kind == "email.complained":
        return "complaint", None
    if kind == "email.bounced":
        bounce = data.get("bounce")
        if isinstance(bounce, dict) and bounce.get("type") == "Permanent":
            detail = bounce.get("message")
            return "bounce", detail if isinstance(detail, str) and detail else None
    return None


def recipients(event: dict[str, Any]) -> list[str]:
    """The addresses an event is about, as `mail_suppression` keys them."""
    to = event["data"].get("to")
    found = [to] if isinstance(to, str) else to if isinstance(to, list) else []
    return sorted(
        {
            address
            for item in found
            # As `mail_suppression` holds them: something before the `@`.
            if isinstance(item, str) and (address := mail_address(item)).find("@") > 0
        }
    )


@router.post(
    RESEND_PATH,
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Unsigned, mis-signed or replayed"},
        status.HTTP_404_NOT_FOUND: {"description": "No RESEND_WEBHOOK_SECRET is set"},
    },
)
async def resend_event(request: Request) -> None:
    secret = request.app.state.settings.resend_webhook_secret
    if not secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no webhook here")
    body = await request.body()
    try:
        verify(signing_key(secret), request.headers, body)
    except SignatureError as exc:
        logger.warning("resend webhook refused", extra={"reason": str(exc)})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature") from None
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not JSON") from None
    found = suppressions(event)
    if found is None:
        return
    reason, detail = found
    addresses = recipients(event)
    async with request.app.state.sessionmaker() as session, session.begin():
        for address in addresses:
            await session.execute(
                SUPPRESS, {"address": address, "reason": reason, "detail": detail}
            )
    logger.info("mail suppressed", extra={"reason": reason, "count": len(addresses)})
