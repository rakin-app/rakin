# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown==3.9"]
# ///
"""Builds rakin.app, the landing page (#343), into a folder Caddy serves as is.

    uv run site/build.py [--out DIR] [--fonts DIR]

Writes, under `--out` (default `site/dist`):

* `index.html`: `site/index.html`, with `site/styles.css` inlined, the dark
  lockup drawn inline and `CONTACT_EMAIL` filled in;
* `privacidad/index.html`: Rakin's own privacy notice,
  `docs/legal/aviso-de-privacidad-rakin.md`, rendered from its policy on, with
  its drafting notes left out;
* `img/` and `video/`, the captures and loops `site/screenshots.py` takes, each named
  for its content (`hoy-390-2x.1a2b3c4d.webp`), so a capture taken again is never
  served from a browser's cache under its old name; `fonts/` and the icons and link
  preview the app also serves (`frontend/public/`).

The page names its captures by shot, never by file: `<img data-shot="hoy-390" …>`
becomes the shot's `src`, its 1× and 2× `srcset`, its `width` and `height`, and lazy
loading unless the tag says how to load; `<video data-loop="validar" …>` gets its
WebM and MP4 sources and its poster as `data-poster`, which the page's script sets
once the page has loaded (a poster is fetched at once, lazy or not, #461); with no
script, a `<noscript>` still of it stands in for the loop, which would never play. A
shot or loop the page names that is not there fails the build.

A shot whose tag gives `sizes` gets, instead of 1× and 2×, every width of it on disk
(`hoy-1280-1.5x.webp` too) as a `srcset` of widths, and, when it has them in AVIF, a
`<source type="image/avif">` before it, so its tag must sit in a `<picture>`. That is
the hero's LCP image (#461), which `<link data-shot="…" imagesizes="…">` also
preloads: the link gets `rel="preload"`, `as`, `type` and the same `imagesrcset`.

`--fonts` is the `@fontsource` directory holding Figtree and Bricolage
Grotesque; by default, the one `npm install` puts under `frontend/node_modules`.
The web image runs this in its own stage (deploy/web.Dockerfile).
"""

import argparse
import hashlib
import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PUBLIC = ROOT / "frontend" / "public"
NOTICE = ROOT / "docs" / "legal" / "aviso-de-privacidad-rakin.md"
LOCKUP_DARK = ROOT / "docs" / "brand" / "lockup-dark.svg"

# TODO(#343): the alias the owner provides; one line to change.
CONTACT_EMAIL = "hola@rakin.app"

# The notice's links to its sibling documents go to the repo, where they are published.
DOCS_URL = "https://github.com/rakin-app/rakin/blob/main/docs/legal/"

FONTS = (
    "figtree/files/figtree-latin-400-normal.woff2",
    "figtree/files/figtree-latin-600-normal.woff2",
    "bricolage-grotesque/files/bricolage-grotesque-latin-600-normal.woff2",
)
ICONS = ("favicon.svg", "favicon.ico", "apple-touch-icon.png", "og-image.png")

NOTICE_PAGE = """<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Aviso de privacidad · Rakin</title>
    <meta name="description" content="Qué datos trata Rakin, para qué y cómo ejercer tus derechos." />
    <meta name="theme-color" content="#0f2e1b" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="icon" href="/favicon.ico" sizes="32x32" />
    <link rel="canonical" href="https://rakin.app/privacidad/" />
    <style>{{STYLES}}</style>
  </head>
  <body>
    <a class="skip" href="#contenido">Saltar al contenido</a>
    <header class="doc-header">
      <div class="wrap narrow"><a class="logo" href="/" aria-label="Rakin, inicio">{{LOCKUP_DARK}}</a></div>
    </header>
    <main id="contenido" class="doc">
      <div class="wrap narrow">
{{BODY}}
      </div>
    </main>
    <footer class="footer">
      <div class="wrap">
        <p>Rakin · Membresías y pagos para academias</p>
        <p><a href="/">Inicio</a> · <a href="mailto:{{CONTACT_EMAIL}}">{{CONTACT_EMAIL}}</a></p>
      </div>
    </footer>
  </body>
</html>
"""


def fill(template: str, **values: str) -> str:
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], template)


