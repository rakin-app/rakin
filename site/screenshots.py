# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.65.2", "pillow==13.0.0"]
# ///
"""Takes the landing page's captures and loops (#343, #449) from a local stack on seed data.

    docker compose up -d --wait && make seed
    uv run --with playwright==1.65.2 playwright install chromium   # once
    uv run site/screenshots.py [--scene NAME]... [--only NAME]...
    uv run site/screenshots.py --hero   # the hero's widths and the AVIFs again, from the 2× on disk

Writes, for each shot, `site/img/<name>-2x.webp` and `<name>-1x.webp`, the screen
taken at 2× (a phone at 390×844, a computer at 1280×800) and cropped to what the shot
proves; and for each loop `site/video/<name>.webm` and `.mp4` with its last frame as
`site/img/<name>-poster-2x.webp`. Loops need `ffmpeg`, to take them only: the site's
build never runs it.

The hero's two screens are the page's LCP image (#461), so each also comes in the
widths its frame shows it at between and around 1× and 2× (`hoy-1280-1.5x.webp`), and
in AVIF beside every WebP. `--hero` writes those again from the 2× captures on disk,
with no stack.

It signs in as the seed's people, the way UX QA does (.claude/commands/ux-qa.md): it
asks the API for a sign-in link and reads it back out of the API's log, since no mail
is sent locally.

Seed data only. The stack is the one in this checkout's `.env` (`PUBLIC_BASE_URL`),
and the script refuses any host but localhost. Before a capture is saved, every email
on the screen must be at example.com and every RUT one the seed's gym holds.

The shots run in `SCENES`, each setting Academia Sur up as a gym of one kind with SQL
that sets every value the shots rely on: its name, its words, its activity, and what
it calls its free practice. `neutral` is a gym of no sport, for the owner's, the
coaches' and the members' sections, and there a shot showing a sport's word fails.
`academia` is the seed as it is, BJJ with belts, and runs last, so the stack is left
as `make seed` made it. A loop never writes: confirming a proof is answered by the
script, and attendance is taken offline, queued in a page that then closes.
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw
from playwright.sync_api import Locator, Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "site" / "img"
VIDEO = ROOT / "site" / "video"

# The seed's invented people (backend/app/seed/data.py), as in UX QA.
OWNER = "martin.fuentes@example.com"  # pii-ok: the seed's owner of Academia Sur
STUDENT = "diego.morales@example.com"  # pii-ok: a seeded student who attends
# pii-ok: a seeded member whose two kids owe this month, with her: "Pagar todo junto"
GUARDIAN = "francisca.figueroa@example.com"

PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
}
DESKTOP = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 2}

# The hero's captures (#461), and the scales each comes in beside 1× and 2×: the
# computer's shows 900 CSS pixels wide, the phone's 302.
HERO = {"hoy-1280": (0.75, 1.5), "hoy-390": (1.5,)}
# Shots added since (#563) come in AVIF too, at 1× and 2× only: the page shows them in a
# `<picture>` with `sizes`, like the hero, but lazy.
AVIF = {"finanzas-390": ()}

# Words that would make the page read as a martial-arts app. In the neutral scene a
# shot whose screen holds one of them fails, so a seed or screen change cannot slip
# one in.
SPORT_WORDS = re.compile(
    r"\b(sparring|open mat|drilling|cintur[oó]n|grados?|graduaci[oó]n|bjj|jiu|tatami|dojo|kimono)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")

# Academia Sur as a gym of one kind. Every statement is safe to run again, and sets
# the value whatever an earlier scene left. The drilling block is found by the id
# migration 0028 gives every gym's default kinds.
SCENE_SQL = """
BEGIN;
UPDATE gym SET name = {name},
    settings = CASE WHEN {words}::jsonb IS NULL THEN settings - 'vocabulary'
                    ELSE jsonb_set(settings, '{{vocabulary}}', {words}::jsonb) END
    WHERE slug = 'academia-sur';
