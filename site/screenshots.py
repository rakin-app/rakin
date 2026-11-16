# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.65.2", "pillow==13.0.0"]
# ///
"""Takes the landing page's screenshots (#343) from a local stack on seed data.

    docker compose up -d --wait && make seed
    uv run --with playwright==1.65.2 playwright install chromium   # once
    uv run site/screenshots.py [--only NAME]...

Writes `site/img/<name>.webp`, each screen at 390×844 (a phone, at 2×) or
1280×800, so they can be taken again after a UX pass. It signs in as the seed's
people, the way UX QA does (.claude/commands/ux-qa.md): it asks the API for a
sign-in link and reads it back out of the API's log, since no mail is sent
locally.

Seed data only. The stack is the one in this checkout's `.env`
(`PUBLIC_BASE_URL`), and the script refuses any host but localhost, so a
screenshot can never hold staging's or a real gym's members.

The page speaks to any gym, and Academia Sur is seeded as a jiu-jitsu academy.
So before the shots the script sets it up as a gym with no sport of its own
(`NEUTRAL_GYM`): its one activity grades no one, so no belts show, and its
classes record no blocks (Drilling, Sparring) and hold no open mats. That
changes the local seed only; `make seed` on a fresh stack puts it back.
"""

import argparse
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "img"

# The seed's invented people (backend/app/seed/data.py), as in UX QA.
OWNER = "martin.fuentes@example.com"  # pii-ok: the seed's owner of Academia Sur
STUDENT = "diego.morales@example.com"  # pii-ok: a seeded student who attends

PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
}
DESKTOP = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 1}

# Words that would make the page read as a martial-arts app. A shot whose screen
# holds one of them fails, so a later seed or screen change cannot slip one in.
SPORT_WORDS = re.compile(
    r"\b(sparring|open mat|drilling|cintur[oó]n|grados?|graduaci[oó]n|bjj|jiu|tatami|dojo|kimono)\b",
    re.IGNORECASE,
)

# Academia Sur as a gym of no particular sport. Each statement is safe to run again.
NEUTRAL_GYM = """
BEGIN;
UPDATE gym_activity SET name = 'Entrenamiento', uses_grades = false;
DELETE FROM session_block;
UPDATE class_type SET kind = 'class', name = 'Práctica libre' WHERE kind = 'open_mat';
COMMIT;
"""


@dataclass(frozen=True)
class Shot:
    name: str
    who: str
    path: str
    device: dict
    # Optional: text on the screen to scroll to the top before the shot.
    scroll_to: str | None = None
    # Optional: follow the first link whose text matches, after loading `path`.
    open_first: str | None = None


SHOTS = (
    # Hero and "Los atrasados, avisados": Hoy, who is overdue and the reminders.
    Shot("hoy-390", OWNER, "/admin", PHONE),
    Shot("hoy-1280", OWNER, "/admin", DESKTOP),
    # "Cada pago, claro": the tiles above the Libro, and a proof validated in a tap.
    Shot("pagos-1280", OWNER, "/admin/pagos", DESKTOP),
    Shot("comprobante-390", OWNER, "/admin/pagos/comprobantes", PHONE),
    # "Tu equipo, al día": who to call, and the student's own page.
    Shot("llamar-390", OWNER, "/admin", PHONE, scroll_to="A quién llamar"),
    Shot("ficha-1280", OWNER, "/admin/alumnos", DESKTOP, open_first="Diego Morales"),
    # The rest: the student's own page, installed on the phone.
    Shot("me-390", STUDENT, "/me", PHONE),
)


def base_url() -> str:
    env = (ROOT / ".env").read_text() if (ROOT / ".env").exists() else ""
    match = re.search(r"^PUBLIC_BASE_URL=(.+)$", env, re.MULTILINE)
    url = match.group(1).strip() if match else "http://localhost:8080"
    if urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
        sys.exit(f"screenshots: {url} is not a local stack; screenshots come from seed data only")
    return url.rstrip("/")


def sign_in_link(base: str, email: str) -> str:
    """Asks for a sign-in link and reads it from the API's log."""
    request = urllib.request.Request(
        f"{base}/api/auth/link",
        data=json.dumps({"email": email}).encode(),
        headers={"content-type": "application/json"},
    )
    urllib.request.urlopen(request).close()
    pattern = re.compile(re.escape(base) + r"/api/auth/callback\?token=[^\"\\\s]+")
    for _ in range(20):
        time.sleep(0.5)
        log = subprocess.run(
            ["docker", "compose", "logs", "api", "--no-log-prefix", "--since", "2m"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        links = pattern.findall(log)
        if links:
            return links[-1]
    sys.exit(f"screenshots: no sign-in link for {email} in the api's log; is the stack seeded?")


def neutral_gym() -> None:
    subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-q", "-v", "ON_ERROR_STOP=1"]
        + ["-U", "rakin", "-d", "rakin"],
        cwd=ROOT,
        input=NEUTRAL_GYM,
        text=True,
        capture_output=True,
        check=True,
    )


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    # No caret, no hover, no transition caught halfway.
    page.add_style_tag(
        content="*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}"
    )
    page.mouse.move(0, 0)
    page.wait_for_timeout(300)


def take(page: Page, base: str, shot: Shot) -> None:
    page.goto(base + shot.path)
    settle(page)
    if shot.open_first:
        page.get_by_role("link", name=re.compile(shot.open_first)).first.click()
        settle(page)
    if shot.scroll_to:
        target = page.get_by_text(shot.scroll_to, exact=False).first
        target.evaluate(
            "el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 72)"
        )
        page.wait_for_timeout(200)
    words = sorted({m.lower() for m in SPORT_WORDS.findall(page.inner_text("body"))})
    if words:
        sys.exit(f"screenshots: {shot.name} shows {', '.join(words)}; the page is for any gym")
    png = page.screenshot()
    image = Image.open(io.BytesIO(png)).convert("RGB")
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / f"{shot.name}.webp", "WEBP", quality=82, method=6)
    print(f"ok   - {shot.name}.webp ({image.width}×{image.height})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", action="append", help="take only this shot (repeatable)")
    args = parser.parse_args()
    shots = [s for s in SHOTS if not args.only or s.name in args.only]
    base = base_url()
    neutral_gym()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        sessions: dict[str, dict] = {}
        for who in dict.fromkeys(s.who for s in shots):
            context = browser.new_context(locale="es-CL", timezone_id="America/Santiago")
            page = context.new_page()
            page.goto(sign_in_link(base, who))
            page.get_by_role("button", name="Entrar").click()
            page.wait_for_url(re.compile(r"/(admin|me)"))
            sessions[who] = context.storage_state()
            context.close()
        for shot in shots:
            context = browser.new_context(
                storage_state=sessions[shot.who],
                locale="es-CL",
                timezone_id="America/Santiago",
                **shot.device,
            )
            take(context.new_page(), base, shot)
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