def lockup() -> str:
    """The dark lockup, inline: a decorative drawing inside a labelled link."""
    svg = LOCKUP_DARK.read_text().strip()
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


# The drafting notes for the lawyer and for later work, in the notice's own markup
# (docs/legal/README.md). They are for the repo's readers, never a visitor.
NOTES = re.compile(r" ?`\[(?:ABOGADO|PENDIENTE):.*?\]`")


def notice_html() -> str:
    """The notice from its policy on, with no drafting notes.

    The draft line the file opens with ("BORRADOR: pendiente de revisión por abogado.
    <fecha>") and the policy's own "Versión N, vigente desde <fecha>" become one line
    under the title: a preliminary version, and the date it was last updated. The text
    before the policy says where the notice is published, for the repo's readers."""
    text = NOTICE.read_text()
    draft = re.match(r"> \*\*BORRADOR[^*]*\*\* (.+?)\.?\n", text)
    if not draft:
        raise SystemExit(f"build: {NOTICE.name} no longer opens with its dated draft line")
    policy = text[text.index("## Política de privacidad de Rakin") :]
    # One level up: the policy's title is the page's h1.
    title, rest = policy[1:].replace("\n#", "\n").split("\n", 1)
    rest = re.sub(r"^\s*Versión [^\n]*\n", "", rest, count=1)
    status = f"*Versión preliminar, en revisión. Última actualización: {draft.group(1)}.*"
    body = NOTES.sub("", f"{title}\n\n{status}\n{rest}")
    if re.search(r"ABOGADO|PENDIENTE|BORRADOR", body):
        raise SystemExit(
            f"build: a drafting note in {NOTICE.name} is not in the `[ABOGADO: …]` form"
        )
    # Sibling documents, and the research one folder up, go to the repo on GitHub.
    body = re.sub(
        r"\]\(\.\./([\w-]+\.md)", r"](https://github.com/rakin-app/rakin/blob/main/docs/\1", body
    )
    body = re.sub(r"\]\(([\w-]+\.md)", rf"]({DOCS_URL}\1", body)
    rendered = markdown.markdown(body, extensions=["tables", "toc"], output_format="html")
    # Links are rendered by now, so a bracket left in the page is a datum still to fill
    # in, such as "[fecha]" (docs/legal/README.md): never published as is.
    if placeholders := re.findall(r"\[[^\]]*\]", rendered):
        raise SystemExit(
            f"build: {NOTICE.name} has unfilled placeholders: {', '.join(placeholders)}"
        )
    return rendered