UPDATE gym_activity SET name = {activity}, preset = {preset}, uses_grades = {grades};
UPDATE class_type SET name = {open_mat} WHERE kind = 'open_mat';
UPDATE block_kind SET name = {practice} WHERE is_sparring;
UPDATE block_kind SET name = {drilling}
    WHERE id = md5(gym_id::text || '/block_kind/drilling')::uuid;
COMMIT;
"""


@dataclass(frozen=True)
class Box:
    """A crop, in CSS pixels of the whole page."""

    x: float
    y: float
    width: float
    height: float


# Where a crop is: a heading's text and the element around it that the crop takes
# (a CSS selector its `closest` finds), the heading itself when none; or a CSS
# selector alone.
Target = tuple[str, str | None] | str

TARGET_BOX = """([text, around]) => {
  let el;
  if (around === undefined) {
    el = document.querySelector(text);
  } else {
    const heads = [...document.querySelectorAll('h1, h2, h3, [aria-label]')];
    const head = heads.find(h => (h.getAttribute('aria-label') || h.textContent).trim() === text);
    el = head && (around ? head.closest(around) : head);
  }
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top + scrollY, width: r.width, height: r.height };
}"""


def box_of(page: Page, target: Target) -> Box:
    found = page.evaluate(TARGET_BOX, [target] if isinstance(target, str) else list(target))
    if found is None:
        sys.exit(f"screenshots: no {target!r} on {page.url}")
    return Box(**found)


def region(*targets: Target, pad: int = 12) -> Callable[[Page], Box]:
    """The crop around `targets`, `pad` past each edge of their union."""

    def crop(page: Page) -> Box:
        boxes = [box_of(page, t) for t in targets]
        left = min(b.x for b in boxes) - pad
        top = min(b.y for b in boxes) - pad
        right = max(b.x + b.width for b in boxes) + pad
        bottom = max(b.y + b.height for b in boxes) + pad
        return Box(max(left, 0), max(top, 0), right - max(left, 0), bottom - max(top, 0))

    return crop


@dataclass(frozen=True)
class Shot:
    name: str
    who: str
    path: str
    device: dict
    # What the shot proves, cropped; the screen as it shows when none.
    crop: Callable[[Page], Box] | None = None
    # Text to bring to `offset` CSS pixels below the top before a screen shot.
    scroll_to: str | None = None
    offset: int = 72
    # Clicks after loading `path`: the role and name of each.
    clicks: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Loop:
    """A short muted capture of the UI: `run` drives it and records its frames."""

    name: str
    who: str
    path: str
    run: Callable[["Recorder"], None]
    clicks: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Scene:
    name: str
    gym: str
    # `gym.settings.vocabulary`; today's words when none.
    words: dict | None
    activity: str
    preset: str | None
    grades: bool
    open_mat: str
    practice: str
    drilling: str
    shots: tuple[Shot, ...] = ()
    loops: tuple[Loop, ...] = ()
    sport_free: bool = False

    def sql(self) -> str:
        def lit(value: object) -> str:
            if value is None:
                return "NULL"
            if isinstance(value, bool):
                return "true" if value else "false"
            return "'" + str(value).replace("'", "''") + "'"

        words = None if self.words is None else json.dumps({**self.words, "by_hand": False})
        return SCENE_SQL.format(
            name=lit(self.gym),
            words=lit(words),
            activity=lit(self.activity),
            preset=lit(self.preset),
            grades=lit(self.grades),
            open_mat=lit(self.open_mat),
            practice=lit(self.practice),
            drilling=lit(self.drilling),
        )


# The loops' frames, ten a second; a change of screen fades over `FADE` of them.
FPS = 10
FADE = 3


class Recorder:
    """Records a loop: holds of the screen as it is, a fade into each change, and a
    touch drawn where a tap lands."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[Image.Image] = []

    def grab(self) -> Image.Image:
        return Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")

    def hold(self, seconds: float) -> None:
        frame = self.grab()
        if self.frames and self.frames[-1].tobytes() != frame.tobytes():
            last = self.frames[-1]
            self.frames += [Image.blend(last, frame, (n + 1) / (FADE + 1)) for n in range(FADE)]
        self.frames += [frame] * max(1, round(seconds * FPS))

    def tap(self, control: Locator) -> None:
        """Shows a touch on the control for a moment, then taps it."""
        control.scroll_into_view_if_needed()
        box = control.bounding_box()
        assert box is not None
        scale = PHONE["device_scale_factor"]
        x = (box["x"] + box["width"] / 2) * scale
        y = (box["y"] + box["height"] / 2) * scale
        frame = self.grab()
        touched = frame.copy()
        overlay = Image.new("RGBA", frame.size)
        r = 22 * scale
        ImageDraw.Draw(overlay).ellipse((x - r, y - r, x + r, y + r), fill=(16, 39, 25, 90))
        touched.paste(overlay, mask=overlay)
        self.frames += [frame] * 2 + [touched] * 4
        control.click()
        self.page.wait_for_timeout(400)


def confirm_proof(rec: Recorder) -> None:
    """Validar comprobante: the amount matches, Confirmar, and the next one."""
    rec.hold(1.6)
    rec.tap(rec.page.get_by_role("button", name=re.compile(r"^Confirmar")))
    rec.hold(2.4)


def take_attendance(rec: Recorder) -> None:
    """Pasar lista with no signal: three taps, Guardar, and the marks wait on the phone."""
    page = rec.page
    page.context.set_offline(True)
    target = box_of(page, ("Asistencia", None))
    page.evaluate(f"window.scrollTo(0, {target.y - 72})")
    page.wait_for_timeout(200)
    rec.hold(0.6)
    people = page.locator("section", has=page.get_by_role("heading", name="Asistencia")).locator(
        "li button"
    )
    for n in range(3):
        rec.tap(people.nth(n))
        rec.hold(0.1)
    rec.tap(page.get_by_role("button", name=re.compile(r"^Guardar asistencia")))
    rec.hold(1.4)


NEUTRAL_WORDS = None  # today's: academia, alumnos, profe

SCENES = (
    Scene(
        "neutral",
        "Academia Sur",
        NEUTRAL_WORDS,
        "Entrenamiento",
        None,
        False,
        open_mat="Práctica libre",
        practice="Práctica libre",
        drilling="Ejercicios",
        sport_free=True,
        shots=(
            # The hero: Hoy on the computer, and on the phone.
            Shot("hoy-1280", OWNER, "/admin", DESKTOP),
            Shot("hoy-390", OWNER, "/admin", PHONE),
            # Para ti, step by step: Pagos, a proof, the overdue and their reminders,
            # who to call and the trials that stayed.
            Shot("pagos-390", OWNER, "/admin/pagos", PHONE),
            Shot("comprobante-390", OWNER, "/admin/pagos/comprobantes", PHONE),
            Shot("vencidos-390", OWNER, "/admin", PHONE, scroll_to="Vencidos"),
            Shot("pruebas-390", OWNER, "/admin", PHONE, scroll_to="Pruebas", offset=360),
            # Lo que entra y lo que sale (#563): Finanzas, the month's result.
            Shot("finanzas-390", OWNER, "/admin/finanzas", PHONE),
            # Para tus profes: the month's classes, and the requirements on a ficha.
            Shot(
                "mes-1280",
                OWNER,
                "/admin/clases?month={month}",
                DESKTOP,
                crop=region('section[aria-labelledby="classes-month"]'),
            ),
            Shot(
                "requisitos-1280",
                OWNER,
                "/admin/alumnos",
                DESKTOP,
                crop=region(("Requisitos", "section")),
                clicks=(("link", "Diego Morales"),),
            ),
            # Para tus alumnos: the next payment, their classes, and a family.
            Shot(
                "me-pago-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(("Próximo pago", "section"), ("Cobros extra", "section")),
            ),
            Shot(
                "me-clases-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(("Mis clases", "section"), ("Mis horas por etiqueta", "section")),
            ),
            Shot(
                "me-familia-390",
                GUARDIAN,
                "/me",
                PHONE,
                crop=region(("Próximo pago", "section"), ("Pagar todo junto", ".together")),
            ),
        ),
        loops=(
            Loop("validar", OWNER, "/admin/pagos/comprobantes", confirm_proof),
            Loop(
                "asistencia",
                OWNER,
                "/admin",
                take_attendance,
                clicks=(("link", "Pasar lista"),),
            ),
        ),
    ),
    Scene(
        "escalada",
        "Muro Sur",
        {"place": "gimnasio", "members": "socios", "coach": "instructor"},
        "Escalada",
        "escalada",
        False,
        open_mat="Escalada libre",
        practice="Escalada libre",
        drilling="Ejercicios",
        shots=(
            Shot(
                "actividad-escalada-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(
                    ("Mi entrenamiento", "section"),
                    ("Mi tiempo de entrenamiento", "section"),
                ),
            ),
        ),
    ),
    Scene(
        "remo",
        "Club de Remo Sur",
        {"place": "club", "members": "socios", "coach": "entrenador"},
        "Remo",
        "remo",
        False,
        open_mat="Remo libre",
        practice="Remo libre",
        drilling="Ejercicios",
        shots=(
            Shot(
                "actividad-remo-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(
                    ("Mi entrenamiento", "section"),
                    ("Mi tiempo de entrenamiento", "section"),
                ),
            ),
        ),
    ),
    # Last: the seed as `make seed` made it.
    Scene(
        "academia",
        "Academia Sur",
        None,
        "BJJ",
        "bjj",
        True,
        open_mat="Open mat",
        practice="Sparring",
        drilling="Drilling",
        shots=(
            Shot(
                "actividad-academia-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(
                    ("Mi entrenamiento", "section"),
                    ("Mi tiempo de entrenamiento", "section"),
                ),
            ),
            # Para tus alumnos: their plan, requirements, belt and promotions.
            Shot(
                "me-grado-390",
                STUDENT,
                "/me",
                PHONE,
                crop=region(("Mi plan", "section"), ("Mi entrenamiento", "section")),
            ),
            # Para tus profes: a promotion given, and the way there.
            Shot(
                "graduacion-1280",
                OWNER,
                "/admin/alumnos",
                DESKTOP,
                crop=region(("Graduación", "section")),
                clicks=(("link", "Diego Morales"),),
            ),
        ),
    ),
)