def webp_size(data: bytes) -> tuple[int, int]:
    """A WebP's width and height, from its header."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP")
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 ":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        return width, int.from_bytes(data[28:30], "little") & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError(f"unknown WebP chunk {chunk!r}")


def fingerprint(source: Path, out: Path) -> dict[str, str]:
    """Copies each file under `source` to `out` as `<stem>.<hash8><suffix>`; the new
    name of each, by the old."""
    out.mkdir(parents=True, exist_ok=True)
    names: dict[str, str] = {}
    for file in sorted(source.iterdir()):
        if not file.is_file() or file.name.startswith("."):
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()[:8]
        names[file.name] = f"{file.stem}.{digest}{file.suffix}"
        shutil.copy2(file, out / names[file.name])
    return names


SHOT = re.compile(r"<img\b([^>]*?)\sdata-shot=\"([\w-]+)\"([^>]*)>")
PRELOAD = re.compile(r"<link\b([^>]*?)\sdata-shot=\"([\w-]+)\"([^>]*)>")
LOOP = re.compile(r"<video\b([^>]*?)\sdata-loop=\"([\w-]+)\"([^>]*)>\s*</video>")


# What follows a shot's name in the file of one of its widths: `-1.5x.webp`.
WIDTH = re.compile(r"-\d+(?:\.\d+)?x\.webp")


def shots(page: str, images: dict[str, str], videos: dict[str, str]) -> str:
    """`page` with each `data-shot` and `data-loop` filled in from `images` and `videos`."""

    def image(name: str) -> str:
        if name not in images:
            raise SystemExit(f"build: the page shows {name}, which site/img does not have")
        return f"/img/{images[name]}"

    def widths(name: str, ext: str) -> str:
        """Every width of `name` on disk, as a `srcset` of `ext` files."""
        files = [
            f
            for f in (SITE / "img").glob(f"{name}-*x.webp")
            if WIDTH.fullmatch(f.name[len(name) :])
        ]
        if not files:
            raise SystemExit(f"build: the page shows {name}, which site/img does not have")
        found = sorted((webp_size(f.read_bytes())[0], f.name) for f in files)
        return ", ".join(
            f"{image(file.removesuffix('.webp') + '.' + ext)} {w}w" for w, file in found
        )

    def avif(name: str) -> bool:
        return any((SITE / "img").glob(f"{name}-*x.avif"))

    def shot(match: re.Match[str]) -> str:
        before, name, after = match.groups()
        width, height = webp_size((SITE / "img" / f"{name}-1x.webp").read_bytes())
        one, two = image(f"{name}-1x.webp"), image(f"{name}-2x.webp")
        srcset, source = f"{one} 1x, {two} 2x", ""
        if sizes := re.search(r'\ssizes="([^"]*)"', before + after):
            srcset = widths(name, "webp")
            if avif(name):
                start = match.start()
                if page.rfind("<picture", 0, start) <= page.rfind("</picture>", 0, start):
                    raise SystemExit(
                        f"build: {name} has AVIF, so the page must show it in a <picture>"
                    )
                source = (
                    f'<source type="image/avif" srcset="{widths(name, "avif")}"'
                    f' sizes="{sizes.group(1)}" />'
                )
        attrs = f' src="{one}" srcset="{srcset}" width="{width}" height="{height}"'
        if "loading=" not in before + after:
            attrs += ' loading="lazy" decoding="async"'
        return f"{source}<img{before}{attrs}{after}>"

    def preload(match: re.Match[str]) -> str:
        before, name, after = match.groups()
        ext = "avif" if avif(name) else "webp"
        return (
            f'<link{before} rel="preload" as="image" type="image/{ext}"'
            f' imagesrcset="{widths(name, ext)}"{after}>'
        )

    def loop(match: re.Match[str]) -> str:
        before, name, after = match.groups()
        for ext in ("webm", "mp4"):
            if f"{name}.{ext}" not in videos:
                raise SystemExit(f"build: the page plays {name}, which site/video has no {ext} of")
        width, height = webp_size((SITE / "img" / f"{name}-poster-1x.webp").read_bytes())
        poster = image(f"{name}-poster-1x.webp")
        label = re.search(r'\saria-label="([^"]*)"', before + after)
        if not label:
            raise SystemExit(f"build: the loop {name} has no aria-label to describe its poster")
        return (
            f'<video{before} data-poster="{poster}" width="{width}" height="{height}"{after}>'
            f'<source src="/video/{videos[name + ".webm"]}" type="video/webm" />'
            f'<source src="/video/{videos[name + ".mp4"]}" type="video/mp4" /></video>'
            f'<noscript><img src="{poster}" width="{width}" height="{height}"'
            f' alt="{label.group(1)}" loading="lazy" decoding="async" /></noscript>'
        )

    return LOOP.sub(loop, PRELOAD.sub(preload, SHOT.sub(shot, page)))


def build(out: Path, fonts: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "privacidad").mkdir(parents=True)
    styles = (SITE / "styles.css").read_text()
    common = {
        "STYLES": styles,
        "LOCKUP_DARK": lockup(),
        "CONTACT_EMAIL": html.escape(CONTACT_EMAIL),
    }

    images = fingerprint(SITE / "img", out / "img")
    videos = fingerprint(SITE / "video", out / "video")
    page = shots(fill((SITE / "index.html").read_text(), **common), images, videos)
    (out / "index.html").write_text(page)
    (out / "privacidad" / "index.html").write_text(fill(NOTICE_PAGE, BODY=notice_html(), **common))

    (out / "fonts").mkdir()
    for font in FONTS:
        shutil.copy2(fonts / font, out / "fonts")
    for icon in ICONS:
        shutil.copy2(PUBLIC / icon, out)
    print(f"build: rakin.app in {out}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=SITE / "dist")
    parser.add_argument(
        "--fonts", type=Path, default=ROOT / "frontend" / "node_modules" / "@fontsource"
    )
    args = parser.parse_args()
    build(args.out, args.fonts)


if __name__ == "__main__":
    main()