def base_url() -> str:
    env = (ROOT / ".env").read_text() if (ROOT / ".env").exists() else ""
    match = re.search(r"^PUBLIC_BASE_URL=(.+)$", env, re.MULTILINE)
    url = match.group(1).strip() if match else "http://localhost:8080"
    if urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
        sys.exit(f"screenshots: {url} is not a local stack; screenshots come from seed data only")
    return url.rstrip("/")


def psql(sql: str) -> str:
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-q",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        + ["-U", "rakin", "-d", "rakin"],
        cwd=ROOT,
        input=sql,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def seed_ruts() -> set[str]:
    """The RUTs the seeded gym holds: its people's, and its own in its settings."""
    rows = psql(
        "SELECT rut FROM gym_person p JOIN gym g ON g.id = p.gym_id"
        " WHERE g.slug = 'academia-sur' AND rut IS NOT NULL"
        " UNION SELECT settings #>> '{bank_account,rut}' FROM gym WHERE slug = 'academia-sur'"
        " UNION SELECT settings #>> '{privacy,rut}' FROM gym WHERE slug = 'academia-sur';"
    )
    return {normal_rut(r) for r in rows.split()}


def seed_month() -> str:
    """The first day of the month the seed depicts, as the Clases URL takes it."""
    as_of = psql("SELECT settings #>> '{seed,as_of}' FROM gym WHERE slug = 'academia-sur';")
    return as_of.strip()[:8] + "01"


def normal_rut(rut: str) -> str:
    return rut.replace(".", "").upper()


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


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    # No caret, no hover, no transition caught halfway.
    page.add_style_tag(
        content="*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}"
    )
    page.mouse.move(0, 0)
    page.wait_for_timeout(300)


def open_screen(page: Page, base: str, path: str, clicks: tuple[tuple[str, str], ...]) -> None:
    page.goto(base + path.format(month=seed_month()))
    settle(page)
    for role, name in clicks:
        page.get_by_role(role, name=re.compile(re.escape(name))).first.click()  # type: ignore[arg-type]
        settle(page)


@dataclass
class Checks:
    """What every capture must pass before it is saved."""

    ruts: set[str]
    sport_free: bool = False
    seen: list[str] = field(default_factory=list)

    def __call__(self, page: Page, name: str) -> None:
        text = page.inner_text("body")
        if self.sport_free:
            words = sorted({m.lower() for m in SPORT_WORDS.findall(text)})
            if words:
                sys.exit(f"screenshots: {name} shows {', '.join(words)}; the page is for any gym")
        for host in EMAIL.findall(text):
            if host != "example.com" and not host.endswith(".example.com"):
                sys.exit(f"screenshots: {name} shows an email at {host}, not a seed one")
        for rut in RUT.findall(text):
            if normal_rut(rut) not in self.ruts:
                sys.exit(f"screenshots: {name} shows the RUT {rut}, which the seed does not hold")
        self.seen.append(name)


def save(image: Image.Image, name: str) -> None:
    """`<name>-2x.webp` as taken, and `<name>-1x.webp` at half its size; the hero's
    widths too, for a hero shot."""
    IMG.mkdir(parents=True, exist_ok=True)
    image.save(IMG / f"{name}-2x.webp", "WEBP", quality=80, method=6)
    half = image.resize((image.width // 2, image.height // 2), Image.Resampling.LANCZOS)
    half.save(IMG / f"{name}-1x.webp", "WEBP", quality=82, method=6)
    print(f"ok   - {name} ({half.width}×{half.height})")
    if name in HERO or name in AVIF:
        hero(image, name)


def hero(image: Image.Image, name: str) -> None:
    """The hero's widths of the 2× capture `image`: WebP at the scales `save` does not
    write, and AVIF at every one."""
    scales = sorted({1, 2, *{**HERO, **AVIF}[name]})
    for scale in scales:
        size = (round(image.width * scale / 2), round(image.height * scale / 2))
        scaled = image if scale == 2 else image.resize(size, Image.Resampling.LANCZOS)
        if scale not in (1, 2):
            scaled.save(IMG / f"{name}-{scale:g}x.webp", "WEBP", quality=80, method=6)
        # 4:4:4 keeps small coloured text as sharp as the WebP.
        scaled.save(
            IMG / f"{name}-{scale:g}x.avif", "AVIF", quality=60, speed=0, subsampling="4:4:4"
        )
    print(f"ok   - {name}: {', '.join(f'{s:g}x' for s in scales)}, also in AVIF")


def take(page: Page, base: str, shot: Shot, check: Checks) -> None:
    open_screen(page, base, shot.path, shot.clicks)
    if shot.scroll_to:
        target = page.get_by_text(shot.scroll_to, exact=True).first
        target.evaluate(
            f"el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - {shot.offset})"
        )
        page.wait_for_timeout(200)
    check(page, shot.name)
    if shot.crop is None:
        png = page.screenshot()
    else:
        box = shot.crop(page)
        clip = {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
        png = page.screenshot(clip=clip, full_page=True)
    save(Image.open(io.BytesIO(png)).convert("RGB"), shot.name)


def record(page: Page, base: str, loop: Loop, check: Checks) -> None:
    confirmed: list[bool] = []

    # Confirming answers here, so the proof stays waiting in the seed; the queue then
    # reads as it would, without the one confirmed.
    def validate(route: Route) -> None:
        confirmed.append(True)
        route.fulfill(json={"credit": None, "period": {"outstanding_clp": 0, "closed": True}})

    def queue(route: Route) -> None:
        response = route.fetch()
        proofs = response.json()
        route.fulfill(response=response, json=proofs[len(confirmed) :])

    page.route("**/api/ledger/proofs/*/validate", validate)
    page.route(re.compile(r".*/api/ledger/proofs$"), queue)
    open_screen(page, base, loop.path, loop.clicks)
    check(page, loop.name)
    rec = Recorder(page)
    loop.run(rec)
    check(page, loop.name)
    with tempfile.TemporaryDirectory() as tmp:
        for n, frame in enumerate(rec.frames):
            frame.save(Path(tmp) / f"f{n:04d}.png")
        VIDEO.mkdir(parents=True, exist_ok=True)
        frames = ["-framerate", str(FPS), "-i", str(Path(tmp) / "f%04d.png")]
        common = ["-an", "-pix_fmt", "yuv420p"]
        ffmpeg(*frames, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "42", "-row-mt", "1",
               *common, str(VIDEO / f"{loop.name}.webm"))  # fmt: skip
        ffmpeg(*frames, "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-movflags",
               "+faststart", *common, str(VIDEO / f"{loop.name}.mp4"))  # fmt: skip
    save(rec.frames[-1], f"{loop.name}-poster")
    seconds = len(rec.frames) / FPS
    sizes = ", ".join(
        f"{ext} {(VIDEO / f'{loop.name}.{ext}').stat().st_size // 1024} KB"
        for ext in ("webm", "mp4")
    )
    print(f"ok   - {loop.name} ({seconds:.1f} s; {sizes})")


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scene", action="append", help="run only this scene (repeatable)")
    parser.add_argument("--only", action="append", help="take only this shot or loop (repeatable)")
    parser.add_argument(
        "--hero", action="store_true", help="write the hero's widths from the 2× on disk; no stack"
    )
    args = parser.parse_args()
    if args.hero:
        for name in {**HERO, **AVIF}:
            hero(Image.open(IMG / f"{name}-2x.webp").convert("RGB"), name)
        return
    scenes = [s for s in SCENES if not args.scene or s.name in args.scene]

    def wanted(name: str) -> bool:
        return not args.only or name in args.only

    loops = any(wanted(loop.name) for s in scenes for loop in s.loops)
    if loops and shutil.which("ffmpeg") is None:
        sys.exit(
            "screenshots: the loops need ffmpeg (brew install ffmpeg, or apt install ffmpeg);"
            " --only a shot runs without it"
        )
    base = base_url()
    ruts = seed_ruts()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        sessions: dict[str, dict] = {}

        def session(who: str) -> dict:
            if who not in sessions:
                context = browser.new_context(locale="es-CL", timezone_id="America/Santiago")
                page = context.new_page()
                page.goto(sign_in_link(base, who))
                page.get_by_role("button", name="Entrar").click()
                page.wait_for_url(re.compile(r"/(admin|me)"))
                sessions[who] = context.storage_state()
                context.close()
            return sessions[who]

        for scene in scenes:
            psql(scene.sql())
            print(f"# {scene.name}")
            check = Checks(ruts, sport_free=scene.sport_free)
            work: list[Shot | Loop] = [*scene.shots, *scene.loops]
            for item in work:
                if not wanted(item.name):
                    continue
                device = item.device if isinstance(item, Shot) else PHONE
                context = browser.new_context(
                    storage_state=session(item.who),
                    locale="es-CL",
                    timezone_id="America/Santiago",
                    **device,
                )
                page = context.new_page()
                if isinstance(item, Shot):
                    take(page, base, item, check)
                else:
                    record(page, base, item, check)
                context.close()
        browser.close()


if __name__ == "__main__":
    main()
